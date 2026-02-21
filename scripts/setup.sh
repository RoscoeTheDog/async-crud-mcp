#!/bin/bash
# ============================================
#   async-crud-mcp Setup
# ============================================
# Unified installer/uninstaller script
# Calls installer.py which presents an interactive menu
# Python script handles its own "Press Enter to close..." prompt

# Find Python
PYTHON_EXE=""
command -v python3 &>/dev/null && PYTHON_EXE="python3"
command -v python &>/dev/null && PYTHON_EXE="${PYTHON_EXE:-python}"

if [[ -z "$PYTHON_EXE" ]]; then
    echo "[ERROR] Python not found in PATH"
    echo "Please install Python 3.10+ first"
    read -rp "Press Enter to exit..."
    exit 1
fi

# Show Python version
PY_VERSION=$("$PYTHON_EXE" --version 2>&1)
echo "Found $PY_VERSION"

# Run Python installer (no args = interactive mode)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$PYTHON_EXE" "$SCRIPT_DIR/installer.py" "$@"
exit $?
