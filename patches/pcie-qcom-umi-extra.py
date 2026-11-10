#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Add the missing include/ELBI definitions for the umi PCIe patch series.

The upstream `pcie-qcom-ltssm-debug.py` checks for the string `ELBI_SYS_STTS`
before adding its definitions.  `pcie-qcom-ltssm-after.py` already inserts code
that references that symbol, so if the debug script runs after it, it exits
"already patched" without adding the `#define`s, and the build fails with
`ELBI_SYS_STTS undeclared`.  This helper makes the result deterministic and also
adds `of_platform.h` needed by `of_platform_device_create()`.

Run only on a tree at /root/linux, matching the rest of patches/.
"""
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"

src = io.open(P, encoding="utf-8").read()
changed = []

if "#include <linux/of_platform.h>" not in src:
    old = "#include <linux/of.h>\n"
    if old not in src:
        sys.exit("include anchor not found")
    src = src.replace(old, old + "#include <linux/of_platform.h>\n", 1)
    changed.append("of_platform.h include")

if "ELBI_SYS_STTS" in src and "#define ELBI_SYS_STTS" not in src:
    old = "#define ELBI_SYS_CTRL\t\t\t\t0x04\n"
    if old not in src:
        sys.exit("ELBI_SYS_CTRL define anchor not found")
    src = src.replace(old, old + "#define ELBI_SYS_STTS\t\t\t\t0x08\n", 1)
    changed.append("ELBI_SYS_STTS define")

if ("ELBI_SYS_STTS_LTSSM_STATE_MASK" in src
        and "#define ELBI_SYS_STTS_LTSSM_STATE_MASK" not in src):
    old = "#define ELBI_SYS_CTRL_LT_ENABLE\t\t\tBIT(0)\n"
    if old not in src:
        sys.exit("ELBI_SYS_CTRL_LT_ENABLE anchor not found")
    add = (old
           + "\n/* ELBI_SYS_STTS register fields (port from 7.2) */\n"
           + "#define ELBI_SYS_STTS_LTSSM_STATE_MASK\t\tGENMASK(17, 12)\n")
    src = src.replace(old, add, 1)
    changed.append("ELBI LTSSM mask define")

if changed:
    io.open(P, "w", encoding="utf-8").write(src)
    print("pcie qcom extra: " + ", ".join(changed))
else:
    print("pcie qcom extra: nothing to do")
