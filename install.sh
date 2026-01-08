#!/bin/bash

# Astropipes Installation Script
# This script sets up the virtual environment and installs all dependencies

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

# Required Python version
REQUIRED_PYTHON_VERSION="3.11"

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

# Check if Python 3.11 is available
check_python() {
    print_step "Checking Python version..."
    
    if command -v python3.11 &> /dev/null; then
        PYTHON_CMD="python3.11"
        PYTHON_VERSION=$(python3.11 --version | cut -d' ' -f2)
        print_message "Found Python $PYTHON_VERSION"
    elif command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
        if [ "$PYTHON_VERSION" == "$REQUIRED_PYTHON_VERSION" ]; then
            PYTHON_CMD="python3"
            print_message "Found Python $PYTHON_VERSION (using python3)"
        else
            print_error "Python $REQUIRED_PYTHON_VERSION is required, but found Python $PYTHON_VERSION"
            print_warning "Some dependencies (e.g., astroscrappy) may not be compatible with other versions"
            read -p "Continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
            PYTHON_CMD="python3"
        fi
    else
        print_error "Python 3 not found. Please install Python 3.11 or later."
        exit 1
    fi
}

# Check if venv module is available
check_venv_module() {
    print_step "Checking for venv module..."
    
    if $PYTHON_CMD -m venv --help &> /dev/null; then
        print_message "venv module is available"
    else
        print_error "venv module not found. Please install python3-venv package."
        print_message "On Debian/Ubuntu: sudo apt-get install python3-venv"
        print_message "On Arch: sudo pacman -S python3"
        exit 1
    fi
}

# Create virtual environment
create_venv() {
    print_step "Creating virtual environment..."
    
    VENV_PATH="$PROJECT_DIR/.venv"
    
    if [ -d "$VENV_PATH" ]; then
        print_warning "Virtual environment already exists at $VENV_PATH"
        read -p "Remove and recreate? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_message "Removing existing virtual environment..."
            rm -rf "$VENV_PATH"
        else
            print_message "Using existing virtual environment"
            return
        fi
    fi
    
    print_message "Creating virtual environment at $VENV_PATH..."
    $PYTHON_CMD -m venv "$VENV_PATH"
    print_message "Virtual environment created successfully"
}

# Upgrade pip
upgrade_pip() {
    print_step "Upgrading pip..."
    
    VENV_PIP="$PROJECT_DIR/.venv/bin/pip"
    
    if [ -f "$VENV_PIP" ]; then
        print_message "Upgrading pip..."
        "$VENV_PIP" install --upgrade pip setuptools wheel
        print_message "pip upgraded successfully"
    else
        print_error "pip not found in virtual environment"
        exit 1
    fi
}

# Install requirements
install_requirements() {
    print_step "Installing requirements..."
    
    VENV_PIP="$PROJECT_DIR/.venv/bin/pip"
    REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
    
    if [ ! -f "$REQUIREMENTS_FILE" ]; then
        print_error "requirements.txt not found at $REQUIREMENTS_FILE"
        exit 1
    fi
    
    print_message "Installing packages from requirements.txt..."
    print_message "This may take several minutes..."
    
    if "$VENV_PIP" install -r "$REQUIREMENTS_FILE"; then
        print_message "All requirements installed successfully"
    else
        print_error "Failed to install some requirements"
        print_warning "You may need to install system dependencies first"
        print_message "On Debian/Ubuntu, you may need:"
        print_message "  sudo apt-get install python3-dev python3-tk libffi-dev"
        exit 1
    fi
}

# Make scripts executable
make_scripts_executable() {
    print_step "Making scripts executable..."
    
    SCRIPTS=("astropipes" "astropipes.py" "autopipe.py" "platesolve.py")
    
    for script in "${SCRIPTS[@]}"; do
        SCRIPT_PATH="$PROJECT_DIR/$script"
        if [ -f "$SCRIPT_PATH" ]; then
            chmod +x "$SCRIPT_PATH"
            print_message "Made $script executable"
        fi
    done
}

# Update shebang in astropipes.py
update_shebang() {
    print_step "Updating shebang in astropipes.py..."
    
    PYTHON_VENV="$PROJECT_DIR/.venv/bin/python"
    ASTROPIPES_PY="$PROJECT_DIR/astropipes.py"
    
    if [ -f "$ASTROPIPES_PY" ]; then
        # Update the shebang line
        sed -i "1s|.*|#!$PYTHON_VENV|" "$ASTROPIPES_PY"
        print_message "Updated shebang in astropipes.py"
    fi
}

# Install desktop files to user applications directory
install_desktop_files() {
    print_step "Installing desktop files..."
    
    # Create user applications directory if it doesn't exist
    USER_APPS_DIR="$HOME/.local/share/applications"
    mkdir -p "$USER_APPS_DIR"
    
    DESKTOP_FILES=("astropipes-viewer.desktop" "astropipes-library.desktop")
    
    for desktop_file in "${DESKTOP_FILES[@]}"; do
        DESKTOP_SOURCE="$PROJECT_DIR/$desktop_file"
        DESKTOP_DEST="$USER_APPS_DIR/$desktop_file"
        
        if [ -f "$DESKTOP_SOURCE" ]; then
            # Copy desktop file to temporary location
            TEMP_DESKTOP=$(mktemp)
            cp "$DESKTOP_SOURCE" "$TEMP_DESKTOP"
            
            # Update paths in the copied desktop file
            sed -i "s|/home/tan/dev/astro-pipelines|$PROJECT_DIR|g" "$TEMP_DESKTOP"
            
            # Install to user applications directory
            cp "$TEMP_DESKTOP" "$DESKTOP_DEST"
            rm "$TEMP_DESKTOP"
            
            # Make sure desktop file has correct permissions
            chmod 644 "$DESKTOP_DEST"
            
            print_message "Installed $desktop_file to $USER_APPS_DIR"
        else
            print_warning "Desktop file not found: $desktop_file"
        fi
    done
    
    # Update desktop database (KDE Plasma will pick this up automatically)
    if command -v update-desktop-database &> /dev/null; then
        print_message "Updating desktop database..."
        update-desktop-database "$USER_APPS_DIR" 2>/dev/null || true
    else
        print_warning "update-desktop-database not found, but desktop files should still work"
        print_message "You may need to log out and log back in for KDE Plasma to see the new applications"
    fi
}

# Print installation summary
print_summary() {
    print_step "Installation Summary"
    
    echo ""
    print_message "Installation completed successfully!"
    echo ""
    echo "Virtual environment location: $PROJECT_DIR/.venv"
    echo ""
    echo "To activate the virtual environment, run:"
    echo "  source $PROJECT_DIR/.venv/bin/activate"
    echo ""
    echo "To use astropipes, you can:"
    echo "  1. Activate the venv and run: python astropipes.py --help"
    echo "  2. Use the wrapper script: ./astropipes --help"
    echo "  3. Launch from KDE Plasma app launcher:"
    echo "     - Astropipes Viewer"
    echo "     - Astropipes Library"
    echo ""
    print_warning "Don't forget to:"
    echo "  - Configure config.py with your paths (CALIBRATION_PATH, DATA_PATH, etc.)"
    echo "  - Install Astrometry.Net if you want to use platesolving features"
    echo ""
    print_message "Desktop files installed to: $HOME/.local/share/applications"
    echo "  If apps don't appear in the launcher, try:"
    echo "  - Refreshing the application menu (right-click on menu > Refresh)"
    echo "  - Logging out and logging back in"
    echo ""
}

# Main installation flow
main() {
    echo ""
    echo "=========================================="
    echo "  Astropipes Installation Script"
    echo "=========================================="
    echo ""
    
    check_python
    check_venv_module
    create_venv
    upgrade_pip
    install_requirements
    make_scripts_executable
    update_shebang
    install_desktop_files
    print_summary
}

# Run main function
main
