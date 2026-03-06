#!/bin/bash
#
# ByteCLI .deb Installer
#
# Installs the .deb package on any Ubuntu/Debian-based system.
# All dependencies (GTK3, Python3, etc.) are available from the
# default system repositories -- no PPA needed.
#
# Usage:
#   ./scripts/install-deb.sh bytecli_1.2.0_amd64.deb
#   ./scripts/install-deb.sh  # auto-detects .deb in current directory
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# --- Resolve .deb path ---
if [ $# -ge 1 ]; then
    DEB_PATH="$1"
else
    DEB_PATH=$(ls "$(dirname "$0")/../"bytecli_*.deb 2>/dev/null | sort -V | tail -1 || true)
    if [ -z "$DEB_PATH" ]; then
        DEB_PATH=$(ls ./bytecli_*.deb 2>/dev/null | sort -V | tail -1 || true)
    fi
fi

if [ -z "$DEB_PATH" ] || [ ! -f "$DEB_PATH" ]; then
    error "No .deb file found. Run ./scripts/build-deb.sh first, or pass the path as an argument."
fi

info "Installing: ${BOLD}${DEB_PATH}${NC}"
echo ""

# ----------------------------------------------------------------
# Install the .deb (apt handles dependencies from default repos)
# ----------------------------------------------------------------
info "Installing ByteCLI .deb package..."
sudo apt-get install -y "$DEB_PATH"

echo ""
echo -e "${GREEN}${BOLD}========================================${NC}"
echo -e "${GREEN}${BOLD}  ByteCLI installed successfully!${NC}"
echo -e "${GREEN}${BOLD}========================================${NC}"
echo ""
echo -e "  ${CYAN}*${NC} Press ${BOLD}Ctrl+Alt+V${NC} to start dictating."
echo -e "  ${CYAN}*${NC} Open ${BOLD}ByteCLI Settings${NC} from your application menu."
echo -e "  ${CYAN}*${NC} Service status: ${BOLD}systemctl --user status bytecli${NC}"
echo ""
