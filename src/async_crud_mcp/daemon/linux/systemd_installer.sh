#!/usr/bin/env bash
# Linux systemd user service installer for async-crud-mcp daemon
# Manages the daemon using systemctl --user

set -euo pipefail

APP_NAME="async-crud-mcp"
SERVICE_NAME="${APP_NAME}-daemon"
UNIT_NAME="${SERVICE_NAME}.service"

# XDG-compliant paths
XDG_DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
XDG_STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-${HOME}/.cache}"

SYSTEMD_USER_DIR="${XDG_CONFIG_HOME}/systemd/user"
UNIT_PATH="${SYSTEMD_USER_DIR}/${UNIT_NAME}"

DATA_DIR="${XDG_DATA_HOME}/${APP_NAME}"
CONFIG_DIR="${XDG_CONFIG_HOME}/${APP_NAME}"
STATE_DIR="${XDG_STATE_HOME}/${APP_NAME}"
CACHE_DIR="${XDG_CACHE_HOME}/${APP_NAME}"
LOGS_DIR="${STATE_DIR}/logs"

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
    mkdir -p "${SYSTEMD_USER_DIR}"
    mkdir -p "${DATA_DIR}"
    mkdir -p "${CONFIG_DIR}"
    mkdir -p "${STATE_DIR}"
    mkdir -p "${CACHE_DIR}"
    mkdir -p "${LOGS_DIR}"
}

# Generate the systemd unit file with resolved paths
generate_unit() {
    local bootstrap_path="$1"

    cat > "${UNIT_PATH}" <<EOF
[Unit]
Description=async-crud-mcp MCP Daemon
Documentation=https://github.com/yourusername/async-crud-mcp
After=network.target

[Service]
Type=simple
ExecStart=${bootstrap_path}
Restart=always
RestartSec=30

# Working directory
WorkingDirectory=${DATA_DIR}

# File descriptor limit
LimitNOFILE=1024

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only

# Read-write paths for application data
ReadWritePaths=${DATA_DIR}
ReadWritePaths=${CONFIG_DIR}
ReadWritePaths=${STATE_DIR}
ReadWritePaths=${CACHE_DIR}
ReadWritePaths=${LOGS_DIR}

# Private temp directory
PrivateTmp=true

# Environment
Environment="PATH=/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=default.target
EOF

    echo "Generated unit file at ${UNIT_PATH}"
}

# Check if loginctl linger is enabled (allows services to run without active session)
check_linger() {
    if command -v loginctl &>/dev/null; then
        if loginctl show-user "${USER}" | grep -q "Linger=yes"; then
            echo "Linger is enabled for user ${USER}"
            return 0
        else
            echo "WARNING: Linger is not enabled. Service may stop when you log out." >&2
            echo "To enable: sudo loginctl enable-linger ${USER}" >&2
            return 1
        fi
    fi
}

# Install the systemd user service
install() {
    echo "Installing ${SERVICE_NAME} systemd user service..."

    local bootstrap_path
    bootstrap_path="$(detect_bootstrap_path)"
    echo "Using bootstrap: ${bootstrap_path}"

    ensure_dirs
    generate_unit "${bootstrap_path}"

    # Reload systemd user daemon
    systemctl --user daemon-reload

    # Enable the service (start on boot)
    systemctl --user enable "${UNIT_NAME}"

    # Start the service
    systemctl --user start "${UNIT_NAME}"

    echo "Systemd user service installed and started successfully"

    # Check linger status
    check_linger || true
}

# Uninstall the systemd user service
uninstall() {
    echo "Uninstalling ${SERVICE_NAME} systemd user service..."

    # Stop the service if running
    if systemctl --user is-active "${UNIT_NAME}" &>/dev/null; then
        systemctl --user stop "${UNIT_NAME}"
        echo "Service stopped"
    fi

    # Disable the service
    if systemctl --user is-enabled "${UNIT_NAME}" &>/dev/null; then
        systemctl --user disable "${UNIT_NAME}"
        echo "Service disabled"
    fi

    # Remove the unit file
    if [[ -f "${UNIT_PATH}" ]]; then
        rm -f "${UNIT_PATH}"
        systemctl --user daemon-reload
        echo "Service unit removed successfully"
    else
        echo "Service unit not found at ${UNIT_PATH}"
    fi
}

# Get status of the service
status() {
    echo "=== Service Status ==="
    systemctl --user status "${UNIT_NAME}" --no-pager || true

    echo ""
    echo "=== Enabled Status ==="
    if systemctl --user is-enabled "${UNIT_NAME}" &>/dev/null; then
        echo "Service is enabled (will start on boot)"
    else
        echo "Service is disabled"
    fi

    echo ""
    echo "=== Active Status ==="
    if systemctl --user is-active "${UNIT_NAME}" &>/dev/null; then
        echo "Service is active (running)"
    else
        echo "Service is inactive"
    fi

    echo ""
    check_linger || true
}

# Start the service
start() {
    systemctl --user start "${UNIT_NAME}"
    echo "Service started"
}

# Stop the service
stop() {
    systemctl --user stop "${UNIT_NAME}"
    echo "Service stopped"
}

# Restart the service
restart() {
    systemctl --user restart "${UNIT_NAME}"
    echo "Service restarted"
}

# Show logs
logs() {
    journalctl --user -u "${UNIT_NAME}" -n 50 --no-pager
}

# Follow logs
logs_follow() {
    journalctl --user -u "${UNIT_NAME}" -f
}

# Enable linger for the user
enable_linger() {
    if command -v loginctl &>/dev/null; then
        echo "Enabling linger for user ${USER}..."
        sudo loginctl enable-linger "${USER}"
        echo "Linger enabled. Service will persist after logout."
    else
        echo "ERROR: loginctl command not found" >&2
        exit 1
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
    restart)
        restart
        ;;
    logs)
        logs
        ;;
    logs-follow)
        logs_follow
        ;;
    enable-linger)
        enable_linger
        ;;
    *)
        echo "Usage: $0 {install|uninstall|status|start|stop|restart|logs|logs-follow|enable-linger}"
        exit 1
        ;;
esac
