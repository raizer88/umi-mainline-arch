<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Recovery notes for the Mi 10 (`umi`)

The project never writes a partition during bring-up: `fastboot boot` loads the
kernel into RAM, and a power cycle returns to Android. The persistent install is
the point where the rules change.

## 1. Back up before the first write

With Android booted and `adb root` (or from TWRP), read-only dumps of:

| Partition | by-name | Mainline device | Why |
|---|---|---|---|
| `boot` | `/dev/block/by-name/boot` | `/dev/sde50` | restore LineageOS |
| `dtbo` | `/dev/block/by-name/dtbo` | `/dev/sde47` | bootloader overlays |
| `recovery` | `/dev/block/by-name/recovery` | `/dev/sda28` | TWRP |
| `vbmeta` | `/dev/block/by-name/vbmeta` | `/dev/sde16` | AVB metadata |

The repository's `tools/pull-part.ps1` does this through TWRP. A direct root
`adb exec-out dd if=/dev/block/by-name/<part> ...` also works. Keep the dumps on
the PC; they are not part of the public repository.

Also copy the stock LineageOS `boot.img`, the LineageOS zip and `twrp.img` to the
PC. `super` (system/vendor/product), `persist`, `modem`/`firmware`, `xbl`,
`abl` and `tz` were never written.

> `vendor_boot` does not exist on this A-only Mi 10; `boot` + `dtbo` +
> `recovery` are the relevant partitions.

## 2. Boot modes

- **Fastboot:** phone off, hold **Volume Down + Power**.
- **TWRP:** phone off, hold **Volume Up + Power**.
- **Android:** normal power; `userdata` is Arch after the install, so Android
  will not boot without restoring/wiping it.

`fastboot boot` works **once per bootloader session**. A second call fails with
`Failed to load/authenticate boot image`; run `fastboot reboot-bootloader` first.
The kernel must be compressed (gzip or `ARM\x64` at offset 56).

## 3. Use TWRP for boot images, not for mounting Arch

TWRP on this device runs a 4.19 kernel and e2fsprogs 1.46. The Arch rootfs uses
newer ext4 features (`metadata_csum_seed`, etc.); TWRP can run `e2fsck` but a
mount fails with `Invalid argument`. For maintenance of the Arch filesystem use:

- the mainline initramfs/rescue shell, or
- `fastboot`/`adb` for `boot`, or
- `debugfs`/`e2fsprogs` from a compatible environment.

TWRP `dd` is still fine for writing `boot`:

```sh
adb push out/boot-umi-arch.img /tmp/boot-umi-arch.img
adb shell 'dd if=/tmp/boot-umi-arch.img of=/dev/block/by-name/boot bs=1M'
adb shell sync
```

## 4. Restore LineageOS

If `boot` still contains LineageOS and `userdata` is Arch, Android will not boot.
To go back:

1. Flash the stock boot image:
   `fastboot flash boot dump/boot-stock.img`
2. Boot TWRP and format `userdata` as f2fs (all Arch data is lost), or
   `fastboot -w`.
3. Reboot Android. The LineageOS system on `super` was never touched.

If `boot` is broken, fastboot is independent of `boot`; `fastboot flash boot` of
the stock image is enough to recover. TWRP is in `recovery` (`sda28`) and is also
independent.

## 5. Recovery from a bad kernel/rootfs

- **Black screen, returns to fastboot in <5 s:** ABL rejected the image (DTB
  matching/compression). Rebuild with `pack-umi.py` and check the board-id/msm-id
  and the gzip magic.
- **Black screen, >8 s or never returns:** kernel started and died/hung. Read
  the previous boot's `pstore` by booting a rescue initramfs (`--root none`), or
  read `/sys/fs/pstore` after the next successful boot.
- **WiFi causes a hang:** see [WIFI-WORKAROUND.md](WIFI-WORKAROUND.md) and
  [UFS-LPM.md](UFS-LPM.md); do not use early `wpa_supplicant`/`iwd`.
- **Rootfs mount fails:** boot the rescue image with `--root none`, mount
  `/dev/sda34`, inspect `journalctl`/`fsck`; do not format until the backups are
  verified.

The rescue initramfs is built with:

```sh
sh scripts/mkinitramfs.sh --root none
python3 tools/pack-umi.py --dtb out/sm8250-xiaomi-umi-wifi.dtb \
  --initramfs out/initramfs.cpio.gz -o out/boot-umi-rescue.img
```

## 6. What is not in this repository

- `boot-stock.img`, `dtbo-stock.img`, `recovery-twrp.img`, `vbmeta-stock.img`
- LineageOS zip/TWRP image
- the Arch rootfs image or the kernel tree
- WiFi passphrases, SSH keys, AP BSSIDs, device serials
- vendor firmware/DTB dumps

Those stay on the owner's PC/device.
