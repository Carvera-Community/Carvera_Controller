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


print_status "Linux development dependencies installed successfully"
