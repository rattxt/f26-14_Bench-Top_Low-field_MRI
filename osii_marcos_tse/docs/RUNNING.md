# Running sequences: step by step

All commands are run from the package folder. On Windows, replace `./osii.sh` with `osii.bat`.

## What happens when you run a sequence

```
.seq ──marga_pulseq──► time/value arrays per channel (tx0, grad_vx/vy/vz, rx0_en, tx_gate)
     ──run_seq.py────► axis→OCRA1 channel mapping, polarity, gradient grid snap,
                       + trig_out (scope trigger), + rx_gate (= ADC window)
     ──marcos_client─► MaRCoS machine code (Device.compile)
     ──TCP 11111─────► marcos_server on the SDRLab streams it to the marga FPGA
                       and returns the RX samples ──► data/<seq>_<time>_rep<k>.npz
```

`marga_pulseq` does the following:

- converts RF amplitudes (Hz) to TX fractions;
- converts gradients (Hz/m) to OCRA1 fractions and samples trapezoid ramps every `grad_t_us`;
- raises `tx_gate` `tx_warmup` µs before each RF pulse and drops it when the pulse ends;
- opens `rx0_en` for each ADC event.

The SDRLab's NCO mixes TX0 up to `larmor_freq_Hz`. RX0 is mixed down with the same NCO and decimated to the ADC dwell.

## Step 1: check the file (no hardware)

```bash
./osii.sh info seq/bench_tse_1tr.seq
```

Example output with the default config:

```
duration            : 0.501 s
readout samples     : 1232   (rx dwell 25 us -> 40 kHz BW)
LO / Larmor         : 2.100000 MHz
RF full scale       : 12500.0 Hz B1
   RF level         : 0.1000 FS  -> 1250.0 Hz -> 90.0 deg per 200 us
   RF level         : 0.2000 FS  -> 2500.0 Hz -> 180.0 deg per 200 us
tx_gate pulses      : 15
ADC windows         : 14
   X -> vx   full scale 319331 Hz/m (7.500 mT/m) | peak 0.4695 FS =  4.695 V =   7.04 A | ...
   Y -> vy   ...                                 | peak 0.4503 FS =  4.503 V =   6.75 A
   Z -> vz   ...                                 | peak 0.7097 FS =  7.097 V =  10.65 A
OCRA1 SPI frame time: 3.92 us ...
timing table        : reports/bench_tse_1tr_timing.csv
```

`reports/<name>_timing.csv` lists every edge and plateau in the plot window with its expected level:

- tx_gate, RF on/off with amplitude and phase;
- every gradient plateau in FS, volts and amps;
- ADC windows.

**Use this table as your checklist against the oscilloscope.** All times are measured from the start of the sequence. On the scope, trigger on `trig_out` (it rises with the first tx_gate edge of each TR) or on TXGATE.

## Step 2: look at the waveforms (no hardware)

```bash
./osii.sh plot seq/bench_tse_1tr.seq --set run.plot_stop_ms=30      # PNG in reports/
./osii.sh plot seq/bench_tse_1tr.seq --show                           # also open a window
```

## Step 3: compile offline (no hardware)

```bash
./osii.sh compile                      # full TSE: ~2.9 M instructions, ~15-30 s
```

This runs the full MaRCoS compiler. It catches gradient updates that come too fast for the OCRA1 SPI link; those samples would be dropped silently on hardware. It must end with `MaRCoS compile OK` and no `!!` lines. The exit code is 0 if OK and 2 if there are update-rate problems.

## Step 4: start the SDRLab

On the SDRLab, run `/root/marcos/start_marcos.sh` (SETUP.md §2.3) and keep that terminal open.

Before powering the amplifiers:

- the GA2 and RFPA should be off, or connected to dummy loads;
- `init_ocra1 = yes` sets all OCRA1 outputs to 0 V when the client connects.

## Step 5: run

```bash
./osii.sh run seq/bench_rf_pulses.seq                 # first: RF only, no amplifiers
./osii.sh run seq/bench_grad_x.seq --set run.repeat=10
./osii.sh run seq/bench_tse_1tr.seq --set run.repeat=20 --set run.repeat_pause_s=0.5
./osii.sh run                                         # full TSE, 550 s
```

Each run does the following:

1. connects;
2. optionally halts any old sequence and resets the OCRA1;
3. sends the program;
4. waits for it to finish. The server streams long sequences into the FPGA memory as they run;
5. prints any server warnings or errors, plus the received and expected sample counts;
6. saves the data.

To abort a long run, press Ctrl-C on the host. Then restart `marcos_server` (Ctrl-C and start it again) and run again; `halt_and_reset` stops any leftover sequence.

## Step 6: data

Each run writes one file, `data/<seq>_<YYYYmmdd_HHMMSS>_rep<k>.npz`:

| array | contents |
|---|---|
| `rx0` | All RX0 samples (complex, arbitrary units), in acquisition order |
| `rx0_adc` | Reshaped as `[n_adc, samples_per_adc]` (only when the count matches) |
| `rx0_adc_decimated` | `rx0_adc` with the ADC oversampling averaged out: `[6160, 44]` for the TSE, at the original 50 µs dwell |
| `rx1` | RX1 (unused, normally empty) |
| `rx_t_us`, `larmor_Hz`, `seq_file` | Acquisition parameters |
| `config` | The full `config.ini` text used for the run |
| `params`, `server_msgs` | marga_pulseq parameters and server messages (JSON) |

`seq/<name>_order.csv` maps ADC number to TR, echo number (0–13), ky index (−22…21) and kz index (−5…4). Use it to sort the TSE into k-space: `kspace[echo, kz, ky, :] = rx0_adc_decimated[adc_index]`.

For a quick look, run `./osii.sh view [file]`. It writes `<file>_view.png` with:

- the whole RX record;
- the ADC windows overlaid;
- the mean echo peak against echo number, which is the T2 decay for the TSE.

Python example:

```python
import numpy as np, csv
d = np.load('data/tse_3d_t2_marcos_..._rep0.npz')
s = d['rx0_adc_decimated']                         # (6160, 44)
rows = list(csv.DictReader(open('seq/tse_3d_t2_marcos_order.csv')))
k = np.zeros((14, 10, 44, 44), complex)
for r in rows:
    k[int(r['echo']), int(r['kz_index']) + 5, int(r['ky_index']) + 22] = s[int(r['adc_index'])]
img_echo0 = np.fft.fftshift(np.fft.ifftn(np.fft.ifftshift(k[0])))
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ConnectionRefusedError` | Server not running, wrong IP, or firewall. `ping` the SDRLab and restart `start_marcos.sh` |
| `marga_pulseq error: Invalid ext id` | The file has Pulseq labels (e.g. the original Nexus file). Convert it: `./osii.sh make tse` |
| `Tx warmup (…) is longer than delay` | The file was not made with this converter, or `tx_warmup` changed. Regenerate with `make` |
| `Gradient event … is larger than gx max` | The sequence needs more than OCRA1 full scale with the current calibration. Check the efficiencies, or use `g?_scale` |
| `Magnitude of RF event … too large` | `rf_90_fraction` > 0.5, or `rf_scale` too high |
| `RX rate outside valid range` | ADC dwell > 33.3 µs. Regenerate with `adc_oversampling = 0` (auto) |
| `!! … OCRA1 update-rate warnings` in compile | Raise `grad_t_us`, keep `grad_snap_us = grad_t_us`, or raise `grad_max_update_rate` |
| Server: `ocra1 gradient error; possibly missing samples` | Same as above, on hardware |
| Server: `RX FIFO/s full` | RX data rate too high for the network/CPU. Use a longer dwell or a shorter ADC |
| Fewer RX samples than expected | The sequence was aborted, or the FIFO overflowed. The raw data is still saved, unreshaped |
| No RF at OUT1 | Check the `larmor_freq_Hz` scope frequency, `rf_scale`, and that the bitstream loaded (server started without errors) |
| Gradients lag RF/ADC on the scope | Set `grad_latency_us` to the measured delay (BENCH_TESTS §2.4) |
| Plot or CSV shows `Gx … held` with odd values | Ramps are sampled every `grad_t_us`; only plateaus longer than 50 µs are listed |
