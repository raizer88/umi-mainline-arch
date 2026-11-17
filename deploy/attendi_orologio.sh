#!/bin/sh
# Wait for a plausible clock and a default route before starting a TLS service.
# The PMIC RTC starts the system clock in 1974; NTP fixes it 90-130 s after
# boot. Exit 0 even on timeout: a service that starts late is better than one
# that never starts. Use as ExecStartPre with TimeoutStartSec=300.
set -u

i=0
while [ "$i" -lt 100 ]; do
    year=$(date +%Y 2>/dev/null || echo 0)
    case "$year" in
        ''|*[!0-9]*) year=0 ;;
    esac
    if [ "$year" -ge 2025 ] && ip route get 1.1.1.1 >/dev/null 2>&1; then
        exit 0
    fi
    sleep 2
    i=$((i + 1))
done

exit 0
