#!/usr/bin/python3
from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
import os
import platform
import toml
from glob import glob
from pathlib import Path

import PyInstaller.__main__
import pyinstaller_versionfile
from ruamel.yaml import YAML

from update_translations import compile_mo

logger = logging.getLogger(__name__)

# ------ Build config ------
APP_NAME = "Carvera-Controller-Community"
PACKAGE_NAME = "carveracontroller"
ASSETS_FOLDER = "packaging_assets"

# ------ Versionfile info ------
COMPANY_NAME = "Carvera-Community"
FILE_DESCRIPTION = APP_NAME
INTERNAL_NAME = APP_NAME
LEGAL_COPYRIGHT = "GNU General Public License v2.0"
PRODUCT_NAME = APP_NAME


# ------ Build paths ------
BUILD_PATH = Path(__file__).parent.resolve()
ROOT_PATH = BUILD_PATH.parent.resolve()
PROJECT_PATH = BUILD_PATH.parent.joinpath(PACKAGE_NAME).resolve()
PACKAGE_PATH = PROJECT_PATH.resolve()
ROOT_ASSETS_PATH = ROOT_PATH.joinpath(ASSETS_FOLDER).resolve()


def build_pyinstaller_args(
    os: str,
    output_filename: str,
    versionfile_path: Path | None = None,
) -> list[str]:
    logger.info("Build Pyinstaller args.")
    build_args = []
    script_entrypoint = f"{PACKAGE_NAME}/__main__.py"

    logger.info(f"entrypoint: {script_entrypoint}")
    build_args += [script_entrypoint]

    logger.info(f"Path to search for imports: {PACKAGE_PATH}")
    build_args += ["-p", f"{PACKAGE_PATH}"]

    logger.info(f"Spec file path: {BUILD_PATH}")
    build_args += ["--specpath", f"{BUILD_PATH}"]

    logger.info(f"Output exe filename: {output_filename}")
    build_args += ["-n", output_filename]

    if os == "macos":
        logger.info(f"Output file icon: {ROOT_ASSETS_PATH.joinpath('icon-src.icns')}")
        build_args += ["--icon", f"{ROOT_ASSETS_PATH.joinpath('icon-src.icns')}"]
        build_args += ["--add-binary", f"{ROOT_ASSETS_PATH.joinpath('hidapi/macos/'+platform.machine()+'/libhidapi.dylib')}:."]
    if os == "windows":
        logger.info("Build option: onefile")
        build_args += ["--onefile"]
        logger.info(f"Output file icon: {ROOT_ASSETS_PATH.joinpath('icon-src.ico')}")
        build_args += ["--icon", f"{ROOT_ASSETS_PATH.joinpath('icon-src.ico')}"]
        logger.info(f"Add hidapi.dll binary: {ROOT_ASSETS_PATH.joinpath('hidapi/windows/hidapi.dll')}")
        build_args += ["--add-binary", f"{ROOT_ASSETS_PATH.joinpath('hidapi/windows/hidapi.dll')}:."]
        logger.info("Add win32timezone to hidden imports")
        build_args += ["--hiddenimport", "win32timezone"]
    else:
        logger.info(f"Output file icon: {ROOT_ASSETS_PATH.joinpath('icon-src.png')}")
        build_args += ["--icon", f"{ROOT_ASSETS_PATH.joinpath('icon-src.png')}"]

    logger.info(f"Add bundled package assets: {PACKAGE_PATH}")
    build_args += ["--add-data", f"{PACKAGE_PATH}:carveracontroller"]

    logger.info("Build options: noconsole, noconfirm, noupx, clean")
    build_args += [
        "--noconsole",
        # "--debug=all",  # debug output toggle
        "--noconfirm",
        "--noupx",  # Not sure if the false positive AV hits are worth it
        "--clean",
        "--log-level=INFO",
    ]

    if versionfile_path is not None:
        logger.info(f"Versionfile path: {versionfile_path}")
        build_args += ["--version-file", f"{versionfile_path}"]

    print(" ".join(build_args))
    return build_args


def run_pyinstaller(build_args: list[str]) -> None:
    PyInstaller.__main__.run(build_args)


def generate_versionfile(package_version: str, output_filename: str) -> Path:
    logger.info("Generate versionfile.txt.")
    versionfile_path = BUILD_PATH.joinpath("versionfile.txt")
    
    # Convert version with suffix to Windows-compatible 4-part version
    # Windows version files require exactly 4 numeric components
    windows_version = convert_version_to_4part(package_version)
    logger.info(f"Converting version '{package_version}' to Windows-compatible version '{windows_version}'")
    
    pyinstaller_versionfile.create_versionfile(
        output_file=versionfile_path,
        version=windows_version,
        company_name=COMPANY_NAME,
        file_description=FILE_DESCRIPTION,
        internal_name=INTERNAL_NAME,
        legal_copyright=LEGAL_COPYRIGHT,
        original_filename=f"{output_filename}.exe",
        product_name=PRODUCT_NAME,
    )

    return versionfile_path


def convert_version_to_4part(version_string: str, always_include_build: bool = False) -> str:
    """
    Generic function to convert a version string with optional suffix to a compatible version.
    
    Args:
        version_string: Version string in X.Y.Z[-SUFFIX] format
        always_include_build: If True, always return 4-part version (X.Y.Z.BUILD)
                             If False, only include build number when suffix exists
    
    Examples:
    - "1.2.3" -> "1.2.3" (always_include_build=False) or "1.2.3.0" (always_include_build=True)
    - "2.0.0-RC1" -> "2.0.0.1"
    - "1.0.0-BETA2" -> "1.0.0.12"
    - "3.1.0-ALPHA" -> "3.1.0.20"
    """
    # Split version and suffix
    if '-' in version_string:
        version_parts = version_string.split('-', 1)
        base_version = version_parts[0]
        suffix = version_parts[1]
    else:
        base_version = version_string
        suffix = None
    
    # Parse base version (should be X.Y.Z)
    version_components = base_version.split('.')
    if len(version_components) != 3:
        raise ValueError(f"Base version must be in X.Y.Z format, got: {base_version}")
    
    # Convert suffix to build number
    build_number = 0  # Default for releases without suffix
    if suffix:
        suffix_upper = suffix.upper()
        if suffix_upper.startswith('RC'):
            # RC1, RC2, etc. -> build numbers 1, 2, etc.
            try:
                build_number = int(suffix_upper[2:]) if len(suffix_upper) > 2 else 1
            except ValueError:
                build_number = 1
        elif suffix_upper.startswith('BETA'):
            # BETA1, BETA2, etc. -> build numbers 10, 11, etc.
            try:
                build_number = 10 + int(suffix_upper[4:]) if len(suffix_upper) > 4 else 10
            except ValueError:
                build_number = 10
        elif suffix_upper.startswith('ALPHA'):
            # ALPHA1, ALPHA2, etc. -> build numbers 20, 21, etc.
            try:
                build_number = 20 + int(suffix_upper[5:]) if len(suffix_upper) > 5 else 20
            except ValueError:
                build_number = 20
        elif suffix_upper.startswith('DEV'):
            # DEV1, DEV2, etc. -> build numbers 30, 31, etc.
            try:
                build_number = 30 + int(suffix_upper[3:]) if len(suffix_upper) > 3 else 30
            except ValueError:
                build_number = 30
        else:
            # Unknown suffix, use a high build number to avoid conflicts
            build_number = 100
    
    # Return version based on always_include_build parameter
    if always_include_build or build_number > 0:
        return f"{version_components[0]}.{version_components[1]}.{version_components[2]}.{build_number}"
    else:
        return base_version

def run_linuxdeploy_appimage(package_version: str) -> None:
    """Build AppImage using linuxdeploy."""
    # Prepare AppDir
    appdir = BUILD_PATH / "AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr/share/icons").mkdir(parents=True, exist_ok=True)

    # Copy icon
    shutil.copy2(ROOT_ASSETS_PATH / "icon-src.png", appdir / "usr/share/icons/carveracontroller.png")
    
    # Copy built files
    dist_dir = ROOT_PATH / "dist" / PACKAGE_NAME
    if not dist_dir.exists():
        print("Error: The dist/ directory doesn't exist. PyInstaller must have failed to output to it.")
        sys.exit(1)
    shutil.copytree(dist_dir, (appdir / "usr/bin"))

    # Create .desktop file
    desktop_file = appdir / "carveracontroller.desktop"
    with open(desktop_file, "w") as f:
        f.write(f"""[Desktop Entry]\nType=Application\nName=Carvera Controller Community\nExec=carveracontroller\nIcon=carveracontroller\nCategories=Utility;\n""")
    
    # Check for linuxdeploy in PATH
    import shutil as sh
    linuxdeploy = sh.which("linuxdeploy")
    if not linuxdeploy:
        print("Error: linuxdeploy not found in PATH. Please install it and try again.")
        sys.exit(1)

    # Run linuxdeploy
    env = os.environ.copy()
    env["LINUXDEPLOY_OUTPUT_VERSION"] = package_version
    subprocess.run([
        linuxdeploy,
        "--appdir", str(appdir),
        "--desktop-file", str(desktop_file),
        "--icon-file", str(appdir / "usr/share/icons/carveracontroller.png"),
        "--output",  'appimage'
    ], check=True, env=env)


def remove_shared_libraries(freeze_dir, *filename_patterns):
    for pattern in filename_patterns:
        for file_path in glob(os.path.join(freeze_dir, pattern)):
            logger.info(f"Removing {file_path}")
            os.remove(file_path)

def fix_macos_version_string(version)-> None:
    command = f"plutil -replace CFBundleShortVersionString -string {version} dist/*.app/Contents/Info.plist"
    result = subprocess.run(command, shell=True, capture_output=False, text=True)
    if result.returncode != 0:
        logger.error(f"Error executing command: {command}")
        logger.error(f"stderr: {result.stderr}")
        sys.exit(result.returncode)


def codegen_version_string(package_version: str, project_path: str, root_path: str, target_os: str = None)-> None:
    # For Android builds, we need to use the converted version without suffix
    # to avoid parsing errors in the Android build system
    if target_os == "android":
        version_for_files = convert_version_to_4part(package_version, always_include_build=True)
        logger.info(f"Using Android-compatible version '{version_for_files}' for __version__.py and pyproject.toml")
    else:
        version_for_files = package_version
    
    # Update the __version__.py file used by the project
    with open(project_path.joinpath("__version__.py").resolve(), "w") as f:
        f.write(f"__version__ = '{version_for_files}'\n")
    
    # Update the value of `version` in` pyproject.toml
    pyproject_path = root_path.joinpath("pyproject.toml").resolve()
    data = toml.load(pyproject_path)
    if "tool" not in data or "poetry" not in data["tool"]:
        raise ValueError("[tool.poetry] section not found in pyproject.toml")
    data["tool"]["poetry"]["version"] = version_for_files
    with open(pyproject_path, "w", encoding="utf-8") as f:
        toml.dump(data, f)


def backup_codegen_files(root_path, project_path):
    backup_dir = Path('scripts/backup')
    files_to_backup = [
        Path(root_path, 'pyproject.toml'),
        Path(project_path, '__version__.py'),
        Path(root_path, 'buildozer.spec')
    ]
    backup_dir.mkdir(parents=True, exist_ok=True)
    for file_path in files_to_backup:
        if file_path.exists():
            shutil.copy2(file_path, backup_dir / file_path.name)
        else:
            print(f"File not found: {file_path}")


def restore_codegen_files(root_path, project_path):
    backup_dir = Path('scripts/backup')
    files_to_restore = [
        { "source_name": 'pyproject.toml', "restore_path": root_path / 'pyproject.toml'} ,
        { "source_name": '__version__.py', "restore_path": project_path / '__version__.py'},
        { "source_name": 'buildozer.spec', "restore_path": root_path / 'buildozer.spec'}
    ]
    for file in files_to_restore:
        source_path = Path(backup_dir / file["source_name"])
        if source_path.exists():
            shutil.copy2(source_path, file["restore_path"])
            print(f"Restored {file['source_name']}")
        else:
            print(f"Backup not found: {file['source_name']}")


def version_type(version_string):
    if not re.match(r'^v?\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$', version_string):
        raise argparse.ArgumentTypeError("Must be in X.Y.Z[-SUFFIX] format (e.g., 1.2.3, v1.2.3, 2.0.0-RC1, or v2.0.0-RC1)")
    
    # Remove 'v' prefix if present
    version_string = version_string.lstrip('v')
    
    # Split version into parts
    parts = version_string.split('.')
    
    # If first part is 4 digits, take last 2 digits
    if len(parts[0]) == 4:
        parts[0] = parts[0][-2:]
    
    return '.'.join(parts)


def rename_release_file(os_name, package_version):
    if os_name == "macos":
        arch = platform.machine()
        if arch == "arm64":
            arch_name = "AppleSilicon"
        else:
            arch_name = "Intel"
        file_name = f"carveracontroller-community-{package_version}-{arch_name}.dmg"
        src = "./dist/carveracontroller-community.dmg"
        dst = f"./dist/{file_name}"
    elif os_name == "windows":
        arch = platform.architecture()[0]
        arch_name = "x64" if arch == "64bit" else "x86"
        file_name = f"carveracontroller-community-{package_version}-windows-{arch_name}.exe"
        src = "./dist/carveracontroller.exe"
        dst = f"./dist/{file_name}"
    elif os_name == "linux":
        arch_name = platform.machine()
        file_name = f"carveracontroller-community-{package_version}-{arch_name}.appimage"
        src = f"./Carvera_Controller_Community-{package_version}-{arch_name}.AppImage"
        dst = f"./dist/{file_name}"
    elif os_name == "android":
        arch_name = "armeabi-v7a_arm64-v8a_x86_64"
        # For Android, we need to use the converted version for the source filename
        # since the APK was built with the converted version (e.g., 2.0.0.1)
        android_version = convert_version_to_4part(package_version, always_include_build=True)
        file_name = f"carveracontroller-community-{package_version}.apk"
        src = f"./dist/carveracontrollercommunity-{android_version}-{arch_name}-debug.apk"
        dst = f"./dist/{file_name}"
    else:
        # For any other OS (and pypi build), don't attempt to rename
        return
    
    shutil.move(src, dst)


def create_macos_dmg():
    dmg_path = "./dist/carveracontroller-community.dmg"
    app_src = "./dist/carveracontroller.app"
    app_dst = "./dist/Carvera Controller Community.app"

    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    # Rename .app
    if os.path.exists(app_src):
        os.rename(app_src, app_dst)
    else:
        raise FileNotFoundError(f"Source app not found: {app_src}")

    cmd = [
        "create-dmg",
        "--volname", "carvera-controller-community",
        "--background", "packaging_assets/dmg_background.jpg",
        "--volicon", "packaging_assets/icon-src.icns",
        "--window-pos", "200", "200",
        "--window-size", "640", "324",
        "--icon", "Carvera Controller Community.app", "130", "130",
        "--icon-size", "64",
        "--hide-extension", "Carvera Controller Community.app",
        "--app-drop-link", "510", "130",
        "--format", "UDBZ",
        "--no-internet-enable",
        dmg_path,
        app_dst
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Error creating DMG:", result.stderr)
        raise RuntimeError("create-dmg failed")


def update_buildozer_version(package_version: str) -> None:
    """Update the version in buildozer.spec file."""
    logger.info("Updating version in buildozer.spec")
    buildozer_spec_path = ROOT_PATH.joinpath("buildozer.spec")
    
    # Convert version with suffix to Android-compatible version
    # Android build system expects a version string that can be parsed into numeric components
    # We need to ensure it's always in a consistent format for parsing
    android_version = convert_version_to_4part(package_version, always_include_build=True)
    logger.info(f"Converting version '{package_version}' to Android-compatible version '{android_version}'")
    
    # Calculate a reasonable version code for Android
    # Format: MMNNPP where MM=major, NN=minor, PP=patch
    # For versions with suffixes, add a small offset to avoid conflicts
    version_parts = android_version.split('.')
    major = int(version_parts[0])
    minor = int(version_parts[1])
    patch = int(version_parts[2])
    
    # Create version code: major * 10000 + minor * 100 + patch
    # This gives us room for up to 99 minor versions and 99 patch versions
    version_code = major * 10000 + minor * 100 + patch
    
    # If there was a suffix in the original version, add a small offset
    if '-' in package_version:
        version_code += 1000  # Add offset for pre-release versions
    
    logger.info(f"Calculated Android version code: {version_code}")
    
    with open(buildozer_spec_path, 'r') as file:
        lines = file.readlines()
    
    # Update the version field
    for i, line in enumerate(lines):
        if line.startswith('version = '):
            lines[i] = f'version = {android_version}\n'
            break
    
    # Update the android.numeric_version field
    for i, line in enumerate(lines):
        if line.startswith('android.numeric_version = '):
            lines[i] = f'android.numeric_version = {version_code}\n'
            break
        elif line.startswith('# android.numeric_version = '):
            # If it's commented out, uncomment and set the value
            lines[i] = f'android.numeric_version = {version_code}\n'
            break
    
    with open(buildozer_spec_path, 'w') as file:
        file.writelines(lines)


def update_buildozer_automation() -> None:
    """Update buildozer.spec for automation/CI environment."""
    logger.info("Updating buildozer.spec for automation")
    buildozer_spec_path = ROOT_PATH.joinpath("buildozer.spec")
    
    with open(buildozer_spec_path, 'r') as file:
        lines = file.readlines()
    
    for i, line in enumerate(lines):
        if line.startswith('# android.accept_sdk_license = '):
            lines[i] = 'android.accept_sdk_license = True\n'
            break
    
    with open(buildozer_spec_path, 'w') as file:
        file.writelines(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--os",
        metavar="os",
        required=True,
        choices=["windows", "macos", "linux", "ios", "pypi", "android"],
        type=str,
        default="linux",
        help="Choices are: windows, macos, pypi, android or linux. Default is linux."
    )

    parser.add_argument('--no-appimage', dest='appimage', action='store_false')
    
    parser.add_argument(
        '--automation',
        action='store_true',
        help='Enable automation mode for CI environments'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode with deploy, run and logcat for Android builds'
    )

    parser.add_argument(
        "--version",
        metavar="version",
        required=True,
        type=version_type,
        help="Version string to use for build. Supports X.Y.Z[-SUFFIX] format (e.g., 1.2.3, 2.0.0-RC1, v2.0.0-BETA2)."
    )

    args = parser.parse_args()
    os_name = args.os
    appimage = args.appimage
    package_version = args.version
    output_filename = PACKAGE_NAME
    versionfile_path = None

    logger.info(f"Version determined to be {package_version}")

    logger.info("Backing up files that will be modified by codegen")
    backup_codegen_files(ROOT_PATH, PROJECT_PATH)

    logger.info("Revising files by codegen")
    codegen_version_string(package_version, PROJECT_PATH, ROOT_PATH, target_os=os_name)

    # Compile translation files
    compile_mo()

    ######### Non-PyInstaller builds #########
    if os_name == "pypi":
        logger.info("Performing pypi build via poetry")
        result = subprocess.run("poetry build", shell=True, capture_output=True, text=True, check=True)

    if os_name == "ios":
        # For iOS we need some special handling as it is not supported by pyinstaller
        # Execute the build_ios.sh script
        command = f"{BUILD_PATH}/build_ios.sh {package_version}"
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Stdout from build_ios.sh: {e.stdout}")
            logger.error(f"Error from build_ios.sh: {e.stderr}")
            sys.exit(1)
        else:
            logger.info(f"Stdout from build_ios.sh: {result.stdout}")

    if os_name == "android":
        # For Android we need some special handling as it is not supported by pyinstaller
        # Update version in buildozer.spec
        
        update_buildozer_version(package_version)
        
        # Update buildozer.spec for automation if flag is set
        if args.automation:
            update_buildozer_automation()

        if not os.path.exists(f"./main.py"):
            logger.info("Copying main.py to root directory for android build")
            shutil.copy2(f"{ROOT_ASSETS_PATH}/android/main.py", "./main.py")

        # Then run the actual build
        logger.info("Building Android APK...")
        if args.debug:
            build_command = "buildozer android debug deploy run logcat"
        else:
            build_command = "buildozer -v android debug"
        result = subprocess.run(build_command, shell=True)
        if result.returncode != 0:
            logger.error("Error building Android APK")
            sys.exit(result.returncode)

        if os.path.exists(f"./main.py"):
            logger.info("Removing main.py from root directory for android build")
            os.remove(f"./main.py")

    ######### Pre PyInstaller tweaks #########
    if os_name == "windows":
        # Windows needs a versionfile created for metadata in the binary artifact
        versionfile_path = generate_versionfile(
            package_version=package_version,
            output_filename=output_filename,
        )

    ######### Run PyInstaller for all os expcept those that don't use it #########
    if os_name not in ("ios", "pypi", "android"):
        build_args = build_pyinstaller_args(
            os=os_name,
            output_filename=output_filename,
            versionfile_path=versionfile_path,
        )
        run_pyinstaller(build_args=build_args)

    ######### Post PyInstaller tweaks #########
    if os_name == "linux":
        # Need to remove some libs for opinionated backwards compatibility
        # https://github.com/pyinstaller/pyinstaller/issues/6993 
        frozen_dir = f"dist/{PACKAGE_NAME}/_internal"
        remove_shared_libraries(frozen_dir, 'libstdc++.so.*', 'libtinfo.so.*', 'libreadline.so.*', 'libdrm.so.*')

        if appimage:
            run_linuxdeploy_appimage(package_version)
    
    if os_name == "macos":
        # Need to manually revise the version string due to
        # https://github.com/pyinstaller/pyinstaller/issues/6943
        import PyInstaller.utils.osx as osxutils
        fix_macos_version_string(package_version)
        osxutils.sign_binary(f"dist/{PACKAGE_NAME}.app", deep=True)
        create_macos_dmg()
    
    logger.info("Renaming artifacts to have version number and platform in filename")
    rename_release_file(os_name, package_version)

    logger.info("Restoring files modified by codegen")
    restore_codegen_files(ROOT_PATH, PROJECT_PATH)

if __name__ == "__main__":
    main()
