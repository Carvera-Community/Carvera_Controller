####
# this program builds the translation files automatically from the main python programs
# it requires gettext https://www.gnu.org/software/gettext/
# on windows this requires installing https://gnuwin32.sourceforge.net/packages/gettext.htm
# to add a new language, update the LANGS array in main.py with the two letter code and the display name.
# run with python update_translations.py while in the carveracontroller directory
####


import os
import subprocess
from pathlib import Path

POT_FILE = "locales/messages.pot"
LANGUAGES = ["en", "zh-CN"]  # Supported Languages

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
            [
                "xgettext",
                "-j",
                "-d",
                "messages",
                "-o",
                POT_FILE,
                "--from-code=UTF-8",
                "--language=Python",
                py_file_path,
            ],
            cwd=PACKAGE_PATH,
        )
        print(f"Appended .pot file with entries from {py_file}")

    # Process .kv files separately with --language=Python
    for kv_file in Path("./carveracontroller").rglob("*.kv"):
        # Get the relative path from the carveracontroller directory
        # Remove the "carveracontroller/" prefix since we're running from that directory
        kv_file_path = str(kv_file).replace("carveracontroller/", "")
        subprocess.run(
            [
                "xgettext",
                "-j",
                "-d",
                "messages",
                "-o",
                POT_FILE,
                "--from-code=UTF-8",
                "--language=Python",
                kv_file_path,
            ],
            cwd=PACKAGE_PATH,
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
            lang_code = po_file.split("/")[-3]  # Extract language code from file path
            subprocess.run(["msginit", "-l", lang_code, "-i", POT_FILE, "-o", po_file])
            print(f"Created new .po file: {po_file}")
        else:
            # Update existing .po file with new entries from .pot file
            subprocess.run(["msgmerge", "-U", po_file, POT_FILE], cwd=PACKAGE_PATH)
            print(f"Updated {po_file} with new entries from {POT_FILE}")


def compile_mo():
    # Compile .po files to .mo files
    import shutil as _shutil
    import struct as _struct
    po_files = [f"{PACKAGE_PATH}/locales/{lang}/LC_MESSAGES/{lang}.po" for lang in LANGUAGES]
    for po_file in po_files:
        mo_file = po_file.replace(".po", ".mo")
        # Prefer external msgfmt if available; fall back to pure-Python compiler
        msgfmt_exe = _shutil.which("msgfmt")
        if msgfmt_exe is not None:
            subprocess.run([msgfmt_exe, "-o", mo_file, po_file], cwd=PACKAGE_PATH)
            print(f"Compiled {po_file} to {mo_file} (msgfmt)")
            continue
        # --- Pure-Python fallback compiler (no gettext tools required) ---
        entries = []
        with open(po_file, encoding="utf-8") as f:
            data = f.read()
        blocks = []
        current = []
        for line in data.splitlines():
            if line.strip() == "":
                if current:
                    blocks.append(current)
                    current = []
            else:
                current.append(line)
        if current:
            blocks.append(current)

        def _strip_quote(s):
            s = s.strip()
            if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
                s = s[1:-1]
            out = []
            i = 0
            while i < len(s):
                if s[i] == "\\" and i + 1 < len(s):
                    n = s[i + 1]
                    out.append({
                        "n": "\n", "t": "\t", "r": "\r",
                        '"': '"', "'": "'", "\\": "\\",
                    }.get(n, n))
                    i += 2
                else:
                    out.append(s[i])
                    i += 1
            return "".join(out)

        for block in blocks:
            msgid_lines = []
            msgstr_lines = []
            mode = None
            for line in block:
                line_s = line.strip()
                if line_s.startswith("#"):
                    continue
                if line_s.startswith("msgid "):
                    mode = "msgid"
                    msgid_lines.append(line_s[len("msgid "):])
                elif line_s.startswith("msgstr "):
                    mode = "msgstr"
                    msgstr_lines.append(line_s[len("msgstr "):])
                elif (line_s[:1] in ('"', "'")):
                    if mode == "msgid":
                        msgid_lines.append(line_s)
                    elif mode == "msgstr":
                        msgstr_lines.append(line_s)
            msgid = _strip_quote("".join(msgid_lines)) if msgid_lines else ""
            msgstr = _strip_quote("".join(msgstr_lines)) if msgstr_lines else ""
            if msgid != "" or msgstr != "":
                entries.append((msgid.encode("utf-8"), msgstr.encode("utf-8")))

        num = len(entries)
        data = bytearray()
        data += _struct.pack("<I", 0x950412de)
        data += _struct.pack("<I", 0)
        data += _struct.pack("<I", num)
        id_off = 28
        str_off = 28 + num * 8
        data += _struct.pack("<I", id_off)
        data += _struct.pack("<I", str_off)
        data += _struct.pack("<I", 0)
        data += _struct.pack("<I", 0)
        # Compute block start
        blob_start = 28 + num * 8 * 2
        cur = blob_start
        id_descs = []
        for msgid, _msgstr in entries:
            id_descs.append((len(msgid), cur))
            cur += len(msgid) + 1
        str_descs = []
        for _msgid, msgstr in entries:
            str_descs.append((len(msgstr), cur))
            cur += len(msgstr) + 1
        for length, offset in id_descs:
            data += _struct.pack("<I", length)
            data += _struct.pack("<I", offset)
        for length, offset in str_descs:
            data += _struct.pack("<I", length)
            data += _struct.pack("<I", offset)
        for msgid, _msgstr in entries:
            data += msgid + b"\x00"
        for _msgid, msgstr in entries:
            data += msgstr + b"\x00"
        with open(mo_file, "wb") as f:
            f.write(bytes(data))
        print(f"Compiled {po_file} to {mo_file} (pure-python fallback)")


def main():
    generate_pot()
    generate_po()
    compile_mo()


if __name__ == "__main__":
    main()
