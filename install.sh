#!/usr/bin/env bash
# install.sh — T.A.L.O.N. installer
# Detects OS, installs system dependencies, creates a virtualenv,
# and installs all Python packages.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh              # Install everything (client + server)
#   ./install.sh --server     # Server only
#   ./install.sh --client     # Client only
#   ./install.sh --dev        # Include development tools (pytest, pyinstaller)

set -euo pipefail

# ---------------------------------------------------------------
# Colors
# ---------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No color

info()  { echo -e "${CYAN}[TALON]${NC} $*"; }
ok()    { echo -e "${GREEN}[  OK ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

# ---------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------
INSTALL_SERVER=true
INSTALL_CLIENT=true
INSTALL_DEV=false

for arg in "$@"; do
    case "$arg" in
        --server) INSTALL_CLIENT=false ;;
        --client) INSTALL_SERVER=false ;;
        --dev)    INSTALL_DEV=true ;;
        --help|-h)
            echo "Usage: ./install.sh [--server|--client] [--dev]"
            echo ""
            echo "  --server   Install server only"
            echo "  --client   Install client only"
            echo "  --dev      Include dev tools (pytest, pyinstaller)"
            echo ""
            echo "  Default: install both client and server."
            exit 0
            ;;
        *) fail "Unknown argument: $arg (try --help)" ;;
    esac
done

# ---------------------------------------------------------------
# Detect OS
# ---------------------------------------------------------------
detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        case "$ID" in
            ubuntu|debian|pop|linuxmint|elementary|zorin)
                OS="debian"
                ;;
            fedora|rhel|centos|rocky|alma)
                OS="fedora"
                ;;
            arch|manjaro|endeavouros)
                OS="arch"
                ;;
            opensuse*|sles)
                OS="suse"
                ;;
            *)
                OS="unknown-linux"
                ;;
        esac
    elif [[ "$(uname -s)" == "Darwin" ]]; then
        OS="macos"
    elif [[ "$(uname -s)" == MINGW* ]] || [[ "$(uname -s)" == MSYS* ]] || [[ "$(uname -s)" == CYGWIN* ]]; then
        OS="windows"
    else
        OS="unknown"
    fi
}

detect_os
info "Detected OS: $OS"

# ---------------------------------------------------------------
# Check Python version
# ---------------------------------------------------------------
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
        if [[ "$major" -ge 3 ]] && [[ "$minor" -ge 10 ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    fail "Python 3.10+ is required but not found. Install Python first."
fi

ok "Found $PYTHON ($ver)"

# ---------------------------------------------------------------
# Install system dependencies
# ---------------------------------------------------------------
info "Installing system dependencies..."

case "$OS" in
    debian)
        PKGS=(
            # SQLCipher — encrypted SQLite
            libsqlcipher-dev
            # Kivy SDL2 dependencies
            libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev
            # Python build tools
            python3-dev python3-venv python3-pip
            build-essential
            # Needed by PyNaCl / cryptography
            libffi-dev libssl-dev
            # Git (for kivy_garden)
            git
        )
        info "Running: sudo apt install ${PKGS[*]}"
        sudo apt update -qq
        sudo apt install -y -qq "${PKGS[@]}"
        ok "System packages installed"
        ;;

    fedora)
        PKGS=(
            sqlcipher-devel
            SDL2-devel SDL2_image-devel SDL2_mixer-devel SDL2_ttf-devel
            python3-devel python3-pip
            gcc gcc-c++
            libffi-devel openssl-devel
            git
        )
        info "Running: sudo dnf install ${PKGS[*]}"
        sudo dnf install -y -q "${PKGS[@]}"
        ok "System packages installed"
        ;;

    arch)
        PKGS=(
            sqlcipher
            sdl2 sdl2_image sdl2_mixer sdl2_ttf
            python python-pip
            base-devel
            libffi openssl
            git
        )
        info "Running: sudo pacman -S ${PKGS[*]}"
        sudo pacman -S --noconfirm --needed "${PKGS[@]}"
        ok "System packages installed"
        ;;

    suse)
        PKGS=(
            sqlcipher-devel
            libSDL2-devel libSDL2_image-devel libSDL2_mixer-devel libSDL2_ttf-devel
            python3-devel python3-pip
            gcc gcc-c++
            libffi-devel libopenssl-devel
            git
        )
        info "Running: sudo zypper install ${PKGS[*]}"
        sudo zypper install -y "${PKGS[@]}"
        ok "System packages installed"
        ;;

    macos)
        if ! command -v brew &>/dev/null; then
            fail "Homebrew not found. Install it from https://brew.sh"
        fi
        PKGS=(sqlcipher sdl2 sdl2_image sdl2_mixer sdl2_ttf libffi openssl git)
        info "Running: brew install ${PKGS[*]}"
        brew install "${PKGS[@]}"
        ok "System packages installed"
        ;;

    windows)
        warn "Windows detected. System deps must be installed manually:"
        warn "  1. SQLCipher: download prebuilt DLL from https://github.com/nicehash/sqlcipher-windows"
        warn "  2. Kivy SDL2 deps: bundled automatically via pip"
        warn "  3. Visual Studio Build Tools: https://visualstudio.microsoft.com/visual-cpp-build-tools/"
        warn ""
        warn "Continuing with Python package install..."
        ;;

    *)
        warn "Unrecognized OS ($OS). Skipping system package install."
        warn "You may need to manually install: libsqlcipher-dev, SDL2 dev libs, python3-dev"
        warn "Continuing with Python package install..."
        ;;
esac

# ---------------------------------------------------------------
# Create virtual environment
# ---------------------------------------------------------------
VENV_DIR=".venv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment in $VENV_DIR/"
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created"
else
    info "Virtual environment already exists at $VENV_DIR/"
fi

# Activate
source "$VENV_DIR/bin/activate" 2>/dev/null || source "$VENV_DIR/Scripts/activate" 2>/dev/null || fail "Could not activate venv"
ok "Virtual environment activated"

# Upgrade pip
pip install --upgrade pip setuptools wheel -q
ok "pip/setuptools/wheel upgraded"

# ---------------------------------------------------------------
# Install Python packages
# ---------------------------------------------------------------
info "Installing T.A.L.O.N. Python packages..."

# Install the package itself (pulls in all dependencies from pyproject.toml)
pip install -e "." -q
ok "Core dependencies installed"

# Map tiles
info "Installing map tile support..."
pip install "mapview>=1.0.6" -q 2>/dev/null && ok "mapview installed" || warn "mapview install failed — map tiles will be unavailable"

# Dev tools
if [[ "$INSTALL_DEV" == true ]]; then
    info "Installing development tools..."
    pip install -e ".[dev]" -q
    ok "Dev tools installed (pytest, pyinstaller, buildozer)"
fi

# ---------------------------------------------------------------
# Verify installation
# ---------------------------------------------------------------
info "Verifying installation..."

ERRORS=0

check_import() {
    local module="$1"
    local label="${2:-$1}"
    if python -c "import $module" 2>/dev/null; then
        ok "$label"
    else
        warn "MISSING: $label ($module)"
        ERRORS=$((ERRORS + 1))
    fi
}

check_import "RNS"            "Reticulum (rns)"
check_import "LXMF"           "LXMF"
check_import "nacl"           "PyNaCl"
check_import "argon2"         "argon2-cffi"
check_import "yaml"           "PyYAML"
check_import "serial"         "pyserial"

if [[ "$INSTALL_CLIENT" == true ]]; then
    check_import "kivy"       "Kivy"
    check_import "kivymd"     "KivyMD"
fi

# SQLCipher — may fail if system lib is missing
if python -c "import sqlcipher3" 2>/dev/null; then
    ok "SQLCipher3"
else
    warn "MISSING: sqlcipher3 — check that libsqlcipher-dev is installed"
    ERRORS=$((ERRORS + 1))
fi

# T.A.L.O.N. itself
check_import "talon.server.app"     "talon.server"
check_import "talon.client.app"     "talon.client"
check_import "talon.sync.protocol"  "talon.sync"
check_import "talon.net.link_manager" "talon.net"

# ---------------------------------------------------------------
# Run tests if dev tools are installed
# ---------------------------------------------------------------
if [[ "$INSTALL_DEV" == true ]]; then
    info "Running test suite..."
    if python -m pytest --tb=line -q 2>/dev/null; then
        ok "All tests passed"
    else
        warn "Some tests failed — check output above"
    fi
fi

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "============================================"
if [[ "$ERRORS" -eq 0 ]]; then
    echo -e "  ${GREEN}T.A.L.O.N. installation complete!${NC}"
else
    echo -e "  ${YELLOW}T.A.L.O.N. installed with $ERRORS warning(s)${NC}"
fi
echo "============================================"
echo ""
echo "  Activate the environment:"
echo "    source .venv/bin/activate"
echo ""
echo "  Start the server:"
echo "    python talon-server.py"
echo ""
echo "  Start a client:"
echo "    python talon-client.py"
echo ""
echo "  Run tests:"
echo "    python -m pytest"
echo ""
