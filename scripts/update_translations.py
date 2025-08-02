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


POT_FILE = "locales/messages.pot"
LANGUAGES = ["en","zh-CN"]  # Supported Languages

BUILD_PATH = Path(__file__).parent.resolve()
PACKAGE_NAME = "carveracontroller"
PROJECT_PATH = BUILD_PATH.parent.joinpath(PACKAGE_NAME).resolve()
PACKAGE_PATH = PROJECT_PATH.resolve()

def generate_pot():
    for py_file in Path("./carveracontroller").rglob("*.py"):
        # Get the relative path from the carveracontroller directory
        # Remove the "carveracontroller/" prefix since we're running from that directory
        py_file_path = str(py_file).replace("carveracontroller/", "")
        
        subprocess.run(
            ["xgettext", "-j", "-d", "messages", "-o", POT_FILE, "--from-code=UTF-8", "--language=Python", py_file_path], 
            cwd=PACKAGE_PATH
        )
        print(f"Appended .pot file with entries from {py_file}")

    # Process .kv files separately with --language=Python
    for kv_file in Path("./carveracontroller").rglob("*.kv"):
        # Get the relative path from the carveracontroller directory
        # Remove the "carveracontroller/" prefix since we're running from that directory
        kv_file_path = str(kv_file).replace("carveracontroller/", "")
        subprocess.run(
            ["xgettext", "-j", "-d", "messages", "-o", POT_FILE, "--from-code=UTF-8", "--language=Python", kv_file_path], 
            cwd=PACKAGE_PATH
        )
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