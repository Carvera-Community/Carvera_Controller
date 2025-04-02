# Carvera Controller

Community developed version of the Makera Carvera Controller software.

## Supported OS

The Controller software works on the following systems:

- Windows 7 x64 or newer
- MacOS using Intel CPUs running Ventura (13) or above
- MacOS using Apple Silicon CPUs running Sonoma (14) or above
- Linux using x64 CPUs running a Linux distribution with Glibc 2.31 or above (eg. Ubuntu 20.04 or higher)
- Apple iPad with iOS 17.6 or higher
- Other systems might be work via the Python Package, see below for more details.

## Installation

See the assets section of [latest release](https://github.com/carvera-community/carvera_controller/releases/latest) for installation packages for your system.

- carveracontroller-community-\<version\>-windows-x64.exe - Standalone Windows binary, without a installer
- carveracontroller-community-\<version\>-Intel.dmg - MacOS with Intel CPU
- carveracontroller-community-\<version\>-AppleSilicon.dmg - MacOS with Apple CPU (M1 etc)
- carveracontroller-community-\<version\>-x86_64.appimage - Linux AppImage for x64 systems

### Usage: Linux App Images

Linux AppImages are a self-contained binary with all the required dependencies to run the application.

To use it, first make it executable (`chmod +x carveracontroller-community-<version>-<arch>.appimage`).

Then you will be able to run it.

If you want a shortcut, consider using [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher).

## Alternative Installation: Python Package

It's best to use one of the pre-built packages as they they have frozen versions of tested dependencies and python interpreter, however if you prefer the software can be installed as a Python package. This might allow you to use a unsupported platform (eg raspi 1) provided that the dependencies can be met.

``` bash
pip install carvera-controller-community
```

Once installed it can be run via the module

``` bash
python3 -m carveracontroller
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
- [gettext](https://www.gnu.org/software/gettext/) is required for language file generation. [Gnuwin32](https://gnuwin32.sourceforge.net/packages/gettext.htm) project has a version for Windows
- For building iOS app, you need a working XCode installation as well as the build tool that can be installed with `brew install autoconf automake libtool pkg-config`

### Installing Poetry

Follow the official installation instructions to install Poetry. The simplest method is via the command line:

```bash
curl -sSL https://install.python-poetry.org | python3 -
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
poetry run python scripts/build.py --os os [--no-appimage]
```

The options for `os` are windows, macos, linux or ios. If selecting `linux`, an appimage is built by default unless --no-appimage is specified.
For iOS, the project will be open in XCode and needs to be built from there to simplify the signing process.

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