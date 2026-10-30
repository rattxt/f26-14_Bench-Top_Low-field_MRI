# Sequence notes: the OSII TSE on MaRCoS

## 1. The original sequence (`source/sequence.seq`)

The original was written by PyPulseq in Pulseq 1.4.2 format. It is named `tse_3d_t2_mapping` and was made for the OSII One with the Nexus console (Zenodo 21807140).

| Parameter | Value |
|---|---|
| Type | 3D turbo spin echo, multi-echo T2 mapping (CPMG) |
| FOV | 200 × 200 × 200 mm, matrix 44 × 44 × 10 |
| TR / TE / echo spacing | 1250 ms / 13 ms / 13 ms, 14 echoes per TR |
| Excitation | 200 µs hard pulse, 1250 Hz B1 (90°), phase 0 |
| Refocusing | 200 µs hard pulse, 2500 Hz (180°), phase +90° (CPMG) |
| Readout | 44 samples × 50 µs (20 kHz BW), 2.2 ms window on a 100 kHz/m (2.35 mT/m) X plateau |
| Phase encode (Y) | 44 lines, area −110…+105 m⁻¹ (Δk = 5 m⁻¹), 1 ms trapezoids, rewound after each echo |
| Partition (Z) | 10 partitions, centric order 0, −1, +1, … , −5, rewound after each echo |
| Crushers (Z) | 226.6 kHz/m (5.32 mT/m), 2 ms, either side of every 180° |
| Ordering | Outer loop ky (44), inner kz (10); the same k-space line is used for all 14 echoes of a TR, so each echo is one T2-weighted image |
| Total | 440 TRs, 50 600 blocks, 6160 ADC events, 550 s |

One TR is 115 blocks:

```
 0      90°x  [Gx prephaser 149.9 kHz/m + Gz crusher]  delay  |  echo 1 .. 14:
 6.62 ms 180°y [Gz crusher] delay [Gy PE, Gz PE] [Gx readout + ADC] [Gy, Gz rewind] [Gz crusher] delay
 ...   final delay to TR = 1250 ms
```

## 2. Why the original file cannot be used directly with marga_pulseq

1. **Labels.** The file uses Pulseq *extensions* (LABELSET LIN/PAR/ECO) on every ADC block. marga_pulseq validates extension ids against an empty table and stops: `Invalid ext id: 3`. That is the error in `marcos_client/my_experiments/ps_interpreter.log`.
2. **TX gate.** marga_pulseq raises `tx_gate` `tx_warmup` µs before an RF pulse *inside the same block*; the default is 500 µs. The original RF delay is only 20 µs, so the interpreter fails: `Tx warmup … is longer than delay`.
3. **ADC dwell.** MaRCoS' CIC decimator allows at most 4095 clocks, which is 33.3 µs. The sequence uses 50 µs, so the MaRCoS compiler stops with `RX rate outside valid range`.
4. **Gradient raster.** With `grad_t = 1 µs` (the earlier `test_osii_seq.py` attempt), trapezoid ramps produce updates every 1 µs. OCRA1 needs about 3.9 µs per SPI frame, so samples would be dropped.

## 3. What the converter changes (and what it doesn't)

`tools/make_seq.py tse`:

1. **Copies every block, RF, trapezoid and ADC event** with the same amplitudes, durations, delays and phases.
2. **Removes extensions.** The labels are written to `<output>_order.csv` instead (TR, echo, ky index, kz index per ADC). The indices are recomputed from the actual phase/partition-encode gradient areas, so they always match the file.
3. **Adds a lead-in** of 1000 µs, so every event moves by +1000 µs.
4. **Makes room for the TX gate without moving any RF.** For each RF block, the RF delay is increased to `tx_warmup_us`, the block is lengthened by the same amount at its start, and the preceding (empty) delay block is shortened by that amount. All absolute event times are unchanged. The converter refuses to go ahead if the preceding block is not free for long enough; for this sequence the limit is about 2100 µs. `tx_warmup` is written into `[DEFINITIONS]`, so marga_pulseq uses the same value.
5. **ADC oversampling.** The 44 × 50 µs ADC becomes 88 × 25 µs. The start time (94 µs into the readout block) and the 2200 µs duration stay the same. `run_seq.py` averages pairs back to 44 points (`rx0_adc_decimated`).
6. **Zero-amplitude trapezoids** are dropped. These are the kz = 0 partition encodes: 0 Hz/m with 1 µs ramps. Their output is identically zero, and dropping them avoids interpreter ramp warnings.
7. **Recomputes** `TotalDuration` and the md5 `[SIGNATURE]`.

Applied at run time (`run_seq.py`) rather than in the file:

- **3.4 Gradient grid snap (`grad_snap_us = 10`).** marga_pulseq samples each trapezoid ramp on a grid that starts at that trapezoid. Y (235 µs ramps) and Z (69–154 µs ramps) phase/partition encodes play in the same block, so their samples interleave a few µs apart. OCRA1 sends all channels in one SPI frame, so updates on different channels must be simultaneous or ≥3.9 µs apart. Without the snap, the offline compile of the full TSE reports 248 304 dropped updates; with it, zero. The snap moves ramp samples by ≤5 µs. Plateaus, areas and RF/ADC timing are unaffected to within that ramp quantisation.
- Axis → OCRA1 channel mapping and polarity, `trig_out` scope triggers, and `rx_gate`.

Things that are **not** reproduced exactly:

- **Gradient ramps.** Ramps are sampled every 10 µs, the same as on any MaRCoS/OCRA1 system; the original raster is 1 µs. The ramp *timing* (start/end) is preserved to within the 10 µs grid.
- **Readout filtering.** The ADC samples come out of the MaRCoS CIC at 25 µs and are averaged ×2. The Nexus receiver's exact filter response is different.

## 4. Verification done for this package

All of the following were run while building the package; you can repeat them with the commands shown.

| Check | Command | Result |
|---|---|---|
| Event equivalence, full 440 TR file | `./osii.sh check` | tx0 13 200, grad_vx 131 120, grad_vy 460 880, grad_vz 816 112, rx0_en 12 320 events: **all identical in time and amplitude** to the original (after the 1000 µs lead-in); **EQUIVALENT** |
| Event equivalence, 1-TR debug file | `./osii.sh check seq/bench_tse_1tr.seq` | **EQUIVALENT** |
| marga_pulseq loads every file | `./osii.sh info <file>` | OK for all 13 files |
| Full MaRCoS compile, full TSE | `./osii.sh compile` | 2.93 M instructions (11.7 MB), 0 OCRA1 update-rate problems |
| Full MaRCoS compile, all bench files | `./osii.sh compile seq/bench_*.seq` | OK, 0 problems |
| Negative test | `compile seq/bench_tse_1tr.seq --set run.grad_t_us=2` | Correctly reports 29 312 update-rate problems |

## 5. FPGA simulation (marga Verilator model)

`bench_tse_1tr.seq` was also run through the marga simulator (`marga_sim csv`) with this package's client code. The simulator stops at 200 ms of simulated time, so the first 161 ms were checked.

All outputs are offset by the same constant 174.21 µs: the server start-up plus the 6 µs initial wait. Compared with `reports/bench_tse_1tr_timing.csv`:

| Signal | Expected (sequence time) | Simulated FPGA output (− 174.21 µs) |
|---|---|---|
| tx_gate | high 920, low 1220; high 7420, low 7720; high 20420 … | Identical |
| trig_out | 920–930 µs | Identical |
| tx0 90° | I = 0.1 FS (3277), 1020–1220 µs | Identical |
| tx0 180° | Q = 0.2 FS (6553), i.e. +90° phase, 7520–7720 µs | Identical |
| rx0_en / rx_gate | 13020–15220, 26020–28220, … | Identical |
| OCRA1 X / Y / Z peaks | 4.695 V / ±4.503 V / 7.097 V | Identical |
| OCRA1 first X ramp step | 1260 µs (10 µs grid) | 1261.76 µs (+1.8 µs SPI transfer) |

## 6. Re-using the converter

`make_seq.py` works for other Pulseq 1.4 files that use hard or shaped RF and trapezoids. See CONFIGURATION.md, "Using your own Pulseq file". After converting, always run `check` and `compile`.
