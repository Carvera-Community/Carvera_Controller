# Community Carvera Controller

The Community developed version of the Carvera Controller has a number of benefits and fixes above and beyond the Makera software. See the [online Documentation site](https://carvera-community.gitbook.io/docs/controller/about) for installation and usage details.

## Functionality Summary
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

## Contributing

Review this guide for [how to contribute](CONTRIBUTING.md) to this codebase.

## Development Environment Setup

To contribute to this project or set up a local development environment, follow these steps to install dependencies and prepare your environment.

### Prerequisites

* Ensure you have [Python](https://www.python.org/downloads/) installed on your system (preferably version 3.8 or later).
* [Poetry](https://python-poetry.org/) is required for dependency management. Poetry simplifies packaging and simplifies the management of Python dependencies.
* One of the python dependencies [QuickLZ](https://pypi.org/project/pyquicklz/) will be compiled by Poetry when installed. Ensure that you have a compiler that Poetry/Pip can use and the Python headers. On a debian based Linux system this can be accomplished with `sudo apt-get install -y python3-dev build-essential`. On Windows installation of (just) the Visual C++ 14.x compiler is required, this can be accomplished with [MSBuild tools package](https://aka.ms/vs/17/release/vs_BuildTools.exe).
* [Squashfs-tools](https://github.com/plougher/squashfs-tools) is required if building Linux AppImages. On Debian based systems it's provided by the package `squashfs-tools`. This is only required if packaging for linux.
* [linuxdeploy](https://github.com/linuxdeploy/linuxdeploy) is required for building Linux AppImages. These must be installed and available in your PATH before building. You can install them using `scripts/install_linux_prereqs.sh` or by following the instructions on their GitHub page.
* [gettext](https://www.gnu.org/software/gettext/) is required for language file generation. [gettext-iconv-windows](https://mlocati.github.io/articles/gettext-iconv-windows.html) project has a version with Windows packages.
* For building iOS app, you need a working XCode installation as well as the build tool that can be installed with `brew install autoconf automake libtool pkg-config`
* Building the Android app needs a Linux host. The prerequisites can be found here: [buildozer prerequisites](https://buildozer.readthedocs.io/en/latest/installation.html). A script to install them is provided in `scripts/install_android_prereqs.sh`. Be aware that buildozer downloads/installs multiple GB of Android development tooling.

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

1. **Clone the repository**

   ```bash
   git clone https://github.com/Carvera-Community/CarveraController.git
   ```

2. **Install the project dependencies**

   ```bash
   poetry install
   ```

   On Windows the ios-dev dependencies cannot be satisfied, so instead you need to run: `poetry install --without ios-dev`

   This command will create a virtual environment (if one doesn't already exist) and install all required dependencies as specified in the `pyproject.toml` file.

3. **Activate the virtual environment** (optional, but useful for running scripts directly)

   ```bash
   poetry env activate
   ```

   This step is usually not necessary since `poetry run <command>` automatically uses the virtual environment, but it can be helpful if you want to run multiple commands without prefixing `poetry run`.

### Running the Project

You can run the Controller software using Poetry's run command without installation. This is handy for iterative development.

```bash
poetry run python -m carveracontroller
```

To run the iOS app, you first need to build its dependencies using the Local Packaging instructions below. The build script will open Xcode for you, or you can open the project manually by finding it in `assets/packaging/ios/carveracontroller-ios`.

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
