#!/bin/bash
# ==============================================================================
# DuckDNS automatic IP updater
# ==============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_FILE="$SCRIPT_DIR/duckdns.conf"

if [ -f "$CONF_FILE" ]; then
    source "$CONF_FILE"
fi

DOMAIN="${DUCKDNS_DOMAIN:-islamradio}"
TOKEN="${DUCKDNS_TOKEN:-}"

if [ -z "$TOKEN" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - DuckDNS token not configured in $CONF_FILE" >> "$SCRIPT_DIR/duckdns.log"
    exit 1
fi

RESPONSE=$(curl -s --max-time 15 "https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=")
if [ "$RESPONSE" = "OK" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - DuckDNS update SUCCESS for ${DOMAIN}.duckdns.org" >> "$SCRIPT_DIR/duckdns.log"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - DuckDNS update FAILED: $RESPONSE" >> "$SCRIPT_DIR/duckdns.log"
fi
