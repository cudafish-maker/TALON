#!/usr/bin/env bash
set -Eeuo pipefail

BUNDLE_NAME="talon-linux"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)

log() {
    printf '%s\n' "$*"
}

warn() {
    printf 'WARNING: %s\n' "$*" >&2
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
TALON Linux installer

Usage:
  install.sh [options] [extracted-talon-linux-dir]

Options:
  --prefix DIR         Install root. Default: $XDG_DATA_HOME/talon or ~/.local/share/talon
  --bin-dir DIR        Launcher directory. Default: ~/.local/bin
  --config PATH        Config file to create/use. Default: ~/.talon/talon.ini for client,
                       ~/.talon-server/talon.ini for server
  --data-dir DIR       TALON data directory. Default follows --mode.
  --rns-dir DIR        Reticulum config/key directory. Default: <data-dir>/reticulum
  --documents-dir DIR  Document storage/cache directory. Default: <data-dir>/documents
  --mode MODE          Initial config mode: client or server. Default: client
  --yes                Assume yes when the system package manager asks for confirmation.
  --no-deps            Do not install system runtime dependencies.
  --no-desktop         Do not create a desktop launcher entry.
  --no-bin             Do not create the ~/.local/bin/talon launcher wrapper.
  --smoke-test         Start the installed app for a short Kivy smoke test.
  -h, --help           Show this help.

Examples:
  tar -xzf talon-linux.tar.gz
  cd talon-linux
  bash ./install.sh --mode client --yes
  bash ./install.sh --mode server --yes
  bash ./install.sh --no-deps --no-desktop
USAGE
}

expand_path() {
    local raw=$1
    case "$raw" in
        "~") printf '%s\n' "$HOME" ;;
        "~/"*) printf '%s/%s\n' "$HOME" "${raw#~/}" ;;
        *) printf '%s\n' "$raw" ;;
    esac
}

make_abs_path() {
    local expanded
    expanded=$(expand_path "$1")
    case "$expanded" in
        /*) printf '%s\n' "$expanded" ;;
        *) printf '%s/%s\n' "$PWD" "$expanded" ;;
    esac
}

shell_quote() {
    local value=$1
    printf "'%s'" "${value//\'/\'\\\'\'}"
}

run_as_root() {
    if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        die "Missing required privileges. Install sudo or run this installer as root for system package installation."
    fi
}

ldconfig_path() {
    if command -v ldconfig >/dev/null 2>&1; then
        command -v ldconfig
    elif [[ -x /sbin/ldconfig ]]; then
        printf '%s\n' /sbin/ldconfig
    elif [[ -x /usr/sbin/ldconfig ]]; then
        printf '%s\n' /usr/sbin/ldconfig
    else
        return 1
    fi
}

have_library() {
    local library=$1
    local ldconfig_bin

    ldconfig_bin=$(ldconfig_path) || return 1
    "$ldconfig_bin" -p 2>/dev/null | grep -Eq "(^|[[:space:]])${library}([[:space:]]|$)"
}

runtime_dependency_gaps() {
    local missing=()

    command -v xdg-open >/dev/null 2>&1 || missing+=("xdg-open")
    command -v xclip >/dev/null 2>&1 || missing+=("xclip")
    have_library "libGL.so.1" || missing+=("libGL.so.1")
    have_library "libGLX.so.0" || missing+=("libGLX.so.0")
    have_library "libEGL.so.1" || missing+=("libEGL.so.1")
    have_library "libxkbcommon.so.0" || missing+=("libxkbcommon.so.0")
    have_library "libmagic.so.1" || missing+=("libmagic.so.1")
    if ! have_library "libsqlcipher.so.1" && ! have_library "libsqlcipher.so.0" && ! have_library "libsqlcipher.so"; then
        missing+=("libsqlcipher")
    fi

    ((${#missing[@]} == 0)) && return 0
    printf '%s\n' "${missing[@]}"
    return 1
}

apt_package_exists() {
    apt-cache show "$1" >/dev/null 2>&1
}

append_first_available_apt_package() {
    local -n target_ref=$1
    shift
    local package
    for package in "$@"; do
        if apt_package_exists "$package"; then
            target_ref+=("$package")
            return 0
        fi
    done
    return 1
}

install_deps_apt() {
    local packages=(
        xdg-utils
        xclip
        libgl1
        libglx0
        libglx-mesa0
        libegl1
        libegl-mesa0
        libxkbcommon0
        libgl1-mesa-dri
        mesa-utils
    )

    append_first_available_apt_package packages libmagic1t64 libmagic1 file || warn "No apt package found for libmagic."
    append_first_available_apt_package packages libsqlcipher1 libsqlcipher0 libsqlcipher-dev sqlcipher || warn "No apt package found for SQLCipher."
    append_first_available_apt_package packages libmtdev1 mtdev-tools >/dev/null 2>&1 || true

    local yes_args=()
    [[ $ASSUME_YES == "1" ]] && yes_args=(-y)
    run_as_root apt-get update
    run_as_root apt-get install "${yes_args[@]}" --no-install-recommends "${packages[@]}"
}

install_deps_dnf() {
    local packages=(
        xdg-utils
        xclip
        mesa-libGL
        mesa-libEGL
        mesa-dri-drivers
        glx-utils
        libxkbcommon
        file-libs
        sqlcipher
    )
    local yes_args=()
    [[ $ASSUME_YES == "1" ]] && yes_args=(-y)
    run_as_root dnf install "${yes_args[@]}" "${packages[@]}"
}

install_deps_yum() {
    local packages=(
        xdg-utils
        xclip
        mesa-libGL
        mesa-libEGL
        mesa-dri-drivers
        glx-utils
        libxkbcommon
        file-libs
        sqlcipher
    )
    local yes_args=()
    [[ $ASSUME_YES == "1" ]] && yes_args=(-y)
    run_as_root yum install "${yes_args[@]}" "${packages[@]}"
}

install_deps_zypper() {
    local packages=(
        xdg-utils
        xclip
        Mesa-libGL1
        Mesa-libEGL1
        Mesa-dri
        libxkbcommon0
        libmagic1
        sqlcipher
    )
    local zypper_args=()
    [[ $ASSUME_YES == "1" ]] && zypper_args=(--non-interactive)
    run_as_root zypper "${zypper_args[@]}" install --no-recommends "${packages[@]}"
}

install_deps_pacman() {
    local packages=(
        xdg-utils
        xclip
        mesa
        libglvnd
        libxkbcommon
        file
        sqlcipher
    )
    local yes_args=()
    [[ $ASSUME_YES == "1" ]] && yes_args=(--noconfirm)
    run_as_root pacman -S --needed "${yes_args[@]}" "${packages[@]}"
}

install_runtime_dependencies() {
    local gaps=()
    mapfile -t gaps < <(runtime_dependency_gaps || true)
    if ((${#gaps[@]} == 0)); then
        log "Runtime dependency check passed."
        return 0
    fi

    log "Missing runtime dependencies: ${gaps[*]}"

    if command -v apt-get >/dev/null 2>&1; then
        install_deps_apt
    elif command -v dnf >/dev/null 2>&1; then
        install_deps_dnf
    elif command -v yum >/dev/null 2>&1; then
        install_deps_yum
    elif command -v zypper >/dev/null 2>&1; then
        install_deps_zypper
    elif command -v pacman >/dev/null 2>&1; then
        install_deps_pacman
    else
        die "Unsupported package manager. Install these manually: ${gaps[*]}"
    fi

    if ! runtime_dependency_gaps >/dev/null; then
        warn "Some dependencies still appear missing after package installation. Continuing, but TALON may not start."
    fi
}

canonical_dir() {
    local path=$1

    (cd "$path" && pwd -P)
}

validate_bundle() {
    local bundle_dir=$1
    local required=(
        "$bundle_dir/talon"
        "$bundle_dir/_internal/base_library.zip"
        "$bundle_dir/_internal/kivy/data/style.kv"
        "$bundle_dir/_internal/kivymd/icon_definitions.py"
    )
    local path

    for path in "${required[@]}"; do
        [[ -e $path ]] || die "TALON bundle is missing required runtime asset: $path"
    done
    chmod +x "$bundle_dir/talon"
}

install_bundle() {
    local source_dir=$1
    local install_root=$2
    local target_dir=$install_root/$BUNDLE_NAME
    local staging_dir=$install_root/.${BUNDLE_NAME}.new.$$
    local backup_dir=""
    local source_real
    local target_real

    validate_bundle "$source_dir"
    mkdir -p "$install_root"
    rm -rf "$staging_dir"

    if [[ -e $target_dir ]]; then
        source_real=$(canonical_dir "$source_dir")
        target_real=$(canonical_dir "$target_dir")
        if [[ $source_real == "$target_real" ]]; then
            die "Refusing to use the current install directory as the source bundle. Extract the release tarball elsewhere and run install.sh from that extracted directory."
        fi
        if [[ ! -x $target_dir/talon || ! -d $target_dir/_internal ]]; then
            die "Refusing to replace non-TALON path: $target_dir"
        fi
        backup_dir="${target_dir}.backup.$(date +%Y%m%d%H%M%S)"
        mv "$target_dir" "$backup_dir"
        printf 'Existing install moved to %s\n' "$backup_dir" >&2
    fi

    if ! cp -a "$source_dir" "$staging_dir"; then
        rm -rf "$staging_dir"
        if [[ -n $backup_dir && -e $backup_dir && ! -e $target_dir ]]; then
            mv "$backup_dir" "$target_dir"
        fi
        die "Failed to stage TALON bundle."
    fi

    mv "$staging_dir" "$target_dir"
    validate_bundle "$target_dir"
    printf '%s\n' "$target_dir"
}

write_default_config() {
    local config_path=$1
    local mode=$2
    local data_dir=$3
    local rns_dir=$4
    local documents_dir=$5

    mkdir -p "$(dirname "$config_path")" "$data_dir" "$rns_dir" "$documents_dir"

    if [[ -f $config_path ]]; then
        log "Keeping existing config: $config_path"
        return 0
    fi

    cat > "$config_path" <<EOF
[talon]
mode = $mode

[paths]
data_dir = $data_dir
rns_config_dir = $rns_dir

[network]
transport_priority = yggdrasil,i2p,tcp,rnode

[security]
lease_duration_seconds = 86400

[documents]
storage_path = $documents_dir
EOF

    chmod 600 "$config_path"
    log "Created config: $config_path"
}

write_launcher_wrapper() {
    local target_dir=$1
    local bin_dir=$2
    local config_path=$3
    local state_dir=$4
    local wrapper=$bin_dir/talon
    local app_q
    local config_q
    local kivy_home_q

    mkdir -p "$bin_dir" "$state_dir/kivy"
    app_q=$(shell_quote "$target_dir/talon")
    config_q=$(shell_quote "$config_path")
    kivy_home_q=$(shell_quote "$state_dir/kivy")

    cat > "$wrapper" <<EOF
#!/usr/bin/env sh
if [ -z "\${TALON_CONFIG:-}" ]; then
  export TALON_CONFIG=$config_q
fi
if [ -z "\${KIVY_HOME:-}" ]; then
  export KIVY_HOME=$kivy_home_q
fi
export KIVY_NO_FILELOG="\${KIVY_NO_FILELOG:-1}"
exec $app_q "\$@"
EOF

    chmod 755 "$wrapper"
    log "Installed launcher: $wrapper"
}

write_desktop_entry() {
    local target_dir=$1
    local bin_dir=$2
    local desktop_dir=$3
    local entry_path=$desktop_dir/talon.desktop
    local icon_path=$target_dir/_internal/Images/talonlogo.png

    mkdir -p "$desktop_dir"
    if [[ ! -f $icon_path ]]; then
        icon_path=$target_dir/_internal/kivy/data/logo/kivy-icon-256.png
    fi

    cat > "$entry_path" <<EOF
[Desktop Entry]
Type=Application
Name=T.A.L.O.N.
Comment=Tactical Awareness and Linked Operations Network
Exec=$bin_dir/talon
Icon=$icon_path
Terminal=false
Categories=Network;Utility;
StartupNotify=true
EOF

    chmod 644 "$entry_path"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
    fi
    log "Installed desktop entry: $entry_path"
}

run_smoke_test() {
    local target_dir=$1
    local config_path=$2
    local state_dir=$3
    local smoke_prefix=(
        env
        "TALON_CONFIG=$config_path"
        "KIVY_HOME=$state_dir/kivy-smoke"
        "KIVY_NO_FILELOG=1"
        "TALON_SMOKE_TEST_SECONDS=1"
    )

    mkdir -p "$state_dir/kivy-smoke"

    if command -v xvfb-run >/dev/null 2>&1; then
        timeout 20s xvfb-run -a "${smoke_prefix[@]}" "$target_dir/talon"
    elif [[ -n ${DISPLAY:-} || -n ${WAYLAND_DISPLAY:-} ]]; then
        timeout 20s "${smoke_prefix[@]}" "$target_dir/talon"
    else
        warn "Skipping smoke test because no display or xvfb-run is available."
        return 0
    fi
}

INPUT_PATH=""
INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/talon"
BIN_DIR="$HOME/.local/bin"
CONFIG_PATH=""
DATA_DIR=""
RNS_DIR=""
DOCUMENTS_DIR=""
MODE="client"
ASSUME_YES="0"
INSTALL_DEPS="1"
INSTALL_DESKTOP="1"
INSTALL_BIN="1"
SMOKE_TEST="0"

positionals=()
while (($#)); do
    case "$1" in
        --tarball)
            die "--tarball is no longer supported. Extract talon-linux.tar.gz, cd into talon-linux, then run bash ./install.sh."
            ;;
        --tarball=*)
            die "--tarball is no longer supported. Extract talon-linux.tar.gz, cd into talon-linux, then run bash ./install.sh."
            ;;
        --prefix)
            shift || die "--prefix requires a directory"
            INSTALL_ROOT=${1:-}
            [[ -n $INSTALL_ROOT ]] || die "--prefix requires a directory"
            ;;
        --prefix=*)
            INSTALL_ROOT=${1#*=}
            ;;
        --bin-dir)
            shift || die "--bin-dir requires a directory"
            BIN_DIR=${1:-}
            [[ -n $BIN_DIR ]] || die "--bin-dir requires a directory"
            ;;
        --bin-dir=*)
            BIN_DIR=${1#*=}
            ;;
        --config)
            shift || die "--config requires a path"
            CONFIG_PATH=${1:-}
            [[ -n $CONFIG_PATH ]] || die "--config requires a path"
            ;;
        --config=*)
            CONFIG_PATH=${1#*=}
            ;;
        --data-dir)
            shift || die "--data-dir requires a directory"
            DATA_DIR=${1:-}
            [[ -n $DATA_DIR ]] || die "--data-dir requires a directory"
            ;;
        --data-dir=*)
            DATA_DIR=${1#*=}
            ;;
        --rns-dir)
            shift || die "--rns-dir requires a directory"
            RNS_DIR=${1:-}
            [[ -n $RNS_DIR ]] || die "--rns-dir requires a directory"
            ;;
        --rns-dir=*)
            RNS_DIR=${1#*=}
            ;;
        --documents-dir)
            shift || die "--documents-dir requires a directory"
            DOCUMENTS_DIR=${1:-}
            [[ -n $DOCUMENTS_DIR ]] || die "--documents-dir requires a directory"
            ;;
        --documents-dir=*)
            DOCUMENTS_DIR=${1#*=}
            ;;
        --mode)
            shift || die "--mode requires client or server"
            MODE=${1:-}
            ;;
        --mode=*)
            MODE=${1#*=}
            ;;
        --yes)
            ASSUME_YES="1"
            ;;
        --no-deps)
            INSTALL_DEPS="0"
            ;;
        --no-desktop)
            INSTALL_DESKTOP="0"
            ;;
        --no-bin)
            INSTALL_BIN="0"
            ;;
        --smoke-test)
            SMOKE_TEST="1"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while (($#)); do
                positionals+=("$1")
                shift
            done
            break
            ;;
        -*)
            die "Unknown option: $1"
            ;;
        *)
            positionals+=("$1")
            ;;
    esac
    shift || true
done

((${#positionals[@]} <= 1)) || die "Only one extracted bundle path may be provided."
if [[ -n $INPUT_PATH && ${#positionals[@]} -eq 1 ]]; then
    die "Use either the default bundle directory or one positional bundle path, not both."
fi
if [[ ${#positionals[@]} -eq 1 ]]; then
    INPUT_PATH=${positionals[0]}
else
    INPUT_PATH=$SCRIPT_DIR
fi

case "$MODE" in
    client|server) ;;
    *) die "--mode must be client or server" ;;
esac

INSTALL_ROOT=$(make_abs_path "$INSTALL_ROOT")
BIN_DIR=$(make_abs_path "$BIN_DIR")
INPUT_PATH=$(make_abs_path "$INPUT_PATH")

if [[ -z $DATA_DIR ]]; then
    if [[ $MODE == "server" ]]; then
        DATA_DIR="$HOME/.talon-server"
    else
        DATA_DIR="$HOME/.talon"
    fi
fi
DATA_DIR=$(make_abs_path "$DATA_DIR")

[[ -n $RNS_DIR ]] || RNS_DIR="$DATA_DIR/reticulum"
[[ -n $DOCUMENTS_DIR ]] || DOCUMENTS_DIR="$DATA_DIR/documents"
[[ -n $CONFIG_PATH ]] || CONFIG_PATH="$DATA_DIR/talon.ini"
RNS_DIR=$(make_abs_path "$RNS_DIR")
DOCUMENTS_DIR=$(make_abs_path "$DOCUMENTS_DIR")
CONFIG_PATH=$(make_abs_path "$CONFIG_PATH")

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/talon"
STATE_DIR=$(make_abs_path "$STATE_DIR")
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_DIR=$(make_abs_path "$DESKTOP_DIR")

if [[ $INSTALL_DEPS == "1" ]]; then
    install_runtime_dependencies
else
    log "Skipping system dependency installation."
fi

SOURCE_BUNDLE_DIR=""
if [[ -d $INPUT_PATH ]]; then
    SOURCE_BUNDLE_DIR=$INPUT_PATH
elif [[ -f $INPUT_PATH ]]; then
    die "Archive input is no longer supported by the installer. Extract talon-linux.tar.gz, cd into talon-linux, then run bash ./install.sh."
else
    die "Input path does not exist: $INPUT_PATH"
fi

TARGET_DIR=$(install_bundle "$SOURCE_BUNDLE_DIR" "$INSTALL_ROOT")
write_default_config "$CONFIG_PATH" "$MODE" "$DATA_DIR" "$RNS_DIR" "$DOCUMENTS_DIR"

if [[ $INSTALL_BIN == "1" ]]; then
    write_launcher_wrapper "$TARGET_DIR" "$BIN_DIR" "$CONFIG_PATH" "$STATE_DIR"
else
    log "Skipping launcher wrapper."
fi

if [[ $INSTALL_DESKTOP == "1" && $INSTALL_BIN == "1" ]]; then
    write_desktop_entry "$TARGET_DIR" "$BIN_DIR" "$DESKTOP_DIR"
else
    log "Skipping desktop entry."
fi

if [[ $SMOKE_TEST == "1" ]]; then
    run_smoke_test "$TARGET_DIR" "$CONFIG_PATH" "$STATE_DIR"
fi

log ""
log "TALON Linux install complete."
log "Bundle:  $TARGET_DIR"
log "Config:  $CONFIG_PATH"
log "Data:    $DATA_DIR"
log "RNS:     $RNS_DIR"
if [[ $INSTALL_BIN == "1" ]]; then
    log "Launcher: $BIN_DIR/talon"
fi
log ""
log "Reticulum interface setup is deployment-specific. Configure $RNS_DIR/config for TCP, Yggdrasil, I2P, or RNode before relying on network sync."
