# Setup

There are three parts:

1. The host PC, which runs this package.
2. The SDRLab 122-16, which runs the MaRCoS FPGA image and `marcos_server`.
3. The wiring.

## 1. Host PC

You need Python 3.8 or newer with pip. Windows, Linux, macOS and WSL all work.

```bash
cd osii_marcos_tse
./setup.sh          # Windows: setup.bat
```

This creates `.venv/` and installs `numpy`, `matplotlib` and `msgpack`. `marga_pulseq` and `marcos_client` are already included under `vendor/`, so they don't need cloning or pip.

**Offline machines.** On a networked PC with the same OS and Python version, run:

```bash
python -m pip download -r requirements.txt -d wheels
```

Copy the `wheels/` folder into the package. `setup.sh` / `setup.bat` installs from it automatically.

**Moving the package.** Copy the whole folder, then run `setup` again on the new machine. Delete `.venv/` before copying, because it is machine-specific. All paths in `config.ini` are relative to the package folder.

Check the install without any hardware:

```bash
./osii.sh info seq/bench_tse_1tr.seq
./osii.sh compile seq/bench_tse_1tr.seq     # must end with "MaRCoS compile OK"
```

## 2. SDRLab 122-16 (MaRCoS side)

The SDRLab needs two things:

- the marga bitstream loaded into its FPGA;
- `marcos_server` running and listening on TCP port 11111.

Both come with the package: `sdrlab/marcos_fpga_rp-122.bit.bin` and `sdrlab/marcos_server/`.

### 2.1 SD card / OS

Use a Red Pitaya OS image for the SDRLab 122-16 that has a working `fpgautil` (Red Pitaya OS 2.x) or the Linux `fpga_manager`. The image also needs `cmake` and `g++` to build the server. If your image lacks these, use the image recommended in the MaRCoS wiki (https://github.com/vnegnev/marcos_extras/wiki, "Setting up the SDRLab"). That wiki is the authoritative reference for the SDRLab side.

Give the SDRLab a fixed IP address, or note its DHCP address. Put that address in `config.ini → [network] ip_address`.

### 2.2 Install (once)

From the host (Linux/macOS/WSL/Git-Bash):

```bash
./sdrlab/install_on_sdrlab.sh 192.168.1.100
```

This does three things:

- copies the bitstream, the server source and `start_marcos.sh` to `/root/marcos` on the SDRLab;
- builds `marcos_server` on the SDRLab;
- makes `start_marcos.sh` executable.

To do it by hand, copy the `sdrlab/` folder to `/root/marcos` with WinSCP or similar, then run:

```bash
cd /root/marcos/marcos_server && mkdir -p build && cd build && cmake ../src && make -j2
```

### 2.3 Start (after every SDRLab boot)

```bash
ssh root@192.168.1.100 /root/marcos/start_marcos.sh
```

The script does three things:

1. stops the Red Pitaya web server, which can reload its own FPGA image;
2. loads the bitstream (`fpgautil -b …`, or `fpga_manager` as a fallback);
3. runs `marcos_server` in the foreground.

Leave that terminal open; server messages appear there. Press Ctrl-C to stop the server.

You are connected when `./osii.sh run seq/bench_rf_pulses.seq` prints the server info lines and `done`. If you get `ConnectionRefusedError`, the server is not running or the IP address is wrong.

**Verify on first use.** The bitstream file from your project folder is `.bit.bin`, which is what `fpgautil` and `fpga_manager` expect. Older images used `cat file.bit > /dev/xdevcfg` with a `.bit` file instead. If loading fails, follow the MaRCoS wiki for your image version. A `.dtbo` overlay is not needed, because `marcos_server` maps the FPGA registers through `/dev/mem`.

### 2.4 Optional: simulator instead of hardware

If you have Verilator, you can build `marga` (see `marga/readme.org` upstream) and run `marga_sim` on the host. Then set `ip_address = localhost`.

The simulator is built with a 200 ms simulated-time limit and runs slowly: about 10 minutes for 160 ms of sequence. It is useful only for short custom files. To dump all FPGA outputs, run `marga_sim csv out.csv`.

This package was checked this way; see SEQUENCE_NOTES.md §5.

## 3. Wiring

```
                        26-pin ribbon (E1 <-> OCRA1 J8)
 SDRLab 122-16 ─────────────────────────────── OCRA1 Rev003
   OUT1 (TX0) ──► [attenuator / OCRA1 J21→J22 PE43704, optional] ──► RFPA RF in (50 Ω)
   IN1  (RX0) ◄── T/R switch J6 "RX" (after built-in LNA)
                                   OCRA1 J20 TXGATE (3.3 V LVTTL, high = transmit)
                                      ├──► T/R switch J10 TXgate
                                      └──► precision 5.0 V buffer ──► RFPA "RF enable" (SMA J2)
   OCRA1 J5  (X BNC) ──► GA2 Vin X ──► GA2 Vout X ──► X coil (or dummy load)
   OCRA1 J25 (Y BNC) ──► GA2 Vin Y ──► GA2 Vout Y ──► Y coil
   OCRA1 J26 (Z BNC) ──► GA2 Vin Z ──► GA2 Vout Z ──► Z coil
   RFPA out ──► T/R switch J8 "TX";  T/R switch J9 "Antenna" ──► RF coil
   GA2 Vmon X/Y/Z (10 V = 15 A) ──► scope        SDRLab trig_out / rx_gate ──► scope (see note)
```

Signal levels and pins below come from the OCRA1 Rev003 schematic, the GA2 design documents, the RFPA README and the A4IM T/R switch schematic.

| Signal | Source | Level / polarity | Notes |
|---|---|---|---|
| Gradient X/Y/Z/Z2 | OCRA1 BNC J5/J25/J26/J27 | ±10 V = ±1.0 FS | Also on RJ45 J17 (single-ended) and J18 (differential) |
| TX gate | marga `tx_gate` → E1 DIO7_N (pin 18) → OCRA1 74LVC1G17 → **BNC J20** | 3.3 V, high during `tx_warmup_us` + RF pulse | Drives the T/R switch directly |
| RFPA enable | your buffer from TXGATE | **5.0 V ±1 %**, active high | The enable level sets the RFPA output amplitude. Do not drive it from 3.3 V |
| TX RF | SDRLab OUT1 | Measure the Vpp at FS into 50 Ω (BENCH_TESTS §3) | RFPA reaches full power (~1 kW) at about 1.1 Vpp input |
| RX RF | SDRLab IN1 | Keep well below ADC full scale | Behind the T/R switch LNA (PHA-13LN+) |
| GA2 current monitor | GA2 Vmon | 10 V = 15 A (0.667 V/A) | |
| `trig_out`, `rx_gate` | SDRLab extension connector | 3.3 V | The pin assignment is set by the MaRCoS FPGA constraints, which are not in this package. Look it up in the MaRCoS wiki, or find the pins with a scope while running `bench_rf_pulses` |

**TX gate polarity.** The T/R switch transmits when TXgate is HIGH. This is from the schematic reading: the TLP387 optocouplers drive the PIN diode current sources. Confirm it in BENCH_TESTS §5 before connecting the LNA output to anything sensitive.
