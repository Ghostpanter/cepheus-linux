#!/bin/sh
# Refresh WireGuard wg0 endpoint/handshake after wlan0 has a default route.
# Does not restart or flap wg0 if a recent handshake already exists.
# Usage: wg0-refresh-endpoint.sh [wait]

PATH=/usr/sbin:/usr/bin:/sbin:/bin
CONF=/etc/wireguard/wg0.conf
LOCK=/run/wg0-refresh.lock
WAIT_MAX="${WG0_REFRESH_WAIT:-90}"
HEALTHY_AGE=150
WG_PEER_PING=10.10.10.4

log() { logger -t wg0-refresh -- "$*"; }

have_default() {
	ip -4 route show default dev wlan0 2>/dev/null | grep -q .
}

ensure_wg0() {
	if ip link show wg0 >/dev/null 2>&1; then
		return 0
	fi
	log "wg0 missing; starting wg-quick@wg0"
	if ! systemctl start wg-quick@wg0; then
		log "failed to start wg-quick@wg0"
		return 1
	fi
}

handshake_healthy() {
	peer="$1"
	hs=$(wg show wg0 latest-handshakes 2>/dev/null | awk -v p="$peer" '$1==p {print $2; exit}')
	now=$(date +%s)
	[ -n "$hs" ] || return 1
	[ "$hs" -gt 0 ] 2>/dev/null || return 1
	age=$((now - hs))
	if [ "$age" -ge 0 ] && [ "$age" -le "$HEALTHY_AGE" ]; then
		return 0
	fi
	return 1
}

do_refresh() {
	if ! have_default; then
		log "no default route on wlan0; skip"
		return 0
	fi
	ensure_wg0 || return 1
	peer=$(wg show wg0 peers 2>/dev/null | awk 'NF{print; exit}')
	if [ -z "$peer" ]; then
		log "wg0 has no peer; skip"
		return 1
	fi
	if handshake_healthy "$peer"; then
		log "wg0 handshake is recent; leave interface alone"
		return 0
	fi
	if [ ! -r "$CONF" ]; then
		log "cannot read $CONF"
		return 1
	fi
	endpoint=$(awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*Endpoint[[:space:]]*=/ {
		sub(/^[^=]*=[[:space:]]*/, "")
		gsub(/[[:space:]]+$/, "")
		print
		exit
	}' "$CONF")
	if [ -z "$endpoint" ]; then
		log "no Endpoint in wg0.conf; skip"
		return 1
	fi
	log "refreshing wg0 endpoint after wlan route (handshake stale or missing)"
	if ! wg set wg0 peer "$peer" endpoint "$endpoint"; then
		log "wg set endpoint failed"
		return 1
	fi
	# Trigger a handshake without flapping the interface
	ping -c 1 -W 2 -I wg0 "$WG_PEER_PING" >/dev/null 2>&1 || true
	return 0
}

wait_for_route() {
	i=0
	while [ "$i" -lt "$WAIT_MAX" ]; do
		if have_default; then
			return 0
		fi
		sleep 1
		i=$((i + 1))
	done
	log "timed out waiting ${WAIT_MAX}s for wlan0 default route"
	return 1
}

mode="${1:-}"

# Avoid concurrent dispatcher + boot oneshot stacking
if command -v flock >/dev/null 2>&1; then
	exec 9>"$LOCK"
	flock -n 9 || exit 0
fi

case "$mode" in
	wait)
		wait_for_route || exit 0
		;;
esac

do_refresh
