#!/bin/sh
# scratch-sync installer
# Usage: curl -LsSf https://raw.githubusercontent.com/talmo/scratch-sync/main/install.sh | sh
#
# Options (via environment variables):
#   INSTALL_DIR    - Where to install binaries (default: ~/.local/bin)
#   NO_SERVICE     - Set to 1 to skip service setup
#   UNINSTALL      - Set to 1 to uninstall
#   UPGRADE        - Set to 1 to check for and install latest version

set -e

# Configuration
SYNCTHING_VERSION="${SYNCTHING_VERSION:-2.0.12}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
CONFIG_DIR=""  # Set per-OS below

# Colors (disable if not a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

info() {
    printf "${BLUE}info${NC}: %s\n" "$1"
}

success() {
    printf "${GREEN}done${NC}: %s\n" "$1"
}

warn() {
    printf "${YELLOW}warn${NC}: %s\n" "$1"
}

error() {
    printf "${RED}error${NC}: %s\n" "$1" >&2
    exit 1
}

# Detect OS and architecture
detect_platform() {
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)

    case "$OS" in
        darwin)
            OS="macos"
            CONFIG_DIR="$HOME/Library/Application Support/Syncthing"
            ;;
        linux)
            OS="linux"
            CONFIG_DIR="$HOME/.config/syncthing"
            ;;
        mingw*|msys*|cygwin*)
            OS="windows"
            CONFIG_DIR="$LOCALAPPDATA/Syncthing"
            ;;
        *)
            error "Unsupported operating system: $OS"
            ;;
    esac

    case "$ARCH" in
        x86_64|amd64)
            ARCH="amd64"
            ;;
        arm64|aarch64)
            ARCH="arm64"
            ;;
        armv7l|armv6l)
            ARCH="arm"
            ;;
        *)
            error "Unsupported architecture: $ARCH"
            ;;
    esac

    PLATFORM="${OS}-${ARCH}"
    info "Detected platform: $PLATFORM"
}

# Check for required commands
check_requirements() {
    for cmd in curl tar unzip; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            error "Required command not found: $cmd"
        fi
    done
}

# Check if syncthing is already installed
check_existing() {
    if command -v syncthing >/dev/null 2>&1; then
        EXISTING=$(command -v syncthing)
        EXISTING_VERSION=$(syncthing --version 2>/dev/null | head -1 | awk '{print $2}' || echo "unknown")
        warn "Syncthing already installed at: $EXISTING (version: $EXISTING_VERSION)"

        # Check if it's running
        if pgrep -x syncthing >/dev/null 2>&1; then
            warn "Syncthing is currently running"
        fi

        printf "Continue with installation? [y/N] "
        read -r REPLY
        case "$REPLY" in
            [yY]|[yY][eE][sS])
                ;;
            *)
                info "Installation cancelled"
                exit 0
                ;;
        esac
    fi
}

# Download and install syncthing
install_syncthing() {
    info "Installing Syncthing v${SYNCTHING_VERSION}..."

    # Create install directory
    mkdir -p "$INSTALL_DIR"

    # Determine archive extension and platform name
    case "$OS" in
        macos)
            # macOS uses universal binary in zip format
            ARCHIVE_EXT="zip"
            DOWNLOAD_PLATFORM="macos-universal"
            ;;
        *)
            ARCHIVE_EXT="tar.gz"
            DOWNLOAD_PLATFORM="$PLATFORM"
            ;;
    esac

    # Build download URL
    DOWNLOAD_URL="https://github.com/syncthing/syncthing/releases/download/v${SYNCTHING_VERSION}/syncthing-${DOWNLOAD_PLATFORM}-v${SYNCTHING_VERSION}.${ARCHIVE_EXT}"

    info "Downloading from: $DOWNLOAD_URL"

    # Create temp directory
    TMP_DIR=$(mktemp -d)
    trap "rm -rf '$TMP_DIR'" EXIT

    # Download
    if ! curl -fsSL "$DOWNLOAD_URL" -o "$TMP_DIR/syncthing.${ARCHIVE_EXT}"; then
        error "Failed to download Syncthing. Check the version number and your internet connection."
    fi

    # Extract based on archive type
    case "$ARCHIVE_EXT" in
        zip)
            unzip -q "$TMP_DIR/syncthing.zip" -d "$TMP_DIR"
            ;;
        tar.gz)
            tar -xzf "$TMP_DIR/syncthing.tar.gz" -C "$TMP_DIR"
            ;;
    esac

    # Find the binary (it's in a subdirectory)
    BINARY=$(find "$TMP_DIR" -name "syncthing" -type f -perm +111 2>/dev/null | head -1)
    if [ -z "$BINARY" ]; then
        # Try without permission check (for compatibility)
        BINARY=$(find "$TMP_DIR" -name "syncthing" -type f | head -1)
    fi

    if [ -z "$BINARY" ]; then
        error "Could not find syncthing binary in downloaded archive"
    fi

    # Install binary
    chmod +x "$BINARY"
    mv "$BINARY" "$INSTALL_DIR/syncthing"

    success "Installed syncthing to $INSTALL_DIR/syncthing"

    # Verify installation
    if "$INSTALL_DIR/syncthing" --version >/dev/null 2>&1; then
        VERSION=$("$INSTALL_DIR/syncthing" --version | head -1)
        success "Verified: $VERSION"
    else
        warn "Could not verify installation"
    fi
}

# Add install dir to PATH if needed
setup_path() {
    # Check if already in PATH
    case ":$PATH:" in
        *":$INSTALL_DIR:"*)
            return
            ;;
    esac

    warn "$INSTALL_DIR is not in your PATH"

    # Detect shell and suggest addition
    SHELL_NAME=$(basename "$SHELL")
    case "$SHELL_NAME" in
        bash)
            RC_FILE="$HOME/.bashrc"
            ;;
        zsh)
            RC_FILE="$HOME/.zshrc"
            ;;
        fish)
            RC_FILE="$HOME/.config/fish/config.fish"
            ;;
        *)
            RC_FILE=""
            ;;
    esac

    if [ -n "$RC_FILE" ]; then
        info "Add this to $RC_FILE:"
        echo ""
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
    fi
}

# Setup auto-start service (macOS)
setup_service_macos() {
    if [ "${NO_SERVICE:-0}" = "1" ]; then
        info "Skipping service setup (NO_SERVICE=1)"
        return
    fi

    PLIST_DIR="$HOME/Library/LaunchAgents"
    PLIST_FILE="$PLIST_DIR/com.syncthing.syncthing.plist"

    mkdir -p "$PLIST_DIR"

    # Check if already exists
    if [ -f "$PLIST_FILE" ]; then
        warn "LaunchAgent already exists at $PLIST_FILE"
        printf "Overwrite? [y/N] "
        read -r REPLY
        case "$REPLY" in
            [yY]|[yY][eE][sS])
                launchctl unload "$PLIST_FILE" 2>/dev/null || true
                ;;
            *)
                return
                ;;
        esac
    fi

    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.syncthing.syncthing</string>
    <key>ProgramArguments</key>
    <array>
        <string>${INSTALL_DIR}/syncthing</string>
        <string>--no-browser</string>
        <string>--no-restart</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>Crashed</key>
        <true/>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/syncthing.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/syncthing.log</string>
</dict>
</plist>
EOF

    # Load the service
    launchctl load "$PLIST_FILE"

    success "Created LaunchAgent at $PLIST_FILE"
    info "Syncthing will start automatically on login"
    info "Logs: ~/Library/Logs/syncthing.log"
}

# Setup auto-start service (Linux)
setup_service_linux() {
    if [ "${NO_SERVICE:-0}" = "1" ]; then
        info "Skipping service setup (NO_SERVICE=1)"
        return
    fi

    # Check for systemd
    if ! command -v systemctl >/dev/null 2>&1; then
        warn "systemd not found, skipping service setup"
        return
    fi

    SERVICE_DIR="$HOME/.config/systemd/user"
    SERVICE_FILE="$SERVICE_DIR/syncthing.service"

    mkdir -p "$SERVICE_DIR"

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Syncthing - Open Source Continuous File Synchronization
Documentation=man:syncthing(1)
After=network.target

[Service]
ExecStart=${INSTALL_DIR}/syncthing --no-browser --no-restart
Restart=on-failure
RestartSec=10
SuccessExitStatus=3 4

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable syncthing.service
    systemctl --user start syncthing.service

    success "Created systemd user service"
    info "Check status: systemctl --user status syncthing"
}

# Setup service based on OS
setup_service() {
    case "$OS" in
        macos)
            setup_service_macos
            ;;
        linux)
            setup_service_linux
            ;;
        windows)
            warn "Windows service setup not implemented. Please set up Task Scheduler manually."
            ;;
    esac
}

# Get latest Syncthing version from GitHub
get_latest_version() {
    LATEST=$(curl -fsSL "https://api.github.com/repos/syncthing/syncthing/releases/latest" | \
        grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')
    echo "$LATEST"
}

# Upgrade syncthing to latest version
upgrade() {
    info "Checking for updates..."

    detect_platform

    LATEST_VERSION=$(get_latest_version)
    if [ -z "$LATEST_VERSION" ]; then
        error "Could not determine latest version"
    fi

    CURRENT_VERSION=""
    if [ -f "$INSTALL_DIR/syncthing" ]; then
        CURRENT_VERSION=$("$INSTALL_DIR/syncthing" version 2>/dev/null | head -1 | awk '{print $2}' | sed 's/^v//')
    fi

    if [ "$CURRENT_VERSION" = "$LATEST_VERSION" ]; then
        success "Already at latest version: v$CURRENT_VERSION"
        exit 0
    fi

    if [ -n "$CURRENT_VERSION" ]; then
        info "Current version: v$CURRENT_VERSION"
    fi
    info "Latest version: v$LATEST_VERSION"

    # Update version and reinstall
    SYNCTHING_VERSION="$LATEST_VERSION"
    install_syncthing

    success "Upgraded to v$LATEST_VERSION"
}

# Uninstall syncthing
uninstall() {
    info "Uninstalling scratch-sync/syncthing..."

    detect_platform

    # Stop service
    case "$OS" in
        macos)
            PLIST_FILE="$HOME/Library/LaunchAgents/com.syncthing.syncthing.plist"
            if [ -f "$PLIST_FILE" ]; then
                launchctl unload "$PLIST_FILE" 2>/dev/null || true
                rm -f "$PLIST_FILE"
                success "Removed LaunchAgent"
            fi
            ;;
        linux)
            if command -v systemctl >/dev/null 2>&1; then
                systemctl --user stop syncthing.service 2>/dev/null || true
                systemctl --user disable syncthing.service 2>/dev/null || true
                rm -f "$HOME/.config/systemd/user/syncthing.service"
                systemctl --user daemon-reload 2>/dev/null || true
                success "Removed systemd service"
            fi
            ;;
    esac

    # Kill any running process
    pkill -x syncthing 2>/dev/null || true

    # Remove binary
    if [ -f "$INSTALL_DIR/syncthing" ]; then
        rm -f "$INSTALL_DIR/syncthing"
        success "Removed $INSTALL_DIR/syncthing"
    fi

    # Ask about config
    if [ -d "$CONFIG_DIR" ]; then
        warn "Config directory exists: $CONFIG_DIR"
        printf "Remove config and data? This cannot be undone! [y/N] "
        read -r REPLY
        case "$REPLY" in
            [yY]|[yY][eE][sS])
                rm -rf "$CONFIG_DIR"
                success "Removed config directory"
                ;;
            *)
                info "Config preserved at: $CONFIG_DIR"
                ;;
        esac
    fi

    success "Uninstall complete"
}

# Print post-install instructions
print_instructions() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    success "scratch-sync installation complete!"
    echo ""
    echo "  Syncthing binary: $INSTALL_DIR/syncthing"
    echo "  Config directory: $CONFIG_DIR"
    echo "  Web UI: http://127.0.0.1:8384"
    echo ""
    echo "  Get your device ID:"
    echo "    syncthing device-id"
    echo ""
    echo "  Use the CLI (requires uv or pip):"
    echo "    uvx scratch-sync init     # Initialize in a git repo"
    echo "    uvx scratch-sync pair     # Discover and pair devices"
    echo "    uvx scratch-sync status   # Show sync status"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Main
main() {
    echo ""
    echo "scratch-sync installer"
    echo ""

    # Handle uninstall
    if [ "${UNINSTALL:-0}" = "1" ]; then
        uninstall
        exit 0
    fi

    # Handle upgrade
    if [ "${UPGRADE:-0}" = "1" ]; then
        check_requirements
        upgrade
        exit 0
    fi

    check_requirements
    detect_platform
    check_existing
    install_syncthing
    setup_path
    setup_service
    print_instructions
}

main "$@"
