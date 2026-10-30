# Bench tests: debugging and validating OCRA1, GA2, RFPA, T/R switch and RX

These procedures use the sequences in `seq/bench_*.seq` and standard lab equipment. They complement the hardware bring-up gates (G0–G4) in *Test & Validation Procedures — OCRA1, GA2 Gradient Amplifier, 1 kW RFPA*. Do G0/G1 (inspection, power-on) on each board first. The tests here are the MaRCoS-driven G2/G3 functional checks plus the integration checks.

**Equipment:**

- 4-channel scope, ≥100 MHz;
- DC current probe ≥20 A, or the GA2 Vmon output;
- 6½-digit DMM;
- 50 Ω dummy load, ≥100 W continuous, flat to 12 MHz;
- a ≥50 dB attenuator chain for looking at RFPA output;
- 30–60 dB of SMA attenuators for loopback;
- gradient dummy loads: 36–213 µH plus 0.15–0.4 Ω, e.g. the GA2 test loads 36 µH + 152 mΩ or 213 µH + 316 mΩ;
- a precision 5.0 V buffer for the RFPA enable.

**For every test:**

1. Run `./osii.sh info <file>` and `./osii.sh plot <file>`. Use `reports/<file>_timing.csv` as the expected-value sheet.
2. Trigger the scope on `trig_out` (rising), or on OCRA1 **TXGATE**. Time 0 on the timing sheet is the start of the sequence. The trigger coincides with the first `tx_gate HIGH` row of each TR in the CSV (920 µs for the TSE files).
3. Use `--set run.repeat=N` so the scope sees a steady pattern.

Default bench levels (`[bench]` in `config.ini`, regenerate with `./osii.sh make bench` after changing):

| file | what it does | expected (defaults) |
|---|---|---|
| `bench_rf_pulses` | 50 × 200 µs hard pulses, 10 ms period, tx_gate leads by `tx_warmup_us` | TX at 0.1 FS, 2 % duty |
| `bench_rf_loopback` | Same, plus an ADC window from 50 µs before to 50 µs after each pulse (3.125 µs dwell) | 96 samples per pulse |
| `bench_grad_x/y/z` | 20 × (+trapezoid, gap, −trapezoid, gap); 250 µs ramps, 2 ms flat | ±1.000 V OCRA1 → ±1.50 A GA2 |
| `bench_grad_xyz` | X, then Y, then Z positive trapezoids | +1.000 V on each in turn |
| `bench_grad_hold_x/y/z` | One 500 ms plateau | +1.000 V, +1.50 A (DMM) |
| `bench_tse_1tr` | One TSE TR (TR 0: ky edge), TR 500 ms, all channels | Exactly the full-TSE waveforms |
| `bench_tse_1tr_rf_only` | Same TR, RF + tx_gate + ADC only | |
| `bench_tse_1tr_grad_only` | Same TR, gradients + ADC only | |

---

## 1. SDRLab and MaRCoS (no amplifiers connected)

**1.1 Communication.**

```bash
./osii.sh run seq/bench_rf_pulses.seq
```

The server terminal should show the connection, and the host should print `done`. Pass: no `server error` lines.

**1.2 TX output and gate timing.** Connect the scope:

- CH1 to SDRLab OUT1, terminated in 50 Ω;
- CH2 to OCRA1 J20 TXGATE (high-Z);
- CH3 to trig_out.

Then run `bench_rf_pulses` with `--set run.repeat=20`.

Pass criteria:

- **Bursts:** 200 µs RF bursts, every 10.000 ms.
- **Carrier:** the RF frequency inside the burst is `larmor_freq_Hz` (2.100 MHz). Check with the scope's FFT/frequency counter.
- **Gate lead:** TXGATE goes high `tx_warmup_us` (100 µs) before the burst and low at its end (±1 µs).
- **Gate level:** TXGATE is 3.3 V logic.
- **Between bursts:** OUT1 shows no carrier leakage. Look at a sensitive vertical scale, or on a spectrum analyser.

**1.3 TX amplitude linearity (also needed before connecting the RFPA).** Measure OUT1 Vpp into 50 Ω for `rf_fraction` = 0.05, 0.1, 0.2, 0.5:

```bash
./osii.sh make bench --set bench.rf_fraction=0.2 && ./osii.sh run seq/bench_rf_pulses.seq
```

Pass: Vpp is proportional to the fraction, within a few %. Write down the **Vpp at FS** (V_FS). The RFPA reaches ~1 kW at ~1.1 Vpp input, so:

```
P_out ≈ 1 kW × (fraction × V_FS / 1.1 V)²
```

If you use the OCRA1 PE43704 attenuator in the TX path, include its loss.

**1.4 RX loopback (validates RX, LO and timing).** Connect OUT1 → 40 dB attenuator → IN1 (adjust the attenuation so IN1 stays well below ADC full scale). Then:

```bash
./osii.sh run seq/bench_rf_loopback.seq && ./osii.sh view
```

Pass criteria:

- **Shape:** each ADC window shows about 16 baseline samples (50 µs), a flat 200 µs pulse (~64 samples) and about 16 baseline samples.
- **Repeatability:** all 50 windows look identical.
- **Phase:** the phase is constant across the pulse and from pulse to pulse, because TX and RX share the NCO.
- **Linearity:** the amplitude scales with `rf_fraction`.

Repeat with `larmor_freq_Hz` changed by +1 kHz: the RX phase must stay constant (shared NCO).

---

## 2. OCRA1 (scope / DMM on the BNC outputs; GA2 not connected)

**2.1 Channel identity and polarity.**

```bash
./osii.sh run seq/bench_grad_xyz.seq --set run.repeat=5
```

Put the scope on J5 (X), J25 (Y) and J26 (Z). Pass:

- +1.000 V trapezoids appear on X, then Y, then Z, each 2.5 ms long with 250 µs ramps;
- the other channels stay at 0 V; any cross-talk is below the noise.

Then run `bench_grad_x` (repeat for y and z). Pass: you see +1 V and then −1 V.

**2.2 DC accuracy.** Run `bench_grad_hold_x` (and y, z) and measure the plateau with the DMM. Expected: +1.0000 V (0.1 FS). Repeat at other levels:

```bash
./osii.sh make bench --set bench.grad_fraction=0.5    # expect 5.000 V
```

Test & Validation G3 asks for an LSB of 76.3 µV and INL/DNL from ≥17 points. Run a sweep of `grad_fraction` from −0.9 to 0.9 and log the DMM readings. With `init_ocra1 = yes`, each run starts and ends at 0 V.

**2.3 Update rate and ramp shape.** Run `bench_tse_1tr_grad_only` and compare with `reports/bench_tse_1tr_grad_only_timing.csv`. Pass criteria:

- **Levels:** plateaus are X 4.695 V, Y −4.503 V, Z 7.097 V (TR 0, default calibration).
- **Ramps:** ramps are staircases of 10 µs steps (`grad_t_us`) with no missing steps.
- **Server:** no `ocra1 gradient error` message in the server output.

**2.4 Gradient-to-RF latency.** Run `bench_tse_1tr` (all channels). Trigger on TXGATE, and measure the time between:

- the end of the 90° tx_gate (CH TXGATE falling edge, at 1220 µs on the timing sheet);
- the start of the X prephaser ramp (block start 1250 µs; first ramp step on the 10 µs grid at about 1260 µs).

The MaRCoS simulator shows OCRA1 outputs about 1.8 µs after the nominal grid time. On hardware, add the OCRA1 output filter and the GA2 delay (measure in §3). Put the total in `[hardware] grad_latency_us` to align gradients with RF/ADC.

---

## 3. GA2 gradient amplifier (dummy load, then coil)

Prerequisites:

- GA2 is biased and passed G1 (Test & Validation §GA2);
- the output is connected to a dummy load: 213 µH + 316 mΩ is closest to a real coil;
- OCRA1 BNC → GA2 Vin;
- current probe on the load lead, or scope on Vmon (10 V = 15 A, i.e. 0.667 V/A).

**3.1 Gain and polarity.** Run `bench_grad_hold_x` at `grad_fraction` 0.1. Expected: +1.50 A (Vmon about +1.0 V). Pass criteria:

- **Gain:** within 2 % of 1.5 A/V (the design document measured 1.52 A/V).
- **Sign.** If the current is negative, set `x_polarity = -1` in `[gradient_mapping]` (or swap the coil leads) and note it. Repeat for Y and Z.

**3.2 Linearity.** Sweep `grad_fraction` over 0.05, 0.1, 0.2, 0.4 and 0.6 (0.075 A … 9 A), using the hold file. Keep each hold ≤ 500 ms and allow cool-down.

**3.3 Dynamic response.** Run `bench_grad_x` (250 µs ramps, ±1.5 A) with `run.repeat=10`. Pass criteria:

- the current follows the 250 µs ramps;
- overshoot is <5 % with no ringing (the GA2 rise time is 50 µs and its bandwidth is 7 kHz);
- the tracking delay from OCRA1 V to current is constant. Record it for `grad_latency_us`.

**3.4 TSE gradients.** Run `bench_tse_1tr_grad_only` with `run.repeat=10`, at TR 500 ms. Compare the current plateaus with the timing CSV (amps column):

| Axis | Plateau | Expected |
|---|---|---|
| X | prephaser | 7.04 A |
| X | readout | 4.70 A |
| Y | phase encode | ±6.75 A |
| Z | crushers | 10.65 A |

Check that the crusher pairs around each 180° are identical; spin-echo crusher symmetry matters.

**3.5 Duty and thermal.** The full TSE at TR 1.25 s runs about 4.5 % duty on Z, so it is safe for the GA2 (30 % limit). For a soak test, run the full sequence (`./osii.sh run`) and monitor the heatsink temperature (alarm at 72 °C).

**3.6 Noise at Larmor.** With the GA2 enabled and idle, sequence running with `gx/gy/gz_scale = 0`, look at the output noise around 2.1 MHz on the spectrum analyser. The Test & Validation reference build measured −123 dBm/Hz.

---

## 4. RFPA (50 Ω dummy load only)

Prerequisites:

- the RFPA has passed bring-up (bias about 2.7 V);
- RFPA output → ≥100 W 50 Ω dummy load, with a ≥50 dB coupler/attenuator to the scope;
- **RFPA enable = TXGATE through a 5.0 V ±1 % buffer;**
- SDRLab OUT1 → RFPA input.

**Never run without the load. Keep duty ≤10 % and pulses ≤20 ms.**

**4.1 Gating.** Set `rf_scale` to low power: `./osii.sh make bench --set bench.rf_fraction=0.02`, then run `bench_rf_pulses`. Pass criteria:

- **Output timing:** RF output appears only inside the enable window.
- **Blanking delay:** enable → output active within ≤0.5 µs. Measure at the leading edge; it is well within the 100 µs `tx_warmup_us`.
- **Blanked noise:** the output noise when blanked is at the noise floor.

**4.2 Gain and compression.** Step `rf_fraction` so the RFPA input is 0.25, 0.4, 0.6, 0.8 and 1.0 Vpp, using the V_FS measured in §1.3. Expected output is about 130 / 300 / 530 / 830 / ~1000 W peak (Test & Validation RFPA power steps). Pass: gain is about 54–55 dB and the compression knee is at ≥800 W. Keep `rf_period_us` ≥ 10 × `rf_duration_us`.

**4.3 TSE pulse train.** Run `bench_tse_1tr_rf_only` with the RFPA. It contains one 90° and fourteen 180° pulses, with 13 ms spacing and the 180° pulses at 90° phase. Pass criteria:

- the 180° output is 2× the 90° output, ±2 %;
- the RF phase steps by 90° between the 90° and the 180° pulses (look at it in loopback through the attenuator into RX, using `bench_rf_loopback`-style checks);
- there is no droop across the train. The supply sag with 15 × 200 µs is negligible, but check it.

---

## 5. T/R switch

Prerequisites:

- T/R J8 "TX" ← RFPA (start with the RFPA off, driving J8 from SDRLab OUT1 through the attenuator, at mW level);
- J9 "Antenna" → 50 Ω load;
- J6 "RX" → scope (50 Ω), or SDRLab IN1 through ≥20 dB attenuation;
- J10 TXgate ← OCRA1 TXGATE;
- LNA powered.

**5.1 Control polarity and switching time.** Run `bench_rf_pulses`, with the scope on TXGATE, the PIN diode bias (PIN1/PIN2 test points) and the RX port. Pass criteria:

- **Polarity:** TXgate HIGH puts the switch in transmit (PIN diodes forward-biased).
- **Switching time:** measure TXgate rising edge → PIN current settled. The TLP387 optocouplers are slow, so this may take tens of µs. **Set `tx_warmup_us` to at least 2× this time** and regenerate.

**5.2 Isolation in TX.** With RF on J8 and the load on J9, compare the RX-port level with the TX level. Expected: high isolation (record it in dB). The RX side is protected by the λ/4 network and the BAV99 clamp.

**5.3 Insertion loss.** In TX, measure J8 → J9. In RX, inject a small 2.1 MHz signal into J9 with TXgate low and measure J9 → J6, which includes the LNA gain.

**5.4 Recovery.** Run `bench_rf_loopback` with the T/R switch in the RX path. Time from TXgate falling to the RX baseline settling: the TSE's first ADC opens ~5.3 ms after each refocusing pulse ends, so recovery must be ≪ 5 ms. Pass: the baseline is back to noise level within ≪ 1 ms.

---

## 6. Full chain (coil + phantom)

1. **Larmor frequency.** Run `bench_rf_loopback` with the coil, the T/R switch and a phantom, at a low `rf_fraction`. Look for the FID after the pulse; extend `loopback_pad_us` to e.g. 5000 µs to see it. Adjust `larmor_freq_Hz` until the FID has no beat, i.e. the phase is constant.
2. **RF calibration.** Sweep `rf_fraction` (or run the TSE with `rf_scale`) and find the 90°. Put it in `[rf_calibration] rf_90_fraction`.
3. **Single TR.** Run `bench_tse_1tr` (or regenerate it with `tse_debug_tr = 220` for the k-space centre) and `./osii.sh view`. You should see 14 echoes whose peak amplitude decays (T2).
4. **Full sequence.** `./osii.sh run` (550 s). The data and k-space ordering are described in RUNNING.md §6.

## Results log template

| Test | Date | Setting | Expected | Measured | Pass |
|---|---|---|---|---|---|
| 1.2 TX freq | | larmor 2.100 MHz | 2.1000 MHz | | |
| 1.2 gate lead | | tx_warmup 100 µs | 100 µs | | |
| 1.3 V_FS | | fraction 1.0 | (record) | | |
| 2.2 X DC 0.1 FS | | | 1.0000 V | | |
| 3.1 X gain | | 1.0 V | 1.50 A | | |
| 3.3 X ramp | | 250 µs | tracks, <5 % OS | | |
| 4.2 RFPA gain | | 1.1 Vpp in | ~1 kW | | |
| 5.1 T/R switch time | | | (record) | | |
