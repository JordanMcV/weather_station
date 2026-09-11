#!/usr/bin/env bash
# Recovers the wifi link when NetworkManager stops retrying. See the README.
set -uo pipefail

STATE_FILE=${WIFI_WATCHDOG_STATE:-/var/lib/weather-wifi-watchdog/state}
IFACE=${WIFI_WATCHDOG_IFACE:-wlan0}
CONNECTION=${WIFI_WATCHDOG_CONNECTION:-preconfigured}

# The timer runs this script every 5 minutes, so one check is 5 minutes. The
# counters below count checks, not seconds. piw has no real time clock, so the
# wall clock is wrong after a reboot that happens while the network is down,
# which is the case this script exists to handle.
CHECKS_BEFORE_FIRST_REBOOT=12
MAX_CHECKS_BETWEEN_REBOOTS=72

log() {
    logger -t weather-wifi-watchdog "[WiFi Watchdog] $1"
}

fails=0
reboots=0
reboot_at_fail=0

if [[ -r "$STATE_FILE" ]]; then
    while IFS='=' read -r key value; do
        [[ "$value" =~ ^[0-9]+$ ]] || continue
        case "$key" in
            fails) fails=$value ;;
            reboots) reboots=$value ;;
            reboot_at_fail) reboot_at_fail=$value ;;
        esac
    done < "$STATE_FILE"
fi

save_state() {
    mkdir -p "$(dirname "$STATE_FILE")"
    printf 'fails=%s\nreboots=%s\nreboot_at_fail=%s\n' \
        "$fails" "$reboots" "$reboot_at_fail" > "$STATE_FILE"
}

gateway=$(ip route show default | awk '/default/ {print $3; exit}')

if [[ -n "$gateway" ]] && ping -c 3 -W 3 -I "$IFACE" "$gateway" >/dev/null 2>&1; then
    if (( fails > 0 )); then
        plural=s; (( reboots == 1 )) && plural=
        log "Link recovered after $(( fails * 5 )) minutes and $reboots reboot${plural}."
        rm -f "$STATE_FILE"
    fi
    exit 0
fi

fails=$(( fails + 1 ))
save_state
log "Check $fails failed. Gateway '${gateway:-none}' unreachable on $IFACE."

# Checks since the last reboot. The state file survives a reboot, so a reboot
# that does not fix the link cannot restart the ladder.
since=$(( fails - reboot_at_fail ))

# Double the wait before each further reboot, up to the cap. A reboot fixes a
# wedged radio. It cannot fix an access point that is still down, so waiting
# longer each time costs nothing and stops a reboot loop.
gap=$CHECKS_BEFORE_FIRST_REBOOT
for (( i = 0; i < reboots; i++ )); do
    gap=$(( gap * 2 ))
    if (( gap > MAX_CHECKS_BETWEEN_REBOOTS )); then
        gap=$MAX_CHECKS_BETWEEN_REBOOTS
        break
    fi
done

if (( since >= gap )); then
    log "No link for $(( since * 5 )) minutes. Rebooting, reboot $(( reboots + 1 )) of this outage."
    reboots=$(( reboots + 1 ))
    reboot_at_fail=$fails
    save_state
    systemctl reboot
    exit 0
fi

case "$since" in
    1|2)
        log "Bringing connection '$CONNECTION' up. This clears an autoconnect block."
        nmcli connection up "$CONNECTION" >/dev/null 2>&1 || log "nmcli connection up failed."
        ;;
    3|4)
        log "Restarting NetworkManager."
        systemctl restart NetworkManager || log "NetworkManager restart failed."
        ;;
    5|6)
        log "Reloading the brcmfmac driver."
        modprobe -r brcmfmac && sleep 5 && modprobe brcmfmac || log "Driver reload failed."
        ;;
    *)
        # The cheap steps did not work, so the access point is probably down.
        # Wait for it, and retry the cheap steps at intervals in case it
        # returns and NetworkManager does not notice.
        if (( since % 24 == 0 )); then
            log "Reloading the brcmfmac driver."
            modprobe -r brcmfmac && sleep 5 && modprobe brcmfmac || log "Driver reload failed."
        elif (( since % 6 == 0 )); then
            log "Bringing connection '$CONNECTION' up."
            nmcli connection up "$CONNECTION" >/dev/null 2>&1 || log "nmcli connection up failed."
        else
            log "Waiting for the access point. Reboot due in $(( (gap - since) * 5 )) minutes."
        fi
        ;;
esac
