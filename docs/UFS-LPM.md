<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# UFS low-power states cause a `hung_task` panic on `umi`

## Symptom

On kernel 6.12.94, with the QCA6390 WiFi active, the UFS controller could hang
and the kernel panic on blocked tasks. The persistent console (`pstore`) showed:

```text
ufshcd-qcom 1d84000.ufshc: pwr ctrl cmd 0x18 with mode 0x0 completion timeout
ufshcd-qcom 1d84000.ufshc: UFS Host state=1
ufshcd-qcom 1d84000.ufshc: Clk gate=1
ufshcd-qcom 1d84000.ufshc: ufshcd_uic_hibern8_exit: hibern8 exit failed. ret = -110
ufshcd-qcom 1d84000.ufshc: ufshcd_err_handler started; HBA state eh_fatal; link is broken
```

followed by blocked `jbd2/sda34`, `blk_mq_get_tag`, `systemd-journal`, the WiFi
userspace task, RCU stalls and:

```text
Kernel panic - not syncing: hung_task: blocked tasks
```

The DPU frame-done timeouts seen on the screen are secondary noise once the
system is wedged.

## Root cause

`drivers/ufs/host/ufs-qcom.c` unconditionally enables:

```c
UFSHCD_CAP_CLK_GATING | UFSHCD_CAP_HIBERN8_WITH_CLK_GATING
UFSHCD_CAP_CLK_SCALING | UFSHCD_CAP_WB_WITH_CLK_SCALING
UFSHCD_CAP_AUTO_BKOPS_SUSPEND
UFSHCD_CAP_AGGR_POWER_COLLAPSE
UFSHCD_CAP_RPM_AUTOSUSPEND
```

The QCA6390 bring-up and the UFS device share several PMIC rails (in particular
the 1.8 V S4A used by UFS `vccq2` and QCA6390 `vddio`). Under association/RF
load the UFS `hibern8` exit can time out. The UFS core then continues using a
dead UniPro link, the block layer never completes I/O, and the hung-task
detector panics.

## Fix used in this branch

### 1. Device-tree opt-out

`dts/sm8250-xiaomi-umi-common.dtsi`:

```dts
&ufs_mem_hc {
    ...
    qcom,disable-lpm;
    status = "okay";
};
```

### 2. Driver patch

`patches/ufs-disable-lpm.py` adds the property check and clears the UFS LPM
caps when it is present:

```c
static void ufs_qcom_set_caps(struct ufs_hba *hba)
{
    if (!of_property_read_bool(hba->dev->of_node, "qcom,disable-lpm")) {
        hba->caps |= UFSHCD_CAP_CLK_GATING | UFSHCD_CAP_HIBERN8_WITH_CLK_GATING;
        hba->caps |= UFSHCD_CAP_CLK_SCALING | UFSHCD_CAP_WB_WITH_CLK_SCALING;
        hba->caps |= UFSHCD_CAP_AUTO_BKOPS_SUSPEND;
        hba->caps |= UFSHCD_CAP_AGGR_POWER_COLLAPSE;
        hba->caps |= UFSHCD_CAP_RPM_AUTOSUSPEND;
    }
    hba->caps |= UFSHCD_CAP_WB_EN;
}
```

Apply after the tree exists:

```sh
python3 patches/ufs-disable-lpm.py       # expects /root/linux
```

or use `patches/apply-umi-patches.sh`, which applies the UFS and PCIe patches in
order.

### 3. Verify

After boot:

```sh
ls /sys/class/devfreq | grep ufs || echo NO_UFS_DEVFREQ
cat /sys/devices/platform/soc@0/1d84000.ufshc/power/runtime_status
dmesg | grep -iE 'hibern8|pwr ctrl cmd' || true
```

On the working unit: no UFS devfreq entry, runtime status `active`, no hibern8
timeout while WiFi is active.

## What was tried and did not fix it

- Disabling runtime PM only (`echo on > .../power/control`) and setting the UFS
  devfreq to a fixed frequency: the clock-gating/hibern8 caps remained, and WiFi
  still triggered the failure.
- Disabling only WiFi power save: no effect on the UFS failure.
- The final reliable combination is the DT opt-out + driver patch above, plus the
  WiFi delayed-start workaround in [WIFI-WORKAROUND.md](WIFI-WORKAROUND.md).

## Trade-off

`qcom,disable-lpm` keeps the UFS controller in higher-power states. It is a
reliability workaround for this bring-up, not an upstream-quality power fix. The
property is not part of upstream 6.12; it exists only after applying the patch.

## Relevant upstream context

- `ufs_qcom_set_caps()` in v6.12 has no DT or module-parameter opt-out for these
  caps.
- `ufs_qcom_clk_scale_notify()` calls `ufshcd_uic_hibern8_exit()` and historically
  ignored its return value; a 2026 patch proposes returning the error instead of
  continuing with a dead link. That patch is not in 6.12.y as of this writing.
- There was no public SM8250/QCA6390-vs-UFS report found during this bring-up;
  the shared-rail/power-draw explanation is the working hypothesis, confirmed
  operationally by the fix and by the absence of the failure after it.
