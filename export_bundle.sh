#!/bin/bash
# ==============================================================================
# OmniRadio Multi-Station Studio - Migration & Backup Packager
# ==============================================================================
set -e

EXPORT_DIR="/tmp/radio_migration"
ARCHIVE_NAME="omniradio_bundle_$(date +%Y%m%d).tar.gz"
RADIO_DIR="/home/saas/radio"

echo "=== 1. Preparing Migration Bundle ==="
rm -rf "$EXPORT_DIR"
mkdir -p "$EXPORT_DIR"

# Copy source code, templates, and configuration
cp -r "$RADIO_DIR/Dockerfile" "$EXPORT_DIR/"
cp -r "$RADIO_DIR/requirements.txt" "$EXPORT_DIR/"
cp -r "$RADIO_DIR/docker-compose.yml" "$EXPORT_DIR/"
cp -r "$RADIO_DIR/src" "$EXPORT_DIR/"
cp -r "$RADIO_DIR/static" "$EXPORT_DIR/"
cp -r "$RADIO_DIR/config" "$EXPORT_DIR/"
mkdir -p "$EXPORT_DIR/audio"/{quran,ambient,uploads}

# Copy existing audio files (if any)
if [ -d "$RADIO_DIR/audio" ]; then
    cp -r "$RADIO_DIR/audio"/* "$EXPORT_DIR/audio/" 2>/dev/null || true
fi

# Add quick launch script
cat << 'EOF' > "$EXPORT_DIR/start.sh"
#!/bin/bash
echo "=== Starting OmniRadio Multi-Station Studio ==="
docker compose up -d --build
echo "Radio is running on http://localhost:9000"
echo "FTP is running on port 2121"
EOF
chmod +x "$EXPORT_DIR/start.sh"

echo "=== 2. Creating Compressed Archive ==="
cd /tmp
tar -czvf "/home/saas/$ARCHIVE_NAME" -C "$EXPORT_DIR" .
rm -rf "$EXPORT_DIR"

echo ""
echo "=================================================================="
echo " SUCCESS! Migration bundle created at: /home/saas/$ARCHIVE_NAME"
echo "=================================================================="
