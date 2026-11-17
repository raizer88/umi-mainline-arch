<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Post-install system integration notes

This page collects **userspace/systemd** changes made after the Arch Linux ARM
rootfs is installed. It is not part of the kernel port and it contains no
credentials. The examples come from a field unit running Plasma Mobile, Hermes
and Cloudflare Tunnel, but the kernel/DT requests at the end apply to every
`umi`.

## 1. RTC starts in 1974

`rtc-pm8xxx` initialises the system clock from the PMIC RTC, but the value is
wrong after a cold boot:

```text
rtc-pm8xxx ... setting system clock to 1974-01-30T12:03:32 UTC
timedatectl
  RTC time: Wed 1974-01-30 ...
  System clock synchronized: yes
hwclock --systohc
  ioctl(RTC_SET_TIME) ... No such device
```

There is no writable `/dev/rtc`, so userspace cannot fix the hardware clock.
NTP (`systemd-timesyncd`) corrects the system clock only 90–130 s after boot.
Until then TLS sees certificates as "not yet valid": the Hermes gateway logs
`CERTIFICATE_VERIFY_FAILED certificate is not yet valid`, `cloudflared` can
crash-loop, and early `curl` calls return `HTTP 000`.

Workaround used on the field unit: a script that waits for a plausible year
(`>= 2025`) **and** a default route, with a 200 s cap, and always exits 0. It is
wired as `ExecStartPre` in the units that need TLS:

```ini
# ~/.config/systemd/user/hermes-gateway.service.d/attesa-orologio.conf
[Service]
ExecStartPre=/home/USER/.hermes/scripts/attendi_orologio.sh
TimeoutStartSec=300
```

The same drop-in is used for `hermes-dashboard.service`; for the system
`cloudflared.service` the path is `/etc/systemd/system/cloudflared.service.d/`.
Measured boot-to-Telegram went from 5 min 52 s to 2 min 07 s, limited by NTP.

**Kernel/DT request:** expose a writable `/dev/rtc` (or a working
`RTC_SET_TIME`) for `rtc-pm8xxx`. Then one early `hwclock -w` would persist the
time and remove the wait. `fake-hwclock` is the userspace fallback, at the cost
of a second source of truth.

## 2. pacman 7 and the Landlock sandbox

The mainline kernel has no Landlock, so pacman 7 cannot download:

```text
error: restricting filesystem access failed because Landlock is not supported by the kernel!
error: switching to sandbox user 'alpm' failed!
```

Add this under `[options]` in `/etc/pacman.conf`:

```ini
DisableSandbox
```

Keep a backup (`/etc/pacman.conf.bak-<date>`). The download is no longer
isolated; remove the line if the kernel gains Landlock.

If the rootfs is a **partial** upgrade, `pacman -S <pkg>` can leave new binaries
linked against `libcrypto.so.4` while the installed OpenSSL is 3.6. A full
`pacman -Su` (or a snapshot matching the repo) is then required; do not run a
bare `-Sy` on Arch. On the field unit a full upgrade pulled 234 packages and
moved OpenSSL to 4.1.0, after which `pacman -Qu` was empty.

## 3. systemd user services and timers

Hermes runs as a normal user with lingering enabled:

```sh
loginctl enable-linger USER
systemctl --user enable --now hermes-gateway.service
systemctl --user enable --now hermes-dashboard.service
```

- gateway: `127.0.0.1:8642`
- dashboard: `127.0.0.1:9119`; it is bound to loopback and is meant to be reached
  through the tunnel. A `302 /login` is expected.

Dashboard unit used on the field unit:

```ini
[Service]
WorkingDirectory=/home/USER/.hermes/hermes-agent
Environment=HERMES_HOME=/home/USER/.hermes
Environment=PATH=/home/USER/.hermes/hermes-agent/.hermes/bin:/home/USER/.local/bin:/usr/local/bin:/usr/bin
ExecStart=/home/USER/.hermes/hermes-agent/.hermes/bin/hermes dashboard \
  --no-open --skip-build --host 127.0.0.1 --port 9119
Restart=on-failure
RestartSec=5
```

`--skip-build` serves the prebuilt `hermes_cli/web_dist`; drop it only if
`pnpm`/Node are available and a rebuild is intended.

Arch has no cron daemon. Convert cron jobs to user timers. Two traps:

1. `Persistent=true` with the 1974 clock makes systemd believe it missed
   decades of runs and starts the job on every boot. Guard the script with a
   "last successful run newer than N hours, or in the future" check.
2. Scripts restored from another host can be mode 644; `ExecStart` then fails
   with `203/EXEC` and no useful log. Run `chmod +x` on the scripts.

Export the runtime directory portably; the UID differs between hosts (1000 vs
1001 on the field unit):

```sh
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
```

## 4. Charge limit without `charge_control_end_threshold`

The stock power-supply class does **not** expose
`charge_control_end_threshold`, and on some units `/sys/class/power_supply/battery/*`
is empty. The active charger is `pm8150b`; `bq2597x` may probe as
`Standalone`/`Part Num:0` and is not the main charger.

On the field unit `pm8150b-charger/charging_enabled` is writable:

```sh
echo 0 | sudo tee /sys/class/power_supply/pm8150b-charger/charging_enabled
echo 1 | sudo tee /sys/class/power_supply/pm8150b-charger/charging_enabled
```

A oneshot service plus a 60 s timer implements an 80/70 limit: above 80 % write
0, below 70 % write 1. This is a **software workaround**, not a battery-health
guarantee; 24/7 at 100 % is still a swelling risk. The service is in
`deploy/`/`docs` examples and is re-applied at boot.

Charger-only logs (`qcom,pmic-typec ... probe failed -22`,
`Apsd not ready`, `bq2597x` I2C warning at shutdown) are noisy but were not the
cause of the boot hang below. They are worth a separate driver/DT fix.

## 5. Charger-only boot hangs: `serial-getty@ttyGS0`

Symptom: with a **charger** (no USB host) the boot stops on the kernel console
after WiFi association and `8021q`; connecting the same cable to a PC lets the
boot complete. The pstore is a clean shutdown, not a panic.

The blocker is the USB-serial getty:

```text
serial-getty@ttyGS0.service
  BindsTo=dev-ttyGS0.device
  Before=getty.target
  Restart=always
```

With no stable USB host the `ttyGS0` gadget state makes the getty stop/restart
and blocks `getty.target`, so `getty@tty1` (autologin) and Plasma never start.
`systemd-networkd-wait-online` on `usb0` was a false lead; excluding `usb0` with
`RequiredForOnline=no` is still useful but did not fix the boot by itself.

Fix used on the field unit:

```sh
sudo systemctl disable --now serial-getty@ttyGS0.service
```

The USB RNDIS network (`usb0`, 192.168.42.1/24) and SSH remain available; only
the serial console on the gadget is lost. Recovery is then SSH/WiFi, or the PC
USB gadget, or TWRP. If the serial console is needed, re-enable the unit
manually and keep a PC host attached.

A `usb0` network file can still avoid a needless online wait:

```ini
# /etc/systemd/network/10-usb0.network
[Match]
Name=usb*
[Network]
Address=192.168.42.1/24
ConfigureWithoutCarrier=yes
DHCPServer=yes
[Link]
RequiredForOnline=no
```

## 6. Cloudflare Tunnel (remote-managed)

The tunnel is **remotely managed** with a token: there is no `config.yml`, no
`<uuid>.json` and no `cert.pem` on disk. The ingress lives in the Cloudflare
account. Install the token with mode 600 and use a system unit:

```ini
# /etc/systemd/system/cloudflared.service
[Service]
Type=simple
EnvironmentFile=/etc/cloudflared/tunnel.env
ExecStart=/usr/bin/cloudflared --no-autoupdate tunnel run
Restart=always
RestartSec=5
```

`/etc/cloudflared/tunnel.env` must be `600`; never commit it.

Remote ingress example:

```text
hermes.example.com -> http://localhost:9119
vox.example.com    -> http://127.0.0.1:8765
```

Two connectors on the **same** tunnel are load-balanced by Cloudflare. If one
host lacks the service behind a hostname, that hostname fails randomly. Before
starting a second connector, stop the old one or use a separate tunnel for the
hostname that is ready. In the field migration `hermes` worked on 9119 while
`vox` returned 502 until the bridge was moved to 8765.

`cloudflared` also starts before NTP; use the clock-wait `ExecStartPre` from §1.

## 7. Chromium/CDP notes

For automation over DevTools Protocol, these flags were required on the field
unit:

```text
--password-store=basic
--ozone-platform=x11
--disable-background-networking --disable-component-update
--disable-default-apps --disable-sync --disable-features=Translate
```

- Without `--password-store=basic`, Chromium waits on the wallet/D-Bus and
  `Page.navigate`/`Runtime.evaluate` time out.
- A profile copied from another host can contain `SingletonLock` pointing at the
  old hostname/PID; remove `Singleton*` only when the recorded host/PID is stale.
- One site blocked `--headless=new`; the graphical X11 path on `DISPLAY=:0`
  worked. Add explicit challenge-page detection instead of reporting "0 results".

## 8. Backup archives

ZIP cannot store timestamps before 1980. A restored file with a 1974 mtime makes
the backup fail with `ZIP does not support timestamps before 1980`. `touch` such
files once, then verify the archive and the remote upload size. Encrypted
archives contain `.env`/`auth.json`; never put them in this repository.

## 9. Open items

- writable RTC / `fake-hwclock` decision;
- battery telemetry and a hardware charge limit;
- suspend (`s2idle`) is absent; if it appears, disable autosuspend first;
- USB-C role/PD (`pm8150b_typec`) is not ported; `qcom,pmic-typec` can fail
  with `-22` and `Apsd not ready`;
- `serial-getty@ttyGS0` should be fixed in the gadget/unit ordering rather than
  permanently disabled;
- two cloudflared connectors need an explicit single-owner rule.
