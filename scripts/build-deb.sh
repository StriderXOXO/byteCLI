#!/bin/bash
#
# ByteCLI .deb Package Builder
# Builds a .deb package using dpkg-deb.
#
# Usage: ./scripts/build-deb.sh
# Output: bytecli_1.0.0_amd64.deb in the project root
#

set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# --- Resolve project directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

VERSION="1.0.0"
PACKAGE_NAME="bytecli"
DEB_NAME="${PACKAGE_NAME}_${VERSION}_amd64.deb"
STAGING="${PROJECT_DIR}/staging"

# ----------------------------------------------------------------
# 1. Clean previous build
# ----------------------------------------------------------------
info "Cleaning previous staging directory..."
rm -rf "${STAGING}"
mkdir -p "${STAGING}"

# ----------------------------------------------------------------
# 2. Install Python package into staging prefix
# ----------------------------------------------------------------
info "Installing Python package into staging prefix..."
pip3 install --prefix="${STAGING}/usr" --no-deps --no-warn-script-location "${PROJECT_DIR}" 2>&1 | tail -1

# Find the site-packages directory that was created
SITE_PACKAGES=$(find "${STAGING}/usr/lib" -type d -name "site-packages" 2>/dev/null | head -1)
if [ -z "${SITE_PACKAGES}" ]; then
    # Try dist-packages (Debian/Ubuntu convention)
    SITE_PACKAGES=$(find "${STAGING}/usr/lib" -type d -name "dist-packages" 2>/dev/null | head -1)
fi

if [ -z "${SITE_PACKAGES}" ]; then
    error "Could not find installed Python package in staging directory"
fi

# Move to dist-packages (Debian convention)
DIST_PACKAGES="${STAGING}/usr/lib/python3/dist-packages"
if [ "${SITE_PACKAGES}" != "${DIST_PACKAGES}" ]; then
    mkdir -p "${DIST_PACKAGES}"
    cp -r "${SITE_PACKAGES}/${PACKAGE_NAME}" "${DIST_PACKAGES}/"
    cp -r "${SITE_PACKAGES}/${PACKAGE_NAME}"*.dist-info "${DIST_PACKAGES}/" 2>/dev/null || true
    # Clean up the pip-created tree
    rm -rf "${STAGING}/usr/lib/python3."*
fi
success "Python package installed to ${DIST_PACKAGES}"

# ----------------------------------------------------------------
# 3. Create wrapper scripts in /usr/bin
# ----------------------------------------------------------------
info "Creating wrapper scripts..."
mkdir -p "${STAGING}/usr/bin"

cat > "${STAGING}/usr/bin/bytecli-service" << 'WRAPPER'
#!/usr/bin/env python3
from bytecli.service.main import main
main()
WRAPPER

cat > "${STAGING}/usr/bin/bytecli-indicator" << 'WRAPPER'
#!/usr/bin/env python3
from bytecli.indicator.main import main
main()
WRAPPER

cat > "${STAGING}/usr/bin/bytecli-settings" << 'WRAPPER'
#!/usr/bin/env python3
from bytecli.settings.main import main
main()
WRAPPER

chmod 755 "${STAGING}/usr/bin/bytecli-service"
chmod 755 "${STAGING}/usr/bin/bytecli-indicator"
chmod 755 "${STAGING}/usr/bin/bytecli-settings"
success "Wrapper scripts created"

# ----------------------------------------------------------------
# 4. Install systemd user service
# ----------------------------------------------------------------
info "Installing systemd service file..."
mkdir -p "${STAGING}/lib/systemd/user"

# Generate a .deb-specific service file with /usr/bin paths
cat > "${STAGING}/lib/systemd/user/bytecli.service" << 'SERVICE'
[Unit]
Description=ByteCLI Voice Dictation Service
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/bytecli-service
Environment=DISPLAY=:0
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus
Restart=on-failure
RestartSec=5
StartLimitBurst=3
StartLimitIntervalSec=60

[Install]
WantedBy=default.target
SERVICE
success "Systemd service file installed"

# ----------------------------------------------------------------
# 5. Install desktop entries
# ----------------------------------------------------------------
info "Installing desktop entries..."

# Settings application entry
mkdir -p "${STAGING}/usr/share/applications"
cp "${PROJECT_DIR}/desktop/bytecli-settings.desktop" \
   "${STAGING}/usr/share/applications/bytecli-settings.desktop"

# Autostart entry
mkdir -p "${STAGING}/etc/xdg/autostart"
cat > "${STAGING}/etc/xdg/autostart/bytecli.desktop" << 'DESKTOP'
[Desktop Entry]
Type=Application
Name=ByteCLI Service
Comment=ByteCLI Voice Dictation Background Service
Exec=/usr/bin/bytecli-service
Terminal=false
Hidden=true
NoDisplay=true
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Phase=Applications
Categories=Utility;Accessibility;
DESKTOP
success "Desktop entries installed"

# ----------------------------------------------------------------
# 6. Generate DEBIAN control files
# ----------------------------------------------------------------
info "Generating DEBIAN control files..."
mkdir -p "${STAGING}/DEBIAN"

cp "${PROJECT_DIR}/debian/control" "${STAGING}/DEBIAN/control"
cp "${PROJECT_DIR}/debian/postinst" "${STAGING}/DEBIAN/postinst"
cp "${PROJECT_DIR}/debian/prerm" "${STAGING}/DEBIAN/prerm"

chmod 755 "${STAGING}/DEBIAN/postinst"
chmod 755 "${STAGING}/DEBIAN/prerm"
success "DEBIAN control files ready"

# ----------------------------------------------------------------
# 7. Fix permissions
# ----------------------------------------------------------------
info "Fixing file permissions..."
find "${STAGING}" -type d -exec chmod 755 {} \;
find "${STAGING}/usr/lib" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "${STAGING}/usr/share" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "${STAGING}/etc" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "${STAGING}/lib" -type f -exec chmod 644 {} \; 2>/dev/null || true
success "Permissions fixed"

# ----------------------------------------------------------------
# 8. Build the .deb package
# ----------------------------------------------------------------
info "Building .deb package..."
dpkg-deb --build "${STAGING}" "${PROJECT_DIR}/${DEB_NAME}"

echo ""
echo -e "${GREEN}${BOLD}========================================${NC}"
echo -e "${GREEN}${BOLD}  .deb package built successfully!${NC}"
echo -e "${GREEN}${BOLD}========================================${NC}"
echo ""
echo -e "Output: ${BOLD}${PROJECT_DIR}/${DEB_NAME}${NC}"
echo -e "Install: ${BOLD}sudo apt install ./${DEB_NAME}${NC}"
echo ""

# Clean up staging
rm -rf "${STAGING}"
success "Staging directory cleaned up"
