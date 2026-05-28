#!/bin/bash
set -e

# Creates a distributable zip for the client
# Ships pre-built indices (no raw JSONs, no .venv)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
OUTPUT_DIR="$PROJECT_DIR/packaging"
OUTPUT_FILE="$OUTPUT_DIR/${PROJECT_NAME}_client.zip"

echo "=== Packaging for client ==="
echo "Project: $PROJECT_DIR"
echo "Output:  $OUTPUT_FILE"
echo ""

# Verify data exists
if [ ! -f "$PROJECT_DIR/data/transcripts.db" ]; then
    echo "ERROR: No database found. Run 'uv run transcripts ingest' first."
    exit 1
fi

if [ ! -d "$PROJECT_DIR/data/chroma" ]; then
    echo "ERROR: No Chroma index found. Run 'uv run transcripts ingest' first."
    exit 1
fi

cd "$PROJECT_DIR/.."

# Create zip excluding large/unnecessary files
zip -r "$OUTPUT_FILE" "$PROJECT_NAME" \
    -x "$PROJECT_NAME/.venv/*" \
    -x "$PROJECT_NAME/__pycache__/*" \
    -x "$PROJECT_NAME/**/__pycache__/*" \
    -x "$PROJECT_NAME/data/raw/*" \
    -x "$PROJECT_NAME/.git/*" \
    -x "$PROJECT_NAME/.DS_Store" \
    -x "$PROJECT_NAME/**/.DS_Store" \
    -x "$PROJECT_NAME/*.pyc" \
    -x "$PROJECT_NAME/packaging/${PROJECT_NAME}_client.zip"

SIZE=$(du -sh "$OUTPUT_FILE" | cut -f1)
echo ""
echo "=== Package created ==="
echo "  File: $OUTPUT_FILE"
echo "  Size: $SIZE"
echo ""
echo "Send this zip to the client. They should:"
echo "  1. Unzip it"
echo "  2. Run: bash packaging/install.sh"
echo "  3. Follow the printed instructions to configure Claude Desktop"
