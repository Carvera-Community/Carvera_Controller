# Carvera Controller

Community developed version of the Makera Carvera Controller software.

## Development Build Environment Setup

To contribute to this project or set up a local development environment, follow these steps to install dependencies and prepare your environment.

### Prerequisites

- Ensure you have [Python](https://www.python.org/downloads/) installed on your system (preferably version 3.8 or later).
- [Poetry](https://python-poetry.org/) is required for dependency management. Poetry simplifies packaging and simplifies the management of Python dependencies.
- [Squashfs-tools](https://github.com/plougher/squashfs-tools) is required if building Linux AppImages. On Debian based systems it's provided by the package `squashfs-tools`

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

You can run your project or specific scripts using Poetry's run command. For example:

```bash
poetry run python carveracontroller/main.py
```

### Local Packaging

The application is packaged using PyInstaller. This tool converts Python applications into a standalone executable, so it can be run on systems without requiring management of a installed Python interpreter or dependent libraries. An build helper script is configured with Poetry and can be run with:

```bash
poetry run python scripts/build.py --os os [--no-appimage]
```

The options for `os` are windows, macos, or linux. Default is linux. If selecting `linux`, an appimage is built by default unless --no-appimage is specified.
