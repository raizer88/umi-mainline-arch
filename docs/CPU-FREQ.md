# CPU frequency and benchmark (Xiaomi Mi 10 / umi)

Status: **works with the opt-in cpufreq/CPR kernel** (2026-11-15).
The default bring-up kernel still leaves cpufreq/CPR off; the experimental
fragment enables them.

## What the kernel exposes

With `ARM_QCOM_CPUFREQ_HW=y` and `QCOM_CPR=y`:

```
/sys/devices/system/cpu/cpufreq/
  policy0  -> CPUs 0-3  (Cortex-A55 / Kryo-4XX-Silver)
  policy4  -> CPUs 4-6  (Cortex-A77 gold)
  policy7  -> CPU 7     (Cortex-A77 prime)
```

| Policy | CPUs | Driver | Min | Max | Available governors |
|---|---|---|---|---|---|
| policy0 | 0-3 | `qcom-cpufreq-hw` | 300.0 MHz | **1804.8 MHz** | ondemand, userspace, performance, schedutil |
| policy4 | 4-6 | `qcom-cpufreq-hw` | 710.4 MHz | **2419.2 MHz** | same |
| policy7 | 7 | `qcom-cpufreq-hw` | 844.8 MHz | **2841.6 MHz** | same |

These are the Snapdragon 865 SM8250 maximums for the three clusters. The
default governor is `schedutil`.

`dmesg` still shows:

```
cpufreq-dt cpufreq-dt: failed register driver: -17
```

That is expected: the generic `cpufreq-dt` loses the registration race to
`qcom-cpufreq-hw` (the QCOM EPSS driver).

## Does schedutil reach the maximum?

Yes. Under `openssl speed -evp sha256 -multi 8`, the three policies went from
idle to the hardware maximum within one sample:

```
sample  policy0    policy4    policy7
1       1248000    1574400    1401600
2       1804800    2419200    2841600
3..12   1804800    2419200    2841600
```

After the load stops, `schedutil` drops back to 787.2 / 940.8 / 844.8 MHz.
So the correct autoscaling is working; no `performance` pin is needed. If the
device must stay at max for a special workload, write `performance` to each
`scaling_governor`; for this always-powered device `schedutil` is already
reaching max under load.

## Benchmark: fixed-clock vs cpufreq

`openssl speed -evp sha256`, 16384-byte block, 8 processes:

| Child | CPU cluster | Fixed-clock kernel (no cpufreq) | cpufreq/CPR kernel |
|---|---|---|---|
| 1, 2, 7 | A55 | ~643 MB/s | **~765 MB/s** |
| 4, 5, 6 | A77 gold | ~446 MB/s | **~1519 MB/s** |
| 3 | A77 prime | ~525 MB/s | **~1784 MB/s** |
| **aggregate** | all 8 | **4.44 GB/s** | **9.39 GB/s** |

The A77 clusters are now clearly faster than the A55s, and the aggregate is
about 2.1x the fixed-clock result. The prime/gold ratio is 1.784 / 1.519 = 1.17,
matching 2.8416 / 2.4192.

## How to build the opt-in kernel

The default `config/umi.config` keeps CPR/cpufreq off. The experimental fragment
is `config/umi-cpufreq.config`:

```
CONFIG_QCOM_CPR=y
CONFIG_ARM_QCOM_CPUFREQ_HW=y
# CONFIG_ARM_QCOM_CPUFREQ_NVMEM is not set
```

Build with the opt-in flags:

```sh
EXTRA_CONFIG=config/umi-cpufreq.config ALLOW_CPUFREQ=1 \
TREE=/root/linux JOBS=16 sh scripts/build.sh
```

`scripts/build.sh` appends `EXTRA_CONFIG` after `config/umi.config` and skips
the `check_n QCOM_CPR/ARM_QCOM_CPUFREQ_HW` guard only when
`ALLOW_CPUFREQ=1`. The `config-audit.py` still lists them as "must not" for the
initial bring-up; this is an explicit experiment, not the default path.

Pack the boot image with the normal Arch initramfs:

```sh
python3 tools/pack-umi.py \
  --dtb out/sm8250-xiaomi-umi-wifi.dtb \
  --initramfs out/initramfs.cpio.gz \
  -o out/boot-umi-cpufreq.img
```

The tested image is `boot-umi-cpufreq.img` (md5 `c35064d91eb1d845b131dcdbd7007779`).
Keep a known-good rollback: `out/boot-before-cpufreq.img`
(md5 `6f72e422a5a2c9984ed70be4fe8c8294`). On this unit the `boot` partition is
`/dev/sde50` (128 MB; the image occupies the first ~16 MB). TWRP can restore it
with `dd` if the CPR kernel does not boot.

## Why this works

- `qcom-cpufreq-hw` drives the EPSS frequency domains and exposes the OPP
  tables from the SM8250 device tree.
- `QCOM_CPR` drives the CPU CPR voltage table, as Android does. This is the part
  that changes CPU voltage; it is why the max OPPs are stable. Keep the rollback
  image: a wrong CPR/OPP combination can hang or reset the device.
- The `cpr`/`epss`/`opp` nodes and the `operating-points-v2` tables are already
  in the mainline `sm8250.dtsi`; no DTS change was needed.
- The generic `cpufreq-dt` is still built but loses the race with `-17`.

## Notes

- `sysbench`/`perf` could not be installed: the current Arch ARM repo wants
  `openssl 4.1.0`, which breaks `pacman`, `curl`, `sudo` and `sshd` on this
  rootfs. `openssl speed` is the benchmark used here.
- The short run did not show thermal throttling; the device is on USB power.
- The charger `bq2597x` logs a `FAULT_STAT=0x80` in `dmesg`; unrelated to the
  CPU frequency test.
- The USB RNDIS link came up as `usb0` at 192.168.42.1, but the Windows-side
  `sshd` connection was unreliable after the kernel swap; the SSH tests above use
  the WiFi address 192.168.1.253. The USB serial console remained usable at the
  login prompt.

## Reproduce

```sh
lscpu
ls -l /sys/devices/system/cpu/cpufreq
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  echo "== $p"
  cat "$p/scaling_driver" "$p/scaling_governor" \
      "$p/cpuinfo_min_freq" "$p/cpuinfo_max_freq" \
      "$p/scaling_cur_freq" "$p/scaling_available_frequencies"
done

openssl speed -evp sha256 -multi 8 -seconds 10
# sample scaling_cur_freq during the load; all three must reach their max
```
