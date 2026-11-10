<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# QCA6390 WiFi workaround: pinned BSSID + delayed `wpa_supplicant`

This is the setup that made QCA6390 WiFi reliable on the Mi 10 (`umi`) with
kernel 6.12.94. It is a workaround for an ath11k firmware/driver issue, not a
proper upstream fix.

## Symptoms

With `iwd` (or an early `wpa_supplicant` autostart) the first association could
produce:

```text
ath11k_pci 0000:01:00.0: failed to receive scan abort comple: timed out
ath11k_pci 0000:01:00.0: failed to abort scan: -110
```

and then blocked I/O, RCU stalls and a `hung_task` panic. Scanning alone usually
worked; the failure appeared when a connect attempted to abort/queue a scan.
Starting WiFi very early made it much worse because `wlan0` (PCIe/ath11k probe)
is not ready yet. On this unit the probe completes around 40 s after boot.

`iwd 3.12` has no `DisableScanAbort` option. The workaround is to avoid iwd and
avoid the scan/abort path: `wpa_supplicant` with a **pinned BSSID and frequency**,
started after the interface exists.

## Final configuration

### 1. Stop and mask iwd

```sh
systemctl disable --now iwd 2>/dev/null || true
systemctl mask iwd
```

Do not use `iwctl`; it can bring iwd back and re-trigger the bug.

### 2. Find the AP BSSID and frequency

```sh
ip link set wlan0 up
iw dev wlan0 scan | grep -B14 'SSID: <SSID>'
```

Pick the BSSID/`freq:` pair you want (5 GHz is stronger on this unit). Do not
connect while the scan is still running.

### 3. Write the wpa_supplicant config

```sh
install -d -m 755 /etc/wpa_supplicant
install -m 600 deploy/wpa_supplicant-wlan0.conf.example \
    /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
```

Edit it and fill in:

```ini
ctrl_interface=/run/wpa_supplicant
update_config=1
ap_scan=1
p2p_disabled=1

network={
    ssid="<SSID>"
    bssid=<AA:BB:CC:DD:EE:FF>
    scan_freq=<FREQ_MHZ>          # 5200 for the 5 GHz example
    psk="<PASSPHRASE>"
    key_mgmt=SAE                  # WPA2-PSK: use WPA-PSK and drop ieee80211w/sae_pwe
    ieee80211w=2
    sae_pwe=2
    proto=RSN
    pairwise=CCMP
    group=CCMP
}
```

The file contains the passphrase: keep it `0600` root-only and never commit it.

### 4. Install the delayed starter

The 90 s timer is intentional. Do not enable `wpa_supplicant@wlan0` or
`dhcpcd@wlan0` at boot.

```sh
install -m 644 deploy/umi-wpa-late.service /etc/systemd/system/
install -m 644 deploy/umi-wpa-late.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl disable --now wpa_supplicant@wlan0 dhcpcd@wlan0 2>/dev/null || true
systemctl enable --now umi-wpa-late.timer
```

`deploy/install-wifi.sh` does the same steps and accepts SSID/BSSID/freq/
passphrase arguments; it writes the secret only to `/etc`.

### 5. Test without rebooting

```sh
systemctl start umi-wpa-late.service
sleep 15
wpa_cli -i wlan0 status
ip -brief addr show wlan0
ping -c 3 www.google.it
```

Expected: `wpa_state=COMPLETED`, an IPv4 address, 0% packet loss. For WPA3-SAE
the status also shows `key_mgmt=SAE` and `pmf=1`.

## Boot behaviour

- `wlan0`/ath11k appears around 40 s.
- `umi-wpa-late.timer` fires at 90 s.
- `wpa_supplicant@wlan0` starts, associates to the pinned BSSID, then
  `dhcpcd@wlan0` gets the lease.
- WiFi is up roughly 90–100 s after power-on. This is the price of avoiding the
  ath11k scan-abort hang.

## Why 90 s and not 30 s

A 30 s timer was tested: it started before the interface/firmware was ready and
the system hung again on the scan abort. 90 s leaves a wide margin after the
PCIe/ath11k probe. If you change it, test a full cold boot, not just a manual
`systemctl start`.

## Verification / troubleshooting

```sh
wpa_cli -i wlan0 status
iw dev wlan0 link
journalctl -u wpa_supplicant@wlan0 -b --no-pager
journalctl -u dhcpcd@wlan0 -b --no-pager
systemctl status umi-wpa-late.timer umi-wpa-late.service
```

Common causes of failure:

- AP changed BSSID or channel → update `bssid`/`scan_freq`.
- WPA2 network → `key_mgmt=WPA-PSK`; remove `ieee80211w`/`sae_pwe` (or set
  `ieee80211w=0` if the AP does not use PMF).
- `iwd` active → mask it; it owns the interface.
- `wpa_supplicant@wlan0` enabled at boot → disable it; use the late timer.
- The Plasma network applet shows “off” because NetworkManager is not installed;
  this does not affect the actual link.

## What does *not* work

- `iwd` + `iwctl` on this firmware/driver combination: scan abort → hang.
- `iwd` `[Scan] DisableScanAbort`: the option does not exist in iwd 3.12.
- `wpa_supplicant` started at boot/30 s: too early.
- Assuming a normal scan/connect sequence is safe: it is the trigger.

## Files

- `deploy/wpa_supplicant-wlan0.conf.example`
- `deploy/umi-wpa-late.service`
- `deploy/umi-wpa-late.timer`
- `deploy/install-wifi.sh`
