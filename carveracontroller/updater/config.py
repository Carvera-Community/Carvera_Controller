"""Canonical GitHub repos and HTTP defaults for the Update Center."""

from __future__ import annotations

API_BASE = "https://api.github.com"
CONTROLLER_OWNER = "Carvera-Community"
CONTROLLER_REPO = "Carvera_Controller"
FIRMWARE_OWNER = "Carvera-Community"
FIRMWARE_REPO = "Carvera_Community_Firmware"
CONTROLLER_RELEASES_URL = f"{API_BASE}/repos/{CONTROLLER_OWNER}/{CONTROLLER_REPO}/releases"
FIRMWARE_RELEASES_URL = f"{API_BASE}/repos/{FIRMWARE_OWNER}/{FIRMWARE_REPO}/releases"
ACCEPT_HEADER = "application/vnd.github+json"
API_VERSION = "2022-11-28"
USER_AGENT = "Carvera-Controller-Community (+https://github.com/Carvera-Community/Carvera_Controller)"
REQUEST_TIMEOUT_S = 20
DOWNLOAD_TIMEOUT_S = 60
RELEASES_PER_PAGE = 30
SKIP_TAGS = frozenset({"dev"})
CACHE_SUBDIR = "updates"
CONTROLLER_CACHE_NAME = "controller-releases.json"
FIRMWARE_CACHE_NAME = "firmware-releases.json"
CACHE_MAX_AGE_S = 6 * 60 * 60
CONFIG_SHOW_UPDATE = "show_update"
CONFIG_INCLUDE_PRERELEASES = "include_prereleases"
