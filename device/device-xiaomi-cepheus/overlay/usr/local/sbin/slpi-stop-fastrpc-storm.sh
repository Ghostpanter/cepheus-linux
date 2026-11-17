#!/bin/sh
# Stop the SLPI remoteproc if it is running.
# Reason: qcom,fastrpc on 2400000.remoteproc (SLPI) tight-loops:
#   qcom_scm: Assign memory protection call failed -22
#   rpmsg_dev_probe: failed: -22
# That floods the panel and burns CPU. ADSP/CDSP/modem are left running.
# Sensors that depend on SLPI will be unavailable until SLPI is started again.
set -e
stop_slpi() {
    for d in /sys/class/remoteproc/remoteproc*; do
        [ -f "$d/name" ] || continue
        if [ "$(cat "$d/name")" = slpi ]; then
            st=$(cat "$d/state")
            if [ "$st" = running ]; then
                echo stop > "$d/state"
                echo "stopped slpi at $d"
            else
                echo "slpi already $st at $d"
            fi
            return 0
        fi
    done
    return 1
}
start_slpi() {
    for d in /sys/class/remoteproc/remoteproc*; do
        [ -f "$d/name" ] || continue
        if [ "$(cat "$d/name")" = slpi ]; then
            st=$(cat "$d/state")
            if [ "$st" = offline ]; then
                echo start > "$d/state"
                echo "started slpi at $d"
            else
                echo "slpi already $st at $d"
            fi
            return 0
        fi
    done
    return 1
}
case "$1" in
    udev)
        stop_slpi || true
        ;;
    start|"")
        i=0
        while [ "$i" -lt 30 ]; do
            if stop_slpi; then
                exit 0
            fi
            i=$((i+1))
            sleep 1
        done
        echo "slpi remoteproc not found after 30s" >&2
        exit 0
        ;;
    stop|restart-slpi)
        start_slpi || true
        ;;
    *)
        echo "usage: $0 {start|stop|udev}" >&2
        exit 2
        ;;
esac
