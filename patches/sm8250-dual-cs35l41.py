#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""sm8250-dual-cs35l41.py — configure both CS35L41 amps on Tertiary MI2S.

sm8250_snd_startup() only calls snd_soc_dai_set_fmt() on the *first* codec DAI
(`snd_soc_rtd_to_codec(rtd, 0)`). The Mi 10 has two CS35L41 amps on the same
Tertiary MI2S dai-link, so the second one never gets a format, a bit clock or
an RX slot; the first hw_params then fails with -EINVAL:

    speaker-test: Setting of hwparams failed: Invalid argument

Walk every codec DAI instead and give each one its own I2S slot. Amps take one
slot each in dai-link order, so the first codec plays left and the second right;
both RX inputs point at that slot, whichever one feeds the DAC.

Same idea as patch 0008 of miercolesvd/nura-mi10-umi-port, keyed on the codec
driver name rather than the board compatible (the stock dtbo rewrites that).

Run after the kernel tree exists:
    python3 patches/sm8250-dual-cs35l41.py
"""
import io
import os
import sys

TREE = os.environ.get("TREE", "/root/linux")
P = os.path.join(TREE, "sound/soc/qcom/sm8250.c")

MARK = "sm8250_umi_amps_setup"

HELPER = '''
/*
 * Two CS35L41 amps (top receiver and bottom loudspeaker on the Xiaomi Mi 10)
 * share Tertiary MI2S. Each needs its format, its bit clock as PLL reference
 * and fs monitor, and its own RX slot; only codec DAI 0 used to be set up, so
 * the second amp stayed unconfigured and hw_params failed with -EINVAL.
 */
static void sm8250_umi_amps_setup(struct snd_soc_pcm_runtime *rtd,
				  unsigned int codec_dai_fmt)
{
	struct snd_soc_dai *dai;
	int i, ret;

	for_each_rtd_codec_dais(rtd, i, dai) {
\t\tunsigned int slot = min(i, 1);
\t\tunsigned int rx_slot[] = { slot, slot };

\t\tsnd_soc_dai_set_fmt(dai, codec_dai_fmt);

\t\tret = snd_soc_component_set_sysclk(dai->component, 0, 0,
\t\t\t\t\t\t   MI2S_BCLK_RATE,
\t\t\t\t\t\t   SND_SOC_CLOCK_IN);
\t\tif (ret)
\t\t\tdev_warn(dai->dev, "PLL ref clock: %d\\n", ret);

\t\tret = snd_soc_dai_set_sysclk(dai, 0, MI2S_BCLK_RATE,
\t\t\t\t\t     SND_SOC_CLOCK_IN);
\t\tif (ret)
\t\t\tdev_warn(dai->dev, "sysclk: %d\\n", ret);

\t\tret = snd_soc_dai_set_channel_map(dai, 0, NULL,
\t\t\t\t\t\t  ARRAY_SIZE(rx_slot), rx_slot);
\t\tif (ret)
\t\t\tdev_warn(dai->dev, "channel map: %d\\n", ret);
\t}
}
'''

OLD = '''static int sm8250_snd_startup(struct snd_pcm_substream *substream)
{'''

NEW = '''static int sm8250_snd_startup(struct snd_pcm_substream *substream)
{'''

TERT_OLD = '''\t\tsnd_soc_dai_set_fmt(cpu_dai, fmt);
\t\tsnd_soc_dai_set_fmt(codec_dai, codec_dai_fmt);
\t\tbreak;
\tdefault:
\t\tbreak;
\t}

\treturn qcom_snd_sdw_startup(substream);'''

TERT_NEW = '''\t\tsnd_soc_dai_set_fmt(cpu_dai, fmt);
\t\t/*
\t\t * Not keyed on the board compatible: the stock bootloader's dtbo
\t\t * overlay replaces the root compatible with "qcom,kona".
\t\t */
\t\tif (codec_dai->component->driver->name &&
\t\t    !strcmp(codec_dai->component->driver->name, "cs35l41-codec"))
\t\t\tsm8250_umi_amps_setup(rtd, codec_dai_fmt);
\t\telse
\t\t\tsnd_soc_dai_set_fmt(codec_dai, codec_dai_fmt);
\t\tbreak;
\tdefault:
\t\tbreak;
\t}

\treturn qcom_snd_sdw_startup(substream);'''


def main():
    if not os.path.isfile(P):
        sys.exit("missing %s (set TREE to the kernel tree)" % P)
    src = io.open(P, encoding="utf-8").read()
    if MARK in src:
        print("already patched")
        return
    if OLD not in src:
        sys.exit("sm8250_snd_startup not found; source differs from v6.12")
    if TERT_OLD not in src:
        sys.exit("TERTIARY_MI2S_RX block not found; source differs from v6.12")

    src = src.replace(OLD, HELPER.lstrip("\n") + "\n" + NEW, 1)
    src = src.replace(TERT_OLD, TERT_NEW, 1)

    # <linux/string.h> for strcmp on kernels that do not pull it in.
    if "#include <linux/string.h>" not in src:
        src = src.replace("#include <linux/module.h>",
                          "#include <linux/module.h>\n#include <linux/string.h>", 1)

    io.open(P, "w", encoding="utf-8").write(src)
    print("sm8250.c: both CS35L41 amps configured on Tertiary MI2S")


main()
