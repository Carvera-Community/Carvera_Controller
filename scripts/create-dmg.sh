#!/bin/bash

echo "Remove previous build if exists ..."
rm -rf ./dist/carveracontroller-community.dmg

echo "Create DMG ..."
create-dmg \
    --volname "carvera-controller-community" \
    --background "packaging_assets/dmg_background.jpg" \
    --volicon "packaging_assets/icon-src.icns" \
    --window-pos 200 200 \
    --window-size 460 160 \
    --icon "carveracontroller.app" 256 256 \
    --icon-size 64 \
    --hide-extension "carveracontroller.app" \
    --app-drop-link 325 80 \
    --format UDBZ \
    --no-internet-enable \
    "./dist/carveracontroller-community.dmg" \
    "./dist/carveracontroller.app"