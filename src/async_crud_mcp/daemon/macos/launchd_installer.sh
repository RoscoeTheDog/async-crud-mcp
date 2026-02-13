#!/usr/bin/env bash
# macOS LaunchAgent installer for async-crud-mcp daemon
# Manages the daemon using launchctl (user-level LaunchAgent)

set -euo pipefail

APP_NAME="async-crud-mcp"
SERVICE_NAME="${APP_NAME}-daemon"
PLIST_LABEL="com.${APP_NAME}.daemon"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${LAUNCH_AGENTS_DIR}/${PLIST_LABEL}.plist"

# Detect bootstrap path (async-crud-mcp entry point)
detect_bootstrap_path() {
    local bootstrap_path=""

    # Try which first
    if command -v async-crud-mcp &>/dev/null; then
        bootstrap_path="$(command -v async-crud-mcp)"
    # Try common venv locations
    elif [[ -f "${HOME}/.local/bin/async-crud-mcp" ]]; then
        bootstrap_path="${HOME}/.local/bin/async-crud-mcp"
    elif [[ -f ".venv/bin/async-crud-mcp" ]]; then
        bootstrap_path="$(pwd)/.venv/bin/async-crud-mcp"
    fi

    if [[ -z "$bootstrap_path" ]]; then
        echo "ERROR: Cannot find async-crud-mcp executable" >&2
        echo "Please ensure async-crud-mcp is installed (pip install async-crud-mcp)" >&2
        exit 1
    fi

    echo "$bootstrap_path"
}

# Ensure required directories exist
ensure_dirs() {
    mkdir -p "${LAUNCH_AGENTS_DIR}"
    mkdir -p "${HOME}/Library/Application Support/${APP_NAME}"
    mkdir -p "${HOME}/Library/Logs/${APP_NAME}"
}

# Generate the plist file with resolved paths
generate_plist() {
    local bootstrap_path="$1"
    local working_dir="${HOME}/Library/Application Support/${APP_NAME}"
    local stdout_log="${HOME}/Library/Logs/${APP_NAME}/stdout.log"
    local stderr_log="${HOME}/Library/Logs/${APP_NAME}/stderr.log"

    cat > "${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${bootstrap_path}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>WorkingDirectory</key>
    <string>${working_dir}</string>

    <key>StandardOutPath</key>
    <string>${stdout_log}</string>

    <key>StandardErrorPath</key>
    <string>${stderr_log}</string>

    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>ProcessType</key>
    <string>Background</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF

    echo "Generated plist at ${PLIST_PATH}"
}

# Install the LaunchAgent
install() {
    echo "Installing ${SERVICE_NAME} LaunchAgent..."

    local bootstrap_path
    bootstrap_path="$(detect_bootstrap_path)"
    echo "Using bootstrap: ${bootstrap_path}"

    ensure_dirs
    generate_plist "${bootstrap_path}"

    # Load the plist
    launchctl load "${PLIST_PATH}"

    echo "LaunchAgent installed and loaded successfully"
    echo "Service will start automatically on login"
}

# Uninstall the LaunchAgent
uninstall() {
    echo "Uninstalling ${SERVICE_NAME} LaunchAgent..."

    if [[ -f "${PLIST_PATH}" ]]; then
        # Unload if currently loaded
        if launchctl list | grep -q "${PLIST_LABEL}"; then
            launchctl unload "${PLIST_PATH}"
            echo "LaunchAgent unloaded"
        fi

        rm -f "${PLIST_PATH}"
        echo "LaunchAgent removed successfully"
    else
        echo "LaunchAgent not found at ${PLIST_PATH}"
        exit 1
    fi
}

# Get status of the LaunchAgent
status() {
    if launchctl list | grep -q "${PLIST_LABEL}"; then
        echo "RUNNING"
        launchctl list | grep "${PLIST_LABEL}"
    else
        echo "STOPPED"
    fi
}

# Start the service
start() {
    if [[ -f "${PLIST_PATH}" ]]; then
        launchctl load "${PLIST_PATH}"
        echo "LaunchAgent started"
    else
        echo "ERROR: LaunchAgent not installed. Run 'install' first." >&2
        exit 1
    fi
}

# Stop the service
stop() {
    if [[ -f "${PLIST_PATH}" ]]; then
        launchctl unload "${PLIST_PATH}"
        echo "LaunchAgent stopped"
    else
        echo "ERROR: LaunchAgent not installed" >&2
        exit 1
    fi
}

# Show logs
logs() {
    local stderr_log="${HOME}/Library/Logs/${APP_NAME}/stderr.log"
    local stdout_log="${HOME}/Library/Logs/${APP_NAME}/stdout.log"

    if [[ -f "${stderr_log}" ]]; then
        echo "=== Error Log (last 20 lines) ==="
        tail -n 20 "${stderr_log}"
    fi

    if [[ -f "${stdout_log}" ]]; then
        echo "=== Output Log (last 20 lines) ==="
        tail -n 20 "${stdout_log}"
    fi
}

# Main command dispatcher
case "${1:-}" in
    install)
        install
        ;;
    uninstall)
        uninstall
        ;;
    status)
        status
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    logs)
        logs
        ;;
    *)
        echo "Usage: $0 {install|uninstall|status|start|stop|logs}"
        exit 1
        ;;
esac
