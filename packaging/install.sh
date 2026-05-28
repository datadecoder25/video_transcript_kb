#!/bin/bash
set -e

echo "=== Transcript Knowledge Base - Installer ==="
echo ""

OS="$(uname -s)"
if [ "$OS" != "Darwin" ] && [ "$OS" != "Linux" ]; then
    echo "ERROR: This tool supports macOS and Linux only."
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo ""
fi

echo "uv version: $(uv --version)"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Project directory: $PROJECT_DIR"
echo ""

echo "Installing dependencies..."
cd "$PROJECT_DIR"
uv sync
echo ""

echo "Verifying installation..."
uv run python -c "import chromadb, sentence_transformers, mcp; print('All packages OK')"
echo ""

DATA_DIR="$PROJECT_DIR/data"
if [ -f "$DATA_DIR/transcripts.db" ]; then
    echo "=== Corpus Stats ==="
    uv run transcripts stats
    echo ""
else
    echo "WARNING: No database found. Run: uv run transcripts ingest"
    echo ""
fi

CLAUDE_CONFIG_FILE="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

echo "=== Claude Desktop Configuration ==="
echo ""
echo "Add this to: $CLAUDE_CONFIG_FILE"
echo "Merge into the mcpServers section:"
echo ""
echo '    "transcripts": {'
echo "      \"command\": \"uv\","
echo "      \"args\": [\"--directory\", \"$PROJECT_DIR\", \"run\", \"python\", \"-m\", \"transcripts.mcp_server\"],"
echo '      "env": {'
echo "        \"TRANSCRIPTS_DATA_DIR\": \"$DATA_DIR\""
echo '      }'
echo '    }'
echo ""
echo "After adding the config:"
echo "  1. Fully quit Claude Desktop (Cmd+Q)"
echo "  2. Reopen Claude Desktop"
echo "  3. Look for the hammer/tools icon"
echo '  4. Ask: "What are the major themes in the transcripts?"'
echo ""
echo "=== Installation Complete ==="
