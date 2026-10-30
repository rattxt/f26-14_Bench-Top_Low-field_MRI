# Configuration (`config.ini`)

Every tool reads `config.ini` from the package folder. There are three ways to change a setting:

- **Edit the file.** This is a permanent change.
- **Override one run.** Add `--set section.key=value` to any command; you can repeat it. Example: `./osii.sh run seq/bench_grad_x.seq --set run.repeat=20`. On Windows, quote it: `--set "run.repeat=20"`.
- **Use a different file.** Pass `--config other.ini`, or set `OSII_CONFIG=/path/other.ini`. This is handy for one file per scanner or per test setup.

You must regenerate the `.seq` files with `./osii.sh make all` after changing:

- `[sequence]` or `[bench]`;
- `tx_warmup_us`;
- the calibration, but only for the bench files, because they are defined as a fraction of full scale.

Changes to `[network]`, `[hardware]`, `[gradient_mapping]` and `[run]` take effect on the next run.

## How amplitudes flow

```
 .seq file (physical units)      calibration (config.ini)            hardware
 RF   Hz of B1      ── ÷ rf_amp_max_Hz ───────────► TX fraction ──► SDRLab OUT1 ─► RFPA
 grad Hz/m          ── ÷ g?_max_Hz_per_m ─────────► DAC fraction ─► OCRA1 ±10 V ─► GA2 ─► A
```

`marga_pulseq` refuses to run if any RF pulse or gradient needs more than full scale (|fraction| > 1). `./osii.sh info` prints the fraction, volts and amps for every channel.

## [network]

| key | meaning |
|---|---|
| `ip_address` | SDRLab IP address (`localhost` for the simulator) |
| `port` | `marcos_server` port, always 11111 |

## [hardware]

| key | default | meaning |
|---|---|---|
| `fpga_clk_freq_MHz` | 122.88 | SDRLab 122-16 clock. Do not change |
| `grad_board` | ocra1 | `ocra1` or `gpa-fhdo` |
| `larmor_freq_Hz` | 2.1e6 | TX/RX NCO frequency. **Set it to your measured Larmor frequency.** It moves with magnet temperature |
| `grad_max_update_rate` | 0.2 | OCRA1 SPI speed (MSPS). 0.2 gives a 3.92 µs frame. Higher is faster, but check signal integrity on the ribbon (Test & Validation G2) |
| `grad_latency_us` | 0 | Moves gradient updates earlier by this much to align with RF/ADC. Set it to the delay you measure (BENCH_TESTS §2.4) |
| `init_ocra1` | yes | Reset the OCRA1 DACs to 0 V when connecting |
| `halt_and_reset` | yes | Stop any sequence still running on the SDRLab when connecting |

## [gradient_calibration]

This section sets the gradient strength, in Hz/m, at OCRA1 +full scale (+10 V) for each axis.

- `mode = physical`: `full_scale = 42.577e6 × efficiency[T/m/A] × amp_gain[A/V] × ocra1_full_scale_V`
  - `ocra1_full_scale_V = 10.0` (AD5781 ±10 V reference).
  - `amp_gain_A_per_V = 1.5` (GA2 design value). The design document measured −1.52 A/V. Measure the sign and fix any inversion with `[gradient_mapping] *_polarity`.
  - `x/y/z_efficiency_mT_per_m_per_A`: **placeholder 0.5**. The coil efficiencies were not in any of the documents I had. Measure them, or take them from the OSII documentation.
- `mode = direct`: give `gx/gy/gz_max_Hz_per_m` yourself.

The defaults give 319 kHz/m (7.5 mT/m) at full scale, so the TSE peaks at 0.47/0.45/0.71 FS on X/Y/Z. For bench work into dummy loads you can set `mode = direct` with larger values. The same sequence then runs at proportionally lower volts and amps. Alternatively, use the `[sequence] g?_scale` multipliers.

## [rf_calibration]

This section sets the B1 (Hz) produced at SDRLab TX full scale.

- `mode = flip90`: give `rf_90_fraction`, the TX fraction that produces a 90° flip with a `rf_90_duration_us` (200 µs) hard pulse. The TSE uses 1250 Hz for 90° and 2500 Hz for 180°, so the 180° pulses run at 2 × `rf_90_fraction`. That value must be ≤ 0.5.
- `mode = direct`: give `rf_amp_max_Hz`.

**Calibration procedure (on the scanner, with a phantom).**

1. Run `bench_rf_loopback.seq` and adjust `[bench] rf_fraction`, or run the TSE with `rf_scale` swept.
2. Find the TX fraction that maximises the FID or first echo. That fraction is the 90°. Start low: 0.05–0.1.

## [gradient_mapping]

| key | meaning |
|---|---|
| `x_channel`, `y_channel`, `z_channel` | OCRA1 channel for each logical axis: `vx`, `vy`, `vz` or `vz2` |
| `x_polarity`, … | `1` or `-1`. Use `-1` if a positive command gives negative current (GA2 sign) or the coil is wired reversed |

The original sequence uses `channel_order x y z`:

- X is readout, plus the read prephaser and its crusher;
- Y is the phase encode (44 lines);
- Z is the partition encode (10) plus the crushers.

## [sequence]: converting the OSII TSE

| key | default | meaning |
|---|---|---|
| `source` | source/sequence.seq | Original Pulseq 1.4 file |
| `output` | seq/tse_3d_t2_marcos.seq | Written file. `<output>_order.csv` is written next to it |
| `name` | | `Name` definition in the file |
| `tx_warmup_us` | 100 | How long before each RF pulse `tx_gate` (TXGATE BNC) goes high. Covers RFPA un-blanking (≤0.5 µs) and T/R switch settling (opto-coupled, tens of µs; measure it). Must be ≤ ~2100 µs for this sequence. RF timing does not move; the gate just starts earlier |
| `lead_in_us` | 1000 | Idle time at the start of the file (≥ `tx_warmup_us` + 10) |
| `first_tr`, `n_tr` | 0, 0 | Keep TRs `first_tr … first_tr+n_tr-1`. `n_tr = 0` keeps all 440. TR 220 is the k-space centre (ky = 0, kz = 0) |
| `tr_ms` | 0 | New TR in ms (0 = 1250). The minimum is about 186.4 ms (90° + 14 echoes) |
| `rf_scale`, `gx_scale`, `gy_scale`, `gz_scale` | 1 | Amplitude multipliers. `0` removes that channel completely, so `rf_scale = 0` also removes tx_gate |
| `adc_enable` | yes | `no` removes all ADC events |
| `adc_oversampling` | 0 (auto) | MaRCoS cannot dwell longer than 33.3 µs, but the TSE uses 50 µs. Auto picks 2: 88 samples at 25 µs over the same 2.2 ms window. `run_seq.py` averages them back to 44 |

Examples:

```bash
# 10 TRs around the k-space centre, TR 300 ms, gradients at half amplitude
./osii.sh make tse --set sequence.first_tr=215 --set sequence.n_tr=10 --set sequence.tr_ms=300 \
   --set sequence.gx_scale=0.5 --set sequence.gy_scale=0.5 --set sequence.gz_scale=0.5 \
   --set sequence.output=seq/tse_centre10.seq
./osii.sh run seq/tse_centre10.seq
```

## [bench]: bench-test sequences

| key | default | used by |
|---|---|---|
| `grad_fraction` | 0.1 | All `bench_grad_*`: amplitude as a fraction of OCRA1 FS (0.1 = 1.0 V = 1.5 A) |
| `grad_rise_us`, `grad_flat_us`, `grad_gap_us`, `grad_repeats` | 250, 2000, 5000, 20 | Trapezoid shape and repetition |
| `grad_hold_ms` | 500 | `bench_grad_hold_*`: DC plateau length |
| `rf_fraction`, `rf_duration_us`, `rf_period_us`, `rf_repeats` | 0.1, 200, 10000, 50 | `bench_rf_pulses`, `bench_rf_loopback` |
| `loopback_dwell_us`, `loopback_pad_us` | 3.125, 50 | ADC dwell and window padding for `bench_rf_loopback` |
| `tse_debug_tr`, `tse_debug_tr_ms` | 0, 500 | Which TR the `bench_tse_1tr*` files use, and their TR |

## [run]

| key | default | meaning |
|---|---|---|
| `seq_file` | seq/tse_3d_t2_marcos.seq | Default file for info/plot/compile/run |
| `grad_t_us` | 10 | Gradient raster: the step marga_pulseq uses to sample trapezoid ramps. Must be ≥ the OCRA1 frame time that `info` prints |
| `grad_snap_us` | 10 | Puts the updates of all gradient channels on one shared grid. Needed with OCRA1 (see SEQUENCE_NOTES §3.4). 0 = off |
| `repeat`, `repeat_pause_s` | 1, 0 | Run the file N times, for scope work |
| `scope_trigger` | tr | Extra `trig_out` pulse: `none`, `sequence` (start), `tr` (each excitation), or `rf` (every pulse). It is aligned with the rising edge of tx_gate |
| `scope_trigger_width_us` | 10 | |
| `rx_gate_follows_adc` | yes | Drive `rx_gate` high while the ADC is open |
| `auto_leds` | yes | SDRLab LEDs count up during the sequence |
| `output_dir`, `reports_dir` | data, reports | |
| `plot_start_ms`, `plot_stop_ms` | 0, 40 | Window for `plot` and for the timing table |

## Using your own Pulseq file

Any Pulseq 1.4 file with trapezoid gradients can go through the converter:

```bash
./osii.sh make tse --set sequence.source=/path/my.seq --set sequence.output=seq/my_marcos.seq
```

The converter removes extensions/labels (marga_pulseq rejects them) and inserts the tx_gate warm-up. If needed, it also oversamples the ADC. TRs are split at the RF event used in the first RF block. Arbitrary `[GRADIENTS]` waveforms are not supported by the converter.
