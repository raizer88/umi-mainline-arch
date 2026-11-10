#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Install the QCA6390 WiFi workaround on an Arch rootfs running on umi.
#
#   sudo sh deploy/install-wifi.sh <SSID> <BSSID> <FREQ_MHZ> <PASSPHRASE> [SAE|PSK]
#
# Example:
#   sudo sh deploy/install-wifi.sh MyHome aa:bb:cc:dd:ee:ff 5200 'secret' SAE
#
# The passphrase is written only to /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
# (0600 root). It is never written to this repository.
set -eu

if [ "$(id -u)" != 0 ]; then
    echo "run as root" >&2
    exit 1
fi
if [ "$#" -lt 4 ]; then
    echo "usage: $0 SSID BSSID FREQ_MHZ PASSPHRASE [SAE|PSK]" >&2
    exit 2
fi

SSID=$1
BSSID=$2
FREQ=$3
PASS=$4
KM=${5:-SAE}
SELF=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

case "$KM" in
    SAE|PSK) ;;
    *) echo "key management must be SAE or PSK" >&2; exit 2 ;;
esac
case "$FREQ" in
    *[!0-9]*|'') echo "FREQ_MHZ must be numeric (e.g. 5200)" >&2; exit 2 ;;
esac
case "$SSID$PASS" in
    *'"'*|*\\*|*'
'*) echo "SSID/passphrase must not contain quotes, backslashes or newlines" >&2; exit 2 ;;
esac

if ! command -v wpa_supplicant >/dev/null 2>&1; then
    echo "wpa_supplicant is not installed (pacman -S wpa_supplicant)" >&2
    exit 3
fi
if ! command -v dhcpcd >/dev/null 2>&1; then
    echo "dhcpcd is not installed (pacman -S dhcpcd)" >&2
    exit 3
fi

install -d -m 755 /etc/wpa_supplicant /run/wpa_supplicant
{
    printf '%s\n' \
        'ctrl_interface=/run/wpa_supplicant' \
        'update_config=1' \
        'ap_scan=1' \
        'p2p_disabled=1' \
        '' \
        'network={' \
        "    ssid=\"$SSID\"" \
        "    bssid=$BSSID" \
        "    scan_freq=$FREQ" \
        "    psk=\"$PASS\""
    if [ "$KM" = SAE ]; then
        printf '%s\n' \
            '    key_mgmt=SAE' \
            '    ieee80211w=2' \
            '    sae_pwe=2'
    else
        printf '%s\n' '    key_mgmt=WPA-PSK'
    fi
    printf '%s\n' \
        '    proto=RSN' \
        '    pairwise=CCMP' \
        '    group=CCMP' \
        '}'
} > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
chmod 600 /etc/wpa_supplicant/wpa_supplicant-wlan0.conf

install -m 644 "$SELF/umi-wpa-late.service" /etc/systemd/system/umi-wpa-late.service
install -m 644 "$SELF/umi-wpa-late.timer"   /etc/systemd/system/umi-wpa-late.timer
systemctl daemon-reload

# Early WiFi startup is the trigger; keep these off.
systemctl disable --now wpa_supplicant@wlan0 2>/dev/null || true
systemctl disable --now dhcpcd@wlan0 2>/dev/null || true
systemctl mask iwd 2>/dev/null || true
systemctl enable --now umi-wpa-late.timer

echo "installed."
echo "config: /etc/wpa_supplicant/wpa_supplicant-wlan0.conf (0600)"
echo "WiFi starts 90 s after boot. To test now:"
echo "    systemctl start umi-wpa-late.service"
echo "    sleep 15; wpa_cli -i wlan0 status; ping -c 3 www.google.it"
