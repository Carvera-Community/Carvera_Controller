#!/bin/bash
# Pre-requisites:
# - Working XCode installation to build iOS app
# - Homebrew installed
# - Python 3 installed
# - git installed

set -e

# Make sure it's the case
if ! command -v brew &> /dev/null
then
    echo "brew command could not be found"
    echo "Please install Homebrew from https://brew.sh/"
    exit
fi

if ! command -v python3 &> /dev/null
then
    echo "python3 command could not be found"
    echo "Please install Python 3 from https://www.python.org/downloads/"
    exit
fi

if ! command -v git &> /dev/null
then
    echo "git command could not be found"
    echo "Please install git from https://git-scm.com/downloads"
    exit
fi

if ! command -v xcode-select &> /dev/null
then
    echo "xcode-select command could not be found"
    echo "Please install XCode from the App Store"
    exit
fi

# Make sure we are in the top directory of the git repo
TOP_LEVEL=$(git rev-parse --show-toplevel)
cd $TOP_LEVEL || exit 1

ln -sf $(pwd)/dist assets/packaging/ios/dist

# numpy is required for stock cut simulation. matplotlib and
# kivy_matplotlib_widget are imported while the app is starting.
python3 -m kivy_ios.toolchain build --add-custom-recipe assets/packaging/ios/recipes/quicklz --add-custom-recipe assets/packaging/ios/recipes/pyserial --add-custom-recipe assets/packaging/ios/recipes/stock_carve --add-custom-recipe assets/packaging/ios/recipes/kivy_matplotlib_widget kivy quicklz pyserial numpy pillow stock_carve matplotlib kivy_matplotlib_widget

python3 -m kivy_ios.toolchain update --add-custom-recipe assets/packaging/ios/recipes/quicklz --add-custom-recipe assets/packaging/ios/recipes/pyserial --add-custom-recipe assets/packaging/ios/recipes/stock_carve --add-custom-recipe assets/packaging/ios/recipes/kivy_matplotlib_widget assets/packaging/ios/carveracontroller-ios

# Patch version if we given as arg
if [ -z "$1" ]
then
    echo "No version given"
else
    plutil -replace CFBundleShortVersionString -string "$1" assets/packaging/ios/carveracontroller-ios/carveracontroller-Info.plist
    plutil -replace CFBundleVersion -string "$1" assets/packaging/ios/carveracontroller-ios/carveracontroller-Info.plist
fi

if [ -n "$CI" ]; then
    xcodebuild -project assets/packaging/ios/carveracontroller-ios/carveracontroller.xcodeproj -scheme CarveraController -configuration Release -sdk iphonesimulator -arch arm64
else
    open assets/packaging/ios/carveracontroller-ios/carveracontroller.xcodeproj
fi
