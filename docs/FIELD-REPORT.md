<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Field report: Arch Linux ARM + Plasma Mobile on the Xiaomi Mi 10 (`umi`)

Date: 2026-11-10. Author: raizer88. Base tree:
[`colorgarden/umi-mainline`](https://github.com/colorgarden/umi-mainline),
commit `5fa2e0048f89b82355d2a9de89c1d74ab9910959` (2026-10-30).

This is a **field report and a working branch**, not an upstream claim. It records
what was actually done on one physical Mi 10, what worked, what failed, and the
fixes that made the system usable. The original project and most of the code are
by `colorgarden`; this copy keeps that history and adds the changes listed below.
No credentials, SSH keys, WiFi passphrases, AP BSSIDs, device serial numbers or
partition backups are included.

## 1. The unit

| Item | Value |
|---|---|
| Device | Xiaomi Mi 10, codename `umi`, model **M2001J2G** |
| SoC | Qualcomm SM8250 (Snapdragon 865), 8 cores |
| Original OS | LineageOS 21 (Android 14), kernel 4.19, TWRP installed |
| `userdata` | 107 GiB, `/dev/sda34` (was f2fs) |
| Panel | **Samsung** `qcom,mdss_dsi_j2_p2_1_38_0c_0a_dsc_cmd`, 1080x2340, DSC command mode |
| Touch | **STMicroelectronics FTS** on `i2c-3`, address `0x49`, 10 slots, MT-B |
| WiFi | Qualcomm **QCA6390** on PCIe0 (`1c00000.pcie`), `ath11k_pci` |
| UFS | WDC `SDINEDK4-128G`, `1d84000.ufshc` |
| Bootloader | unlocked, product `umi`, no A/B slots |

The panel and touch are the two hardware lottery items. The upstream test device
was CSOT (`j2_mp_42_02_0b`); this unit is Samsung (`38 0c 0a`) and FTS, not
Goodix. The Samsung panel node in `dts/xiaomi-umi-panels.dtsi` was regenerated
from this unit's downstream DTB with `tools/gen-panel-dts.py`.

## 2. Status

| Subsystem | State | Notes |
|---|---|---|
| Kernel 6.12.94-umi | **works** | boots to userspace, ~15 s to serial shell |
| Samsung AMOLED | **works** | 1080x2340@60, DSC 540x65, 4-lane command mode; generated panel DTS |
| Backlight | **works** | 1..2047, usable from ~1000 |
| ST FTS touch | **works** | `/dev/input/event*`, 10 slots, MT-B |
| USB CDC-ACM console | **works** | `ttyGS0`/CDC-ACM, 115200; `COMx` on Windows |
| USB RNDIS | **works** | `usb0` = 192.168.42.1/24, DHCP server for the host |
| UFS / Arch rootfs | **works** | 106 GiB ext4 on `/dev/sda34` |
| Display blank/resume | **glitch** | DSI timeout+FIFO error, panel noise; off/on recovers; disable auto blank/lock, see [DISPLAY-RESUME.md](DISPLAY-RESUME.md) |
| Arch Linux ARM | **works** | base Arch, `pacman`, `systemd` |
| Plasma Mobile | **works** | Plasma Mobile 6.8.2, KWin Wayland, tty1 autologin |
| SSH | **works** | root key auth over USB and over WiFi |
| WiFi QCA6390 | **works with workaround** | 90 s delayed `wpa_supplicant`, pinned BSSID/frequency; WPA3-SAE 5 GHz, 864 Mbit/s |
| WiFi via iwd / early autostart | **broken** | ath11k scan-abort timeout hangs the system |
| WiFi UI in Plasma | **cosmetic off** | `plasma-nm` expects NetworkManager; actual link is up |
| Camera / modem | **not done** | out of scope |
| Suspend / audio / fingerprint | **not done** | out of scope |
| 90 Hz | **not enabled** | timing exists, not enabled |
| UFS low-power states | **disabled** | `qcom,disable-lpm`; fixes a hibern8/link-dead panic |

## 3. What was done

1. **Phase 0, read-only.** Identified the panel and touch from Android; saved
   `fastboot getvar all`; backed up `boot`, `dtbo`, `recovery`, `vbmeta`;
   verified that `fastboot boot` works and that the kernel is compressed.
2. **Kernel.** Built Linux 6.12.94 with GCC 16.1 (Alpine WSL), Rust 1.82 and
   bindgen for the QR panic screen. Regenerated the Samsung panel DTS. Applied
   the QCA6390 PCIe early-power-on / LTSSM / PERST patches from `patches/` and
   added the UFS LPM opt-out (`qcom,disable-lpm`).
3. **Arch rootfs.** Built a 6 GiB ext4 image from the Arch Linux ARM aarch64
   tarball, initialized the pacman keyring, installed Plasma Mobile and `iwd`,
   installed the custom kernel modules, flashed it to `userdata` (fastboot
   auto-sparsed the raw image), wrote `boot` via TWRP `dd`, and resized the
   filesystem to 106 GiB.
4. **Cache test.** Before touching `userdata`, a 64 MiB busybox rootfs was
   flashed to `cache` and booted with an initramfs whose root was `/dev/sda29`.
   `MINI ROOTFS IS ALIVE (switch_root worked)` confirmed the chain.
5. **WiFi debugging.** The first WiFi connection attempts crashed with UFS
   `hibern8 exit -110`; later, after the UFS fix, with `ath11k` scan-abort
   timeouts. The final working path is `wpa_supplicant` with a pinned BSSID and
   frequency, started 90 s after boot by a systemd timer. Details:
   [WIFI-WORKAROUND.md](WIFI-WORKAROUND.md), [UFS-LPM.md](UFS-LPM.md).

## 4. Key findings

### 4.1 The panel is a variant, not a constant

The upstream DTS enables CSOT. This unit needs the Samsung node. The generator
reads the downstream DTB and emits one `umi-panel@0`; do not put multiple panel
nodes under the same DSI parent. The generated file is the one in this branch.

### 4.2 UFS low-power states are unsafe while WiFi is active

`ufs-qcom` unconditionally enables clock gating, hibern8-with-clock-gating,
clock scaling and runtime autosuspend. Under WiFi load the UFS link can fail:

```text
ufshcd-qcom 1d84000.ufshc: pwr ctrl cmd 0x18 with mode 0x0 completion timeout
ufshcd-qcom 1d84000.ufshc: ufshcd_uic_hibern8_exit: hibern8 exit failed. ret = -110
ufshcd-qcom 1d84000.ufshc: ufshcd_err_handler started; HBA state eh_fatal; link is broken
```

then `hung_task` panics. The fix used here is a DT opt-out plus a small driver
patch that clears the UFS LPM caps. See [UFS-LPM.md](UFS-LPM.md).

### 4.3 ath11k scan abort kills early WiFi startup

Starting `iwd` (or `wpa_supplicant`) before `wlan0` is ready produces:

```text
ath11k_pci 0000:01:00.0: failed to receive scan abort comple: timed out
ath11k_pci 0000:01:00.0: failed to abort scan: -110
```

followed by a block-layer/RCU hang. `iwd 3.12` has **no** `DisableScanAbort`
option. The reliable workaround is to avoid the scan/abort path entirely:
`wpa_supplicant` with a pinned BSSID and `scan_freq`, started after the interface
is up. A 90 s timer is used; a 30 s timer was still too early on this unit
(`wlan0`/PCIe probe completes around 40 s). See
[WIFI-WORKAROUND.md](WIFI-WORKAROUND.md).

### 4.4 TWRP cannot mount this ext4

The final rootfs uses features from e2fsprogs 1.47 (for example
`metadata_csum_seed`). TWRP's 4.19 kernel/e2fsprogs 1.46 can read the partition
table and run `e2fsck`, but a mount returns `Invalid argument`. Use the mainline
kernel/initramfs for maintenance, or `fastboot`/`dd` for boot. The boot partition
is `/dev/sde50` in mainline (`/dev/block/by-name/boot` in TWRP).

### 4.5 `verify.ps1` and the USB watcher had stale assumptions

`tools/config-audit.py` still treats `DRM_MSM=y` and `ARM_PSCI_CPUIDLE=y` as
forbidden, while the current `build.sh` requires both. `tools/watch-usb.ps1` used
`$Pid`, a read-only PowerShell variable, and looked for gadget PID `0104`; the
initramfs uses `0105`. Both were fixed in this branch. The `verify.ps1` boot-img
path check has a Windows path-splitting bug; `pack-umi.py` and `bootimg.py` are
the authoritative checks.

## 5. Reproduce

- [ARCH-INSTALL.md](ARCH-INSTALL.md): WSL, kernel, modules, rootfs, Plasma, flash,
  resize, SSH.
- [WIFI-WORKAROUND.md](WIFI-WORKAROUND.md): wpa_supplicant template, BSSID/freq,
  90 s timer, verification.
- [UFS-LPM.md](UFS-LPM.md): the UFS panic, the DT property, the driver patch.
- [RECOVERY.md](RECOVERY.md): backups, TWRP, returning to LineageOS.
- `patches/apply-umi-patches.sh`: applies the PCIe and UFS patches to
  `/root/linux` in the order used here.

## 6. Limitations and next steps

- WiFi is deliberately delayed by 90 s. Reducing it is possible only after the
  ath11k firmware/scan-abort issue is understood; do not enable
  `wpa_supplicant@wlan0` or `dhcpcd@wlan0` at boot.
- The display can corrupt after blank/resume with `dsi_err_worker: status=5`
  (DSI timeout+FIFO); the host does not reset the link. Disable automatic screen
  blanking/locking or toggle the screen off/on. See
  [DISPLAY-RESUME.md](DISPLAY-RESUME.md).
- The pinned BSSID/frequency is a workaround, not a general fix. If the AP
  changes channel or BSSID, update `deploy/wpa_supplicant-wlan0.conf`.
- The WiFi icon in Plasma may show "off" because `plasma-nm` expects
  NetworkManager. The link is up; use `wpa_cli`/`ip`/`ping`.
- `qcom,disable-lpm` trades UFS power for reliability. It is not upstream.
- No camera, modem, suspend, audio, fingerprint or 90 Hz work was done.
- The kernel tree and rootfs image are not committed; only source, patches,
  config templates and documentation are.

## 7. Credits and licenses

The base project and most files are from
[`colorgarden/umi-mainline`](https://github.com/colorgarden/umi-mainline). This
branch adds the Samsung panel DTS, the UFS LPM patch, the WiFi workaround notes,
the Arch install notes and the watcher fix. License follows the upstream table:
`patches/` GPL-2.0-only, `dts/` BSD-3-Clause, scripts CC0-1.0, documentation
CC-BY-4.0. See [LICENSE](../LICENSE) and [LICENSES](../LICENSES/).
