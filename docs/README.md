<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Documentation index

The field-report documents added by this branch are in **English**:

| Document | Contents |
|---|---|
| [FIELD-REPORT.md](FIELD-REPORT.md) | what was done, what works, what does not, hardware variants |
| [ARCH-INSTALL.md](ARCH-INSTALL.md) | WSL build, rootfs, Plasma, modules, flashing, resize, SSH |
| [WIFI-WORKAROUND.md](WIFI-WORKAROUND.md) | QCA6390 ath11k scan-abort workaround (pinned BSSID/freq + 90 s timer) |
| [UFS-LPM.md](UFS-LPM.md) | UFS hibern8/link-dead panic and the `qcom,disable-lpm` fix |
| [RECOVERY.md](RECOVERY.md) | backups, TWRP, restoring LineageOS, rescue images |

Deploy templates live in [`../deploy/`](../deploy/); the kernel patch series is
in [`../patches/`](../patches/), with `apply-umi-patches.sh` applying the PCIe
and UFS changes in order.

The original upstream technical notes are kept in Chinese (they contain the
detailed vendor-register/protocol archaeology):

`BATTERY.md`, `BUILD.md`, `DIAGNOSIS.md`, `DISPLAY.md`, `GPU.md`, `HARDWARE.md`,
`KDE.md`, `NETWORK.md`, `PORTING.md`, `RUNBOOK.md`, `TESTLOG.md`, `TOUCH.md`,
`WIFI.md`, and `docs/notes/`.

> On the Samsung-panel field-report unit, the `iwd` section in the upstream
> `WIFI.md` is not applicable as-is: use `WIFI-WORKAROUND.md`.

## Quick start

1. Read [FIELD-REPORT.md](FIELD-REPORT.md) for the status and the hardware
   variant warning.
2. Read [RECOVERY.md](RECOVERY.md) before writing any partition.
3. Build with [ARCH-INSTALL.md](ARCH-INSTALL.md).
4. Bring up WiFi with [WIFI-WORKAROUND.md](WIFI-WORKAROUND.md).
5. Keep [UFS-LPM.md](UFS-LPM.md) in mind when changing the UFS/power setup.
