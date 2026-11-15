<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Deploy files

These files implement the QCA6390 WiFi workaround described in
[`docs/WIFI-WORKAROUND.md`](../docs/WIFI-WORKAROUND.md).

| File | Purpose |
|---|---|
| `wpa_supplicant-wlan0.conf.example` | template; fill SSID/BSSID/freq/passphrase |
| `umi-wpa-late.service` | starts `wpa_supplicant@wlan0`, then `dhcpcd@wlan0` |
| `umi-wpa-late.timer` | fires 90 s after boot |
| `install-wifi.sh` | installs the config/units and disables early WiFi |

## Quick install

On the phone, as root:

```sh
# 1. Get the BSSID/frequency while the AP is visible.
ip link set wlan0 up
iw dev wlan0 scan | grep -B14 'SSID: <SSID>'

# 2. Install. WPA3-SAE:
sh deploy/install-wifi.sh '<SSID>' '<AA:BB:CC:DD:EE:FF>' 5200 '<PASSPHRASE>' SAE
# WPA2:
sh deploy/install-wifi.sh '<SSID>' '<AA:BB:CC:DD:EE:FF>' 2412 '<PASSPHRASE>' PSK

# 3. Test without rebooting.
systemctl start umi-wpa-late.service
sleep 15
wpa_cli -i wlan0 status
ping -c 3 www.google.it
```

On reboot, WiFi comes up about 90 s after power-on. This is deliberate: `wlan0`
and the ath11k firmware are not ready before that, and starting the supplicant
too early triggers the ath11k scan-abort hang.

**Do not enable** `wpa_supplicant@wlan0` or `dhcpcd@wlan0` at boot, and do not
unmask `iwd`/use `iwctl` on this firmware. The late timer is the only supported
path in this branch.

The passphrase lives only in `/etc/wpa_supplicant/wpa_supplicant-wlan0.conf`
(0600 root). Do not commit that file.

## SSH keys and host aliases

The phone uses public-key authentication for both `root` and `umi`. The
effective `/etc/ssh/sshd_config.d/10-umi.conf` is:

```
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
```

The public key is the same for both accounts; the private key stays on the
Windows host at `C:/Users/panza/.ssh/umi_ed25519`. Test:

```sh
ssh -i C:/Users/panza/.ssh/umi_ed25519 root@192.168.1.253
ssh -i C:/Users/panza/.ssh/umi_ed25519 umi@192.168.1.253
```

`deploy/ssh-config.example` contains ready-made `Host` blocks for
`umi`/`umi-usb` (root) and `umi-user`/`umi-user-usb` (`umi`). Append it to
`C:\Users\panza\.ssh\config` (that directory is outside the agent's write
scope). The WiFi address is the reliable path; `usb0` is `192.168.42.1`.
