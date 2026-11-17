#!/bin/sh
# Provide the WCN3990 board and API stub files that ath10k_snoc looks for
# under ath10k/WCN3990/hw1.0/. Board data comes from the modem partition
# (bdwlan.bin). firmware-5.bin is the 60-byte QCA-ATH10K API stub from
# linux-firmware; the actual WLAN firmware is already loaded via QMI.
set -e
SRC=""
for c in \
    /run/msm-firmware-loader/target/bdwlan.bin \
    /run/msm-firmware-loader/mnt/modem/image/bdwlan.bin
do
    if [ -e "$c" ]; then
        SRC=$c
        break
    fi
done
PERSIST=/lib/firmware/ath10k/WCN3990/hw1.0
RUNDIR=/run/msm-firmware-loader/target/ath10k/WCN3990/hw1.0
mkdir -p "$PERSIST"
if [ -n "$SRC" ] && [ -e "$SRC" ]; then
    if [ ! -s "$PERSIST/board.bin" ]; then
        cp -L "$SRC" "$PERSIST/board.bin"
        chmod 644 "$PERSIST/board.bin"
    fi
    if [ -d /run/msm-firmware-loader/target ]; then
        mkdir -p "$RUNDIR"
        ln -sfn ../../../bdwlan.bin "$RUNDIR/board.bin"
        if [ -s "$PERSIST/firmware-5.bin" ]; then
            ln -sfn /lib/firmware/ath10k/WCN3990/hw1.0/firmware-5.bin "$RUNDIR/firmware-5.bin"
        fi
    fi
    echo "ath10k board.bin ready (src=$SRC)"
else
    if [ -s "$PERSIST/board.bin" ]; then
        echo "ath10k board.bin present under $PERSIST (loader not ready)"
        exit 0
    fi
    echo "bdwlan.bin not found and no persistent board.bin" >&2
    exit 1
fi
