# CPU frequency and benchmark (Xiaomi Mi 10 / umi)

Measured on 2026-11-15 on the running Arch Linux ARM install (kernel
`6.12.94-umi`, 8 cores online). `openssl` is the only benchmark available
without upgrading `openssl`; `sysbench`/`perf` could not be installed because
the current Arch ARM repo wants `openssl 4.1.0`, which breaks `pacman`, `curl`,
`sudo` and `sshd` on this rootfs.

## What the kernel exposes

```
$ ls /sys/devices/system/cpu/cpufreq
# empty: no cpufreq policies at all

$ dmesg | grep cpufreq
platform cpufreq-dt: deferred probe pending: (reason unknown)
```

Config:

```
CONFIG_CPUFREQ_DT=y
CONFIG_CPUFREQ_DT_PLATDEV=y
# CONFIG_ARM_QCOM_CPUFREQ_HW is not set
# CONFIG_ARM_QCOM_CPUFREQ_NVMEM is not set
# CONFIG_QCOM_CPR is not set
```

The device tree does contain `operating-points-v2` for every CPU
(`/proc/device-tree/cpus/cpu@*/operating-points-v2`), but there is no CPU PLL
in `/sys/kernel/debug/clk/clk_summary` (only `gcc_cpuss_ahb_clk_src` at 19.2 MHz;
`gpll0` etc. are GPU/NPU clocks). The APSS/cpufreq provider is the missing piece.

**Consequence:** Linux does not manage CPU frequency at all. The cores stay at
whatever frequency the bootloader programmed; the kernel cannot raise, lower or
report it. This is not a governor setting and cannot be fixed with `cpupower`.

## Topology

```
CPU0-3:  ARM part 0x805  (Kryo-4XX-Silver / Cortex-A55)
CPU4-7:  ARM part 0xd0d  (Cortex-A77)
```

All eight are online. `lscpu` reports two groups of four cores and no CPU MHz
field.

## Benchmark

`openssl speed -evp sha256` (SHA-256 with ARMv8 crypto extensions), 16384-byte
block, one process pinned with `taskset` per core:

| Pinned CPU | Core | 16384-byte SHA-256 |
|---|---|---|
| 0 | A55 | 644.0 MB/s |
| 4 | A77 | 446.0 MB/s |
| 7 | A77 (prime) | 528.3 MB/s |

All eight cores with `openssl speed -evp sha256 -multi 8 -seconds 2`:

| child | 16384-byte SHA-256 |
|---|---|
| 0 | 643.2 MB/s |
| 1 | 643.5 MB/s |
| 2 | 643.5 MB/s |
| 3 | 446.0 MB/s |
| 4 | 445.8 MB/s |
| 5 | 445.7 MB/s |
| 6 | 642.6 MB/s |
| 7 | 525.3 MB/s |
| **aggregate** | **4.436 GB/s** |

The aggregate is the sum of the eight children, so the scheduler does use all
eight cores. The prime/gold ratio (525.3 / 445.8 = 1.178) is close to the
Snapdragon 865 clocks 2.84 / 2.42 = 1.174, which is consistent with the
bootloader having left the big cluster at 2.42 GHz and the prime at 2.84 GHz.
However, the A77 numbers are *below* the A55 (644 MB/s), so the absolute
frequency cannot be confirmed without a PMU/cpufreq source. It may be a
per-clock crypto difference, or the big cluster may be lower than 2.42 GHz.
What is certain is that Linux is not scaling it.

Idle thermal zones read 28.1-31.2 C; no thermal throttling was observed during
the short benchmark.

## What would be needed to really use/verify the full range

A kernel with the QCOM CPU frequency/CPR stack:

```
CONFIG_ARM_QCOM_CPUFREQ_HW=y
CONFIG_QCOM_CPR=y
CONFIG_ARM_QCOM_CPUFREQ_NVMEM=y   # if using the NVMEM OPP path
```

plus the `cpufreq_hw`/APSS node and the OPP tables wired to the CPU clock
provider. The base repo's `config-audit.py` marks these as "must not" for the
initial bring-up (they can hang the boot), so this should be a separate test
kernel with a known-good recovery image. Once `cpufreq` appears, use
`performance` for a max test and `schedutil` for normal use, and re-run the
benchmark to compare.

## Reproduce

```sh
lscpu
dmesg | grep -i cpufreq
cat /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq 2>/dev/null
taskset -c 0 openssl speed -evp sha256 -seconds 3
taskset -c 4 openssl speed -evp sha256 -seconds 3
taskset -c 7 openssl speed -evp sha256 -seconds 3
openssl speed -evp sha256 -multi 8 -seconds 2
```
