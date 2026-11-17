#!/bin/bash
set -euo pipefail
# Set these for your machine. Do not commit real passwords or proxies.
#   export PHONE_PASS=...          # used only as pmbootstrap install --password
#   export http_proxy=...          # optional
DEST=${DEST:-$PWD}
WORK=${WORK:-$HOME/cepheus-pmbootstrap-work}

export PATH="$HOME/.local/bin:/usr/sbin:/sbin:$PATH"

LOG="$DEST/build.log"
APK="$WORK/packages/edge/aarch64/linux-postmarketos-qcom-sm8150-7.0.0-r8.apk"

exec > >(tee -a "$LOG") 2>&1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') install on ext4 (reuse kernel apk) ====="
echo "tty=$(tty || true)"

# Prefer a cached ticket (sudo-rs on a non-tty will treat `sudo -v` + empty
# stdin as failed password attempts and abort even when `sudo -n` works).
if sudo -n true 2>/dev/null; then
  echo "sudo already cached"
else
  if ! sudo -v; then
    echo "sudo auth failed"
    exit 1
  fi
fi
( while sudo -n true 2>/dev/null; do sleep 30; done ) &
SUDOKEEP=$!
trap 'kill $SUDOKEEP 2>/dev/null || true' EXIT

if [ ! -f "$WORK/version" ]; then
  echo "8" > "$WORK/version"
fi
if [ ! -f "$APK" ]; then
  echo "missing kernel apk: $APK"
  exit 1
fi
if [ ! -f "$WORK/packages/edge/aarch64/APKINDEX.tar.gz" ]; then
  echo "missing APKINDEX, aborting"
  exit 1
fi

pmbootstrap config work "$WORK"
echo "work=$(pmbootstrap config work)"
echo "kernel apk: $(ls -lh "$APK" | awk '{print $5}')"

# pmos (uid 12345) must be able to write newly built apks here
echo "fixing packages dir ownership"
sudo chown -R 12345:12345 "$WORK/packages"

echo "restarting qemu binfmt"
sudo systemctl restart systemd-binfmt
ls /proc/sys/fs/binfmt_misc | grep -E 'qemu-aarch64$|qemu-arm$' || true

if [ -z "${PHONE_PASS:-}" ] || [ "$PHONE_PASS" = "CHANGE_ME" ]; then
  echo "Set PHONE_PASS to the password you want baked into the image (not a secret in git)."
  exit 1
fi
echo "continuing pmbootstrap install"
pmbootstrap -y -j 16 --details-to-stdout install --password "$PHONE_PASS" --add device-xiaomi-cepheus-nonfree-firmware
echo "===== $(date '+%Y-%m-%d %H:%M:%S') DONE ====="
