# Carvera Controller

Community developed version of the Makera Carvera Controller software.

## Supported OS

The Controller software works on the following systems:

- Windows
- MacOS using Intel CPUs running Ventura (13) or above
- MacOS using Apple Silicon CPUs running Sonoma (14) or above
- Linux using x64 CPU running a Linux distribution with Glibc 2.31 or above (eg. Ubuntu 20.04 or higher)
- Linux using ARM64 CPUs (eg RasPi 3 or above) running a distribution Glibc 2.36 or above (eg. Raspios Bookworm or higher) 


## Installation

See the assets section of [latest release](https://github.com/carvera-community/carvera_controller/releases/latest) for installation packages for your system.

- carveracontroller-community-<version>-windows-x64.exe - Standalone Windows binary, without a installer
- carveracontroller-community-<version>-Intel.dmg - MacOS with Intel CPU
- carveracontroller-community-<version>-AppleSilicon.dmg - MacOS with Apple CPU (M1 etc)
- carveracontroller-community-<version>-x86_64.appimage - Linux AppImage for x64 systems
- carveracontroller-community-<version>-aarch64.appimage - Linux AppImage for ARM64 systems


## Development Environment Setup

To contribute to this project or set up a local development environment, follow these steps to install dependencies and prepare your environment.

### Prerequisites

- Ensure you have [Python](https://www.python.org/downloads/) installed on your system (preferably version 3.8 or later).
- [Poetry](https://python-poetry.org/) is required for dependency management. Poetry simplifies packaging and simplifies the management of Python dependencies.
- One of the python dependencies [QuickLZ](https://pypi.org/project/pyquicklz/) will be compiled by Poetry when installed. Ensure that you have a compiler that Poetry/Pip can use and the Pythong headers. On a debian based Linux system this can be accomplished with `sudo apt-get install python3-dev build essential`. On Windows installation of (just) the Visual C++ 14.x compiler is required, this can be accomplished with [MSBuild tools package](https://wiki.python.org/moin/WindowsCompilers#Microsoft_Visual_C.2B-.2B-_14.2_standalone:_Build_Tools_for_Visual_Studio_2019_.28x86.2C_x64.2C_ARM.2C_ARM64.29). 
- [Squashfs-tools](https://github.com/plougher/squashfs-tools) is required if building Linux AppImages. On Debian based systems it's provided by the package `squashfs-tools`. This is only required if packaging for linux.

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

   This command will create a virtual environment (if one doesn't already exist) and install all required dependencies as specified in the `pyproject.toml` file.

3. Activate the virtual environment (optional, but useful for running scripts directly):

   ```bash
   poetry shell
   ```

   This step is usually not necessary since `poetry run <command>` automatically uses the virtual environment, but it can be helpful if you want to run multiple commands without prefixing `poetry run`.

### Running the Project

You can run your project or specific scripts using Poetry's run command. This is handy for iterative development. For example:

```bash
poetry run python carveracontroller/main.py
```

### Local Packaging

The application is packaged using PyInstaller. This tool converts Python applications into a standalone executable, so it can be run on systems without requiring management of a installed Python interpreter or dependent libraries. An build helper script is configured with Poetry and can be run with:

```bash
poetry run python scripts/build.py --os os [--no-appimage]
```

The options for `os` are windows, macos, or linux. Default is linux. If selecting `linux`, an appimage is built by default unless --no-appimage is specified.
