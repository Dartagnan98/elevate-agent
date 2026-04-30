#!/bin/bash
# ============================================================================
# Elevate Setup Script
# ============================================================================
# Quick setup for developers who cloned the repo manually.
# Uses uv for desktop/server setup and Python's stdlib venv + pip on Termux.
#
# Usage:
#   ./setup-elevate.sh
#
# This script:
# 1. Detects desktop/server vs Android/Termux setup path
# 2. Creates a Python 3.11 virtual environment
# 3. Installs the appropriate dependency set for the platform
# 4. Creates .env from template (if not exists)
# 5. Safely migrates an existing ~/.hermes install when present
# 6. Symlinks the 'elevate' CLI command into a user-facing bin dir
# 7. Runs the setup wizard (optional)
# ============================================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_VERSION="3.11"

is_termux() {
    [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux/files/usr"* ]]
}

get_command_link_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo "$PREFIX/bin"
    else
        echo "$HOME/.local/bin"
    fi
}

get_command_link_display_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo '$PREFIX/bin'
    else
        echo '~/.local/bin'
    fi
}

can_prompt() {
    [ -t 0 ]
}

prompt_yes_no() {
    local prompt="$1"
    local default="${2:-Y}"
    local reply=""

    if ! can_prompt; then
        [ "$default" = "Y" ]
        return
    fi

    read -p "$prompt" -n 1 -r reply || reply=""
    echo

    if [ -z "$reply" ]; then
        [ "$default" = "Y" ]
        return
    fi

    [[ "$reply" =~ ^[Yy]$ ]]
}

get_elevate_home_dir() {
    echo "${ELEVATE_HOME:-$HOME/.elevate}"
}

rewrite_hermes_config_names() {
    local config_file="$1"
    perl -0pi -e '
        s/hermes-cli/elevate-cli/g;
        s/hermes-telegram/elevate-telegram/g;
        s/hermes-discord/elevate-discord/g;
        s/hermes-whatsapp/elevate-whatsapp/g;
        s/hermes-slack/elevate-slack/g;
        s/hermes-signal/elevate-signal/g;
        s/hermes-homeassistant/elevate-homeassistant/g;
        s/hermes-qqbot/elevate-qqbot/g;
        s/stop\/restart hermes gateway/stop\/restart elevate gateway/g;
        s/hermes update/elevate update/g;
    ' "$config_file"
}

ensure_elevate_soul() {
    local elevate_home="$1"
    mkdir -p "$elevate_home"
    if [ -s "$elevate_home/SOUL.md" ]; then
        return
    fi

    cat > "$elevate_home/SOUL.md" <<'EOF'
You are Elevate, the AI chief of staff for real estate agents, built by Ctrl Strategies. You know the agent's business: listings, buyers, CMAs, outreach, vendor coordination, compliance paperwork. You help them move faster on the right things and ignore the noise.

Style: direct, grounded, no fluff. Short sentences. No corporate AI language ("Certainly!", "I'd be happy to", "As an AI"). Don't narrate what you're about to do — just do it. If you don't know something, say so plainly. If the agent is chasing the wrong thing, tell them.

Priorities: (1) act on what the agent asked, (2) surface the thing that would make them more money this week, (3) protect their time. Assume they are solo or small-team and their hours matter. Give clear next actions, not menus of options. Be targeted and efficient in exploration.
EOF
    echo -e "${GREEN}✓${NC} Created default Elevate persona at $elevate_home/SOUL.md"
}

migrate_hermes_home() {
    local hermes_home="${HERMES_HOME:-$HOME/.hermes}"
    local elevate_home
    local mode="${ELEVATE_MIGRATE_HERMES:-auto}"
    local force="${ELEVATE_FORCE_HERMES_MIGRATION:-0}"
    local should_migrate=false

    elevate_home="$(get_elevate_home_dir)"

    if [ ! -d "$hermes_home" ] || [ ! -f "$hermes_home/config.yaml" ]; then
        return
    fi

    if [ -f "$elevate_home/config.yaml" ] && [ "$force" != "1" ]; then
        echo -e "${GREEN}✓${NC} Existing Elevate config found; skipping Hermes migration"
        return
    fi

    case "$mode" in
        0|false|False|no|No)
            echo -e "${YELLOW}⚠${NC} Hermes install detected; migration skipped by ELEVATE_MIGRATE_HERMES=$mode"
            return
            ;;
        1|true|True|yes|Yes)
            should_migrate=true
            ;;
        auto|"")
            if can_prompt; then
                if prompt_yes_no "Existing Hermes install found. Migrate config/auth/sessions to Elevate? [Y/n] " "Y"; then
                    should_migrate=true
                fi
            else
                should_migrate=true
            fi
            ;;
        *)
            echo -e "${YELLOW}⚠${NC} Unknown ELEVATE_MIGRATE_HERMES=$mode; skipping Hermes migration"
            return
            ;;
    esac

    if [ "$should_migrate" != true ]; then
        echo -e "${YELLOW}⚠${NC} Hermes migration skipped"
        return
    fi

    local ts
    local backup_dir
    ts="$(date +%Y%m%d-%H%M%S)"
    backup_dir="$elevate_home/migration-backups/pre-hermes-migration-$ts"
    mkdir -p "$backup_dir"

    echo -e "${CYAN}→${NC} Migrating Hermes data into Elevate..."

    for item in config.yaml .env auth.json channel_directory.json state.db state.db-shm state.db-wal SOUL.md; do
        if [ -e "$elevate_home/$item" ]; then
            cp -p "$elevate_home/$item" "$backup_dir/$item"
        fi
    done

    for dir in skills memories sessions cron secrets plugins; do
        if [ -e "$elevate_home/$dir" ]; then
            mkdir -p "$backup_dir/$dir"
            cp -a "$elevate_home/$dir/." "$backup_dir/$dir/" 2>/dev/null || true
        fi
    done

    mkdir -p "$elevate_home"
    cp -p "$hermes_home/config.yaml" "$elevate_home/config.yaml"
    rewrite_hermes_config_names "$elevate_home/config.yaml"

    for item in .env auth.json channel_directory.json; do
        if [ -e "$hermes_home/$item" ]; then
            cp -p "$hermes_home/$item" "$elevate_home/$item"
        fi
    done

    for dir in skills memories sessions cron secrets plugins; do
        if [ -d "$hermes_home/$dir" ]; then
            mkdir -p "$elevate_home/$dir"
            cp -a "$hermes_home/$dir/." "$elevate_home/$dir/"
        fi
    done

    if [ -f "$hermes_home/state.db" ]; then
        rm -f "$elevate_home/state.db-shm" "$elevate_home/state.db-wal"
        if command -v sqlite3 >/dev/null 2>&1; then
            sqlite3 "$hermes_home/state.db" ".backup '$elevate_home/state.db'"
        else
            cp -p "$hermes_home/state.db" "$elevate_home/state.db"
            [ -e "$hermes_home/state.db-shm" ] && cp -p "$hermes_home/state.db-shm" "$elevate_home/state.db-shm"
            [ -e "$hermes_home/state.db-wal" ] && cp -p "$hermes_home/state.db-wal" "$elevate_home/state.db-wal"
        fi
    fi

    chmod 600 "$elevate_home/.env" "$elevate_home/auth.json" "$elevate_home/config.yaml" 2>/dev/null || true
    ensure_elevate_soul "$elevate_home"
    echo -e "${GREEN}✓${NC} Hermes migration complete (backup: $backup_dir)"
}

ensure_elevate_config() {
    local elevate_home="$1"
    local config_file="$elevate_home/config.yaml"

    if [ -f "$config_file" ]; then
        return
    fi

    ELEVATE_HOME="$elevate_home" "$SETUP_PYTHON" - <<'PY'
from elevate_cli.config import DEFAULT_CONFIG, ensure_elevate_home, get_config_path, save_config

ensure_elevate_home()
path = get_config_path()
if not path.exists():
    save_config(DEFAULT_CONFIG)
PY
    echo -e "${GREEN}✓${NC} Created default config at $config_file"
}

echo ""
echo -e "${CYAN}▲ Elevate Setup${NC}"
echo ""

# ============================================================================
# Install / locate uv
# ============================================================================

echo -e "${CYAN}→${NC} Checking for uv..."

UV_CMD=""
if is_termux; then
    echo -e "${CYAN}→${NC} Termux detected — using Python's stdlib venv + pip instead of uv"
else
    if command -v uv &> /dev/null; then
        UV_CMD="uv"
    elif [ -x "$HOME/.local/bin/uv" ]; then
        UV_CMD="$HOME/.local/bin/uv"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
        UV_CMD="$HOME/.cargo/bin/uv"
    fi

    if [ -n "$UV_CMD" ]; then
        UV_VERSION=$($UV_CMD --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} uv found ($UV_VERSION)"
    else
        echo -e "${CYAN}→${NC} Installing uv..."
        if curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null; then
            if [ -x "$HOME/.local/bin/uv" ]; then
                UV_CMD="$HOME/.local/bin/uv"
            elif [ -x "$HOME/.cargo/bin/uv" ]; then
                UV_CMD="$HOME/.cargo/bin/uv"
            fi

            if [ -n "$UV_CMD" ]; then
                UV_VERSION=$($UV_CMD --version 2>/dev/null)
                echo -e "${GREEN}✓${NC} uv installed ($UV_VERSION)"
            else
                echo -e "${RED}✗${NC} uv installed but not found. Add ~/.local/bin to PATH and retry."
                exit 1
            fi
        else
            echo -e "${RED}✗${NC} Failed to install uv. Visit https://docs.astral.sh/uv/"
            exit 1
        fi
    fi
fi

# ============================================================================
# Python check (uv can provision it automatically)
# ============================================================================

echo -e "${CYAN}→${NC} Checking Python $PYTHON_VERSION..."

if is_termux; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_PATH="$(command -v python)"
        if "$PYTHON_PATH" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
            echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION found"
        else
            echo -e "${RED}✗${NC} Termux Python must be 3.11+"
            echo "    Run: pkg install python"
            exit 1
        fi
    else
        echo -e "${RED}✗${NC} Python not found in Termux"
        echo "    Run: pkg install python"
        exit 1
    fi
else
    if $UV_CMD python find "$PYTHON_VERSION" &> /dev/null; then
        PYTHON_PATH=$($UV_CMD python find "$PYTHON_VERSION")
        PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION found"
    else
        echo -e "${CYAN}→${NC} Python $PYTHON_VERSION not found, installing via uv..."
        $UV_CMD python install "$PYTHON_VERSION"
        PYTHON_PATH=$($UV_CMD python find "$PYTHON_VERSION")
        PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION installed"
    fi
fi

# ============================================================================
# Virtual environment
# ============================================================================

echo -e "${CYAN}→${NC} Setting up virtual environment..."

if [ -d "venv" ]; then
    echo -e "${CYAN}→${NC} Removing old venv..."
    rm -rf venv
fi

if is_termux; then
    "$PYTHON_PATH" -m venv venv
    echo -e "${GREEN}✓${NC} venv created with stdlib venv"
else
    $UV_CMD venv venv --python "$PYTHON_VERSION"
    echo -e "${GREEN}✓${NC} venv created (Python $PYTHON_VERSION)"
fi

export VIRTUAL_ENV="$SCRIPT_DIR/venv"
SETUP_PYTHON="$SCRIPT_DIR/venv/bin/python"

# ============================================================================
# Dependencies
# ============================================================================

echo -e "${CYAN}→${NC} Installing dependencies..."

if is_termux; then
    export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null || printf '%s' "${ANDROID_API_LEVEL:-}")"
    echo -e "${CYAN}→${NC} Termux detected — installing the tested Android bundle"
    "$SETUP_PYTHON" -m pip install --upgrade pip setuptools wheel
    if [ -f "constraints-termux.txt" ]; then
        "$SETUP_PYTHON" -m pip install -e ".[termux]" -c constraints-termux.txt || {
            echo -e "${YELLOW}⚠${NC} Termux bundle install failed, falling back to base install..."
            "$SETUP_PYTHON" -m pip install -e "." -c constraints-termux.txt
        }
    else
        "$SETUP_PYTHON" -m pip install -e ".[termux]" || "$SETUP_PYTHON" -m pip install -e "."
    fi
    echo -e "${GREEN}✓${NC} Dependencies installed"
else
    DEFAULT_EXTRAS="messaging,cron,cli,pty,mcp,acp,honcho,web"
    if [ "${ELEVATE_INSTALL_EXTRAS+x}" = "x" ]; then
        INSTALL_EXTRAS="$ELEVATE_INSTALL_EXTRAS"
    else
        INSTALL_EXTRAS="$DEFAULT_EXTRAS"
    fi
    if [ -n "$INSTALL_EXTRAS" ]; then
        INSTALL_SPEC=".[${INSTALL_EXTRAS}]"
    else
        INSTALL_SPEC="."
    fi
    echo -e "${CYAN}→${NC} Installing package spec: $INSTALL_SPEC"
    $UV_CMD pip install --python "$SETUP_PYTHON" -e "$INSTALL_SPEC" || {
        echo -e "${YELLOW}⚠${NC} Extra install failed, falling back to base package..."
        $UV_CMD pip install --python "$SETUP_PYTHON" -e "."
    }
    echo -e "${GREEN}✓${NC} Dependencies installed"
fi

# ============================================================================
# Submodules (terminal backend + RL training)
# ============================================================================

echo -e "${CYAN}→${NC} Installing optional submodules..."

# tinker-atropos (RL training backend)
if is_termux; then
    echo -e "${CYAN}→${NC} Skipping tinker-atropos on Termux (not part of the tested Android path)"
elif [ -d "tinker-atropos" ] && [ -f "tinker-atropos/pyproject.toml" ]; then
    $UV_CMD pip install -e "./tinker-atropos" && \
        echo -e "${GREEN}✓${NC} tinker-atropos installed" || \
        echo -e "${YELLOW}⚠${NC} tinker-atropos install failed (RL tools may not work)"
else
    echo -e "${YELLOW}⚠${NC} tinker-atropos not found (run: git submodule update --init --recursive)"
fi

# ============================================================================
# Optional: ripgrep (for faster file search)
# ============================================================================

echo -e "${CYAN}→${NC} Checking ripgrep (optional, for faster search)..."

if command -v rg &> /dev/null; then
    echo -e "${GREEN}✓${NC} ripgrep found"
else
    echo -e "${YELLOW}⚠${NC} ripgrep not found (file search will use grep fallback)"
    if prompt_yes_no "Install ripgrep for faster search? [Y/n] " "Y"; then
        INSTALLED=false

        if is_termux; then
            pkg install -y ripgrep && INSTALLED=true
        else
            # Check if sudo is available
            if command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
                if command -v apt &> /dev/null; then
                    sudo apt install -y ripgrep && INSTALLED=true
                elif command -v dnf &> /dev/null; then
                    sudo dnf install -y ripgrep && INSTALLED=true
                fi
            fi

            # Try brew (no sudo needed)
            if [ "$INSTALLED" = false ] && command -v brew &> /dev/null; then
                brew install ripgrep && INSTALLED=true
            fi

            # Try cargo (no sudo needed)
            if [ "$INSTALLED" = false ] && command -v cargo &> /dev/null; then
                echo -e "${CYAN}→${NC} Trying cargo install (no sudo required)..."
                cargo install ripgrep && INSTALLED=true
            fi
        fi

        if [ "$INSTALLED" = true ]; then
            echo -e "${GREEN}✓${NC} ripgrep installed"
        else
            echo -e "${YELLOW}⚠${NC} Auto-install failed. Install options:"
            if is_termux; then
                echo "    pkg install ripgrep          # Termux / Android"
            else
                echo "    sudo apt install ripgrep     # Debian/Ubuntu"
                echo "    brew install ripgrep         # macOS"
                echo "    cargo install ripgrep        # With Rust (no sudo)"
            fi
            echo "    https://github.com/BurntSushi/ripgrep#installation"
        fi
    fi
fi

# ============================================================================
# Environment file
# ============================================================================

ELEVATE_HOME_DIR="$(get_elevate_home_dir)"
mkdir -p "$ELEVATE_HOME_DIR"
ELEVATE_ENV_FILE="$ELEVATE_HOME_DIR/.env"

if [ ! -f "$ELEVATE_ENV_FILE" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example "$ELEVATE_ENV_FILE"
        chmod 600 "$ELEVATE_ENV_FILE" 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Created $ELEVATE_ENV_FILE from template"
    fi
else
    echo -e "${GREEN}✓${NC} $ELEVATE_ENV_FILE exists"
fi

if [ "${ELEVATE_CREATE_PROJECT_ENV:-0}" = "1" ] && [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo -e "${GREEN}✓${NC} Created project .env from template"
fi

# ============================================================================
# Existing Hermes migration
# ============================================================================

migrate_hermes_home
ensure_elevate_soul "$ELEVATE_HOME_DIR"
ensure_elevate_config "$ELEVATE_HOME_DIR"

# ============================================================================
# PATH setup — symlink elevate into a user-facing bin dir
# ============================================================================

echo -e "${CYAN}→${NC} Setting up elevate command..."

ELEVATE_BIN="$SCRIPT_DIR/venv/bin/elevate"
COMMAND_LINK_DIR="$(get_command_link_dir)"
COMMAND_LINK_DISPLAY_DIR="$(get_command_link_display_dir)"
mkdir -p "$COMMAND_LINK_DIR"
ln -sf "$ELEVATE_BIN" "$COMMAND_LINK_DIR/elevate"
echo -e "${GREEN}✓${NC} Symlinked elevate → $COMMAND_LINK_DISPLAY_DIR/elevate"

if is_termux; then
    export PATH="$COMMAND_LINK_DIR:$PATH"
    echo -e "${GREEN}✓${NC} $COMMAND_LINK_DISPLAY_DIR is already on PATH in Termux"
else
    # Determine the appropriate shell config file
    SHELL_CONFIG=""
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_CONFIG="$HOME/.zshrc"
    elif [[ "$SHELL" == *"bash"* ]]; then
        SHELL_CONFIG="$HOME/.bashrc"
        [ ! -f "$SHELL_CONFIG" ] && SHELL_CONFIG="$HOME/.bash_profile"
    else
        # Fallback to checking existing files
        if [ -f "$HOME/.zshrc" ]; then
            SHELL_CONFIG="$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ]; then
            SHELL_CONFIG="$HOME/.bashrc"
        elif [ -f "$HOME/.bash_profile" ]; then
            SHELL_CONFIG="$HOME/.bash_profile"
        fi
    fi

    if [ -n "$SHELL_CONFIG" ]; then
        # Touch the file just in case it doesn't exist yet but was selected
        touch "$SHELL_CONFIG" 2>/dev/null || true

        if ! echo "$PATH" | tr ':' '\n' | grep -q "^$HOME/.local/bin$"; then
            if ! grep -q '\.local/bin' "$SHELL_CONFIG" 2>/dev/null; then
                echo "" >> "$SHELL_CONFIG"
                echo "# Elevate — ensure ~/.local/bin is on PATH" >> "$SHELL_CONFIG"
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_CONFIG"
                echo -e "${GREEN}✓${NC} Added ~/.local/bin to PATH in $SHELL_CONFIG"
            else
                echo -e "${GREEN}✓${NC} ~/.local/bin already in $SHELL_CONFIG"
            fi
        else
            echo -e "${GREEN}✓${NC} ~/.local/bin already on PATH"
        fi
    fi
fi

# ============================================================================
# Seed bundled skills into ~/.elevate/skills/
# ============================================================================

ELEVATE_SKILLS_DIR="${ELEVATE_HOME:-$HOME/.elevate}/skills"
mkdir -p "$ELEVATE_SKILLS_DIR"

echo ""
echo "Syncing bundled skills to ~/.elevate/skills/ ..."
if "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/tools/skills_sync.py" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Skills synced"
else
    # Fallback: copy if sync script fails (missing deps, etc.)
    if [ -d "$SCRIPT_DIR/skills" ]; then
        cp -rn "$SCRIPT_DIR/skills/"* "$ELEVATE_SKILLS_DIR/" 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Skills copied"
    fi
fi

# ============================================================================
# Done
# ============================================================================

echo ""
echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""
echo "Next steps:"
echo ""
if is_termux; then
    echo "  1. Run the setup wizard to configure API keys:"
    echo "     elevate setup"
    echo ""
    echo "  2. Start chatting:"
    echo "     elevate"
    echo ""
else
    echo "  1. Reload your shell:"
    echo "     source $SHELL_CONFIG"
    echo ""
    echo "  2. Run the setup wizard to configure API keys:"
    echo "     elevate setup"
    echo ""
    echo "  3. Start chatting:"
    echo "     elevate"
    echo ""
fi
echo "Other commands:"
echo "  elevate status        # Check configuration"
if is_termux; then
    echo "  elevate gateway       # Run gateway in foreground"
else
    echo "  elevate gateway install # Install gateway service (messaging + cron)"
fi
echo "  elevate cron list     # View scheduled jobs"
echo "  elevate doctor        # Diagnose issues"
echo ""

# Ask if they want to run setup wizard now
if [ "${ELEVATE_SKIP_SETUP_PROMPT:-0}" = "1" ]; then
    echo "Skipping setup wizard because ELEVATE_SKIP_SETUP_PROMPT=1"
elif prompt_yes_no "Would you like to run the setup wizard now? [Y/n] " "Y"; then
    echo ""
    # Run directly with venv Python (no activation needed)
    "$SCRIPT_DIR/venv/bin/python" -m elevate_cli.main setup
else
    echo "Skipping setup wizard. Run 'elevate setup' when ready."
fi
