#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""ufs-disable-lpm.py — add qcom,disable-lpm opt-out to ufs-qcom.

umi's QCA6390 WiFi association triggers ufshcd_uic_hibern8_exit() -110
("pwr ctrl cmd 0x18 completion timeout"), the UFS link is declared broken and
the kernel panics on hung_task.  ufs-qcom unconditionally enables clock gating,
hibern8-with-clk-gating, clock scaling and runtime autosuspend; there is no DT
or cmdline knob in 6.12.  This adds one, used by &ufs_mem_hc { qcom,disable-lpm; }.

Run after the kernel tree exists:
    python3 patches/ufs-disable-lpm.py
"""
import io
import sys

P = "/root/linux/drivers/ufs/host/ufs-qcom.c"

src = io.open(P, encoding="utf-8").read()
if "qcom,disable-lpm" in src:
    print("already patched")
    sys.exit(0)

old = """static void ufs_qcom_set_caps(struct ufs_hba *hba)
{
\thba->caps |= UFSHCD_CAP_CLK_GATING | UFSHCD_CAP_HIBERN8_WITH_CLK_GATING;
\thba->caps |= UFSHCD_CAP_CLK_SCALING | UFSHCD_CAP_WB_WITH_CLK_SCALING;
\thba->caps |= UFSHCD_CAP_AUTO_BKOPS_SUSPEND;
\thba->caps |= UFSHCD_CAP_WB_EN;
\thba->caps |= UFSHCD_CAP_AGGR_POWER_COLLAPSE;
\thba->caps |= UFSHCD_CAP_RPM_AUTOSUSPEND;
}
"""

new = """static void ufs_qcom_set_caps(struct ufs_hba *hba)
{
\t/*
\t * umi: QCA6390 association can make hibern8 exit fail (-110), after
\t * which the core keeps using a dead UniPro link and hung_task panics.
\t * Allow DT to keep the UFS controller awake.
\t */
\tif (!of_property_read_bool(hba->dev->of_node, "qcom,disable-lpm")) {
\t\thba->caps |= UFSHCD_CAP_CLK_GATING | UFSHCD_CAP_HIBERN8_WITH_CLK_GATING;
\t\thba->caps |= UFSHCD_CAP_CLK_SCALING | UFSHCD_CAP_WB_WITH_CLK_SCALING;
\t\thba->caps |= UFSHCD_CAP_AUTO_BKOPS_SUSPEND;
\t\thba->caps |= UFSHCD_CAP_AGGR_POWER_COLLAPSE;
\t\thba->caps |= UFSHCD_CAP_RPM_AUTOSUSPEND;
\t}
\thba->caps |= UFSHCD_CAP_WB_EN;
}
"""

if old not in src:
    sys.exit("ufs_qcom_set_caps block not found; source differs from v6.12")

io.open(P, "w", encoding="utf-8").write(src.replace(old, new, 1))
print("ufs qcom caps: qcom,disable-lpm opt-out added")
