#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""qcom-kona-compatible.py — match SM8250 drivers after the stock dtbo overlay.

The Mi 10 bootloader applies the stock dtbo, which replaces the root
``compatible`` of our DTB with ``"qcom,kona-mtp", "qcom,kona"``.  Drivers that
match the SoC on ``qcom,sm8250`` therefore never bind:

  * ``cpufreq-dt-platdev`` does not blocklist the SoC, so a ``cpufreq-dt``
    device is created and stays in deferred probe forever
    (``cpufreq-dt: probe with driver cpufreq-dt failed with error -17``);
  * ``qcom_pd_mapper`` finds no domain table and logs
    ``PDM: no support for the platform``, so the ADSP audio power domain never
    comes up and APR registers no services (no audio).

Adding ``qcom,kona`` to both tables fixes the root cause instead of working
around it with the opt-in ``ARM_QCOM_CPUFREQ_HW``/``QCOM_CPR`` config.

Credit: same two hunks as patch 0010 of miercolesvd/nura-mi10-umi-port.

Run after the kernel tree exists:
    python3 patches/qcom-kona-compatible.py
"""
import io
import os
import sys

TREE = os.environ.get("TREE", "/root/linux")
PLATDEV = os.path.join(TREE, "drivers/cpufreq/cpufreq-dt-platdev.c")
PDMAP = os.path.join(TREE, "drivers/soc/qcom/qcom_pd_mapper.c")

MARK = "qcom,kona"

PLATDEV_OLD = """\t{ .compatible = "qcom,sm8250", },
\t{ .compatible = "qcom,sm8350", },
"""

PLATDEV_NEW = """\t{ .compatible = "qcom,sm8250", },
\t/* SM8250 after a downstream dtbo overlay (umi: "qcom,kona-mtp") */
\t{ .compatible = "qcom,kona", },
\t{ .compatible = "qcom,sm8350", },
"""

PDMAP_OLD = """\t{ .compatible = "qcom,apq8096", .data = msm8996_domains, },
"""

PDMAP_NEW = """\t{ .compatible = "qcom,apq8096", .data = msm8996_domains, },
\t/*
\t * Downstream Qualcomm bootloaders apply the stock dtbo, which replaces
\t * the root compatible of SM8250 phones (e.g. Xiaomi Mi 10) with
\t * "qcom,kona-mtp", "qcom,kona".  Match it so the ADSP power domains are
\t * mapped; otherwise APR registers no services and audio never starts.
\t */
\t{ .compatible = "qcom,kona", .data = sm8250_domains, },
"""


def patch(path, old, new, label):
    if not os.path.isfile(path):
        sys.exit("missing %s (set TREE to the kernel tree)" % path)
    src = io.open(path, encoding="utf-8").read()
    if MARK in src:
        print("%s: already patched" % label)
        return
    if old not in src:
        sys.exit("%s: anchor not found; source differs from v6.12" % label)
    io.open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
    print("%s: qcom,kona added" % label)


patch(PLATDEV, PLATDEV_OLD, PLATDEV_NEW, "cpufreq-dt-platdev")
patch(PDMAP, PDMAP_OLD, PDMAP_NEW, "qcom_pd_mapper")
