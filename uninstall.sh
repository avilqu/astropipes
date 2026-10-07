#!/bin/bash

# Astropipes Uninstallation Script
# Undoes everything install.sh did outside the repository (command links, desktop files,
# systemd user service), then deletes the virtual environment and build artifacts,
# leaving only the original repository.
#
# Your settings, library database and image folders are not touched.

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR"
VENV_PATH="$PROJECT_DIR/.venv"

# Print colored message
print_message() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_step() {
    echo -e "\n${BLUE}==>${NC} $1"
}

# Stop, disable and remove the systemd user unit
remove_systemd_unit() {
    print_step "Removing systemd user service..."

    UNIT_NAME="astropipes-watch.service"
    USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    UNIT_FILE="$USER_UNIT_DIR/$UNIT_NAME"

    if command -v systemctl &> /dev/null; then
        if systemctl --user is-active --quiet "$UNIT_NAME" 2>/dev/null; then
            print_message "Stopping $UNIT_NAME (the current job may take up to 2 minutes to stop)..."
            systemctl --user stop "$UNIT_NAME" || print_warning "Could not stop $UNIT_NAME"
        fi
        if systemctl --user is-enabled --quiet "$UNIT_NAME" 2>/dev/null; then
            print_message "Disabling $UNIT_NAME..."
            systemctl --user disable "$UNIT_NAME" || print_warning "Could not disable $UNIT_NAME"
        fi
    fi

    if [ -f "$UNIT_FILE" ]; then
        rm -f "$UNIT_FILE"
        print_message "Removed $UNIT_FILE"
    else
        print_message "$UNIT_NAME not installed, skipping"
    fi

    if command -v systemctl &> /dev/null; then
        systemctl --user daemon-reload 2>/dev/null || print_warning "Could not reload the systemd user manager; run: systemctl --user daemon-reload"
        systemctl --user reset-failed "$UNIT_NAME" 2>/dev/null || true
    fi
}

# Remove the desktop files from the user applications directory
remove_desktop_files() {
    print_step "Removing desktop files..."

    USER_APPS_DIR="$HOME/.local/share/applications"
    DESKTOP_FILES=("astropipes-viewer.desktop" "astropipes-library.desktop")

    for desktop_file in "${DESKTOP_FILES[@]}"; do
        DESKTOP_DEST="$USER_APPS_DIR/$desktop_file"
        if [ -f "$DESKTOP_DEST" ]; then
            rm -f "$DESKTOP_DEST"
            print_message "Removed $DESKTOP_DEST"
        else
            print_message "$desktop_file not installed, skipping"
        fi
    done

    if command -v update-desktop-database &> /dev/null && [ -d "$USER_APPS_DIR" ]; then
        print_message "Updating desktop database..."
        update-desktop-database "$USER_APPS_DIR" 2>/dev/null || true
    fi
}

# Remove the command links from ~/bin and ~/.local/bin (only links pointing into this venv)
remove_command_links() {
    print_step "Removing command links..."

    for bin_dir in "$HOME/bin" "$HOME/.local/bin"; do
        for cmd in astropipes astropipes-viewer; do
            LINK="$bin_dir/$cmd"
            if [ -L "$LINK" ]; then
                if [ "$(readlink "$LINK")" == "$VENV_PATH/bin/$cmd" ]; then
                    rm -f "$LINK"
                    print_message "Removed $LINK"
                else
                    print_warning "$LINK points to $(readlink "$LINK"), not this install; leaving it"
                fi
            fi
        done
    done
}

# Delete the virtual environment and the files generated inside the repository
remove_venv_and_artifacts() {
    print_step "Removing virtual environment and build artifacts..."

    if [ -d "$VENV_PATH" ]; then
        rm -rf "$VENV_PATH"
        print_message "Removed $VENV_PATH"
    else
        print_message "No virtual environment at $VENV_PATH, skipping"
    fi

    # Left by the editable install (pip install -e)
    for artifact in "$PROJECT_DIR"/*.egg-info "$PROJECT_DIR/build"; do
        if [ -e "$artifact" ]; then
            rm -rf "$artifact"
            print_message "Removed $artifact"
        fi
    done

    # Python bytecode caches (skipping .git and .claude)
    find "$PROJECT_DIR" \( -path "$PROJECT_DIR/.git" -o -path "$PROJECT_DIR/.claude" \) -prune \
        -o -type d -name __pycache__ -prune -exec rm -rf {} +
    print_message "Removed __pycache__ folders"
}

# Print uninstallation summary
print_summary() {
    print_step "Uninstallation Summary"

    echo ""
    print_message "Uninstallation completed successfully!"
    echo ""
    echo "The repository is still at $PROJECT_DIR; run ./install.sh to reinstall."
    echo ""
    print_warning "Not removed (your data):"
    echo "  - Settings file: ${ASTROPIPES_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/astropipes/config.toml}"
    echo "  - Library database, image folders and processed files (DATA_PATH, STACKS_PATH,"
    echo "    PROCESSED_PATH, ... as set in your settings; by default under ~/Astro and ~/.cache/astropipes)"
    echo ""
    echo "If you ran 'loginctl enable-linger \$USER' only for the watch service, you can undo it with:"
    echo "  loginctl disable-linger \$USER"
    echo ""
}

# Main uninstallation flow
main() {
    echo ""
    echo "=========================================="
    echo "  Astropipes Uninstallation Script"
    echo "=========================================="
    echo ""

    echo "This will remove the astropipes commands, desktop files and systemd service,"
    echo "and delete $VENV_PATH. Your settings and data are kept."
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi

    remove_systemd_unit
    remove_desktop_files
    remove_command_links
    remove_venv_and_artifacts
    print_summary
}

# Run main function
main
