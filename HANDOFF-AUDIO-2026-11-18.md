# Handoff — Mi 10 (`umi`) mainline audio: crackling + very low volume

Written 18 Nov 2026 at the end of a very long debugging session. Everything
below was measured on the device or read in the kernel source; where something
is an inference it says so.

**Goal for the reader**: we have audio *working but wrong* (crackles, and very
low volume ~10 % of what the hardware should give). We have exhausted every
configuration-level fix we could think of. We want a diagnosis or a next
experiment we have not tried.

---

## 1. Hardware and software stack

| Item | Value |
|---|---|
| Device | Xiaomi Mi 10 (`umi`, SM8250), bootloader unlocked, Samsung panel variant (`j2_p2_1_38_0c_0a`) |
| Rootfs | Arch Linux ARM on `/dev/sda34`, user `umi` uid 1001 |
| Kernel | `6.12.94-umi` `#6 SMP PREEMPT Tue Nov 17 19:18:00 UTC 2026`, built with gcc 16.1.0 (aarch64-none-elf-) |
| Kernel source | `/root/linux` (WSL `umi` distro) |
| Sound card | `sm8250-sndcard`, `card 0: X10 [sm8250]` |
| Amps | 2× Cirrus CS35L41 on i2c bus 3: `0x40` (prefix `RCV`, IRQ GPIO 113) and `0x42` (prefix `LCV`, IRQ GPIO 112), shared reset GPIO 114 |
| Audio stack | PipeWire 1.6.11 + WirePlumber 0.5.19 + pipewire-pulse |
| Reference port | `miercolesvd/nura-mi10-umi-port` (targets the **CSOT** panel variant, reports audio working) |
| Upstream this is based on | `colorgarden/umi-mainline` |

---

## 2. What works right now

```
card 0: X10 [sm8250]: Xiaomi Mi 10
sink: alsa_output.platform-sound.playback.0.0   s16le 2ch 48000Hz
hw_params during playback:
  access: RW_INTERLEAVED
  format: S16_LE
  channels: 2
  period_size: 480        <-- NOTE: 480, see §5
  buffer_size: 1920
DAPM during playback (both amps):
  ASPRX1      On  in 1 out 1 - R18432(0x4800) mask 0x10000
  PCM Source  On  in 1 out 1
  CLASS H     On  in 1 out 1 - R8220(0x201c) mask 0x10
  Main AMP    On  in 1 out 1 - R8216(0x2018) mask 0x1
  SPK         On  in 1 out 1
  <card> Speaker On in 1 out 1
```

Audio **is audible and continuous**. A 1 kHz sine is clean. What is wrong:

- **Pink/white noise crackles** (broadband content distorts).
- **Volume is roughly 10 %** of what the phone produces under Android, even with
  every gain control at maximum.

---

## 3. The three real bugs already fixed (do not re-investigate)

### 3.1 Missing Speaker routes in the sound card

`&sound { widgets = "Speaker", "RCV Speaker", ... }` declares the widgets but
`audio-routing` had no matching entries, so both stayed `Off  in 0` forever and
never powered the codec's `SPK` output. Added:

```dts
audio-routing =
	"RCV Speaker", "RCV SPK",
	"LCV Speaker", "LCV SPK",
	...
```

Verified: before `Off in 0`, after `On in 1 out 1`.

### 3.2 PipeWire only plays S16_LE without MMAP

This was the cause of *total silence*, and it is measured and reproducible:

| path | access | format | period | audible |
|---|---|---|---|---|
| `speaker-test -D hw:0,0` | `RW_INTERLEAVED` | `S16_LE` | 12000 | yes |
| PipeWire defaults | `MMAP_INTERLEAVED` | `S24_LE` | 480 | **no** |
| PipeWire + `disable-mmap` + `S16LE` | `RW_INTERLEAVED` | `S16_LE` | 480 | yes |

With MMAP, `sw_params` shows `start_threshold = S64_MAX`; the DSP consumes the
buffer, `hw_ptr` advances at exactly 48000 frame/s, and nothing comes out.

Fix (`deploy/wireplumber-umi-alsa-format.conf`):

```text
api.alsa.disable-mmap = true
audio.format          = "S16LE"
audio.rate            = 48000
audio.channels        = 2
api.alsa.period-size  = 12000
api.alsa.period-num   = 4
```

### 3.3 `EXT_BOOST` without the mandatory GPIO1 configuration

With `cirrus,boost-type = <1>` the binding **requires**
`cirrus,gpio1-output-enable` and `cirrus,gpio1-src-select = <1>`, and **forbids**
`boost-peak-milliamp`/`ind`/`cap`. We had `<1>` and none of the GPIO properties,
so `cs35l41_gpio_config()` programmed GPIO1 as an **input**
(`!gpio1->out_en << CS35L41_GPIO_DIR_SHIFT`) and the VSPK switch never closed.
Adding them changed `GPIO_PAD_CONTROL` from `0x04000000` to `0x04010000` and
made the VSPK widget appear and turn on — **this removed most of the crackling**.
It did not fix the volume.

---

## 4. Current DTS (the state to reason about)

```dts
cs35l41_speaker: speaker-amp@40 {          /* bottom loudspeaker, prefix RCV */
	compatible = "cirrus,cs35l41";
	reg = <0x40>;
	interrupt-parent = <&tlmm>;
	interrupts = <113 IRQ_TYPE_LEVEL_LOW>;
	reset-gpios = <&tlmm 114 GPIO_ACTIVE_HIGH>;
	cirrus,temp-warn_threshold = <3>;
	cirrus,boost-type = <0>;               /* INT_BOOST: what the stock dtbo says */
	cirrus,boost-peak-milliamp = <4500>;
	cirrus,boost-ind-nanohenry = <1000>;
	cirrus,boost-cap-microfarad = <15>;
	cirrus,asp-sdout-hiz = <1>;
	cirrus,gpio2-src-select = <4>;
	cirrus,gpio2-output-enable;
	sound-name-prefix = "RCV";
	VA-supply = <&vreg_s4a_1p8>;
	VP-supply = <&vph_pwr>;
	#sound-dai-cells = <1>;
};

cs35l41_rcv: speaker-amp@42 {              /* top receiver, prefix LCV */
	/* identical, plus cirrus,right-channel-amp; */
	reg = <0x42>;
	interrupts = <112 IRQ_TYPE_LEVEL_LOW>;
};
```

Dai-link (unchanged from the reference port):

```dts
speaker-dai-link {
	link-name = "Tertiary MI2S Playback";
	cpu    { sound-dai = <&q6afedai TERTIARY_MI2S_RX>; };
	platform { sound-dai = <&q6routing>; };
	codec  { sound-dai = <&cs35l41_rcv 0>, <&cs35l41_speaker 0>; };
};
amp-loopback-dai-link {
	link-name = "Tertiary TDM Capture";
	cpu    { sound-dai = <&q6afedai TERTIARY_TDM_TX_0>; };
	codec  { sound-dai = <&cs35l41_rcv 0>, <&cs35l41_speaker 0>; };
};
```

Pinmux: `tert_tdm_active`, `mi2s2_sck/data0/ws/data1` on gpio133/134/135/137.

---

## 5. The volume problem — what the registers say

During playback, read over I2C (not the regmap cache), amp `0x42`:

| register | value | meaning |
|---|---|---|
| `0x2014` PWR_CTRL1 | `0x00000001` | `GLOBAL_EN` set |
| `0x2018` PWR_CTRL2 | `0x00000001` | `Main AMP` on, **`BST_EN` bits[5:4] = 0 → boost OFF** |
| `0x201c` PWR_CTRL3 | `0x01000010` | `CLASS H` on |
| `0x4800` SP_ENABLES | `0x00010000` | `ASPRX1` enabled |
| `0x4808` SP_FORMAT | `0x10180200` | ASP_FMT=2 (I2S), TX_WL=0x18 (24), RX_WL=0x10 (16) |
| `0x4840` SP_RX_WL | `0x00000010` | 16 bit — correct for S16_LE |
| `0x3800` BSTCVRT | `0x00000000` | **boost converter target: not configured** |
| `0x3804` | `0x00000001` | |
| `0x2c08` AMP_GAIN | `0x00000003` | |
| `0x11008` GPIO1_CTRL1 | (INT_BOOST → never written) | |

Gain controls, all set to maximum already:

```text
LCV/RCV Analog  PCM Volume = 20/20   (+20.5 dB, chip maximum)
LCV/RCV Digital PCM Volume = 600..913 of 913
PipeWire sink volume       = 100 %
```

**Raising the analog gain to maximum changed nothing audible.** That is the
key observation: the limit is *before* the amplifier's gain stage.

### Why the boost is off

`cs35l41_boost_enable()` is **only called from the three IRQ error handlers**
(`VBST OVP`, `BST DCM UVP`, `BST short`), never from DAPM:

```
$ grep -n "cs35l41_boost_enable(" sound/soc/codecs/*.c
cs35l41.c:359: static void cs35l41_boost_enable(...)      <- definition
cs35l41.c:445:   cs35l41_boost_enable(cs35l41, 0);        <- IRQ: VBST OVP
cs35l41.c:447:   cs35l41_boost_enable(cs35l41, 1);
cs35l41.c:453:   cs35l41_boost_enable(cs35l41, 0);        <- IRQ: DCM UVP
cs35l41.c:455:   cs35l41_boost_enable(cs35l41, 1);
cs35l41.c:461:   cs35l41_boost_enable(cs35l41, 0);        <- IRQ: BST short
cs35l41.c:463:   cs35l41_boost_enable(cs35l41, 1);
```

`cs35l41_main_amp_event()` (the `Main AMP` DAPM widget handler) calls
`cs35l41_global_enable()`, which for `INT_BOOST` only flips `GLOBAL_EN`,
polls `IRQ1_STATUS1` and returns; it never sets `BST_EN`. So the boost is
expected to come up on its own from the `PWR_CTRL2` default written by
`cs35l41_boost_config()` at probe — which on this board does not happen
(`0x3800` stays 0, `BST_EN` stays 0).

The IRQ lines exist and are enabled but have counted **zero** events:

```
230:  0 0 0 0 0 0 0 0   msmgpio 113 Level  cs35l41
231:  0 0 0 0 0 0 0 0   msmgpio 112 Level  cs35l41
```

### Which supply feeds the output stage

```
$ cat /sys/kernel/debug/regulator/regulator_summary
 vph_pwr          9 use  open 10   3700mV   0mA
    3-0042-VP    1
    3-0040-VP    1
    vreg_bob     4 use
```

`vph_pwr` is a **`regulator-fixed` with no driver behind it** (see
`dts/sm8250-xiaomi-umi-common.dtsi`): it declares 3.7 V exists and never
touches hardware. If the real VBAT rail is not what the amp expects, or the
boost cannot start from it, this is consistent with the symptom. Unverified:
we cannot measure the rail.

---

## 6. What has been tried and ruled out

| Attempt | Result |
|---|---|
| Sample format S24_LE + PipeWire default (MMAP) | **silence** |
| `api.alsa.disable-mmap = true` | needed, but not sufficient alone |
| `audio.format = "S16LE"` | **required**; with it audio appears |
| UCM installed under the driver name, `Syntax 6` (`conf.d/sm8250/Xiaomi Mi 10.conf`) | **works**, sink named `HiFi__Speaker__sink`, 2ch. Not used right now: ACP forces `period_size = 480` and ignores `api.alsa.period-size`, so we run the native ALSA path instead |
| `PlaybackPeriod` / `PlaybackBuffer` in UCM | ignored by the driver |
| `default.clock.quantum = 8192`, `clock.force-quantum` | does not change the ALSA period (driver-imposed 480) |
| `api.alsa.period-size = 12000` on the ALSA path | **not honoured**: `hw_params` shows 480 either way |
| `cirrus,asp-sdout-hiz` 3 (stock dtbo value) vs 1 | 3 keeps `LCV SPK Off` and `CLASS H` off; **1 is required here** |
| `cirrus,boost-type` absent / `0` (INT_BOOST) | audible but quiet, `BST_EN = 0` |
| `cirrus,boost-type = 1` (EXT_BOOST) + `gpio1-output-enable` + `gpio1-src-select = <1>` | fixed most crackling (VSPK turns on, `GPIO_PAD_CONTROL 0x04010000`), **volume unchanged** |
| Amp at `0x41` (as the stock dtbo says) | **does not ACK on I2C**; `0x42` returns Cirrus ID `0x35a40`. The stock dtbo describes the CSOT variant |
| Volumes: digital 300…913, analog 4…20, sink 40…100 % | only affects cleanliness (lower = less crackle); **the ceiling does not move** |
| `Tertiary TDM Capture` loopback link | no audible change |
| ADSP firmware vs the phone's `modem` partition | **20/20 files byte-identical** (`adsp.mdt` + `adsp.b00..b18` + `adsp*.jsn`) |
| Kernel config vs the reference port (audio, LPASS, clocks) | **identical option by option** |
| `qcom_pd_mapper` / `qcom,kona` compatible | applied, ADSP runs, APR registered |
| Patch `cs35l41-ignore-pup.py` (ignore missing PUP_DONE) | already applied; PUP_DONE in fact never arrives on this unit |
| DSP firmware `cs35l41-dsp1-spk-prot-*.wmfw` + `.bin` | **not loaded** (`booted = N`); not packaged in `/lib/firmware`, not extractable (no readable vendor partition) |
| Web search (lore, GitHub, pmaports, XDA, Reddit) | **no public report** of this symptom on SM8250 phones; all `cs35l41 PUP_DONE` lore hits are the HDA laptop driver |

Also verified as **not** the cause: the USB cable (a single ALSA card exists, no
USB audio device enumerates), and any other sink (one sink only).

---

## 7. The measurements that seem most diagnostic

1. **`aplay` with a 1 s buffer is clean; PipeWire with a 10 ms buffer crackles.**
   Telemetry: `avail: 480` with `buffer_size: 1920` during playback;
   `dmesg` repeats `q6asm-dai ... command[0x10dab] not expecting rsp`.
   The ALSA period is imposed by the driver and cannot be changed from any
   configuration layer we tried (`period-size`, `PlaybackPeriod`, quantum).
2. **Broadband noise crackles, a 1 kHz sine does not.** That points at
   high-frequency content, i.e. an underrun/truncation artefact rather than
   clipping (verified: lowering the volume does not remove it; raising the
   analog gain to maximum does not fix the level).
3. **Analog gain at maximum (+20.5 dB) changes nothing.** The ceiling sits
   before the amp's gain stage → the boost / supply, not the mixer.
4. **`BST_EN = 0` and `0x3800 = 0` during playback** with `INT_BOOST`, and
   `cs35l41_boost_enable()` is unreachable from the playback path.

---

## 8. Open questions we would like an opinion on

1. **Is `BST_EN = 0` during playback expected with `INT_BOOST`?** The driver
   never sets it outside the IRQ handlers. If it is expected, where is the
   volume supposed to come from — or does the amp genuinely need `EXT_BOOST`
   with a real external boost on this board?
2. **Does CS35L41 need the DSP firmware for correct gain?** Our reading is that
   the `.bin` carries per-board tuning/attenuation and speaker protection, and
   that without it the amp runs on datasheet defaults. Is a missing `.bin` a
   plausible cause of "10 % volume", or only of missing protection?
3. **Can the q6asm period really not be changed?** We could not move
   `period_size` below/above 480 from PipeWire, UCM or the native ALSA path.
   Is that a known limitation, and is 480 frames known to cause the crackle?
   Is patching `q6asm-dai.c` (snd_pcm_hardware period_bytes_min/max) the
   intended fix?
4. **Does `cirrus,right-channel-amp` on the second amp interact with volume?**
   Both amps are at maximum gain and both are `On`; we cannot tell by ear which
   one is producing the sound.
5. **Which of these is worth trying next**, in your judgement — and is there an
   experiment we have not thought of that would separate "boost/supply" from
   "transport/underrun"?

---

## 9. Artefacts

- `docs/AUDIO.md` in the repo: full narrative with the same measurements.
- `deploy/wireplumber-umi-alsa-format.conf`: the PipeWire configuration in use.
- `deploy/ucm2/`: the working UCM (currently bypassed).
- Boot images (all flashed and verified by readback md5):
  `out/boot-umi-*.img`. Currently flashed: the INT_BOOST build.
- Kernel patches used: `patches/sm8250-dual-cs35l41.py`,
  `patches/cs35l41-ignore-pup.py`, `patches/qcom-kona-compatible.py`.
- Repo: `raizer88/umi-mainline-arch`, branch `master`, HEAD `db05017`
  (the working DTS with `INT_BOOST` is uncommitted on top of it).
