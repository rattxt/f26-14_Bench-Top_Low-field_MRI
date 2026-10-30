# OSII v1 on MaRCoS: TSE sequence and bench-test package

This package runs the OSII One 3D TSE T2-mapping sequence on an **OSII v1** scanner. The original file was made for the Nexus console (Zenodo record 21807140, `source/sequence.seq`). Here the scanner is controlled by **MaRCoS**: a RedPitaya SDRLab 122-16 running the marga FPGA, an OCRA1 gradient DAC, a TU Delft GA2 gradient amplifier, the 1 kW RFPA and the A4IM T/R switch.

The package does three things:

1. **Converts** the Nexus `.seq` into a `.seq` that `marga_pulseq` can load. Every RF, gradient and ADC event keeps its original timing. This has been checked sample by sample; see [docs/SEQUENCE_NOTES.md](docs/SEQUENCE_NOTES.md).
2. **Generates bench-test sequences** for each subsystem: OCRA1, GA2, RFPA, T/R switch and the RX chain.
3. **Runs** any of these sequences on the scanner with one command. It prints the levels and timings you should see on a scope or DMM, and saves the RX data.

Everything is configured in one file, **`config.ini`**.

```
osii_marcos_tse/
├── README.md                  this file
├── config.ini                 THE configuration file (network, calibration, sequence, run)
├── setup.sh / setup.bat       one-time host setup (creates .venv)
├── osii.sh  / osii.bat        command wrapper
├── seq/                       generated .seq files (+ *_order.csv acquisition order)
│   ├── tse_3d_t2_marcos.seq   full converted TSE (440 TR, 550 s)
│   └── bench_*.seq            bench-test sequences
├── source/sequence.seq        original OSII/Nexus file (unchanged)
├── tools/                     make_seq.py, run_seq.py, check_equivalence.py, view_rx.py
├── vendor/                    marcos_client + marga_pulseq (pinned copies, MIT)
├── sdrlab/                    MaRCoS bitstream, marcos_server source, install/start scripts
├── docs/                      SETUP, CONFIGURATION, RUNNING, BENCH_TESTS, SEQUENCE_NOTES
├── data/                      RX data written by runs (.npz)
└── reports/                   timing tables, plots, interpreter logs
```

## Quick start

```bash
./setup.sh                                  # once per PC (Windows: setup.bat)
# edit config.ini: [network] ip_address and every value marked "!! VERIFY"
./osii.sh make all                          # (re)generate all .seq files from config.ini
./osii.sh check                             # prove the TSE conversion is equivalent
./osii.sh plot seq/bench_tse_1tr.seq        # waveform PNG + timing table, no hardware
./osii.sh compile                           # full MaRCoS compile offline, no hardware
# SDRLab: ssh root@<ip> /root/marcos/start_marcos.sh   (see docs/SETUP.md)
./osii.sh run seq/bench_rf_pulses.seq       # first hardware test
./osii.sh run                               # full TSE (550 s), data -> data/*.npz
./osii.sh view                              # quick look at the newest data file
```

On Windows use `osii.bat` instead of `./osii.sh`, and put quotes around overrides: `osii run --set "run.repeat=10"`.

## Read next

| Document | Contents |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Host PC setup, SDRLab setup (bitstream + server), wiring diagram |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every `config.ini` key, how to calibrate, common changes |
| [docs/RUNNING.md](docs/RUNNING.md) | Step-by-step operation: info, plot, compile, run, data format, troubleshooting |
| [docs/BENCH_TESTS.md](docs/BENCH_TESTS.md) | Test procedures with lab equipment for OCRA1, GA2, RFPA, T/R switch, RX, full chain |
| [docs/SEQUENCE_NOTES.md](docs/SEQUENCE_NOTES.md) | What the TSE does, what was changed for MaRCoS and why, verification results |

## Safety summary (read before connecting amplifiers)

- **Gradient levels.** OCRA1 full scale is ±10 V. Through the GA2 (1.5 A/V) that is ±15 A. The full TSE peaks at about 0.71 FS on Z, which is about 10.6 A with the placeholder calibration. Run `./osii.sh info` before every run and check the printed peak volts and amps.
- **RFPA limits.** The RFPA has no overload protection. Always use a 50 Ω load, ≤10 % duty and ≤20 ms pulses. Its enable input needs **5.0 V ±1 %**, but OCRA1 TXGATE is 3.3 V, so use a precision buffer. Measure the SDRLab TX output level before connecting the RFPA (BENCH_TESTS.md §3).
- **GA2 duty.** Keep each channel at ≤30 %. The `bench_tse_1tr*` files use TR = 500 ms, which gives about 11 % on Z.
- **Upstream example.** `test_ocra1_simple.py` in upstream marcos_client commands 0.8 FS (= 8 V ≈ 12 A), not "1 V" as its comment says.
