#!/bin/bash

echo "Remove previous build if exists ..."
rm -rf ./dist/carveracontroller-community.dmg

# rename .app
mv "./dist/carveracontroller.app" "./dist/Carvera Controller Community.app"

echo "Creating DMG ..."
create-dmg \
    --volname "carvera-controller-community" \
    --background "packaging_assets/dmg_background.jpg" \
    --volicon "packaging_assets/icon-src.icns" \
    --window-pos 200 200 \
    --window-size 640 324 \
    --icon "Carvera Controller Community.app" 130 130 \
    --icon-size 64 \
    --hide-extension "Carvera Controller Community.app" \
    --app-drop-link 510 130 \
    --format UDBZ \
    --no-internet-enable \
    "./dist/carveracontroller-community.dmg" \
    "./dist/Carvera Controller Community.app"
