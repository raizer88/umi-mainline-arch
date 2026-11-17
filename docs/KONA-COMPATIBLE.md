<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `qcom,kona`: the stock dtbo rewrites our root compatible

## Symptom

`cpufreq-dt` never binds and stays in deferred probe forever:

```text
cpufreq-dt cpufreq-dt: failed register driver: -17
cpufreq-dt cpufreq-dt: probe with driver cpufreq-dt failed with error -17
platform c440000.spmi:pmic@2:typec@1500: deferred probe pending: (reason unknown)
```

With `CONFIG_QCOM_Q6V5_PAS` (ADSP/audio) the same root cause also stops audio:

```text
PDM: no support for the platform
apr: no services registered
```

## Cause

The Mi 10 bootloader applies the stock `dtbo`, and those overlays **replace the
root `model` and `compatible`** of our DTB with:

```text
qcom,kona-mtp, qcom,kona
```

Every driver that matches the SoC on `qcom,sm8250` therefore misses:

| Driver | Table | Effect when missing |
|---|---|---|
| `cpufreq-dt-platdev` | blocklist | `cpufreq-dt` device is created, then deferred-probes forever |
| `qcom_pd_mapper` | `qcom_pdm_domains` | no PD table → ADSP audio domain never comes up, APR registers no services |

This is the same finding as patch `0010` of
[`miercolesvd/nura-mi10-umi-port`](https://github.com/miercolesvd/nura-mi10-umi-port):
their bootloader behaves identically.

## Fix

Two entries, no DT change:

```c
/* drivers/cpufreq/cpufreq-dt-platdev.c, blocklist[] */
{ .compatible = "qcom,sm8250", },
{ .compatible = "qcom,kona", },	/* SM8250 after a downstream dtbo overlay */
```

```c
/* drivers/soc/qcom/qcom_pd_mapper.c, qcom_pdm_domains[] */
{ .compatible = "qcom,kona", .data = sm8250_domains, },
```

Apply with the in-tree script (idempotent, honours `TREE`):

```sh
python3 patches/qcom-kona-compatible.py          # TREE defaults to /root/linux
TREE=/root/linux python3 patches/qcom-kona-compatible.py
```

`patches/apply-umi-patches.sh` runs it together with the PCIe and UFS patches.

## Why it matters

Blocklisting `qcom,kona` in `cpufreq-dt-platdev` is the **root-cause** fix for
the deferred-probe CPU node. The opt-in `config/umi-cpufreq.config`
(`ARM_QCOM_CPUFREQ_HW` + `QCOM_CPR`) is a working alternative, but it only fixes
the symptom: the stale `cpufreq-dt` device and the missing PD map stay.

With the entry in place, `cpufreq-dt` is never instantiated on this board and
the deferred-probe warning disappears.

## Verify after boot

```sh
dmesg | grep -i cpufreq-dt        # expect: nothing
journalctl -k -b | grep -i 'PDM: no support'   # expect: nothing
ls /sys/class/devfreq | grep ufs || true
```

If `ARM_QCOM_CPUFREQ_HW` is enabled, `/sys/devices/system/cpu/cpufreq/policy*`
still exists and `schedutil` still scales — see [CPU-FREQ.md](CPU-FREQ.md).

## Note on the root compatible

The DTB still declares `compatible = "xiaomi,umi", "qcom,sm8250"`. The
bootloader's overlay is what rewrites it at load time, so the source DTS stays
correct for upstream and the kernel tables carry the downstream alias. Do not
"fix" this by changing the DTS to `qcom,kona`: it would break the ABL
board-id/msm-id match.
