#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Apply the PCIe/QCA6390 and UFS patches used by the umi Arch bring-up.
#
# The individual scripts in this directory are from the upstream tree and
# hard-code /root/linux.  Keep the kernel tree there (the same convention as
# scripts/build.sh) or adjust the scripts.
#
#   sh patches/apply-umi-patches.sh
#
# Safe to re-run: every patch has an idempotence marker.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TREE=${TREE:-/root/linux}
P="$TREE/drivers/pci/controller/dwc/pcie-qcom.c"
U="$TREE/drivers/ufs/host/ufs-qcom.c"

[ -f "$P" ] || { echo "missing $P" >&2; exit 1; }
[ -f "$U" ] || { echo "missing $U" >&2; exit 1; }

# QCA6390 PCIe: early power-on before PERST#, LTSSM diagnostics, PERST timing.
python3 "$HERE/pcie-qcom-early-poweron.py"
python3 "$HERE/pcie-qcom-early-poweron2.py"
python3 "$HERE/fix-node-names.py"
python3 "$HERE/pcie-qcom-ltssm-debug.py"
python3 "$HERE/pcie-qcom-ltssm-after.py"
python3 "$HERE/pcie-qcom-perst-delay.py"
python3 "$HERE/revert-pcie-refclk.py"
python3 "$HERE/pcie-qcom-umi-extra.py"

# UFS: clear CLK_GATING/HIBERN8/CLK_SCALING/RPM when qcom,disable-lpm is set.
python3 "$HERE/ufs-disable-lpm.py"

echo "--- verification ---"
grep -n "early WLAN power-on" "$P" | head -3 || true
grep -n "qcom,disable-lpm" "$U" | head -3 || true
grep -n "ELBI_SYS_STTS" "$P" | head -3 || true
echo "now run scripts/build.sh with TREE=$TREE"
