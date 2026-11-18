<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Audio on the Mi 10 (`umi`)

Status: **playback does not work: no audio reaches the speakers.** The card
binds, both CS35L41 amps bind on I2C, the ADSP runs, the whole DAPM chain powers
up during a stream, and the DSP acknowledges the MI2S clock command — yet the
amps never raise `PUP_DONE` and never enable their output stage (`0x742c`), so
nothing comes out. Everything tried and measured is recorded in
[Not working: playback has no valid frames](#not-working-playback-has-no-valid-frames)
at the end of this file. The pieces below are what the hardware needs, read out
of *this* unit's silicon and stock `dtbo`, not copied from another board.

## Topology

```text
Playback  APPS -> ADSP (q6asm/q6afe) -> TERTIARY MI2S (mi2s2: gpio133/134/135/137)
          -> two CS35L41 amps (I2C control, I2S audio) -> receiver + speaker
Capture   WCD938x over SoundWire (swr1 = RX, swr2 = TX)
          + LPASS VA macro DMICs (VA Capture link)
```

| Part | Bus | Address | Notes |
|---|---|---|---|
| CS35L41 (bottom speaker, prefix `RCV`) | `i2c3` (`qupv3_se3`) | `0x40` | IRQ GPIO 113 |
| CS35L41 (top receiver, prefix `LCV`) | `i2c3` | `0x42` | IRQ GPIO 112, `cirrus,right-channel-amp` |
| both amps | — | reset GPIO 114 shared | |
| WCD938x | SoundWire | `0:4` (rx) / `0:3` (tx) | reset GPIO 32, micbias 2.75 V |

**Variant warning.** A CSOT unit of the same phone puts the second amp at
`0x42`. The values here come from the Samsung unit's `fragment@125`; check
`/proc/device-tree` (or the stock dtbo) before assuming either.

## Files

| Path | What |
|---|---|
| `dts/sm8250-xiaomi-umi-audio.dtsi` | sound card, dai links, amps, WCD938x, SoundWire, pinctrl |
| `patches/cs35l41-ignore-pup.py` | PUP/PDN poll becomes a warning |
| `deploy/install-audio-firmware.sh` | copies ADSP firmware out of the `modem` partition |
| `config/umi.config` | `CONFIG_SND_SOC_CS35L41{,_I2C,_LIBRARY}=m` |

## Why the patch is needed

Both amps power up and play, but never raise the PUP/PDN done bits in
`CS35L41_IRQ1_STATUS1`. The driver polls for 100 ms and then fails the DAPM
event with `-ETIMEDOUT`, so the card never starts:

```text
cs35l41-codec: Enable(1) failed: -110
```

`patches/cs35l41-ignore-pup.py` downgrades both polls (INT_BOOST and the
default case) to `dev_warn` and carries on. Same approach as patch 0007 of
`miercolesvd/nura-mi10-umi-port`.

## ADSP firmware

Not in this repository: it ships in the phone's own `modem` partition.

```text
/dev/disk/by-partlabel/modem -> image/adsp.mdt, adsp.b00..b18
                                image/adspr.jsn, image/adspua.jsn
```

`deploy/install-audio-firmware.sh` copies them to
`/lib/firmware/qcom/sm8250/xiaomi/umi/`, which is what the DTS
`&adsp { firmware-name = ... }` names.

The `.jsn` files matter as much as the firmware: `qcom_pd_mapper` reads them to
publish the ADSP audio power domains. Without them the log says
`PDM: no support for the platform` and the card never binds — which is also why
`qcom,kona` had to be added to `qcom_pdm_domains` (see
[KONA-COMPATIBLE.md](KONA-COMPATIBLE.md)).

## Modules

```sh
modprobe qcom_pd_mapper qcom_q6v5_pas
modprobe q6core q6afe q6afe-dai q6afe-clocks q6asm q6asm-dai q6adm q6routing
modprobe snd-soc-cs35l41-i2c snd-soc-sm8250
```

The q6 components are not reliably auto-loaded by modalias, so the card defers
once and never retries. `deploy/umi-audio-init.sh` (installed as the
`umi-audio-init` unit) does all of it: modules, the routing below, and the
levels.

## Routing is required

`hw:0,0` is the `MultiMedia1` **frontend**; it has no backend until this route
is on, and `hw_params` fails with `-EINVAL` until it is:

```sh
amixer -c 0 sset 'TERT_MI2S_RX Audio Mixer MultiMedia1' on
```

The RX controls are named the other way round from the TX ones, which is easy to
miss:

```text
RX:  "<port> Audio Mixer MultiMediaN"     e.g. TERT_MI2S_RX Audio Mixer MultiMedia1
TX:  "MultiMediaN Mixer <port>"           e.g. MultiMedia1 Mixer TERT_MI2S_TX
```

## Levels

The driver defaults (`913/913` digital, `20/20` analog) are loud enough to trip
`cs35l41 3-0042: Over temperature warning`. The init script sets 42 % and 60 %.
These controls are **not** simple controls, so `sset <name>` fails — use
`cset name='...'`, and address them by name rather than numid:

```sh
amixer -c 0 cset name='LCV Digital PCM Volume' 42%
amixer -c 0 cset name='RCV Digital PCM Volume' 42%
amixer -c 0 cset name='LCV Analog PCM Volume'  60%
amixer -c 0 cset name='RCV Analog PCM Volume'  60%
```

Override at boot with `DIGITAL_PCT=` / `ANALOG_PCT=` in the unit's
`Environment=` lines.

## Verify

```sh
dmesg | grep -iE 'adsp|PDM|apr|cs35l41|sm8250-sndcard'
# expect: adsp ... is now online
#         PDM: service 'avs/audio' ...
#         cs35l41 ... probe
aplay -l                 # the card should be listed
speaker-test -c2 -t wav  # left = bottom speaker, right = top receiver
```

If the card does not appear:

1. `cat /sys/class/remoteproc/*/state` — ADSP must be `running`.
2. `dmesg | grep 'PDM: no support'` — a hit means the `.jsn` files or the
   `qcom,kona` entry are missing.
3. `dmesg | grep 'ASM_DATA_CMD_WRITE_V2'` — playback fails with `ENOTREADY`
   when `&q6asmdai` has no `iommus` (the DTS sets `apps_smmu 0x1801`).
4. `i2cdetect -y 3` — the amps must answer at `0x40` and `0x42` (`0x40` shows as
   `UU` once the driver has bound it, `0x42` stays visible).

## Known gaps

- **Playback produces no sound at all** — see the section below.
- USB-C analogue headsets (WCD938x path) untested.
- Earpiece-only routing for calls depends on the modem, which is not ported.
- The receiver is driven as a normal speaker channel; call audio would need the
  voice call dai links.

## Not working: playback has no valid frames

Measured on 18 Nov 2026, kernel `6.12.94-umi #6`, while a 440 Hz tone ran
through PipeWire (PCM state `RUNNING`, `hw_ptr` advancing at 48000 frame/s).

The software chain looks healthy:

```text
TERT_MI2S_RX                        On    (backend DAI)
Tertiary MI2S Playback              On
TERT_MI2S_RX Audio Mixer            On
RCV/LCV Speaker                     On  in 1 out 1
RCV/LCV SPK, Main AMP, CLASS H      On
```

Reading the amps over I2C (not the driver's regmap cache) gives, on `0x42`:

| register | value | meaning |
|---|---|---|
| `0x2014` | `0x00000001` | `GLOBAL_EN` set |
| `0x2018` | `0x00000021` | `Main AMP` + boost enabled |
| `0x201c` | `0x01000010` | `CLASS H` on |
| `0x4800` | `0x00010000` | `ASPRX1` enabled |
| `0x2d10` | `0x00054034` | FS monitor reads a ratio (reset value `0x00020016`) |
| `0x10010` | `0x00400000` | **`PUP_DONE` (bit 24) never arrives** |
| `0x742c` | `0x00000000` | **output stage never enabled** |

`0x742c` is written only on the `EXT_BOOST` path (`safe_to_active_en_spk`
sets it to `0xf9`); with `boost-type = <0>` (`INT_BOOST`) the driver never
touches it. Writing it by hand has no effect: it sits behind the test key.

The root cause is one level up:

```text
$ grep TER_MI2S /sys/kernel/debug/clk/clk_summary      # during playback
 LPASS_CLK_ID_TER_MI2S_EBIT    en=0
 LPASS_CLK_ID_TER_MI2S_IBIT    en=0
```

**This row is a red herring, not the root cause.** `q6afe_mi2s_set_sysclk()`
does not go through the Linux clock framework at all: it sends an AFE command
to the DSP (`q6afe_port_set_sysclk()` -> `q6afe_set_lpass_clock_v2()`). The
`clk_summary` entries come from the separate `q6afe_clocks` provider and are
not on the playback path — `q6afe_clocks` is loaded (13 references) and the
`deviceless` consumer is normal.

The command itself is correct; instrumenting `q6afe_port_set_sysclk()` showed

```text
qcom-q6afe aprsvc:service:4:4: umi-instr-afe:
    clk_id=0x104 freq=1536000 enable=1 ret=0
```

`afe_apr_send_pkt()` really waits for the response and reads `result->status`,
so `ret=0` means the DSP answered `status=0`. The DSP acknowledges the clock
command and the amps still never see valid frames.

`TST_FS_MON0` reading a different value during playback (`0x00054034` vs the
`0x00020016` the driver writes) is **not** proof that a bit clock reaches the
amp either: it is a configuration register whose live field changes.

`cs35l41-ignore-pup.py` hides the symptom: it turns the `-ETIMEDOUT` from the
missing `PUP_DONE` into a warning. The comment it inherited from the reference
port says the amps "power up and play" regardless; on this unit they do not,
so the patch currently masks a real failure.

### Audio stack: UCM (fixed)

The card has a working UCM, taken from `miercolesvd/nura-mi10-umi-port`. It
must be installed under the **driver** name, with `Syntax 6`:

```text
/usr/share/alsa/ucm2/conf.d/sm8250/Xiaomi Mi 10.conf
/usr/share/alsa/ucm2/Xiaomi/umi/HiFi.conf
```

```sh
alsaucm -c sm8250 list _verbs      # 0: HiFi   Default
```

With it, WirePlumber builds a real sink instead of the broken fallback
(`audio.channels = 64` before):

```text
alsa_output.platform-sound.HiFi__Speaker__sink   s24-32le 2ch 48000Hz
```

The `api.alsa.use-acp = false` workaround in `deploy/wireplumber-umi-alsa.conf`
is therefore obsolete: rename that file to `.disabled` (or drop it) once the
UCM is installed.

### The DSP acknowledges the clock command

Instrumented `sm8250_snd_startup()` and `q6afe_port_set_sysclk()` on the device
(18 Nov 2026, kernel `6.12.94-umi #6`, modules rebuilt and loaded):

```text
q6afe-dai ...: umi-instr: set_sysclk -> 0
q6afe-dai ...: umi-instr: set_fmt -> 0
qcom-q6afe aprsvc:service:4:4: umi-instr-afe:
    clk_id=0x104 freq=1536000 enable=1 ret=0
```

- `clk_id = 0x104` is `Q6AFE_LPASS_CLK_ID_TER_MI2S_IBIT` — the right clock.
- `freq = 1536000` is `MI2S_BCLK_RATE` — 48 kHz × 32 bit.
- `enable = 1`, and `q6afe_set_lpass_clock_v2()` returns 0.

So the kernel builds the correct AFE clock command **and the DSP accepts it**.
`afe_apr_send_pkt()` waits for the response and inspects `result->status`, so
`ret=0` means the DSP answered `status=0` — it is not a silently ignored call.

The `clk_summary` `en=0` shown above is a red herring: this path never touches
the Linux clock framework.

## Everything tried, and what it ruled out

| attempt | result |
|---|---|
| Speaker widget routes (`"RCV Speaker", "RCV SPK"`) | **real bug, fixed**: without them the widgets stayed `Off in 0` |
| UCM installed under the driver name, `Syntax 6` | **real bug, fixed**: WirePlumber now builds a 2ch `HiFi__Speaker__sink` instead of an 8ch fallback |
| `cirrus,asp-sdout-hiz` 3 (stock dtbo) vs 1 (reference port) | **3 breaks the DAPM chain** (`LCV SPK` stays `Off`, `CLASS H` off); 1 is required here |
| `cirrus,boost-type = <0>` | no effect, reverted |
| amp at `0x41` (stock dtbo) vs `0x42` | `0x41` does not ACK on I2C; `0x42` returns the Cirrus ID `0x35a40` — **the stock dtbo is for the CSOT variant** |
| amp volumes from the reference UCM (817 / 4, DRE off) | no effect |
| sink volume 90 % and 100 % | no effect |
| `Tertiary TDM Capture` loopback dai-link | no effect |
| ADSP firmware vs the `modem` partition | **20/20 files byte-identical** |
| kernel config vs the reference (audio, LPASS, clocks) | **identical option by option** |
| clean reboots before each test | no effect |

What is left, with everything software-side excluded:

- The reference port targets the **CSOT** panel variant; this unit is **Samsung**
  (`j2_p2_1_38_0c_0a`). Same SoC, different board — the CS35L41 wiring or the
  ADSP configuration of the amp blocks may differ.
- Building the reference port's own kernel (clang, `pkgrel=10`) and playing the
  same tone here would settle it: if it plays, diff the two binaries; if it does
  not, the fault is in this unit's hardware or its variant firmware.

The instrumentation used for all of the above is not committed: both kernel
files were restored and the rebuilt `snd-soc-sm8250.ko` is byte-identical to the
original (`md5 17bed4f01093c60c8994746bc9783c57`).
