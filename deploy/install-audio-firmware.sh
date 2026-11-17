#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# install-audio-firmware.sh — make the Mi 10's own ADSP firmware available.
#
# The ADSP firmware is not redistributable and does not live in this repo: it
# ships inside the phone's "modem" partition (image/adsp.mdt + adsp.b00..b18).
# pd-mapper also needs adspr.jsn / adspua.jsn to publish the audio power
# domains; without them the sound card never binds ("PDM: no support").
#
# Run as root on the phone:
#   sh deploy/install-audio-firmware.sh
set -eu

PART=${PART:-/dev/disk/by-partlabel/modem}
MNT=${MNT:-/mnt/modem-fw}
FW=/lib/firmware/qcom/sm8250/xiaomi/umi

[ -b "$PART" ] || { echo "missing $PART" >&2; exit 1; }

mkdir -p "$MNT"
mountpoint -q "$MNT" || mount -o ro "$PART" "$MNT"

[ -f "$MNT/image/adsp.mdt" ] || { echo "no image/adsp.mdt on $PART" >&2; exit 1; }

mkdir -p "$FW"
n=0
for f in "$MNT"/image/adsp.*; do
	install -m 644 "$f" "$FW/$(basename "$f")"
	n=$((n + 1))
done

# pd-mapper reads these from the same directory.
for f in adspr.jsn adspua.jsn; do
	[ -f "$MNT/image/$f" ] && install -m 644 "$MNT/image/$f" "$FW/$f"
done

echo "installed $n ADSP files into $FW"
ls -l "$FW" | head -5

umount "$MNT" 2>/dev/null || true

cat <<'EOM'

Next:
  1. modprobe remoteproc_q6v5_pas qcom_pd_mapper q6core q6afe q6asm q6adm q6routing
  2. dmesg | grep -iE 'adsp|PDM|apr'      # expect "adsp ... is now online"
  3. aplay -l                             # expect the sm8250 sound card
EOM
