<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Arch Linux ARM install notes for the Mi 10 (`umi`)

These are the steps that were actually used to go from LineageOS to a persistent
Arch Linux ARM + Plasma Mobile installation. They assume an unlocked bootloader,
a working `fastboot`, and a PC with WSL2. Read [RECOVERY.md](RECOVERY.md) first.

> **Destructive step:** writing `userdata` erases all Android data. Back up the
> boot/dtbo/recovery/vbmeta partitions and everything you care about before
> touching `userdata`.

## 1. WSL build environment

The kernel tree must live on ext4 (WSL), not on a Windows/NTFS mount: the tree
contains files that differ only by case. The upstream repository provides
`scripts/setup-wsl.ps1`, which creates an Alpine distro called `umi` and installs
clang/lld/dtc/make/gcc. On a PC without a `D:` drive, pass explicit paths:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-wsl.ps1 `
  -InstallDir C:\WSL\umi -CacheDir C:\WSL\cache
```

The base tree expects a kernel at `/root/linux`. A 6.12.94 tree was used here.
The QCA6390 and UFS fixes need the extra patches:

```sh
# in WSL, from the repo root
sh scripts/prepare-tree.sh                  # if you keep a local linux-src
# or clone/extract a 6.12.94 tree directly to /root/linux
sh patches/apply-umi-patches.sh              # PCIe + UFS patches
TREE=/root/linux JOBS=16 sh scripts/build.sh
make -C /root/linux ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- \
     O=/root/linux/out -j16 modules
```

The build produces `out/Image.gz`, the three DTBs and `out/config-effective`.
The Samsung panel node is already in `dts/xiaomi-umi-panels.dtsi` in this branch.
If you have a different panel, regenerate it from the downstream DTB:

```sh
python3 tools/gen-panel-dts.py dump/panels \
  -o dts/xiaomi-umi-panels.dtsi --enable qcom,mdss_dsi_<panel>
```

## 2. Rootfs image

Download the Arch Linux ARM aarch64 tarball (about 800 MB) and create a 6 GiB
ext4 image:

```sh
OUT=/root/arch/umi-rootfs.img \
sh scripts/mk-arch-rootfs.sh /root/arch/ArchLinuxARM-aarch64-latest.tar.gz
```

The script sets:

- `/dev/sda34` as `/`, ext4, in `/etc/fstab`
- root password `umi` (change it)
- serial `ttyGS0` autologin root
- `tty1` getty
- `sshd` enabled, root password login
- `usb0` at 192.168.42.1/24
- hostname `umi`

Before installing packages, initialize the pacman keyring (the base tarball does
not do it):

```sh
pacman-key --init
pacman-key --populate archlinuxarm
```

Pacman 7's Landlock sandbox is not supported by this kernel; every pacman
operation needs `--disable-sandbox`:

```sh
pacman -Sy --disable-sandbox
pacman -S --needed --disable-sandbox \
  plasma-mobile plasma-settings kscreen konsole sudo
pacman -S --needed --disable-sandbox wpa_supplicant dhcpcd
```

Create the desktop user and groups. The upstream `umi-plasma.sh` expects the
groups to exist; the base image did not have `input`/`video`/`render`/`audio`,
so create them first:

```sh
for g in wheel input video render audio; do
  getent group "$g" >/dev/null || groupadd "$g"
done
UMI_USER=umi UMI_PASS='<password>' sh scripts/umi-plasma.sh --apply
```

`umi-plasma.sh` installs the tty1 autologin, `~/.bash_profile` that starts
Plasma, the sudo rule, the udev uaccess rule for the platform touch device and
UTF-8 locale.

## 3. Kernel modules

The kernel builds many drivers as modules; the rootfs needs them for WiFi,
RTC and other subsystems. From the build environment:

```sh
make -C /root/linux ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- \
     O=/root/linux/out INSTALL_MOD_PATH=/root/modules-stage modules_install
tar -C /root/modules-stage -czf /root/modules-6.12.94-umi.tar.gz \
     lib/modules/6.12.94-umi
```

Copy the tarball to the phone and install:

```sh
tar -xzf /tmp/modules-6.12.94-umi.tar.gz -C /tmp
rm -rf /usr/lib/modules/6.12.94-umi
cp -a /tmp/lib/modules/6.12.94-umi /usr/lib/modules/
depmod -a 6.12.94-umi
```

The QCA6390 firmware is in `linux-firmware` under
`/usr/lib/firmware/ath11k/QCA6390/hw2.0/`.

## 4. Pack the boot images

The normal image uses an initramfs with `root=/dev/sda34`; the rescue image uses
`--root none`.

```sh
# normal Arch image (after build + modules)
sh scripts/mkinitramfs.sh --root /dev/sda34
python3 tools/pack-umi.py \
  --dtb out/sm8250-xiaomi-umi-wifi.dtb \
  --initramfs out/initramfs.cpio.gz \
  -o out/boot-umi-arch.img

# optional low-risk switch_root test on cache
sh scripts/mk-mini-rootfs.sh
sh scripts/mkinitramfs.sh --root /dev/sda29
python3 tools/pack-umi.py \
  --dtb out/sm8250-xiaomi-umi-wifi.dtb \
  --initramfs out/initramfs.cpio.gz \
  -o out/boot-umi-cachetest.img
```

The Mi 10 ABL accepts only one `fastboot boot` per bootloader session. If the
boot image is going to be written to `boot`, use a fresh session.

## 5. Flash

### 5.1 Cache test (recommended, non-destructive to userdata)

```sh
fastboot flash cache out/umi-mini-rootfs.img
fastboot boot out/boot-umi-cachetest.img
```

Expected serial output: `MINI ROOTFS IS ALIVE (switch_root worked)`.

### 5.2 Persistent install

Back up `boot`, `dtbo`, `recovery`, `vbmeta` first. Then, in one bootloader
session:

```sh
fastboot flash userdata out/arch-rootfs.img
```

`fastboot` auto-sparses the raw ext4 image; a 6 GiB image took about 60 s on the
test unit. Then write `boot`. On the test unit the fastboot link became unstable
after the large write, so the boot image was written from TWRP instead:

```sh
adb push out/boot-umi-arch.img /tmp/boot-umi-arch.img
adb shell 'dd if=/tmp/boot-umi-arch.img of=/dev/block/by-name/boot bs=1M'
adb shell sync
adb shell reboot
```

In mainline Arch the boot partition is `/dev/sde50`; in TWRP it is
`/dev/block/by-name/boot`. Do not confuse it with `sda28` (recovery).

### 5.3 First boot and resize

The first boot mounts `/dev/sda34`, starts systemd and shows the Arch login. Log
in as `root` with the password set by `mk-arch-rootfs.sh` (default `umi`), then
grow the 6 GiB filesystem to the whole 107 GiB `userdata`:

```sh
resize2fs /dev/sda34
df -h /
```

## 6. SSH and WiFi

The image has `sshd` enabled. On the phone:

```sh
mkdir -p /root/.ssh
# add the PC public key to /root/.ssh/authorized_keys (0600)
```

The USB RNDIS interface is 192.168.42.1/24; a systemd-networkd DHCP server on
`usb0` gives the PC an address. Then:

```sh
ssh -i ~/.ssh/umi_ed25519 root@192.168.42.1
```

WiFi needs the pinned-BSSID workaround and the 90 s delayed starter:
[WIFI-WORKAROUND.md](WIFI-WORKAROUND.md). Do not enable `iwd` or early
`wpa_supplicant`/`dhcpcd` units.

## 7. Verify

```sh
uname -a
df -h /
systemctl --failed
wpa_cli -i wlan0 status
ip -brief addr show wlan0
ping -c 3 www.google.it
ps -ef | grep -E 'kwin_wayland|plasmashell' | grep -v grep
```

Expected on the working unit: kernel `6.12.94-umi`, root on `/dev/sda34` 106 GiB,
0 failed units, WiFi `wpa_state=COMPLETED`, Plasma processes present.

## 8. Notes

- `pacman` needs `--disable-sandbox` on this kernel (no Landlock).
- The stock Arch `mkinitcpio` hooks may run for the stock Arch kernel; they do
  not affect the mainline boot image.
- The normal boot image used in the final setup is
  `boot-umi-arch-ufs.img` (UFS LPM patch + pinned WiFi setup).
- Diagnostic/recovery boot images (`boot-umi-diagnostic*.img`) are not part of
  the final system; they were used to recover the boot loop.
