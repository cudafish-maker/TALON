#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="talon-desktop"
ROLE_MARKER=".talon-artifact-role"
DELETE_CONFIRMATION="DELETE TALON DATA"
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
TALON PySide6 Linux desktop installer

Usage:
  install.sh [options] [extracted-talon-desktop-client-linux-dir|extracted-talon-desktop-server-linux-dir]
  install.sh --uninstall --confirm-delete "DELETE TALON DATA" [options]

Options:
  --prefix DIR         Install root. Default: $XDG_DATA_HOME/talon or ~/.local/share/talon
  --bin-dir DIR        Launcher directory. Default: ~/.local/bin
  --config PATH        Config file to create/use. Default follows artifact role.
  --data-dir DIR       TALON data directory. Default follows artifact role.
  --rns-dir DIR        Reticulum config/key directory. Default: <data-dir>/reticulum
  --documents-dir DIR  Document storage/cache directory. Default: <data-dir>/documents
  --confirm-delete TXT Required exact phrase for destructive role switches.
                       Also required for full uninstall cleanup.
  --uninstall          Remove local TALON desktop/legacy installs and data, then exit.
  --yes                Assume yes for supported system package managers.
  --no-deps            Do not install system runtime dependencies.
  --no-desktop         Do not create a desktop launcher entry.
  --no-bin             Do not create the role-specific launcher wrapper.
  --smoke-test         Run the installed PySide6 package smoke test.
  -h, --help           Show this help.

Examples:
  tar -xzf talon-desktop-client-linux.tar.gz
  cd talon-desktop-client-linux
  bash ./install.sh --yes
  tar -xzf talon-desktop-server-linux.tar.gz
  cd talon-desktop-server-linux
  bash ./install.sh --yes
  bash ./install.sh --uninstall --confirm-delete "DELETE TALON DATA"
  bash ./install.sh --no-deps --no-desktop --smoke-test
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

have_library_file() {
    local library=$1
    local dir

    for dir in /lib /usr/lib /usr/local/lib /lib64 /usr/lib64 /lib/*-linux-gnu /usr/lib/*-linux-gnu; do
        [[ -d $dir ]] || continue
        compgen -G "$dir/$library" >/dev/null && return 0
        compgen -G "$dir/$library.*" >/dev/null && return 0
    done

    return 1
}

have_library() {
    local library=$1
    local ldconfig_bin

    if ldconfig_bin=$(ldconfig_path); then
        "$ldconfig_bin" -p 2>/dev/null | grep -Eq "(^|[[:space:]])${library}([[:space:]]|$)" && return 0
    fi

    have_library_file "$library"
}

runtime_dependency_gaps() {
    local missing=()

    command -v xdg-open >/dev/null 2>&1 || missing+=("xdg-open")
    have_library "libGL.so.1" || missing+=("libGL.so.1")
    have_library "libEGL.so.1" || missing+=("libEGL.so.1")
    have_library "libxkbcommon.so.0" || missing+=("libxkbcommon.so.0")
    have_library "libxcb-cursor.so.0" || missing+=("libxcb-cursor.so.0")
    have_library "libxcb-icccm.so.4" || missing+=("libxcb-icccm.so.4")
    have_library "libxcb-image.so.0" || missing+=("libxcb-image.so.0")
    have_library "libxcb-keysyms.so.1" || missing+=("libxcb-keysyms.so.1")
    have_library "libxcb-render-util.so.0" || missing+=("libxcb-render-util.so.0")
    have_library "libxcb-xinerama.so.0" || missing+=("libxcb-xinerama.so.0")
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
        libgl1
        libegl1
        libxkbcommon0
        libxcb-cursor0
        libxcb-icccm4
        libxcb-image0
        libxcb-keysyms1
        libxcb-render-util0
        libxcb-xinerama0
        libx11-xcb1
        libdbus-1-3
        libfontconfig1
        libfreetype6
    )

    append_first_available_apt_package packages libmagic1t64 libmagic1 file || warn "No apt package found for libmagic."
    append_first_available_apt_package packages libsqlcipher1 libsqlcipher0 libsqlcipher-dev sqlcipher || warn "No apt package found for SQLCipher."

    local yes_args=()
    [[ $ASSUME_YES == "1" ]] && yes_args=(-y)
    run_as_root apt-get update
    run_as_root apt-get install "${yes_args[@]}" --no-install-recommends "${packages[@]}"
}

install_deps_dnf() {
    local packages=(
        xdg-utils
        mesa-libGL
        mesa-libEGL
        libxkbcommon
        xcb-util-cursor
        xcb-util-wm
        xcb-util-image
        xcb-util-keysyms
        xcb-util-renderutil
        file-libs
        sqlcipher
    )
    local yes_args=()
    [[ $ASSUME_YES == "1" ]] && yes_args=(-y)
    run_as_root dnf install "${yes_args[@]}" "${packages[@]}"
}

install_deps_pacman() {
    local packages=(
        xdg-utils
        mesa
        libglvnd
        libxkbcommon
        xcb-util-cursor
        xcb-util-wm
        xcb-util-image
        xcb-util-keysyms
        xcb-util-renderutil
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

read_artifact_role() {
    local bundle_dir=$1
    local role_file=$bundle_dir/$ROLE_MARKER
    local role

    [[ -f $role_file ]] || die "TALON desktop bundle is missing role marker: $role_file"
    role=$(tr -d '[:space:]' < "$role_file")
    case "$role" in
        client|server) printf '%s\n' "$role" ;;
        *) die "Invalid TALON desktop artifact role: $role" ;;
    esac
}

validate_bundle() {
    local bundle_dir=$1
    local required=(
        "$bundle_dir/$APP_NAME"
        "$bundle_dir/_internal/base_library.zip"
        "$bundle_dir/$ROLE_MARKER"
    )
    local path

    for path in "${required[@]}"; do
        [[ -e $path ]] || die "TALON desktop bundle is missing required runtime asset: $path"
    done
    read_artifact_role "$bundle_dir" >/dev/null
    [[ ! -d $bundle_dir/_internal/kivy ]] || die "PySide6 bundle unexpectedly contains Kivy."
    [[ ! -d $bundle_dir/_internal/kivymd ]] || die "PySide6 bundle unexpectedly contains KivyMD."
    chmod +x "$bundle_dir/$APP_NAME"
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
        if [[ ! -x $target_dir/$APP_NAME || ! -d $target_dir/_internal ]]; then
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
        die "Failed to stage TALON desktop bundle."
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
    chmod 700 "$(dirname "$config_path")" "$data_dir" "$rns_dir" "$documents_dir"

    if [[ -f $config_path ]]; then
        log "Keeping existing config: $config_path"
        chmod 600 "$config_path"
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

write_default_rns_config() {
    local rns_dir=$1
    local role=$2
    local config_path=$rns_dir/config
    local enable_transport="False"

    [[ $role == "server" ]] && enable_transport="True"

    mkdir -p "$rns_dir"
    chmod 700 "$rns_dir"

    if [[ -f $config_path ]]; then
        log "Keeping existing Reticulum config: $config_path"
        chmod 600 "$config_path"
        return 0
    fi

    cat > "$config_path" <<EOF
[reticulum]
  enable_transport = $enable_transport
  share_instance = No

[logging]
  loglevel = 4

[interfaces]
  [[TALON AutoInterface]]
    type = AutoInterface
    enabled = Yes

# TCP, Yggdrasil, I2P, and RNode interfaces are deployment-specific.
# Add matching TCPServerInterface/TCPClientInterface stanzas here when needed.
EOF

    chmod 600 "$config_path"
    log "Created Reticulum config: $config_path"
}

write_launcher_wrapper() {
    local target_dir=$1
    local bin_dir=$2
    local config_path=$3
    local state_dir=$4
    local launcher_name=$5
    local role=$6
    local wrapper=$bin_dir/$launcher_name
    local app_q
    local config_q
    local launch_log_q

    mkdir -p "$bin_dir" "$state_dir"
    chmod 700 "$state_dir"
    app_q=$(shell_quote "$target_dir/$APP_NAME")
    config_q=$(shell_quote "$config_path")
    launch_log_q=$(shell_quote "$state_dir/desktop-${role}-launcher.log")

    cat > "$wrapper" <<EOF
#!/usr/bin/env bash
if [ -z "\${TALON_CONFIG:-}" ]; then
  export TALON_CONFIG=$config_q
fi

app=$app_q
launch_log=$launch_log_q
mkdir -p "\$(dirname "\$launch_log")"

printf '\\n--- TALON desktop launch: %s ---\\n' "\$(date -Is)" >> "\$launch_log"
exec "\$app" "\$@" >> "\$launch_log" 2>&1
EOF

    chmod 755 "$wrapper"
    log "Installed launcher: $wrapper"
}

write_desktop_entry() {
    local target_dir=$1
    local bin_dir=$2
    local desktop_dir=$3
    local launcher_name=$4
    local entry_name=$5
    local display_name=$6
    local entry_path=$desktop_dir/$entry_name
    local icon_path=$target_dir/_internal/Images/talonlogo.png

    mkdir -p "$desktop_dir"
    [[ -f $icon_path ]] || icon_path=

    cat > "$entry_path" <<EOF
[Desktop Entry]
Type=Application
Name=$display_name
Comment=Tactical Awareness and Linked Operations Network
Exec=$bin_dir/$launcher_name
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
    local mode=$3
    local smoke_prefix=(
        env
        "TALON_CONFIG=$config_path"
        "QT_QPA_PLATFORM=offscreen"
    )

    timeout 30s "${smoke_prefix[@]}" "$target_dir/$APP_NAME" --smoke --mode "$mode"
}

manifest_path_for_role() {
    local state_dir=$1
    local role=$2
    printf '%s\n' "$state_dir/desktop-${role}.install"
}

write_install_manifest() {
    local manifest_path=$1
    local role=$2
    local target_dir=$3
    local launcher_path=$4
    local desktop_entry_path=$5
    local config_path=$6
    local data_dir=$7
    local rns_dir=$8
    local documents_dir=$9

    mkdir -p "$(dirname "$manifest_path")"
    chmod 700 "$(dirname "$manifest_path")"
    cat > "$manifest_path" <<EOF
role=$role
bundle=$target_dir
launcher=$launcher_path
desktop_entry=$desktop_entry_path
config=$config_path
data=$data_dir
rns=$rns_dir
documents=$documents_dir
EOF
    chmod 600 "$manifest_path"
}

add_existing_path() {
    local -n target_ref=$1
    local path=$2
    [[ -n $path ]] || return 0
    [[ -e $path || -L $path ]] || return 0
    target_ref+=("$path")
}

add_talon_owned_file_path() {
    local -n target_ref=$1
    local path=$2
    local link_target=""

    [[ -n $path ]] || return 0
    [[ -e $path || -L $path ]] || return 0
    if [[ -L $path ]]; then
        link_target=$(readlink "$path" || :)
        if [[ $link_target == *talon* || $link_target == *TALON* ]]; then
            target_ref+=("$path")
        fi
        return 0
    fi
    [[ -f $path ]] || return 0
    if grep -Eiq "TALON|T\\.A\\.L\\.O\\.N\\.|Tactical Awareness|talon-desktop|talon-linux" "$path" 2>/dev/null; then
        target_ref+=("$path")
    fi
}

add_install_artifact_globs() {
    local -n target_ref=$1
    local install_root=$2
    local artifact_name=$3
    local nullglob_state
    local path

    nullglob_state=$(shopt -p nullglob || :)
    shopt -s nullglob
    for path in "$install_root"/"$artifact_name".backup.* "$install_root"/."$artifact_name".new.*; do
        [[ -e $path || -L $path ]] || continue
        target_ref+=("$path")
    done
    eval "$nullglob_state"
}

add_manifest_paths() {
    local -n target_ref=$1
    local manifest_path=$2
    local key
    local value

    [[ -e $manifest_path || -L $manifest_path ]] && target_ref+=("$manifest_path")
    [[ -f $manifest_path ]] || return 0
    while IFS='=' read -r key value; do
        case "$key" in
            bundle|launcher|desktop_entry|config|data|rns|documents)
                [[ -n $value && ( -e $value || -L $value ) ]] && target_ref+=("$value")
                ;;
        esac
    done < "$manifest_path"
}

collect_talon_footprint_paths() {
    local output_name=$1
    local -n output_ref=$output_name
    local install_root=$2
    local bin_dir=$3
    local desktop_dir=$4
    local state_dir=$5
    local include_install_artifacts=${6:-0}
    local artifact_name
    local settings_home

    output_ref=()
    add_existing_path "$output_name" "$HOME/.talon"
    add_existing_path "$output_name" "$HOME/.talon-server"
    add_existing_path "$output_name" "$install_root/talon-linux"
    add_existing_path "$output_name" "$install_root/talon-desktop-linux"
    add_existing_path "$output_name" "$install_root/talon-desktop-client-linux"
    add_existing_path "$output_name" "$install_root/talon-desktop-server-linux"
    add_talon_owned_file_path "$output_name" "$bin_dir/talon"
    add_talon_owned_file_path "$output_name" "$bin_dir/talon-desktop"
    add_talon_owned_file_path "$output_name" "$bin_dir/talon-desktop-client"
    add_talon_owned_file_path "$output_name" "$bin_dir/talon-desktop-server"
    add_talon_owned_file_path "$output_name" "$desktop_dir/talon.desktop"
    add_talon_owned_file_path "$output_name" "$desktop_dir/talon-desktop.desktop"
    add_talon_owned_file_path "$output_name" "$desktop_dir/talon-desktop-client.desktop"
    add_talon_owned_file_path "$output_name" "$desktop_dir/talon-desktop-server.desktop"
    add_existing_path "$output_name" "$state_dir"
    add_manifest_paths "$output_name" "$(manifest_path_for_role "$state_dir" client)"
    add_manifest_paths "$output_name" "$(manifest_path_for_role "$state_dir" server)"

    if [[ $include_install_artifacts == "1" ]]; then
        for artifact_name in \
            talon-linux \
            talon-desktop-linux \
            talon-desktop-client-linux \
            talon-desktop-server-linux; do
            add_install_artifact_globs "$output_name" "$install_root" "$artifact_name"
        done
        settings_home=$(make_abs_path "${XDG_CONFIG_HOME:-$HOME/.config}")
        add_existing_path "$output_name" "$settings_home/TALON"
        add_existing_path "$output_name" "${TALON_DESKTOP_SETTINGS_PATH:-}"
    fi

    unique_existing_paths "$output_name" "${output_ref[@]}"
}

path_in_list() {
    local needle=$1
    shift
    local item
    for item in "$@"; do
        [[ $needle == "$item" ]] && return 0
    done
    return 1
}

unique_existing_paths() {
    local -n output_ref=$1
    shift
    local path
    output_ref=()
    for path in "$@"; do
        [[ -n $path ]] || continue
        [[ -e $path || -L $path ]] || continue
        path_in_list "$path" "${output_ref[@]}" || output_ref+=("$path")
    done
}

require_delete_confirmation() {
    local operation=$1
    shift
    local -a paths=("$@")
    local path
    warn "$operation requires deleting previous local TALON files."
    warn "This includes local databases, RNS identities, documents, launchers, desktop entries, bundles, and logs."
    warn "Paths that will be removed:"
    for path in "${paths[@]}"; do
        warn "  $path"
    done

    if [[ -n $CONFIRM_DELETE ]]; then
        [[ $CONFIRM_DELETE == "$DELETE_CONFIRMATION" ]] || die "Invalid destructive confirmation phrase."
        return 0
    fi

    [[ -t 0 ]] || die "$operation requires --confirm-delete \"$DELETE_CONFIRMATION\"."
    printf 'Type %s to delete previous TALON data and continue: ' "$DELETE_CONFIRMATION" >&2
    local response
    IFS= read -r response
    [[ $response == "$DELETE_CONFIRMATION" ]] || die "$operation was not confirmed."
}

delete_paths() {
    local -a paths=("$@")
    local path
    for path in "${paths[@]}"; do
        rm -rf -- "$path"
    done
}

enforce_role_path_reservation() {
    local role=$1
    local data_dir=$2
    local config_path=$3
    local client_data
    local server_data

    client_data=$(make_abs_path "$HOME/.talon")
    server_data=$(make_abs_path "$HOME/.talon-server")
    if [[ $role == "client" ]]; then
        [[ $data_dir != "$server_data" ]] || die "Client artifact cannot use the server profile directory."
        [[ $config_path != "$server_data/talon.ini" ]] || die "Client artifact cannot use the server config path."
    else
        [[ $data_dir != "$client_data" ]] || die "Server artifact cannot use the client profile directory."
        [[ $config_path != "$client_data/talon.ini" ]] || die "Server artifact cannot use the client config path."
    fi
}

guard_role_switch() {
    local role=$1
    local install_root=$2
    local bin_dir=$3
    local desktop_dir=$4
    local state_dir=$5
    local target_dir=$6
    local launcher_path=$7
    local desktop_entry_path=$8
    local config_path=$9
    local data_dir=${10}
    local rns_dir=${11}
    local documents_dir=${12}
    local current_manifest=${13}
    local -a detected=()
    local -a expected=()
    local -a unexpected=()
    local -a destructive=()
    local path

    expected=(
        "$target_dir"
        "$launcher_path"
        "$desktop_entry_path"
        "$config_path"
        "$data_dir"
        "$rns_dir"
        "$documents_dir"
        "$current_manifest"
        "$state_dir"
    )

    collect_talon_footprint_paths detected "$install_root" "$bin_dir" "$desktop_dir" "$state_dir" 0
    for path in "${detected[@]}"; do
        if ! path_in_list "$path" "${expected[@]}"; then
            unexpected+=("$path")
        fi
    done

    ((${#unexpected[@]} == 0)) && return 0
    unique_existing_paths destructive "${detected[@]}"
    require_delete_confirmation "Destructive role switch" "${destructive[@]}"
    delete_paths "${destructive[@]}"
}

run_uninstall_cleanup() {
    local install_root=$1
    local bin_dir=$2
    local desktop_dir=$3
    local state_dir=$4
    local -a cleanup=()
    local removed_count

    collect_talon_footprint_paths cleanup "$install_root" "$bin_dir" "$desktop_dir" "$state_dir" 1
    add_existing_path cleanup "$CONFIG_PATH"
    add_existing_path cleanup "$DATA_DIR"
    add_existing_path cleanup "$RNS_DIR"
    add_existing_path cleanup "$DOCUMENTS_DIR"
    unique_existing_paths cleanup "${cleanup[@]}"

    if ((${#cleanup[@]} == 0)); then
        log "No local TALON desktop or legacy install paths were found."
        return 0
    fi

    require_delete_confirmation "Uninstalling TALON" "${cleanup[@]}"
    removed_count=${#cleanup[@]}
    delete_paths "${cleanup[@]}"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
    fi

    log "TALON desktop uninstall complete."
    log "Removed $removed_count path(s)."
}

INPUT_PATH=""
INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/talon"
BIN_DIR="$HOME/.local/bin"
CONFIG_PATH=""
DATA_DIR=""
RNS_DIR=""
DOCUMENTS_DIR=""
ARTIFACT_ROLE=""
BUNDLE_NAME=""
LAUNCHER_NAME=""
DESKTOP_ENTRY_NAME=""
DESKTOP_DISPLAY_NAME=""
CONFIRM_DELETE=""
ASSUME_YES="0"
INSTALL_DEPS="1"
INSTALL_DESKTOP="1"
INSTALL_BIN="1"
SMOKE_TEST="0"
UNINSTALL="0"

positionals=()
while (($#)); do
    case "$1" in
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
            die "--mode is not supported. Install a client or server artifact instead."
            ;;
        --mode=*)
            die "--mode is not supported. Install a client or server artifact instead."
            ;;
        --confirm-delete)
            shift || die "--confirm-delete requires the exact confirmation phrase"
            CONFIRM_DELETE=${1:-}
            ;;
        --confirm-delete=*)
            CONFIRM_DELETE=${1#*=}
            ;;
        --uninstall)
            UNINSTALL="1"
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

INSTALL_ROOT=$(make_abs_path "$INSTALL_ROOT")
BIN_DIR=$(make_abs_path "$BIN_DIR")
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/talon"
STATE_DIR=$(make_abs_path "$STATE_DIR")
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_DIR=$(make_abs_path "$DESKTOP_DIR")

if [[ -n $CONFIG_PATH ]]; then
    CONFIG_PATH=$(make_abs_path "$CONFIG_PATH")
fi
if [[ -n $DATA_DIR ]]; then
    DATA_DIR=$(make_abs_path "$DATA_DIR")
fi
if [[ -n $RNS_DIR ]]; then
    RNS_DIR=$(make_abs_path "$RNS_DIR")
fi
if [[ -n $DOCUMENTS_DIR ]]; then
    DOCUMENTS_DIR=$(make_abs_path "$DOCUMENTS_DIR")
fi

if [[ $UNINSTALL == "1" ]]; then
    ((${#positionals[@]} == 0)) || die "--uninstall does not accept a bundle path."
    [[ $SMOKE_TEST == "0" ]] || die "--smoke-test cannot be used with --uninstall."
    run_uninstall_cleanup "$INSTALL_ROOT" "$BIN_DIR" "$DESKTOP_DIR" "$STATE_DIR"
    exit 0
fi

if [[ ${#positionals[@]} -eq 1 ]]; then
    INPUT_PATH=${positionals[0]}
else
    INPUT_PATH=$SCRIPT_DIR
fi
INPUT_PATH=$(make_abs_path "$INPUT_PATH")

if [[ -d $INPUT_PATH ]]; then
    SOURCE_BUNDLE_DIR=$INPUT_PATH
elif [[ -f $INPUT_PATH ]]; then
    die "Archive input is not supported. Extract the TALON desktop artifact, cd into it, then run bash ./install.sh."
else
    die "Input path does not exist: $INPUT_PATH"
fi

ARTIFACT_ROLE=$(read_artifact_role "$SOURCE_BUNDLE_DIR")
BUNDLE_NAME="talon-desktop-${ARTIFACT_ROLE}-linux"
LAUNCHER_NAME="talon-desktop-${ARTIFACT_ROLE}"
DESKTOP_ENTRY_NAME="talon-desktop-${ARTIFACT_ROLE}.desktop"
if [[ $ARTIFACT_ROLE == "server" ]]; then
    DESKTOP_DISPLAY_NAME="T.A.L.O.N. Server"
else
    DESKTOP_DISPLAY_NAME="T.A.L.O.N. Client"
fi

if [[ -z $DATA_DIR ]]; then
    if [[ $ARTIFACT_ROLE == "server" ]]; then
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
TARGET_DIR="$INSTALL_ROOT/$BUNDLE_NAME"
LAUNCHER_PATH="$BIN_DIR/$LAUNCHER_NAME"
DESKTOP_ENTRY_PATH="$DESKTOP_DIR/$DESKTOP_ENTRY_NAME"
INSTALL_MANIFEST=$(manifest_path_for_role "$STATE_DIR" "$ARTIFACT_ROLE")

enforce_role_path_reservation "$ARTIFACT_ROLE" "$DATA_DIR" "$CONFIG_PATH"
guard_role_switch \
    "$ARTIFACT_ROLE" \
    "$INSTALL_ROOT" \
    "$BIN_DIR" \
    "$DESKTOP_DIR" \
    "$STATE_DIR" \
    "$TARGET_DIR" \
    "$LAUNCHER_PATH" \
    "$DESKTOP_ENTRY_PATH" \
    "$CONFIG_PATH" \
    "$DATA_DIR" \
    "$RNS_DIR" \
    "$DOCUMENTS_DIR" \
    "$INSTALL_MANIFEST"

if [[ $INSTALL_DEPS == "1" ]]; then
    install_runtime_dependencies
else
    log "Skipping system dependency installation."
fi

TARGET_DIR=$(install_bundle "$SOURCE_BUNDLE_DIR" "$INSTALL_ROOT")
write_default_config "$CONFIG_PATH" "$ARTIFACT_ROLE" "$DATA_DIR" "$RNS_DIR" "$DOCUMENTS_DIR"
write_default_rns_config "$RNS_DIR" "$ARTIFACT_ROLE"

if [[ $INSTALL_BIN == "1" ]]; then
    write_launcher_wrapper "$TARGET_DIR" "$BIN_DIR" "$CONFIG_PATH" "$STATE_DIR" "$LAUNCHER_NAME" "$ARTIFACT_ROLE"
else
    log "Skipping launcher wrapper."
fi

if [[ $INSTALL_DESKTOP == "1" && $INSTALL_BIN == "1" ]]; then
    write_desktop_entry "$TARGET_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$LAUNCHER_NAME" "$DESKTOP_ENTRY_NAME" "$DESKTOP_DISPLAY_NAME"
else
    log "Skipping desktop entry."
fi

write_install_manifest \
    "$INSTALL_MANIFEST" \
    "$ARTIFACT_ROLE" \
    "$TARGET_DIR" \
    "$LAUNCHER_PATH" \
    "$DESKTOP_ENTRY_PATH" \
    "$CONFIG_PATH" \
    "$DATA_DIR" \
    "$RNS_DIR" \
    "$DOCUMENTS_DIR"

if [[ $SMOKE_TEST == "1" ]]; then
    run_smoke_test "$TARGET_DIR" "$CONFIG_PATH" "$ARTIFACT_ROLE"
fi

log ""
log "TALON PySide6 desktop install complete."
log "Bundle:  $TARGET_DIR"
log "Role:    $ARTIFACT_ROLE"
log "Config:  $CONFIG_PATH"
log "Data:    $DATA_DIR"
log "RNS:     $RNS_DIR"
if [[ $INSTALL_BIN == "1" ]]; then
    log "Launcher: $LAUNCHER_PATH"
fi
log ""
log "Reticulum interface setup is deployment-specific. First networked launch will ask you to review and accept $RNS_DIR/config before sync starts."
