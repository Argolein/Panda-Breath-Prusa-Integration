#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_INSTALL_DIR="$SCRIPT_DIR"
DEFAULT_SERVICE_NAME="panda-prusa-bridge"
DEFAULT_PRUSA_URL=""
BRIDGE_LISTEN_HOST="0.0.0.0"
BRIDGE_LISTEN_PORT="7126"
PRUSA_STATUS_PATH="/api/v1/status"
REQUEST_TIMEOUT="3.0"
CACHE_TTL="2.0"
FALLBACK_TARGET="0.0"
FALLBACK_CURRENT="0.0"
LOG_LEVEL="INFO"
PRUSA_AUTH_TYPE="digest"

say() {
  printf '%s\n' "$*"
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

prompt() {
  local label="$1"
  local default_value="$2"
  local reply

  if [[ -n "$default_value" ]]; then
    read -r -p "$label [$default_value]: " reply
    printf '%s' "${reply:-$default_value}"
  else
    read -r -p "$label: " reply
    printf '%s' "$reply"
  fi
}

prompt_secret() {
  local label="$1"
  local reply
  read -r -s -p "$label: " reply
  printf '\n' >&2
  printf '%s' "$reply"
}

ensure_python3() {
  if command -v python3 >/dev/null 2>&1; then
    return
  fi

  say "python3 not found. Trying to install it."

  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm python
  elif command -v apk >/dev/null 2>&1; then
    sudo apk add python3
  else
    fail "Could not install python3 automatically. Please install it and rerun this script."
  fi
}

ensure_systemd() {
  command -v systemctl >/dev/null 2>&1 || fail "systemctl is required."
  command -v sudo >/dev/null 2>&1 || fail "sudo is required."
}

copy_project_files() {
  local source_dir="$1"
  local install_dir="$2"

  if [[ "$source_dir" == "$install_dir" ]]; then
    return
  fi

  sudo mkdir -p "$install_dir"
  sudo cp "$source_dir/app.py" "$install_dir/app.py"
  sudo cp "$source_dir/README.md" "$install_dir/README.md"
  sudo cp "$source_dir/LICENSE" "$install_dir/LICENSE"
  sudo rm -rf "$install_dir/panda_prusa_bridge"
  sudo cp -R "$source_dir/panda_prusa_bridge" "$install_dir/panda_prusa_bridge"
}

write_config() {
  local target_path="$1"
  export INSTALL_LISTEN_HOST="$LISTEN_HOST"
  export INSTALL_LISTEN_PORT="$LISTEN_PORT"
  export INSTALL_PRUSA_HOST="$PRUSA_HOST"
  export INSTALL_PRUSA_STATUS_PATH="$PRUSA_STATUS_PATH"
  export INSTALL_PRUSA_AUTH_TYPE="$PRUSA_AUTH_TYPE"
  export INSTALL_PRUSA_USERNAME="$PRUSA_USERNAME"
  export INSTALL_PRUSA_PASSWORD="$PRUSA_PASSWORD"
  export INSTALL_REQUEST_TIMEOUT="$REQUEST_TIMEOUT"
  export INSTALL_CACHE_TTL="$CACHE_TTL"
  export INSTALL_FALLBACK_TARGET="$FALLBACK_TARGET"
  export INSTALL_FALLBACK_CURRENT="$FALLBACK_CURRENT"
  export INSTALL_LOG_LEVEL="$LOG_LEVEL"

  python3 - <<'PY' | sudo tee "$target_path" >/dev/null
import json
import os

config = {
    "listen_host": os.environ["INSTALL_LISTEN_HOST"],
    "listen_port": int(os.environ["INSTALL_LISTEN_PORT"]),
    "prusa_host": os.environ["INSTALL_PRUSA_HOST"],
    "prusa_status_path": os.environ["INSTALL_PRUSA_STATUS_PATH"],
    "prusa_auth_type": os.environ["INSTALL_PRUSA_AUTH_TYPE"],
    "prusa_username": os.environ["INSTALL_PRUSA_USERNAME"],
    "prusa_password": os.environ["INSTALL_PRUSA_PASSWORD"],
    "prusa_api_key": "",
    "request_timeout_seconds": float(os.environ["INSTALL_REQUEST_TIMEOUT"]),
    "cache_ttl_seconds": float(os.environ["INSTALL_CACHE_TTL"]),
    "fallback_bed_target": float(os.environ["INSTALL_FALLBACK_TARGET"]),
    "fallback_bed_current": float(os.environ["INSTALL_FALLBACK_CURRENT"]),
    "log_level": os.environ["INSTALL_LOG_LEVEL"],
}

json.dump(config, fp=open("/dev/stdout", "w", encoding="utf-8"), indent=2)
print()
PY
}

write_service() {
  local service_path="$1"
  local python_bin="$2"

  sudo tee "$service_path" >/dev/null <<EOF
[Unit]
Description=Panda Breath Prusa Core One Bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$python_bin $INSTALL_DIR/app.py --config $INSTALL_DIR/config.json
Restart=always
RestartSec=5
User=$SERVICE_USER

[Install]
WantedBy=multi-user.target
EOF
}

say "Panda Breath Prusa Bridge installer"
say

ensure_python3
ensure_systemd
sudo -v

CURRENT_USER="$(id -un)"
PYTHON_BIN="$(command -v python3)"

INSTALL_DIR="$DEFAULT_INSTALL_DIR"
SERVICE_USER="$CURRENT_USER"
LISTEN_HOST="$BRIDGE_LISTEN_HOST"
LISTEN_PORT="$BRIDGE_LISTEN_PORT"
PRUSA_HOST="$(prompt "PrusaLink URL (example: http://PRUSA-IP)" "$DEFAULT_PRUSA_URL")"
PRUSA_USERNAME="$(prompt "PrusaLink username" "")"
PRUSA_PASSWORD="$(prompt_secret "PrusaLink password")"

ENABLE_SERVICE="$(prompt "Enable and start the service now? (yes/no)" "yes")"
SERVICE_PATH="/etc/systemd/system/${DEFAULT_SERVICE_NAME}.service"

say
say "Installing files to $INSTALL_DIR"
copy_project_files "$SCRIPT_DIR" "$INSTALL_DIR"
write_config "$INSTALL_DIR/config.json"
write_service "$SERVICE_PATH" "$PYTHON_BIN"

sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
sudo chmod 600 "$INSTALL_DIR/config.json"

sudo systemctl daemon-reload

if [[ "$ENABLE_SERVICE" == "yes" ]]; then
  sudo systemctl enable --now "${DEFAULT_SERVICE_NAME}.service"
  sudo systemctl --no-pager --full status "${DEFAULT_SERVICE_NAME}.service"
else
  say "Service file installed at $SERVICE_PATH"
  say "Start it later with: sudo systemctl enable --now ${DEFAULT_SERVICE_NAME}.service"
fi

say
say "Done."
say "Config: $INSTALL_DIR/config.json"
say "Logs:   sudo journalctl -u ${DEFAULT_SERVICE_NAME}.service -f"
