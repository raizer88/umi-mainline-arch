#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""cs35l41-ignore-pup.py — don't fail power-up when PUP/PDN status never comes.

Both CS35L41 amps on the Mi 10 power up and play, but never raise the PUP/PDN
done bits in CS35L41_IRQ1_STATUS1. The driver polls for 100 ms and then fails
the DAPM event with -ETIMEDOUT, so the sound card never starts.

Downgrade both polls to a warning and carry on. Same idea as patch 0007 of
miercolesvd/nura-mi10-umi-port.

Run after the kernel tree exists:
    python3 patches/cs35l41-ignore-pup.py
"""
import io
import os
import sys

TREE = os.environ.get("TREE", "/root/linux")
P = os.path.join(TREE, "sound/soc/codecs/cs35l41-lib.c")

MARK = "no PUP/PDN status"

OLD = """\t\tret = regmap_read_poll_timeout(regmap, CS35L41_IRQ1_STATUS1,
\t\t\t\t\tint_status, int_status & pup_pdn_mask,
\t\t\t\t\t1000, 100000);
\t\tif (ret)
\t\t\tdev_err(dev, "Enable(%d) failed: %d\\n", enable, ret);
"""

NEW = """\t\tret = regmap_read_poll_timeout(regmap, CS35L41_IRQ1_STATUS1,
\t\t\t\t\tint_status, int_status & pup_pdn_mask,
\t\t\t\t\t1000, 100000);
\t\tif (ret) {
\t\t\t/*
\t\t\t * Both amps on the Xiaomi Mi 10 never raise the PUP/PDN
\t\t\t * done bits, yet power up and play. Don't fail the DAPM
\t\t\t * event over it.
\t\t\t */
\t\t\tdev_warn(dev, "Enable(%d): no PUP/PDN status (%d), continuing\\n",
\t\t\t\t enable, ret);
\t\t\tret = 0;
\t\t}
"""


def main():
    if not os.path.isfile(P):
        sys.exit("missing %s (set TREE to the kernel tree)" % P)
    src = io.open(P, encoding="utf-8").read()
    if MARK in src:
        print("already patched")
        return
    count = src.count(OLD)
    if count == 0:
        sys.exit("anchor not found; source differs from v6.12")
    io.open(P, "w", encoding="utf-8").write(src.replace(OLD, NEW))
    print("cs35l41: %d PUP/PDN poll(s) downgraded to a warning" % count)


main()
