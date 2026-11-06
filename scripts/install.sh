#!/usr/bin/env bash
# Builds the Claude Bridge MIDI Remote script and installs it for Nuendo.
# Usage: ./scripts/install.sh            (auto-detects the Nuendo MIDI Remote folder)
#        NUENDO_SCRIPTS_DIR=... ./scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null; then
  echo "Installing uv (Python package manager)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv sync --quiet

DEST="${NUENDO_SCRIPTS_DIR:-}"
if [[ -z "$DEST" ]]; then
  for d in "$HOME/Documents/Steinberg/Nuendo/MIDI Remote/Driver Scripts/Local" \
           "$HOME/Documents/Steinberg/Nuendo 13/MIDI Remote/Driver Scripts/Local" \
           "$HOME/Documents/Steinberg/Cubase/MIDI Remote/Driver Scripts/Local"; do
    if [[ -d "$(dirname "$d")" ]]; then DEST="$d"; break; fi
  done
fi
if [[ -z "$DEST" ]]; then
  echo "Couldn't find Nuendo's 'MIDI Remote/Driver Scripts' folder."
  echo "Open Nuendo once (Studio > MIDI Remote Manager creates it), or set NUENDO_SCRIPTS_DIR."
  exit 1
fi
mkdir -p "$DEST"
OUT=$(uv run python nuendo_script/build.py "$DEST")
echo "✓ Installed bridge script: $OUT"
echo
echo "Next: in Nuendo open Studio > MIDI Remote Manager > Scripts > Reload Scripts."
echo "MCP server command for Claude:  $(pwd)/.venv/bin/nuendo-mcp"
