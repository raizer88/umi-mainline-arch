#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# umi-audio-init.sh — bring the Mi 10 sound card up and set sane levels.
#
# The q6 components are not reliably auto-loaded by modalias, so the card defers
# once and never retries. Loading them explicitly and opening the
# MultiMedia1 -> TERT_MI2S_RX route gives a working card; the mixer then needs
# the CS35L41 volumes brought down from the driver default (913/913, 20/20),
# which is loud enough to trip the amp's over-temperature warning.
#
# Controls are addressed by name, never by numid: numids shift when the card is
# rebuilt. Values are percent of the control's own max.
#
#   sh deploy/umi-audio-init.sh            # apply
#   DIGITAL_PCT=30 ANALOG_PCT=50 sh ...    # custom levels
set -u

CARD=${CARD:-0}
DIGITAL_PCT=${DIGITAL_PCT:-100}
ANALOG_PCT=${ANALOG_PCT:-100}

log() { echo "umi-audio: $*" >&2; }

# ---- modules ---------------------------------------------------------------
# remoteproc first: it needs pd-mapper's domains before the q6 dais can attach.
for m in qcom_pd_mapper qcom_q6v5_pas; do
	modprobe "$m" 2>/dev/null || log "modprobe $m failed"
done

# Wait for the ADSP; the audio topology is loaded by the remoteproc.
i=0
while [ "$i" -lt 50 ]; do
	state=$(cat /sys/class/remoteproc/remoteproc*/state 2>/dev/null | head -1)
	[ "$state" = "running" ] && break
	sleep 0.2
	i=$((i + 1))
done
[ "${state:-}" = "running" ] || log "ADSP not running (state=${state:-none})"

for m in q6core q6afe q6afe-dai q6afe-clocks q6asm q6asm-dai q6adm q6routing \
	 snd-soc-cs35l41-i2c snd-soc-sm8250; do
	modprobe "$m" 2>/dev/null || log "modprobe $m failed"
done

# The ADSP reports "running" before it has registered its APR services, and the
# sound card binds only once the q6 DAIs have names. Without this the card probe
# fails with "snd-sm8250: MultiMedia1: error getting cpu dai name", and because
# the card node has no status property nothing retries it later: the boot ends
# with no sound card at all. Reload the machine driver until the card appears.
i=0
while [ "$i" -lt 40 ]; do
	grep -q "sm8250" /proc/asound/cards 2>/dev/null && break
	modprobe -r snd-soc-sm8250 2>/dev/null
	modprobe snd-soc-sm8250 2>/dev/null
	sleep 0.25
	i=$((i + 1))
done

# ---- sound card ------------------------------------------------------------
i=0
while [ "$i" -lt 50 ]; do
	grep -q "sm8250" "/proc/asound/cards" 2>/dev/null && break
	sleep 0.2
	i=$((i + 1))
done

if ! grep -q "sm8250" "/proc/asound/cards" 2>/dev/null; then
	log "no sm8250 card; giving up"
	exit 0
fi

# ---- routing ---------------------------------------------------------------
# Frontend MultiMedia1 has no backend until this route is on. Note the name
# order is inverted compared with the TX controls:
#   RX: "<port> Audio Mixer MultiMediaN"
#   TX: "MultiMediaN Mixer <port>"
amixer -c "$CARD" -q sset 'TERT_MI2S_RX Audio Mixer MultiMedia1' on 2>/dev/null ||
	log "route TERT_MI2S_RX -> MultiMedia1 not set"

# ---- levels ----------------------------------------------------------------
# Percent of max keeps this correct if the driver changes its scale.
for ctl in 'LCV Digital PCM Volume' 'RCV Digital PCM Volume'; do
	amixer -c "$CARD" -q cset name="$ctl" "${DIGITAL_PCT}%" 2>/dev/null ||
		log "could not set $ctl"
done

for ctl in 'LCV Analog PCM Volume' 'RCV Analog PCM Volume'; do
	amixer -c "$CARD" -q cset name="$ctl" "${ANALOG_PCT}%" 2>/dev/null ||
		log "could not set $ctl"
done

log "ready (card $CARD, digital ${DIGITAL_PCT}%, analog ${ANALOG_PCT}%)"
exit 0
