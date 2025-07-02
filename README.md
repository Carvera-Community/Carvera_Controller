# Carvera Controller

Community developed version of the Makera Carvera Controller software.

## Why use the Community Controller?

The Community developed version of the Carvera Controller has a number of benefits and fixes above and beyond the Makera software.
See the [CHANGELOG](CHANGELOG.md) and [screenshots](docs/screenshots/) for more details.
* **3-axis** and advanced **probing** UI screens for various geometries (**corners**, **axis**, **bore/pocket**, **angles**) for use with a [true 3D touch probe](https://www.instructables.com/Carvera-Touch-Probe-Modifications/) (not the included XYZ probe block)
* **Pendant** device support, via **WHB04** family of **MPG devices**. Such devices can be used to jog, run macros, and perform feed/speed overrides.
* Options to **reduce** the **autolevel** probe **area** to avoid probing obstacles
* **Tooltip support** for user guidance with over 110 tips and counting
* **Background images** for bolt hole positions in probe/start screens; users can add their own too
* Support for setting/changing to **custom tool numbers** beyond 1-6
* Keyboard button based **jog movement** controls
* **No dial-home** back to Makera
* **Single portable binary** for Windows and Linux
* **Laser Safety** prompt to **remind** operators to put on **safety glasses**
* **Multiple developers** with their own **Carvera** machines _"drinking their own [software] champagne"_ daily and working to improve the machine's capabilities.
* Various **Quality-of-life** improvements:
   * **Controller config settings** (UI Density, screensaver disable, Allow MDI while machine running, virtual keyboard)
   * **Enclosure light** and **External Ouput** switch toggle in the center control panel
   * Machine **reconnect** functionality with stored last used **machine network address**
   * **Set Origin** Screen pre-populated with **current** offset values
   * **Collet Clamp/Unclamp** buttons in Tool Changer menu for the original Carvera
   * Better file browser **upload-and-select** workflow
   * **Previous** file browsing location is **reopened** and **previously** used locations stored to **quick access list**
   * **Greater speed/feed** override scaling range from **10%** and up to **300%**
   * **Improved** 3D gcode visualisations, including **correct rendering** of movements around the **A axis**


## Supported OS

The Controller software works on the following systems:

- Windows 7 x64 or newer
- MacOS using Intel CPUs running Ventura (13) or above
- MacOS using Apple Silicon CPUs running Sonoma (14) or above
- Linux using x64 CPUs running a Linux distribution with Glibc 2.35 or above (eg. Ubuntu 22.04 or higher)
- Linux using aarch64 CPUs (eg Raspberyy Pi 3+) running a Linux distribution with Glibc 2.39 or above (eg. Ubuntu 24.04 or higher)
- Apple iPad with iOS 17.6 or higher
- Android devices with Android 11 or higher running ARM 32-bit processors (ARMv7a)
- Other systems might be work via the Python Package, see below for more details.

## Installation

See the assets section of [latest release](https://github.com/carvera-community/carvera_controller/releases/latest) for installation packages for your system.

- carveracontroller-community-\<version\>-windows-x64.exe - Standalone Windows binary, without a installer
- carveracontroller-community-\<version\>-Intel.dmg - MacOS with Intel CPU
- carveracontroller-community-\<version\>-AppleSilicon.dmg - MacOS with Apple CPU (M1 etc)
- carveracontroller-community-\<version\>-x86_64.appimage - Linux AppImage for x64 systems
- carveracontroller-community-\<version\>-arm664.appimage - Linux AppImage for aarch64/arm64 systems
- carveracontroller-community-\<version\>-android-armeabi-v7a.apk - Android installable package
- carvera_controller_community-\<version\>-py3-none-any.whl  - Python wheel package

### Usage: Android

When using the file browser in the Controller, the app will guide you to a permission page of android where you have to grant the app full access to your android devices files. Without this you will not see any files.

Be aware that there is a known bug in one of the libraries used for graphics rendering, this can result in the screen stay black after starting the app. Until this is resolved in the upstream library we have implemented a workaround to try to prevent this from occuring. If you still encounter this issue, you then need to go to the homescreen and back to the app. Please give feedback via github issue if this occurs for you.

### Usage: Linux App Images

Linux AppImages are a self-contained binary with all the required dependencies to run the application.

To use it, first make it executable (`chmod +x carveracontroller-community-<version>-<arch>.appimage`).

Then you will be able to run it.

If you want a shortcut, consider using [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher).

### Alternative Installation: Docker

## Alternative Installation: Docker with noVNC

Its also possible to run the controller under Docker, which is then access via a browser or VNC client. This enables you to run the controller on a remote machine and access it from your local machine, and thus overcome the single-network-connection at a time limitation.

The docker image expects a volume `/config` which is used to store the configuration and log files.  If not provided, the application will run, but will not persist any configuration or log files.

The docker image is available on [GitHub Container Registry](https://ghcr.io/carvera-community/carvera-controller) with the following tag patterns:
- latest - The latest tagged release version
- dev - The latest development build
- x.y.z - A specific tagged version

The latest reeleased version can be pulled with the following command:

``` bash
docker pull ghcr.io/carvera-community/carvera-controller-<arch>:latest
```
Where `<arch>` is `x64` or `arm64` depending on your system architecture.  To run the docker image, use the following command:

``` bash
docker run -p 5900:5900 -p 8080:8080 -v /path/to/config:/config ghcr.io/carvera-community/carvera-controller-<arch>:latest
```

The application can then be accessed via a web browser at `http://<host>:8080` or via a VNC client at `<host>:5900`.  The VNC connection does not require a password.


## Alternative Installation: Python Package

It's best to use one of the pre-built packages as they they have frozen versions of tested dependencies and python interpreter, however if you prefer the software can be installed as a Python package. This might allow you to use a unsupported platform (eg raspi 1) provided that the dependencies can be met.

``` bash
pip install carvera-controller-community
```

Once installed it can be run via the module

``` bash
python3 -m carveracontroller
```

## Pendant Support

The Community controller supports the WBH04 family of pendants to control the machine. They can be purchased from [AliExpress](https://www.aliexpress.com/item/1005006270475983.html) or from other online retailers.

### Linux device permissions

To use the pendant in Linux, you need to grant your user access to the USB device. Most Linux distributions (Ubuntu/Debian/Fedora) automatically add users to the `plugdev` group, so the easiest and most secure approach is to create a udev rule that grants this group access to the device.

Run this command to create the udev rule:

```bash
sudo sh -c 'echo "SUBSYSTEM==\"hidraw\", ATTRS{idVendor}==\"10ce\", ATTRS{idProduct}==\"eb93\", GROUP=\"plugdev\", MODE=\"0660\"" > /etc/udev/rules.d/90-xhc.rules'
```

After creating the rule, you may need to reload the udev rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Contributing

Review this guide for [how to contribute](CONTRIBUTING.md) to this codebase.

## Development Environment Setup

To contribute to this project or set up a local development environment, follow these steps to install dependencies and prepare your environment.

### Prerequisites

- Ensure you have [Python](https://www.python.org/downloads/) installed on your system (preferably version 3.8 or later).
- [Poetry](https://python-poetry.org/) is required for dependency management. Poetry simplifies packaging and simplifies the management of Python dependencies.
- One of the python dependencies [QuickLZ](https://pypi.org/project/pyquicklz/) will be compiled by Poetry when installed. Ensure that you have a compiler that Poetry/Pip can use and the Pythong headers. On a debian based Linux system this can be accomplished with `sudo apt-get install python3-dev build essential`. On Windows installation of (just) the Visual C++ 14.x compiler is required, this can be accomplished with [MSBuild tools package](https://aka.ms/vs/17/release/vs_BuildTools.exe).
- [Squashfs-tools](https://github.com/plougher/squashfs-tools) is required if building Linux AppImages. On Debian based systems it's provided by the package `squashfs-tools`. This is only required if packaging for linux.
- [gettext](https://www.gnu.org/software/gettext/) is required for language file generation. [gettext-iconv-windows](https://mlocati.github.io/articles/gettext-iconv-windows.html) project has a version with Windows packages.
- For building iOS app, you need a working XCode installation as well as the build tool that can be installed with `brew install autoconf automake libtool pkg-config`
- Building the Android app needs a Linux host. The prerequisites can be found here: [buildozer prerequisites](https://buildozer.readthedocs.io/en/latest/installation.html). A script to install them is provided in `scripts/install_android_prereqs.sh`. Be aware that buildozer downloads/installs multiple GB of Android development tooling.

### Installing Poetry

Follow the official installation instructions to install Poetry. The simplest method is via the command line:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

or on Windows:

```bash
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

Once installed, make sure Poetry is in your system's PATH so you can run it from any terminal window. Verify the installation by checking the version:

```bash
poetry --version
```

### Setting Up the Development Environment

Once you have Poetry installed, setting up the development environment is straightforward:

1. Clone the repository:

   ```bash
   git clone https://github.com/Carvera-Community/CarveraController.git
   cd CarveraController
   ```

2. Install the project dependencies:

   ```bash
   poetry install
   ```

   On Windows
   ```bash
   poetry install --without ios-dev
   ```

   This command will create a virtual environment (if one doesn't already exist) and install all required dependencies as specified in the `pyproject.toml` file.

3. Activate the virtual environment (optional, but useful for running scripts directly):

   ```bash
   poetry shell
   ```

   This step is usually not necessary since `poetry run <command>` automatically uses the virtual environment, but it can be helpful if you want to run multiple commands without prefixing `poetry run`.

### Running the Project

You can run the Controller software using Poetry's run command without installation. This is handy for iterative development.

```bash
poetry run python -m carveracontroller
```

### Local Packaging

The application is packaged using PyInstaller (except for iOS). This tool converts Python applications into a standalone executable, so it can be run on systems without requiring management of a installed Python interpreter or dependent libraries. An build helper script is configured with Poetry and can be run with:

```bash
poetry run python scripts/build.py --os os --version version [--no-appimage]
```

The options for `os` are windows, macos, linux, pypi, ios or android. If selecting `linux`, an appimage is built by default unless --no-appimage is specified.
For iOS, the project will be open in XCode and needs to be built from there to simplify the signing process.

The value of `version` should be in the format of X.Y.Z e.g., 1.2.3 or v1.2.3.

### Setting up translations

The Carvera Controller UI natively uses the English language, but is capable of displaying other languages as well. Today only English and Simplified Chinese is supported. UI Translations are made using the string mapping file `carveracontroller/locales/messages.pot` and the individual language strings are stored in `carveracontroller/locales/{lang}}/LC_MESSAGES/{lang}.po`. During build the `.po` files are compiled into a binary `.mo` file using the *msgfmt* utility.

If you add or modify any UI text strings you need to update the messages.pot file and individual .po files to account for it. This way translators can help add translations for the new string in the respective .po language files.

Updating the .pot and .po strings, as well as compiling to .mo can be performed by running the following command:

``` bash
poetry run python scripts/update_translations.py
```

This utility scans the python and kivvy code for new strings and updates the mapping files. It does not clear/overwrite previous translations.

### Collected Data & Privacy

See [the privacy page](PRIVACY.md) for more details.