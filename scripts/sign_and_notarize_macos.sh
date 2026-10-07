#!/bin/bash
# Sign, notarize, and staple a macOS disk image produced by CI.
#
# The release workflow builds carveracontroller-community-<version>-AppleSilicon.dmg
# and carveracontroller-community-<version>-Intel.dmg. PyInstaller ad-hoc signs the
# .app inside those images. Apple notarization requires a Developer ID signature,
# the hardened runtime, and a secure timestamp, so this script re-signs the app,
# puts it back in the disk image (keeping the background and icon layout), then
# signs, notarizes, and staples the disk image.
#
# Run it on a Mac, in a terminal, after downloading the CI artifacts:
#
#   gh run download RUN_ID -n macos-assets-AppleSilicon -D ~/Downloads
#   gh run download RUN_ID -n macos-assets-Intel -D ~/Downloads
#   ./scripts/sign_and_notarize_macos.sh ~/Downloads/carveracontroller-community-*.dmg
#
# Signing, notarization, and stapling are done with rcodesign
# (https://gregoryszorc.com/docs/apple-codesign/stable/index.html):
#
#   cargo install --features smartcard apple-codesign
#
# rcodesign cannot change files inside a disk image, so this script copies the
# app out, signs and notarizes it, puts it back (keeping the background and
# icon layout), then signs, notarizes, and staples the disk image.
#
# A smart card asks for its PIN before every signature. rcodesign keeps that PIN
# for the whole app, so you type it once per app and once per disk image.
#
# Notarization uses an App Store Connect API key, not a notarytool Apple ID
# profile. Create one at https://appstoreconnect.apple.com/access/api
#
# Leave free disk space of about three times the size of each disk image.
# Keep the disk images on a local folder. Signing fails on some network and
# iCloud folders. Each notarization usually takes several minutes.

set -euo pipefail

export COPYFILE_DISABLE=1

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

MOUNTED=""
WORKDIR=""
SIGN_IDENTITY=""
SIGN_IDENTITY_NAME=""
SIGN_IDENTITY_SOURCE=""
SMARTCARD_SLOT=""
SIGN_FINGERPRINT=""
API_KEY_FILE=""
OUTPUT_DIR=""
SIGNER_ARGS=()
ENTITLEMENTS="${ENTITLEMENTS_PLIST:-$ROOT_DIR/assets/packaging/macos/entitlements.plist}"

DMG_INPUTS=()
IDENTITY_HASHES=()
IDENTITY_NAMES=()
IDENTITY_SOURCES=()
IDENTITY_SLOTS=()
IDENTITY_FINGERPRINTS=()
SIGNED_OUTPUTS=()

usage() {
  cat <<'EOF'
Usage: sign_and_notarize_macos.sh [options] [disk-image ...]

Sign and notarize CI-built Carvera Controller .dmg files. With no disk image
paths, the script asks for them. Drag files from Finder into the terminal.

Options:
  -h, --help    Show this help

Environment (each one skips the matching prompt):
  CODESIGN_IDENTITY                 Certificate name, SHA-1, or SHA-256 fingerprint
  APP_STORE_CONNECT_API_KEY_FILE    JSON from rcodesign encode-app-store-connect-api-key
  SIGNED_DMG_DIR                    Folder for signed disk images (default: beside each input)
  ENTITLEMENTS_PLIST                Override the hardened-runtime entitlements plist

The signed image is written next to the input as <name>-signed.dmg unless you
choose another folder. The original disk image is left unchanged.
Keep the files on a local disk, with free space of about three times the image size.
EOF
}

say() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf '\nerror: %s\n' "$*" >&2
  exit 1
}

need_tty() {
  if [[ ! -t 0 ]]; then
    die "This step needs an interactive terminal ($1). Re-run in Terminal, or set the environment variables listed in --help."
  fi
}

confirm() {
  local answer
  need_tty "$1"
  read -r -p "$1 [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

normalize_path() {
  local p="$1"
  local first last
  p="${p#"${p%%[![:space:]]*}"}"
  p="${p%"${p##*[![:space:]]}"}"
  if [[ ${#p} -ge 2 ]]; then
    first=${p:0:1}
    last=${p:$((${#p} - 1)):1}
    if [[ "$first" == "$last" && ("$first" == "'" || "$first" == '"') ]]; then
      p=${p:1:$((${#p} - 2))}
    fi
  fi
  # Finder drag-and-drop escapes spaces.
  p=${p//\\ / }
  if [[ "$p" == "~" ]]; then
    p="$HOME"
  elif [[ "$p" == "~/"* ]]; then
    p="${HOME}/${p:2}"
  fi
  printf '%s\n' "$p"
}

absolute_path() {
  local p="$1"
  local dir base
  p=$(normalize_path "$p")
  [[ -n "$p" ]] || die "Empty path."
  [[ -e "$p" ]] || die "Path does not exist: $p"
  dir=$(cd "$(dirname "$p")" && pwd)
  base=$(basename "$p")
  if command -v realpath >/dev/null 2>&1; then
    realpath "$dir/$base"
  else
    printf '%s\n' "$dir/$base"
  fi
}

preflight() {
  local tool
  [[ "$(uname -s)" == "Darwin" ]] || die "Run this script on macOS."
  if [[ -x "${HOME}/.cargo/bin/rcodesign" ]]; then
    PATH="${HOME}/.cargo/bin:${PATH}"
    export PATH
  fi
  for tool in codesign hdiutil ditto plutil xattr openssl; do
    command -v "$tool" >/dev/null 2>&1 || die "Required tool not found: $tool"
  done
  command -v rcodesign >/dev/null 2>&1 || die "rcodesign is not on PATH. Install it with: cargo install --features smartcard apple-codesign"
  [[ -f "$ENTITLEMENTS" ]] || die "Entitlements file not found: $ENTITLEMENTS"
  plutil -lint "$ENTITLEMENTS" >/dev/null
}

add_dmg() {
  local path="$1"
  local existing
  path=$(absolute_path "$path")
  [[ -f "$path" ]] || die "Not a file: $path"
  case "$path" in
    *.dmg | *.DMG) ;;
    *) die "Not a .dmg file: $path" ;;
  esac
  if [[ ${#DMG_INPUTS[@]} -gt 0 ]]; then
    for existing in "${DMG_INPUTS[@]}"; do
      if [[ "$existing" == "$path" ]]; then
        echo "Already added: $path"
        return 0
      fi
    done
  fi
  DMG_INPUTS+=("$path")
  echo "Added: $path"
}

collect_dmgs() {
  local arg line
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h | --help)
        usage
        exit 0
        ;;
      --)
        shift
        break
        ;;
      -*)
        die "Unknown option: $1"
        ;;
      *)
        add_dmg "$1"
        ;;
    esac
    shift
  done
  for arg in "$@"; do
    add_dmg "$arg"
  done

  if [[ ${#DMG_INPUTS[@]} -eq 0 ]]; then
    need_tty "disk image path"
    echo
    echo "Enter a path to a CI-built .dmg. You can drag the file into this window."
    echo "Submit an empty line when you are done. Both Apple Silicon and Intel images can be added."
    while true; do
      read -r -p "DMG path: " line
      line=$(normalize_path "$line")
      [[ -z "$line" ]] && break
      add_dmg "$line"
    done
  fi
  [[ ${#DMG_INPUTS[@]} -gt 0 ]] || die "No disk images to sign."
}

developer_id_cn_from_line() {
  local line="$1"
  if [[ "$line" =~ \((Developer ID Application:.*)\)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

identity_name_known() {
  local name="$1"
  local i count
  count=${#IDENTITY_NAMES[@]}
  [[ "$count" -eq 0 ]] && return 1
  for i in $(seq 0 $((count - 1))); do
    if [[ "${IDENTITY_NAMES[$i]}" == "$name" ]]; then
      return 0
    fi
  done
  return 1
}

# security find-identity does not search smart cards. Read the PIV certificate
# and use its SHA-1, which is what codesign accepts for a smart card identity.
certificate_sha1_for_cn() {
  local cn="$1"
  local slot pem subject fp
  command -v yubico-piv-tool >/dev/null 2>&1 || return 1
  command -v openssl >/dev/null 2>&1 || return 1
  pem=$(mktemp "${TMPDIR:-/tmp}/piv-cert.XXXXXX")
  for slot in 9a 9c 9d 9e; do
    if ! yubico-piv-tool -a read-certificate -s "$slot" -o "$pem" >/dev/null 2>&1; then
      continue
    fi
    subject=$(openssl x509 -in "$pem" -noout -subject 2>/dev/null || true)
    case "$subject" in
      *"$cn"*) ;;
      *) continue ;;
    esac
    fp=$(openssl x509 -in "$pem" -noout -fingerprint -sha1 2>/dev/null || true)
    rm -f "$pem"
    fp=${fp##*=}
    fp=${fp//:/}
    fp=${fp//$'\r'/}
    [[ -n "$fp" ]] || return 1
    printf '%s %s\n' "$(printf '%s' "$fp" | tr '[:lower:]' '[:upper:]')" "$slot"
    return 0
  done
  rm -f "$pem"
  return 1
}

certificate_sha256_for_name() {
  local name="$1"
  local fp
  fp=$(security find-certificate -c "$name" -p 2>/dev/null | openssl x509 -noout -fingerprint -sha256 2>/dev/null || true)
  [[ -n "$fp" ]] || return 1
  fp=${fp##*=}
  fp=${fp//:/}
  fp=${fp//$'\r'/}
  printf '%s' "$fp" | tr '[:lower:]' '[:upper:]'
}

remember_identity() {
  local hash="$1"
  local name="$2"
  local source="$3"
  local slot="$4"
  local fingerprint="$5"
  identity_name_known "$name" && return 0
  IDENTITY_HASHES+=("$hash")
  IDENTITY_NAMES+=("$name")
  IDENTITY_SOURCES+=("$source")
  IDENTITY_SLOTS+=("$slot")
  IDENTITY_FINGERPRINTS+=("$fingerprint")
}

load_keychain_identities() {
  local line hash name fingerprint
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*[0-9]+\)[[:space:]]+([0-9A-Fa-f]{40,})[[:space:]]+\"(.*)\"[[:space:]]*$ ]]; then
      hash="${BASH_REMATCH[1]}"
      name="${BASH_REMATCH[2]}"
      case "$name" in
        "Developer ID Application:"*)
          fingerprint=$(certificate_sha256_for_name "$name" || true)
          remember_identity "$hash" "$name" "keychain" "" "$fingerprint"
          ;;
      esac
    fi
  done < <(security find-identity -v -p codesigning)
}

load_smartcard_identities() {
  local line cn parsed sha slot
  command -v sc_auth >/dev/null 2>&1 || return 0
  while IFS= read -r line; do
    cn=$(developer_id_cn_from_line "$line") || continue
    if parsed=$(certificate_sha1_for_cn "$cn"); then
      sha=${parsed%% *}
      slot=${parsed##* }
      remember_identity "$sha" "$cn" "smartcard" "$slot" ""
    else
      remember_identity "$cn" "$cn" "smartcard" "" ""
    fi
  done < <(sc_auth identities 2>/dev/null || true)
}

load_identities() {
  IDENTITY_HASHES=()
  IDENTITY_NAMES=()
  IDENTITY_SOURCES=()
  IDENTITY_SLOTS=()
  IDENTITY_FINGERPRINTS=()
  load_keychain_identities
  load_smartcard_identities
}

identity_label() {
  local i="$1"
  if [[ "${IDENTITY_SOURCES[$i]}" == "smartcard" ]]; then
    printf '%s [smart card]\n' "${IDENTITY_NAMES[$i]}"
  else
    printf '%s\n' "${IDENTITY_NAMES[$i]}"
  fi
}

select_identity_at() {
  local i="$1"
  SIGN_IDENTITY="${IDENTITY_HASHES[$i]}"
  SIGN_IDENTITY_NAME="${IDENTITY_NAMES[$i]}"
  SIGN_IDENTITY_SOURCE="${IDENTITY_SOURCES[$i]}"
  SMARTCARD_SLOT="${IDENTITY_SLOTS[$i]}"
  SIGN_FINGERPRINT="${IDENTITY_FINGERPRINTS[$i]}"
}

use_selected_identity() {
  local scan_out
  if [[ "$SIGN_IDENTITY_SOURCE" == "smartcard" ]]; then
    [[ -n "$SMARTCARD_SLOT" ]] || die "Could not find which YubiKey slot holds ${SIGN_IDENTITY_NAME}."
    scan_out=$(rcodesign smartcard-scan 2>&1 || true)
    case "$scan_out" in
      *"crate feature"*)
        die "This rcodesign build has no smart card support. Reinstall with: cargo install --features smartcard apple-codesign"
        ;;
    esac
    SIGNER_ARGS=(--smartcard-slot "$SMARTCARD_SLOT")
  else
    [[ -n "$SIGN_FINGERPRINT" ]] || die "Could not read a SHA-256 fingerprint for ${SIGN_IDENTITY_NAME}."
    SIGNER_ARGS=(--keychain-domain user --keychain-fingerprint "$SIGN_FINGERPRINT")
  fi
}

same_identity() {
  local wanted="$1"
  local hash="$2"
  local name="$3"
  local fingerprint="$4"
  local wanted_l hash_l fingerprint_l
  [[ "$wanted" == "$name" || "$wanted" == "$hash" || "$wanted" == "$fingerprint" ]] && return 0
  wanted_l=$(printf '%s' "$wanted" | tr '[:upper:]' '[:lower:]')
  hash_l=$(printf '%s' "$hash" | tr '[:upper:]' '[:lower:]')
  fingerprint_l=$(printf '%s' "$fingerprint" | tr '[:upper:]' '[:lower:]')
  [[ "$wanted_l" == "$hash_l" || "$wanted_l" == "$fingerprint_l" ]]
}

choose_identity() {
  local i choice count env_id
  load_identities
  count=${#IDENTITY_HASHES[@]}
  if [[ "$count" -eq 0 ]]; then
    die "No Developer ID Application certificate found. Plug in the YubiKey and run 'sc_auth identities'. A certificate that stays on the card does not appear in 'security find-identity'."
  fi

  if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
    env_id="$CODESIGN_IDENTITY"
    for i in $(seq 0 $((count - 1))); do
      if same_identity "$env_id" "${IDENTITY_HASHES[$i]}" "${IDENTITY_NAMES[$i]}" "${IDENTITY_FINGERPRINTS[$i]}"; then
        select_identity_at "$i"
        say "Using certificate from CODESIGN_IDENTITY: $(identity_label "$i")"
        use_selected_identity
        return 0
      fi
    done
    die "CODESIGN_IDENTITY does not match a Developer ID Application certificate: $env_id"
  fi

  echo
  echo "Developer ID Application certificates:"
  for i in $(seq 0 $((count - 1))); do
    printf '  %d) %s\n' $((i + 1)) "$(identity_label "$i")"
  done

  if [[ "$count" -gt 1 ]]; then
    need_tty "signing certificate"
  fi

  if [[ "$count" -eq 1 ]]; then
    select_identity_at 0
    confirm "Use $(identity_label 0)?" || die "Cancelled."
    use_selected_identity
    return 0
  fi

  while true; do
    read -r -p "Certificate number: " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -ge 1 ]] && [[ "$choice" -le "$count" ]]; then
      select_identity_at $((choice - 1))
      use_selected_identity
      return 0
    fi
    echo "Enter a number from 1 to $count."
  done
}

choose_api_key() {
  local line default_key issuer key_id p8_path
  default_key="${APP_STORE_CONNECT_API_KEY_FILE:-${HOME}/.appstoreconnect/carveracontroller-key.json}"
  if [[ -n "${APP_STORE_CONNECT_API_KEY_FILE:-}" ]]; then
    [[ -f "$APP_STORE_CONNECT_API_KEY_FILE" ]] || die "APP_STORE_CONNECT_API_KEY_FILE does not exist: $APP_STORE_CONNECT_API_KEY_FILE"
    API_KEY_FILE=$(absolute_path "$APP_STORE_CONNECT_API_KEY_FILE")
    say "Using App Store Connect API key ${API_KEY_FILE}"
    return 0
  fi

  need_tty "App Store Connect API key"
  echo
  echo "rcodesign notarizes with an App Store Connect API key."
  echo "Create one with the Developer role at https://appstoreconnect.apple.com/access/api"
  echo "How to encode it: https://gregoryszorc.com/docs/apple-codesign/stable/apple_codesign_getting_started.html"
  read -r -p "API key JSON [${default_key}]: " line
  line=$(normalize_path "$line")
  line="${line:-$default_key}"
  if [[ -f "$line" ]]; then
    API_KEY_FILE=$(absolute_path "$line")
    say "Using App Store Connect API key ${API_KEY_FILE}"
    return 0
  fi

  echo "No key file at ${line}."
  confirm "Create one with rcodesign encode-app-store-connect-api-key?" || die "An App Store Connect API key JSON file is required."
  read -r -p "Issuer ID: " issuer
  read -r -p "Key ID: " key_id
  read -r -p "Path to the AuthKey .p8 file: " p8_path
  p8_path=$(absolute_path "$p8_path")
  [[ -f "$p8_path" ]] || die "Private key not found: $p8_path"
  mkdir -p "$(dirname "$line")"
  rcodesign encode-app-store-connect-api-key -o "$line" "$issuer" "$key_id" "$p8_path"
  chmod 600 "$line" || true
  API_KEY_FILE=$(absolute_path "$line")
  say "Wrote App Store Connect API key ${API_KEY_FILE}"
}

choose_output_dir() {
  local line
  if [[ -n "${SIGNED_DMG_DIR:-}" ]]; then
    line="$SIGNED_DMG_DIR"
  elif [[ ! -t 0 ]]; then
    OUTPUT_DIR=""
    return 0
  else
    read -r -p "Folder for signed disk images [same folder as each input]: " line
    line=$(normalize_path "$line")
  fi
  if [[ -z "$line" ]]; then
    OUTPUT_DIR=""
    return 0
  fi
  [[ -d "$line" ]] || die "Output folder does not exist: $line"
  OUTPUT_DIR=$(absolute_path "$line")
  [[ -d "$OUTPUT_DIR" ]] || die "Output folder does not exist: $OUTPUT_DIR"
}

output_path_for() {
  local input="$1"
  local dir base
  if [[ -n "$OUTPUT_DIR" ]]; then
    dir="$OUTPUT_DIR"
  else
    dir=$(dirname "$input")
  fi
  base=$(basename "$input")
  base="${base%.dmg}"
  base="${base%.DMG}"
  case "$base" in
    *-signed) printf '%s\n' "$dir/${base}.dmg" ;;
    *) printf '%s\n' "$dir/${base}-signed.dmg" ;;
  esac
}

cleanup_work() {
  if [[ -n "${MOUNTED:-}" ]]; then
    hdiutil detach "$MOUNTED" -quiet >/dev/null 2>&1 || hdiutil detach "$MOUNTED" -force >/dev/null 2>&1 || true
    MOUNTED=""
  fi
  if [[ -n "${WORKDIR:-}" && -d "${WORKDIR:-}" ]]; then
    rm -rf "$WORKDIR"
    WORKDIR=""
  fi
}

on_exit() {
  status=$?
  cleanup_work
  exit "$status"
}

attach_image() {
  local image="$1"
  local mode="$2"
  local mp="$WORKDIR/mnt"
  mkdir -p "$mp"
  if [[ -n "${MOUNTED:-}" ]]; then
    hdiutil detach "$MOUNTED" -quiet >/dev/null 2>&1 || hdiutil detach "$MOUNTED" -force >/dev/null 2>&1 || true
    MOUNTED=""
  fi
  # Record the mount before attach so a failed attach still gets detached.
  MOUNTED="$mp"
  if [[ "$mode" == "readwrite" ]]; then
    hdiutil attach "$image" -readwrite -nobrowse -owners off -mountpoint "$mp"
  else
    hdiutil attach "$image" -readonly -nobrowse -owners off -mountpoint "$mp"
  fi
}

detach_mount() {
  local attempt
  [[ -n "${MOUNTED:-}" ]] || return 0
  sync
  for attempt in 1 2 3 4 5; do
    if hdiutil detach "$MOUNTED" -quiet >/dev/null 2>&1; then
      MOUNTED=""
      return 0
    fi
    sleep 1
  done
  hdiutil detach "$MOUNTED" -force
  MOUNTED=""
}

convert_dmg() {
  local format="$1"
  local src="$2"
  local dest="$3"
  local base
  base="${dest%.dmg}"
  rm -f "$dest" "${base}.dmg.dmg" "${base}.sparseimage"
  hdiutil convert "$src" -format "$format" -ov -o "$base"
  if [[ ! -f "$dest" && -f "${base}.dmg.dmg" ]]; then
    mv "${base}.dmg.dmg" "$dest"
  elif [[ ! -f "$dest" && -f "${base}.sparseimage" ]]; then
    mv "${base}.sparseimage" "$dest"
  fi
  [[ -f "$dest" ]] || die "hdiutil convert -format $format did not create $dest"
}

sign_app_bundle() {
  local app="$1"
  local plist exe_name exe_path exe_rel
  plist="$app/Contents/Info.plist"
  [[ -f "$plist" ]] || die "App is missing Contents/Info.plist: $app"
  exe_name=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$plist")
  exe_path="$app/Contents/MacOS/$exe_name"
  exe_rel="Contents/MacOS/${exe_name}"
  [[ -n "$exe_name" && -f "$exe_path" ]] || die "App is missing its main executable: $exe_path"

  if command -v dot_clean >/dev/null 2>&1; then
    dot_clean -m "$app" >/dev/null 2>&1 || true
  fi
  find "$app" -name '.DS_Store' -delete
  find "$app" -name '._*' -delete
  xattr -cr "$app"

  say "Signing the app with rcodesign. Nested binaries are signed in this one session."
  if [[ "$SIGN_IDENTITY_SOURCE" == "smartcard" ]]; then
    echo "Enter the YubiKey PIN when rcodesign asks. That entry is reused for every binary in this app."
    echo "If this PIV key also requires a touch on every signature, touch the YubiKey for each binary."
  fi
  # --for-notarization turns on the hardened runtime for every Mach-O in the bundle.
  # Entitlements stay on the main executable. https://gregoryszorc.com/docs/apple-codesign/stable/apple_codesign_rcodesign_notarizing.html
  if ! rcodesign sign \
    "${SIGNER_ARGS[@]}" \
    --for-notarization \
    --entitlements-xml-file "${exe_rel}:${ENTITLEMENTS}" \
    "$app"; then
    die "rcodesign sign failed for $app. If the YubiKey is busy, unplug it, plug it back in, and run this script again."
  fi
  rcodesign verify "$exe_path"
  codesign --verify --deep --strict --verbose=2 "$app"
}

sign_disk_image() {
  local dest="$1"
  say "Signing the disk image with rcodesign."
  if [[ "$SIGN_IDENTITY_SOURCE" == "smartcard" ]]; then
    echo "Enter the YubiKey PIN if rcodesign asks."
  fi
  if ! rcodesign sign "${SIGNER_ARGS[@]}" "$dest"; then
    die "rcodesign sign failed for $dest"
  fi
  codesign --verify --verbose=2 "$dest"
}

replace_app_on_image() {
  local image="$1"
  local signed_app="$2"
  local app_name mount app_kb avail_kb total_kb new_mb
  app_name=$(basename "$signed_app")
  case "$app_name" in
    *.app) ;;
    *) die "Refusing to replace '$app_name' on the disk image." ;;
  esac

  attach_image "$image" readwrite
  mount="$MOUNTED"
  [[ -d "$mount/$app_name" ]] || die "The disk image does not contain $app_name"
  rm -rf "$mount/$app_name"

  app_kb=$(du -sk "$signed_app" | awk '{print $1}')
  avail_kb=$(df -k "$mount" | awk 'NR==2 {print $4}')
  total_kb=$(df -k "$mount" | awk 'NR==2 {print $2}')
  # Signature blobs need a little extra room. Grow by the shortfall only.
  if [[ "$avail_kb" -lt $((app_kb + 16384)) ]]; then
    say "Growing the disk image so the signed app fits."
    detach_mount
    new_mb=$(((total_kb + (app_kb + 16384 - avail_kb) + 32768 + 1023) / 1024))
    hdiutil resize -size "${new_mb}m" "$image"
    attach_image "$image" readwrite
    mount="$MOUNTED"
  fi

  ditto "$signed_app" "$mount/$app_name"
  sync
  detach_mount
}

repack_dmg() {
  local src_dmg="$1"
  local signed_app="$2"
  local dest_dmg="$3"
  local rw="$WORKDIR/rw.dmg"
  say "Building a read-write copy of the disk image."
  convert_dmg UDRW "$src_dmg" "$rw"
  say "Replacing the app and keeping the existing disk image layout."
  replace_app_on_image "$rw" "$signed_app"
  say "Compressing the signed disk image."
  convert_dmg UDBZ "$rw" "$dest_dmg"
}

verify_app_in_dmg() {
  local image="$1"
  local app_name="$2"
  local mount
  say "Checking the signature of the app inside the new disk image."
  attach_image "$image" readonly
  mount="$MOUNTED"
  [[ -d "$mount/$app_name" ]] || die "Signed app $app_name is missing from $image"
  codesign --verify --deep --strict --verbose=2 "$mount/$app_name"
  detach_mount
}

notarize_and_staple() {
  local dest="$1"
  say "Notarizing and stapling $(basename "$dest") with rcodesign."
  echo "This waits for Apple. The limit is 3 hours."
  echo "If you interrupt the wait, list the submission later with:"
  echo "  rcodesign notary-list --api-key-file \"${API_KEY_FILE}\""
  if ! rcodesign notary-submit \
    --api-key-file "$API_KEY_FILE" \
    --staple \
    --max-wait-seconds 10800 \
    "$dest"; then
    die "Notarization was not accepted for $dest."
  fi
}

assess_disk_image() {
  local dest="$1"
  local rc
  echo
  echo "Gatekeeper assessment:"
  set +e
  spctl --assess --type open --context context:primary-signature --verbose=2 "$dest"
  rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    echo "warning: rcodesign stapled the ticket, and spctl did not accept the disk image yet."
    echo "warning: Ship this stapled image. Gatekeeper applies the ticket when the downloaded file is opened."
  fi
}

describe_app() {
  local app="$1"
  local plist="$app/Contents/Info.plist"
  local version bundle_id exe_name arch
  version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$plist" 2>/dev/null || true)
  bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$plist" 2>/dev/null || true)
  exe_name=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$plist" 2>/dev/null || true)
  arch=""
  if [[ -n "$exe_name" && -f "$app/Contents/MacOS/$exe_name" ]]; then
    arch=$(lipo -archs "$app/Contents/MacOS/$exe_name" 2>/dev/null || true)
  fi
  echo "    App: $(basename "$app")"
  echo "    Version: ${version:-unknown}"
  echo "    Bundle id: ${bundle_id:-unknown}"
  echo "    Architecture: ${arch:-unknown}"
}

process_dmg() {
  local input="$1"
  local output app_name src extracted mount
  output=$(output_path_for "$input")
  if [[ "$output" == "$input" ]]; then
    die "Refusing to overwrite the input disk image: $input"
  fi
  if [[ -e "$output" ]]; then
    confirm "Output already exists: $output. Overwrite?" || die "Cancelled."
    rm -f "$output"
  fi

  WORKDIR=$(mktemp -d "$(dirname "$output")/.sign-work.XXXXXX")
  say "Reading $(basename "$input")"
  hdiutil imageinfo "$input" >/dev/null
  attach_image "$input" readonly
  mount="$MOUNTED"

  local old_nullglob=0
  local apps=()
  shopt -q nullglob && old_nullglob=1
  shopt -s nullglob
  apps=("$mount"/*.app)
  if [[ "$old_nullglob" -eq 0 ]]; then
    shopt -u nullglob
  fi
  [[ ${#apps[@]} -eq 1 ]] || die "Expected one .app at the top of $(basename "$input"), found ${#apps[@]}."
  src="${apps[0]}"
  app_name=$(basename "$src")
  describe_app "$src"
  if [[ "$app_name" != "Carvera Controller Community.app" ]]; then
    confirm "This disk image contains '$app_name' rather than 'Carvera Controller Community.app'. Continue?" || die "Cancelled."
  fi

  extracted="$WORKDIR/$app_name"
  say "Copying the app out of the disk image."
  ditto "$src" "$extracted"
  detach_mount

  sign_app_bundle "$extracted"
  notarize_and_staple "$extracted"
  repack_dmg "$input" "$extracted" "$output"
  verify_app_in_dmg "$output" "$app_name"

  sign_disk_image "$output"
  notarize_and_staple "$output"
  assess_disk_image "$output"
  SIGNED_OUTPUTS+=("$output")
  cleanup_work
  say "Finished $output"
}

main() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      -h | --help)
        usage
        exit 0
        ;;
    esac
  done

  trap on_exit EXIT
  preflight

  echo "Sign, notarize, and staple a Carvera Controller macOS disk image with rcodesign."
  echo "The app is signed and notarized first, then packed back into the disk image,"
  echo "which is signed, notarized, and stapled."

  collect_dmgs "$@"
  choose_identity
  choose_api_key
  choose_output_dir

  local input output
  echo
  echo "Ready to sign and notarize:"
  echo "  Certificate: $SIGN_IDENTITY_NAME"
  echo "  API key: $API_KEY_FILE"
  echo "  Entitlements: $ENTITLEMENTS"
  echo "  Each disk image is notarized twice: once as an app, then once as a disk image."
  for input in "${DMG_INPUTS[@]}"; do
    output=$(output_path_for "$input")
    echo "  $input"
    echo "    -> $output"
  done
  echo
  confirm "Proceed?" || die "Cancelled."

  for input in "${DMG_INPUTS[@]}"; do
    process_dmg "$input"
  done

  echo
  echo "Signed, notarized, and stapled:"
  for output in "${SIGNED_OUTPUTS[@]}"; do
    echo "  $output"
  done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
