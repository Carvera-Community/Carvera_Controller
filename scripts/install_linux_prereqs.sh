#!/bin/bash
set -e  # Exit on error

# Function to print status messages
print_status() {
    echo "==> $1"
}

# Install system dependencies
print_status "Updating package lists"
sudo apt update

print_status "Installing system dependencies"
sudo apt install -y \
    git \
    python3 \
    python3-dev \
    python3-pip \
    build-essential \
    squashfs-tools \
    gettext \
    autoconf \
    automake \
    libtool \
    pkg-config \
    mtdev-tools \
    libhidapi-hidraw0


print_status "Installing linuxdeploy (AppImage)"
LINUXDEPLOY_URL="https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
LINUXDEPLOY_BIN="linuxdeploy"
TMP_LINUXDEPLOY="/tmp/linuxdeploy-x86_64.AppImage"
curl -L "$LINUXDEPLOY_URL" -o "$TMP_LINUXDEPLOY"
chmod +x "$TMP_LINUXDEPLOY"
if [ "$(id -u)" -eq 0 ]; then
    mv "$TMP_LINUXDEPLOY" "/usr/local/bin/$LINUXDEPLOY_BIN"
else
    mkdir -p "$HOME/.local/bin"
    mv "$TMP_LINUXDEPLOY" "$HOME/.local/bin/$LINUXDEPLOY_BIN"
fi

print_status "Linux development dependencies installed successfully"
