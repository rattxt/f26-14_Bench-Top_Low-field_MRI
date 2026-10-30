#!/usr/bin/env bash
# Run on the HOST PC:  ./sdrlab/install_on_sdrlab.sh <sdrlab-ip>
# Copies the MaRCoS bitstream + server source to the SDRLab, builds marcos_server there,
# and installs start_marcos.sh. Needs ssh/scp access as root (Red Pitaya default
# password: root). Re-running is safe.
set -e
IP=${1:?usage: $0 <sdrlab-ip>}
cd "$(dirname "$0")"
DEST=/root/marcos
echo "== copying files to root@$IP:$DEST"
ssh root@"$IP" "mkdir -p $DEST"
scp -r marcos_fpga_rp-122.bit.bin marcos_server start_marcos.sh root@"$IP":$DEST/
echo "== building marcos_server on the SDRLab (needs cmake, g++, make on the SDRLab)"
ssh root@"$IP" "cd $DEST/marcos_server && mkdir -p build && cd build && cmake ../src && make -j2"
ssh root@"$IP" "chmod +x $DEST/start_marcos.sh"
echo "== done. Start the server with:  ssh root@$IP $DEST/start_marcos.sh"
