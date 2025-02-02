####
# this program builds the translation files automatically from the main python programs
# it requires gettext https://www.gnu.org/software/gettext/
# on windows this requires installing https://gnuwin32.sourceforge.net/packages/gettext.htm
# to add a new language, update the LANGS array in main.py with the two letter code and the display name. 
# run with python update_translations.py while in the carveracontroller directory
####


import subprocess
import os
from pathlib import Path

# Source files with UI text. This is analysed to create the .pot file
PY_FILES = ["main.py", "Controller.py", "GcodeViewer.py"]  # Python source files
KV_FILES = ["makera.kv","addons/probing/ProbingPopup.kv","addons/probing/preview/ProbingPreviewPopup.kv"]  # .kv files

POT_FILE = "locales/messages.pot"
LANGUAGES = ["en","zh-CN"]  # Supported Languages

BUILD_PATH = Path(__file__).parent.resolve()
PACKAGE_NAME = "carveracontroller"
PROJECT_PATH = BUILD_PATH.parent.joinpath(PACKAGE_NAME).resolve()
PACKAGE_PATH = PROJECT_PATH.resolve()

def generate_pot():
    subprocess.run(["xgettext", "-d", "messages", "-o", POT_FILE, "--from-code=UTF-8"] + PY_FILES, cwd=PACKAGE_PATH)
    print(f"Generated .pot file from Python files: {PY_FILES}")

    # Process .kv files separately with --language=Python
    for kv_file in KV_FILES:
        subprocess.run(["xgettext", "-j", "-d", "messages", "-o", POT_FILE, "--from-code=UTF-8", "--language=Python", kv_file], cwd=PACKAGE_PATH)
        print(f"Appended .pot file with entries from {kv_file}")

def generate_po():
    # List of languages for .po files
    po_files = [f"{PACKAGE_PATH}/locales/{lang}/LC_MESSAGES/{lang}.po" for lang in LANGUAGES]

    # Check if .po files exist; if not, create them from .pot file
    for po_file in po_files:
        os.makedirs(os.path.dirname(po_file), exist_ok=True)
        
        if not os.path.exists(po_file):
            # Initialize the .po file using msginit
            lang_code = po_file.split('/')[-3]  # Extract language code from file path
            subprocess.run(["msginit", "-l", lang_code, "-i", POT_FILE, "-o", po_file])
            print(f"Created new .po file: {po_file}")
        else:
            # Update existing .po file with new entries from .pot file
            subprocess.run(["msgmerge", "-U", po_file, POT_FILE], cwd=PACKAGE_PATH)
            print(f"Updated {po_file} with new entries from {POT_FILE}")

def compile_mo():
    # Compile .po files to .mo files
    po_files = [f"{PACKAGE_PATH}/locales/{lang}/LC_MESSAGES/{lang}.po" for lang in LANGUAGES]
    for po_file in po_files:
        mo_file = po_file.replace(".po", ".mo")
        subprocess.run(["msgfmt", "-o", mo_file, po_file], cwd=PACKAGE_PATH)
        print(f"Compiled {po_file} to {mo_file}")

def main():
    generate_pot()
    generate_po()
    compile_mo()

if __name__ == "__main__":
    main()