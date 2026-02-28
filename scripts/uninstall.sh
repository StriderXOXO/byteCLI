#!/bin/bash
#
# ByteCLI Uninstallation Script
# Removes the ByteCLI voice dictation service and its files.
#

set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; }
step()    { echo -e "\n${CYAN}${BOLD}=> $*${NC}"; }

echo -e "${RED}${BOLD}========================================${NC}"
echo -e "${RED}${BOLD}  ByteCLI Uninstaller${NC}"
echo -e "${RED}${BOLD}========================================${NC}"

# ----------------------------------------------------------------
# 1. Stop the service
# ----------------------------------------------------------------
step "Stopping ByteCLI service"

if systemctl --user is-active --quiet bytecli 2>/dev/null; then
    systemctl --user stop bytecli
    success "Service stopped"
else
    info "Service is not running"
fi

# ----------------------------------------------------------------
# 2. Disable the service
# ----------------------------------------------------------------
step "Disabling ByteCLI service"

if systemctl --user is-enabled --quiet bytecli 2>/dev/null; then
    systemctl --user disable bytecli
    success "Service disabled"
else
    info "Service is not enabled"
fi

# ----------------------------------------------------------------
# 3. Remove systemd service file
# ----------------------------------------------------------------
step "Removing systemd service file"

SERVICE_FILE="${HOME}/.config/systemd/user/bytecli.service"
if [ -f "$SERVICE_FILE" ]; then
    rm "$SERVICE_FILE"
    systemctl --user daemon-reload
    success "Removed ${SERVICE_FILE}"
else
    info "Service file not found (already removed)"
fi

# ----------------------------------------------------------------
# 4. Remove desktop entries
# ----------------------------------------------------------------
step "Removing desktop entries"

SETTINGS_DESKTOP="${HOME}/.local/share/applications/bytecli-settings.desktop"
if [ -f "$SETTINGS_DESKTOP" ]; then
    rm "$SETTINGS_DESKTOP"
    success "Removed ${SETTINGS_DESKTOP}"
else
    info "Settings desktop entry not found"
fi

# ----------------------------------------------------------------
# 5. Remove autostart entry if present
# ----------------------------------------------------------------
step "Removing autostart entry"

AUTOSTART_DESKTOP="${HOME}/.config/autostart/bytecli.desktop"
if [ -f "$AUTOSTART_DESKTOP" ]; then
    rm "$AUTOSTART_DESKTOP"
    success "Removed ${AUTOSTART_DESKTOP}"
else
    info "Autostart entry not found"
fi

# ----------------------------------------------------------------
# 6. Ask about user data removal
# ----------------------------------------------------------------
step "User data"

echo -e "The following directories contain your ByteCLI data:"
echo -e "  ${BOLD}~/.config/bytecli/${NC}              (configuration)"
echo -e "  ${BOLD}~/.local/share/bytecli/models/${NC}   (downloaded models)"
echo -e "  ${BOLD}~/.local/share/bytecli/logs/${NC}     (log files)"
echo -e "  ${BOLD}~/.local/share/bytecli/${NC}          (history & data)"
echo ""
read -rp "Remove all user data? This cannot be undone. [y/N] " answer
answer="${answer:-N}"
if [[ "$answer" =~ ^[Yy]$ ]]; then
    rm -rf "${HOME}/.config/bytecli"
    rm -rf "${HOME}/.local/share/bytecli"
    success "User data removed"
else
    info "User data preserved"
fi

# ----------------------------------------------------------------
# 7. Uninstall Python package
# ----------------------------------------------------------------
step "Uninstalling ByteCLI Python package"

if pip3 show bytecli &>/dev/null; then
    pip3 uninstall bytecli -y
    success "ByteCLI Python package uninstalled"
else
    info "ByteCLI Python package not found (already removed)"
fi

# ----------------------------------------------------------------
# Done
# ----------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}========================================${NC}"
echo -e "${GREEN}${BOLD}  ByteCLI cleanup complete.${NC}"
echo -e "${GREEN}${BOLD}========================================${NC}"
echo ""
