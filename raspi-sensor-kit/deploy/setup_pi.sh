#!/bin/bash
set -euo pipefail

APP_USER="${SUDO_USER:-$USER}"
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
TARGET_DIR="${APP_HOME}/raspi4"

echo "[1/7] Install OS packages..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-serial python3-httpx git build-essential

echo "[2/7] Ensure pigpio python module available..."
python3 - <<'PY'
import importlib.util
import subprocess
import sys
if importlib.util.find_spec("pigpio") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pigpio"])
PY

echo "[3/7] Install pigpiod binary if missing..."
if ! command -v pigpiod >/dev/null 2>&1; then
  rm -rf /tmp/pigpio-build
  mkdir -p /tmp/pigpio-build
  cd /tmp/pigpio-build
  git clone --depth 1 https://github.com/joan2937/pigpio.git
  cd pigpio
  make -j"$(nproc)"
  make install
fi

echo "[4/7] Deploy app files..."
mkdir -p "$TARGET_DIR"
cp -f app/main.py app/sensors.py app/device_info.py app/api.py "$TARGET_DIR"/
chown -R "$APP_USER":"$APP_USER" "$TARGET_DIR"

echo "[5/7] Configure serial permissions..."
usermod -aG dialout "$APP_USER" || true
install -m 644 deploy/zzz-ttyS0-dialout.rules /etc/udev/rules.d/zzz-ttyS0-dialout.rules

if [ -f /boot/firmware/cmdline.txt ]; then
  cp -a /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.bak.serialfix || true
  sed -i 's/[[:space:]]*console=serial0,115200//g' /boot/firmware/cmdline.txt
  sed -i 's/[[:space:]]*console=ttyS0,115200//g' /boot/firmware/cmdline.txt
  sed -i 's/^[[:space:]]\+//' /boot/firmware/cmdline.txt
fi

systemctl stop serial-getty@ttyS0.service 2>/dev/null || true
systemctl mask serial-getty@ttyS0.service 2>/dev/null || true
udevadm control --reload-rules
udevadm trigger --subsystem-match=tty || true

echo "[6/7] Install and enable pigpiod service..."
install -m 644 deploy/pigpiod.service /etc/systemd/system/pigpiod.service
systemctl daemon-reload
systemctl enable --now pigpiod

echo "[7/7] Done."
echo "Reboot recommended now: sudo reboot"
echo "After reboot: python3 ~/raspi4/main.py"
