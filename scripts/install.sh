#!/bin/bash
#
# ByteCLI Installation Script
# Installs ByteCLI voice dictation service and its dependencies.
#

set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- Helpers ---
info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; }
step()    { echo -e "\n${CYAN}${BOLD}=> $*${NC}"; }

# --- Resolve project directory (where this script lives) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ----------------------------------------------------------------
# 1. Check for required system packages
# ----------------------------------------------------------------
step "Checking system dependencies"

REQUIRED_PKGS=(xclip xdotool portaudio19-dev)
MISSING_PKGS=()

for pkg in "${REQUIRED_PKGS[@]}"; do
    if dpkg -s "$pkg" &>/dev/null; then
        success "$pkg is installed"
    else
        warn "$pkg is NOT installed"
        MISSING_PKGS+=("$pkg")
    fi
done

# ----------------------------------------------------------------
# 2. Install missing packages (with confirmation)
# ----------------------------------------------------------------
if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    step "Installing missing system packages"
    echo -e "The following packages need to be installed: ${BOLD}${MISSING_PKGS[*]}${NC}"
    read -rp "Install with apt-get? [Y/n] " answer
    answer="${answer:-Y}"
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        sudo apt-get update -qq
        sudo apt-get install -y "${MISSING_PKGS[@]}"
        success "System packages installed"
    else
        error "Cannot continue without required packages. Aborting."
        exit 1
    fi
else
    success "All system dependencies are satisfied"
fi

# ----------------------------------------------------------------
# 3. Install ByteCLI Python package in editable mode
# ----------------------------------------------------------------
step "Installing ByteCLI Python package"

if ! command -v pip3 &>/dev/null; then
    error "pip3 not found. Please install python3-pip first."
    exit 1
fi

pip3 install --user -e "${PROJECT_DIR}"
success "ByteCLI Python package installed (editable mode)"

# ----------------------------------------------------------------
# 4. Create data directories
# ----------------------------------------------------------------
step "Creating data directories"

DATA_DIRS=(
    "${HOME}/.config/bytecli"
    "${HOME}/.local/share/bytecli/models"
    "${HOME}/.local/share/bytecli/logs"
)

for dir in "${DATA_DIRS[@]}"; do
    mkdir -p "$dir"
    success "Created $dir"
done

# ----------------------------------------------------------------
# 5. Install systemd user service
# ----------------------------------------------------------------
step "Installing systemd user service"

SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
mkdir -p "${SYSTEMD_USER_DIR}"

cp "${PROJECT_DIR}/systemd/bytecli.service" "${SYSTEMD_USER_DIR}/bytecli.service"
success "Copied bytecli.service to ${SYSTEMD_USER_DIR}"

systemctl --user daemon-reload
success "systemd user daemon reloaded"

# ----------------------------------------------------------------
# 6. Install desktop entries
# ----------------------------------------------------------------
step "Installing desktop entries"

APPS_DIR="${HOME}/.local/share/applications"
mkdir -p "${APPS_DIR}"

cp "${PROJECT_DIR}/desktop/bytecli-settings.desktop" "${APPS_DIR}/bytecli-settings.desktop"
success "Copied bytecli-settings.desktop to ${APPS_DIR}"

# Install autostart entry so ByteCLI starts on login.
AUTOSTART_DIR="${HOME}/.config/autostart"
mkdir -p "${AUTOSTART_DIR}"

cp "${PROJECT_DIR}/desktop/bytecli.desktop" "${AUTOSTART_DIR}/bytecli.desktop"
success "Copied bytecli.desktop to ${AUTOSTART_DIR} (auto-start on login)"

# ----------------------------------------------------------------
# 7. Enable and start the service
# ----------------------------------------------------------------
step "Starting ByteCLI service"

systemctl --user enable bytecli
success "Service enabled (will start on login)"

systemctl --user start bytecli
sleep 2

if systemctl --user is-active bytecli >/dev/null 2>&1; then
    success "ByteCLI service is running!"
else
    warn "Service started but may still be downloading the model..."
    warn "Check status with: systemctl --user status bytecli"
fi

# ----------------------------------------------------------------
# 8. Done
# ----------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}========================================${NC}"
echo -e "${GREEN}${BOLD}  ByteCLI installed successfully!${NC}"
echo -e "${GREEN}${BOLD}========================================${NC}"
echo ""
echo -e "ByteCLI is running! Look for the indicator at the bottom of your screen."
echo ""
echo -e "  ${CYAN}*${NC} Press ${BOLD}Ctrl+Alt+V${NC} to start dictating."
echo -e "  ${CYAN}*${NC} Open Settings from your application menu: ${BOLD}ByteCLI Settings${NC}"
echo -e "  ${CYAN}*${NC} Check service status: ${BOLD}systemctl --user status bytecli${NC}"
echo ""
