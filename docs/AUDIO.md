<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Audio on the Mi 10 (`umi`)

Status: **works — clean and loud, with PulseAudio.** PipeWire produces a
permanent crackle on this board that no configuration could remove; PulseAudio
plays the same files clean, which is also what the reference port
(`miercolesvd/nura-mi10-umi-port`) uses. See
[Why PulseAudio, not PipeWire](#why-pulseaudio-not-pipewire) below for the full
comparison and the leads that cost most of the investigation.

Deployment, all verified on the device and surviving a reboot:

| piece | where |
|---|---|
| `pulseaudio` + `pulseaudio-alsa` installed, `pipewire-audio` removed | system packages |
| `pulseaudio.service` / `.socket` enabled per user | `~/.config/systemd/user/` |
| sink default + volume 100 % | `deploy/pulse/99-umi.conf` |
| amp levels at maximum (913/913 digital, 20/20 analog) | `deploy/ucm2/Xiaomi/umi/HiFi.conf` |
| ALSA `default` points at PulseAudio | `/etc/alsa/conf.d/99-pulseaudio-default.conf` |

`pipewire`, `wireplumber` and `libpipewire` stay **installed but stopped**:
`kwin` and `xdg-desktop-portal` require them as dependencies, so removing them
would break the Plasma session. `pipewire-audio` (the part that creates audio
nodes) is removed, and no PipeWire process runs.

The amp volume levels live in the **UCM**, not in a service: PulseAudio applies
them every time it opens the card, which is why raising them with `amixer` did
not survive a restart. The reference port ships 817/4 (conservative, CSOT
panel); this unit wants 913/20.

There is also a boot race, unrelated to the format: the ADSP reports `running`
, unrelated to the format: the ADSP reports `running`
before its APR services exist, so the card probe can fail with
`snd-sm8250: MultiMedia1: error getting cpu dai name` and no card is created at
all. `deploy/umi-audio-init.sh` retries the machine driver until the card
appears.

The pieces below are what the hardware needs, read out of *this* unit's silicon
and stock `dtbo`, not copied from another board.

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
speaker-test -c2 -t wav  # audible: RW_INTERLEAVED + S16_LE
paplay /path/to.wav      # the working path (PulseAudio)
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

- Playback works only as `S16_LE` without MMAP; the backend accepts
  `S24_LE` + MMAP and stays silent. See below.
- USB-C analogue headsets (WCD938x path) untested.
- Earpiece-only routing for calls depends on the modem, which is not ported.
- The receiver is driven as a normal speaker channel; call audio would need the
  voice call dai links.

## Why PulseAudio, not PipeWire

Playback was measured on the device with the same files on both stacks
(18-19 Nov 2026, kernel `6.12.94-umi #6`):

| path | result |
|---|---|
| `aplay -D hw:0,0` (direct ALSA) | **clean** |
| PipeWire, defaults | silent |
| PipeWire, `S16LE` + `disable-mmap` | audible but **crackles permanently** |
| **PulseAudio** | **clean and loud** |

Getting PipeWire to produce any sound at all required `S16_LE` without MMAP
(its defaults, `S24_LE` + `MMAP_INTERLEAVED`, give a PCM that reports `RUNNING`,
advances `hw_ptr` at 48000 frame/s, powers the whole DAPM chain and emits
nothing; `sw_params` shows `start_threshold = S64_MAX` on that path).

That still crackled. Tried on PipeWire, none of which removed it:

- `api.alsa.period-size` from 480 to 12000 and `api.alsa.period-num` 4
- `default.clock.quantum` 8192 and `clock.force-quantum` 960
- `resample.quality = 14` and `default.clock.allowed-rates = [ 48000 ]`
- `PCM Soft Ramp` 30 ms on both amps, `dapm_pop_time` 500 ms
- volumes from 40 % to 100 %, analog gain 4 to 20
- UCM active vs the native ALSA path

PulseAudio played clean with no audio-specific tuning beyond `S16_LE` handling,
and it is what the reference port uses. `pipewire-audio` was therefore removed.

A useful diagnostic that came out of this: `aplay` accepts large periods
(`--period-size=12000 --buffer-size=48000` was negotiated verbatim), so the
480-frame period is *PipeWire's choice*, not a driver limit.

### Leads that cost time, and what they actually showed

These all looked like the cause and none of them was. Recorded so nobody
repeats them:

| observation | why it misled |
|---|---|
| `PUP_DONE` never set, `0x742c` stays 0 | with `INT_BOOST` the driver never writes `0x742c` at all: that branch only sets `GLOBAL_EN` and polls. `0x742c` is reached only on `EXT_BOOST`, after PUP_DONE |
| `clk_summary` shows `TER_MI2S_IBIT en=0` | this path never touches the Linux clock framework; `q6afe_mi2s_set_sysclk()` sends an AFE command |
| DSP acknowledges the clock with `ret=0` | true and correct; `afe_apr_send_pkt()` does check `result->status`. It was simply not the failure |
| `TST_FS_MON0` differs while playing | a configuration register with a live field, not a bit-clock measurement |
| `EXT_BOOST` adds a `VSPK` widget that turns on | the chain then reaches `SPK` and `VSPK`, `0x742c = 0xf9`, and it is *still* silent — because the fault was the sample format, one layer up |
| amp at `0x41` per the stock dtbo | `0x41` does not ACK on I2C; `0x42` returns the Cirrus ID `0x35a40`. The stock dtbo describes the CSOT variant |
| raw 32-bit I2C register reads | byte order is ambiguous over `i2ctransfer`; do not draw conclusions from them |

Also ruled out by measurement: the ADSP firmware (20/20 files byte-identical to
the `modem` partition), the kernel config (identical to the reference port
option by option), the boost values (4000 mA / 1000 nH / 15 uF, matching the
stock dtbo), UCM presence, sink volume, and the USB cable (a single ALSA card
exists; no USB audio device is enumerated).

### The boot race

Independently of the format, the card sometimes fails to be created at boot:

```text
sound  snd-sm8250: MultiMedia1: error getting cpu dai name
umi-audio: no sm8250 card; giving up
```

The ADSP reports `running` before it has registered its APR services, and the
sound node has no `status` property, so nothing retries the probe. `deploy/umi-audio-init.sh`
now reloads `snd-soc-sm8250` until `/proc/asound/cards` shows the card.

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

With it, PulseAudio builds a real sink instead of a null fallback:

```text
alsa_output.platform-sound.HiFi__Speaker__sink   s16le 2ch 44100Hz
```

The amp levels come from the UCM's `Speaker` section and PulseAudio applies
them **every time it opens the card**. That is why `amixer cset` does not
survive a restart. The reference port ships `817` (digital) and `4` (analog),
chosen to keep a CSOT unit cool; this Samsung unit runs at the chip maximum
`913` / `20` without distortion:

```text
cset "name='LCV Analog PCM Volume' 20"
cset "name='RCV Analog PCM Volume' 20"
cset "name='LCV Digital PCM Volume' 913"
cset "name='RCV Digital PCM Volume' 913"
```

If audio comes back silent after a package upgrade, check in this order:
`pactl get-default-sink` (must not be `auto_null`), then the amp levels, then
`cat /proc/asound/card0/pcm0p/sub0/hw_params` while playing (expect
`RW_INTERLEAVED` + `S16_LE`).
