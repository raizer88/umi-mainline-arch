<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Audio on the Mi 10 (`umi`)

Status: **works on the device.** Playback verified with `speaker-test` on both
channels; the two CS35L41 amps, the ADSP and the WCD938x all bind. The pieces
below are what the hardware needs, read out of *this* unit's silicon and stock
`dtbo`, not copied from another board.

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

- USB-C analogue headsets (WCD938x path) untested.
- Earpiece-only routing for calls depends on the modem, which is not ported.
- The receiver is driven as a normal speaker channel; call audio would need the
  voice call dai links.
