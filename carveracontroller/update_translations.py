####
#this program builds the translation files automatically from the main python programs
#it requires gettext https://www.gnu.org/software/gettext/
#on windows this requires installing https://gnuwin32.sourceforge.net/packages/gettext.htm

#to add a new language, update the LANGS array in main.py with the two letter code and the display name. 

#run with python update_translations.py while in the carveracontroller directory


####


import subprocess
import os

# Generate the .pot file from source files. Add any new UI source files here
# Separate .kv files to use the --language=Python option
python_files = ["main.py", "controller.py", "gcodeViewer.py"]  # Python source files
kv_files = ["makera.kv"]  # .kv files

pot_file = "locales/messages.pot"
subprocess.run(["xgettext", "-d", "messages", "-o", pot_file, "--from-code=UTF-8"] + python_files)
print(f"Generated .pot file from Python files: {pot_file}")

# Process .kv files separately with --language=Python
for kv_file in kv_files:
    subprocess.run(["xgettext", "-j", "-d", "messages", "-o", pot_file, "--from-code=UTF-8", "--language=Python", kv_file])
    print(f"Appended .pot file with entries from {kv_file}")

# List of languages for .po files
languages = ["de", "en", "es", "fr", "it", "ja", "ko", "pt", "zh-CN", "zh-TW"]
po_files = [f"locales/{lang}/LC_MESSAGES/{lang}.po" for lang in languages]

# Check if .po files exist; if not, create them from .pot file
for po_file in po_files:
    os.makedirs(os.path.dirname(po_file), exist_ok=True)
    
    if not os.path.exists(po_file):
        # Initialize the .po file using msginit
        lang_code = po_file.split('/')[-3]  # Extract language code from file path
        subprocess.run(["msginit", "-l", lang_code, "-i", pot_file, "-o", po_file])
        print(f"Created new .po file: {po_file}")
    else:
        # Update existing .po file with new entries from .pot file
        subprocess.run(["msgmerge", "-U", po_file, pot_file])
        print(f"Updated {po_file} with new entries from {pot_file}")

# Compile .po files to .mo files
for po_file in po_files:
    mo_file = po_file.replace(".po", ".mo")
    subprocess.run(["msgfmt", "-o", mo_file, po_file])
    print(f"Compiled {po_file} to {mo_file}")


