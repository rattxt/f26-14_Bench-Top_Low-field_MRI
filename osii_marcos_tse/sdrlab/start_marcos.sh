#!/usr/bin/env bash
# Run on the SDRLab as root:
#   /root/start_marcos.sh
# Or remotely:
#   ssh -t root@<ip> /root/start_marcos.sh

set -Eeuo pipefail

BIT="/root/marcos_pack/marcos_extras/marcos_fpga_rp-122.bit.bin"
SERVER="/root/marcos_server"
FIRMWARE_NAME="$(basename "$BIT")"
FIRMWARE="/lib/firmware/$FIRMWARE_NAME"
FPGA="/sys/class/fpga_manager/fpga0"

# Verify required files and interfaces.
[[ -f "$BIT" ]] || {
    echo "ERROR: FPGA bitstream not found: $BIT" >&2
    exit 1
}
[[ -x "$SERVER" ]] || {
    echo "ERROR: Server executable missing or not executable: $SERVER" >&2
    exit 1
}
[[ -e "$FPGA/firmware" ]] || {
    echo "ERROR: FPGA firmware interface not found: $FPGA/firmware" >&2
    exit 1
}

# Stop the Red Pitaya web server to prevent it reloading its FPGA image.
systemctl stop redpitaya_nginx 2>/dev/null || true

# Install the FPGA bitstream into the firmware directory.
install -D -m 0644 "$BIT" "$FIRMWARE"

# Load the MaRCoS FPGA image.
echo "Loading MaRCoS FPGA bitstream..."
echo "$FIRMWARE_NAME" > "$FPGA/firmware"

# Verify FPGA state before starting the server.
STATE="$(cat "$FPGA/state")"
echo "FPGA state: $STATE"

[[ "$STATE" == "operating" ]] || {
    echo "ERROR: FPGA did not reach operating state; refusing to start server." >&2
    exit 1
}

# Start MaRCoS in the foreground.
echo "Starting MaRCoS server..."
exec "$SERVER"