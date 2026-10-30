#!/usr/bin/env python3
"""
Interpret a .seq with marga_pulseq and inspect / compile / run it on MaRCoS.

  python tools/run_seq.py info    [seq]   expected levels + timing table, no hardware
  python tools/run_seq.py plot    [seq]   waveform plot (PNG in reports/), no hardware
  python tools/run_seq.py compile [seq]   full MaRCoS compile offline (catches OCRA1
                                          update-rate problems), no hardware
  python tools/run_seq.py run     [seq]   run on the SDRLab and save RX data

[seq] defaults to [run] seq_file in config.ini. Options:
  --config FILE           alternative config file
  --set sec.key=value     override a config value (repeatable)
  --show                  open the plot window as well as saving the PNG
"""

import argparse
import csv
import datetime
import json
import os
import sys
import time
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Config, pkg_path, add_vendor_paths   # noqa: E402
import pulseq_io                                        # noqa: E402

AXES = ('x', 'y', 'z')


# --------------------------------------------------------------------------
def interpret(cfg, seq_file):
    add_vendor_paths()
    from marga_pulseq.interpreter import PSInterpreter

    gmax = cfg.grad_max_hz_per_m()
    rf_max = cfg.rf_amp_max_hz()
    rep = pkg_path(cfg.get('run', 'reports_dir', 'reports'))
    os.makedirs(rep, exist_ok=True)
    ps = PSInterpreter(rf_center=cfg.larmor_hz(), rf_amp_max=rf_max,
                       gx_max=gmax['x'], gy_max=gmax['y'], gz_max=gmax['z'],
                       grad_t=cfg.float('run', 'grad_t_us'),
                       log_file=os.path.join(rep, 'ps_interpreter'))
    t0 = time.time()
    try:
        out, params = ps.interpret(seq_file)
    except AssertionError as e:
        msg = str(e)
        hint = ''
        if 'larger than' in msg and 'max' in msg:
            hint = ('\n -> a gradient exceeds OCRA1 full scale with the current '
                    '[gradient_calibration]; raise efficiency/gain or scale the sequence down.')
        elif 'too large relative to RF max' in msg:
            hint = ('\n -> an RF pulse exceeds TX full scale; lower [rf_calibration] '
                    'rf_90_fraction (must be <= 0.5 for 180 deg pulses) or rf_scale.')
        elif 'warmup' in msg.lower():
            hint = '\n -> regenerate the .seq with make_seq.py (it sets tx_warmup in the file).'
        elif 'ext id' in msg:
            hint = ('\n -> the file has Pulseq extensions/labels, which marga_pulseq rejects. '
                    'Convert it with tools/make_seq.py first.')
        sys.exit('marga_pulseq error: %s%s' % (msg, hint))
    print('interpreted in %.1f s' % (time.time() - t0))
    return out, params


def scope_triggers(cfg, seq_file):
    """Times (us) for an extra trig_out pulse, from the .seq block structure."""
    mode = cfg.get('run', 'scope_trigger', 'none').lower()
    if mode == 'none':
        return None
    seq = pulseq_io.read(seq_file)
    warm = float(seq.definitions.get('tx_warmup', '500'))
    starts, total = seq.block_starts_us()
    if mode == 'sequence':
        times = [0.0]
    else:
        rf_blocks = [(s, b) for s, b in zip(starts, seq.blocks) if b['rf']]
        if not rf_blocks:
            times = [0.0]
        else:
            exc = rf_blocks[0][1]['rf']
            times = [s + seq.rf[b['rf']]['delay'] - warm for s, b in rf_blocks
                     if mode == 'rf' or b['rf'] == exc]
    w = cfg.float('run', 'scope_trigger_width_us', 10)
    t = np.array([[x, x + w] for x in times]).ravel()
    v = np.tile([1, 0], len(times))
    return t, v


def snap_to_grid(t, v, grid):
    """Put every gradient update on a common time grid (multiples of grid us from the
    sequence start). OCRA1 sends all four channels in one SPI frame, so updates on
    different channels must be either simultaneous or >= one frame (~3.9 us) apart;
    trapezoids with different ramp times otherwise interleave a few us apart and
    samples get dropped. Moves each ramp sample by at most grid/2."""
    if not grid:
        return t, v
    tq = np.round(np.asarray(t) / grid) * grid
    keep = np.append(tq[1:] != tq[:-1], True)          # same slot: last value wins
    tq, vq = tq[keep], np.asarray(v)[keep]
    chg = np.concatenate([[True], vq[1:] != vq[:-1]])  # drop repeats
    return tq[chg], vq[chg]


def build_flodict(cfg, out):
    """Map interpreter output onto MaRCoS channels (axis mapping, polarity, gates)."""
    fd = {'tx0': out['tx0'], 'rx0_en': out['rx0_en'], 'tx_gate': out['tx_gate']}
    used = set()
    for ax in AXES:
        ch = cfg.get('gradient_mapping', '%s_channel' % ax, 'v' + ax)
        pol = cfg.float('gradient_mapping', '%s_polarity' % ax, 1)
        if ch not in ('vx', 'vy', 'vz', 'vz2') or ch in used:
            sys.exit('[gradient_mapping] %s_channel=%s invalid or used twice' % (ax, ch))
        used.add(ch)
        t, v = snap_to_grid(*out['grad_v' + ax], cfg.float('run', 'grad_snap_us', 0))
        fd['grad_' + ch] = (t, pol * v)
    if cfg.bool('run', 'rx_gate_follows_adc', 'no'):
        fd['rx_gate'] = out['rx0_en']
    return fd


def ocra1_min_spacing_us(cfg):
    rate = cfg.float('hardware', 'grad_max_update_rate', 0.2)
    clk = cfg.float('hardware', 'fpga_clk_freq_MHz', 122.88)
    spi_div = min(int(np.floor(1 / (30 * rate / clk))) - 1, 63)
    return (24 * (1 + spi_div) + 2) / clk


# --------------------------------------------------------------------------
def summarize(cfg, seq_file, out, params, fd):
    gmax = cfg.grad_max_hz_per_m()
    rf_max = cfg.rf_amp_max_hz()
    vfs = cfg.float('gradient_calibration', 'ocra1_full_scale_V', 10)
    gain = cfg.float('gradient_calibration', 'amp_gain_A_per_V', 1.5)
    dur = max(v[0][-1] for v in out.values())
    print('\n=== %s' % os.path.relpath(seq_file))
    print('duration            : %.3f s' % (dur * 1e-6))
    print('readout samples     : %d   (rx dwell %.4g us -> %.4g kHz BW)'
          % (params['readout_number'], params['rx_t'] or 0,
             1e3 / params['rx_t'] if params['rx_t'] else 0))
    print('LO / Larmor         : %.6f MHz' % (cfg.larmor_hz() / 1e6))
    print('RF full scale       : %.1f Hz B1' % rf_max)
    tx = np.abs(out['tx0'][1])
    print('RF peak             : %.4f of TX full scale (%.1f Hz B1)' % (tx.max(), tx.max() * rf_max))
    for lvl in sorted(set(np.round(tx[tx > 0], 4))):
        print('   RF level         : %.4f FS  -> %.1f Hz -> %.1f deg per 200 us'
              % (lvl, lvl * rf_max, 360 * lvl * rf_max * 200e-6))
    ng = int(np.sum(np.diff(out['tx_gate'][1]) > 0))
    print('tx_gate pulses      : %d' % ng)
    print('ADC windows         : %d' % int(np.sum(np.diff(out['rx0_en'][1]) > 0)))
    print('gradients (logical axis -> OCRA1 channel):')
    for ax in AXES:
        ch = cfg.get('gradient_mapping', '%s_channel' % ax, 'v' + ax)
        t, v = fd['grad_' + ch]
        pk = np.max(np.abs(v)) if len(v) else 0
        dts = np.diff(t[np.abs(np.diff(np.concatenate([[0], v]))) > 0]) if len(v) > 1 else []
        mind = np.min(dts) if len(dts) else float('nan')
        print('   %s -> %-4s full scale %9.0f Hz/m (%.3f mT/m) | peak %.4f FS = %6.3f V = %6.2f A '
              '| min update spacing %.2f us'
              % (ax.upper(), ch, gmax[ax], gmax[ax] / 42.577478e3, pk, pk * vfs, pk * vfs * gain, mind))
    lim = ocra1_min_spacing_us(cfg)
    print('OCRA1 SPI frame time: %.2f us (grad_max_update_rate=%s); updates closer than this '
          'are dropped' % (lim, cfg.get('hardware', 'grad_max_update_rate')))
    if cfg.float('run', 'grad_t_us') < lim:
        print('   !! WARNING: [run] grad_t_us is below the OCRA1 frame time')


def edges(t, v, thr=1e-9):
    d = np.abs(np.diff(np.concatenate([[0], v]))) > thr
    return t[d], v[d]


def timing_table(cfg, out, fd, path, t_lo, t_hi):
    """Event list in a time window, for comparing against the oscilloscope."""
    rf_max = cfg.rf_amp_max_hz()
    vfs = cfg.float('gradient_calibration', 'ocra1_full_scale_V', 10)
    gain = cfg.float('gradient_calibration', 'amp_gain_A_per_V', 1.5)
    rows = []
    for name in ('tx_gate', 'rx0_en', 'rx_gate'):
        if name in fd:
            t, v = edges(*fd[name])
            for a, b in zip(t, v):
                rows.append((a, name, 'HIGH' if b else 'LOW', ''))
    t, v = edges(out['tx0'][0], np.abs(out['tx0'][1]))
    ph = out['tx0'][1]
    for a, b in zip(t, v):
        p = np.angle(ph[np.searchsorted(out['tx0'][0], a)]) if b else 0
        rows.append((a, 'tx0 (RF)', '%.4f FS' % b if b else 'OFF',
                     '%.1f Hz B1, phase %.1f deg' % (b * rf_max, np.degrees(p)) if b else ''))
    for ax in AXES:
        ch = cfg.get('gradient_mapping', '%s_channel' % ax, 'v' + ax)
        t, v = fd['grad_' + ch]
        # report plateaus only (value held > 50 us), plus returns to zero
        for i in range(len(t) - 1):
            hold = t[i + 1] - t[i]
            if (hold > 50 or v[i] == 0) and (i == 0 or v[i] != v[i - 1]):
                rows.append((t[i], 'G%s (%s)' % (ax, ch), '%.4f FS' % v[i],
                             '%.3f V, %.3f A, held %.0f us' % (v[i] * vfs, v[i] * vfs * gain, hold)))
    rows = sorted(r for r in rows if t_lo <= r[0] <= t_hi)
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_us', 'channel', 'level', 'detail'])
        for r in rows:
            w.writerow(['%.3f' % r[0]] + list(r[1:]))
    return len(rows)


def plot(cfg, out, fd, path, t_lo, t_hi, show):
    import matplotlib
    if not show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    vfs = cfg.float('gradient_calibration', 'ocra1_full_scale_V', 10)
    fig, axs = plt.subplots(4, 1, figsize=(14, 9), sharex=True)
    ms = lambda t: np.asarray(t) / 1000.0

    def step(ax, t, v, **kw):
        sel = (t >= t_lo - 1) & (t <= t_hi + 1)
        i0 = max(np.argmax(sel) - 1, 0) if sel.any() else 0
        tt = np.concatenate([t[i0:][t[i0:] <= t_hi + 1], [t_hi]])
        vv = np.concatenate([v[i0:][t[i0:] <= t_hi + 1], [v[i0:][t[i0:] <= t_hi + 1][-1]]])
        ax.step(ms(tt), vv, where='post', **kw)

    t, v = out['tx0']
    step(axs[0], t, np.abs(v), label='|tx0| (FS)')
    step(axs[0], t, v.real, label='I', alpha=0.5)
    step(axs[0], t, v.imag, label='Q', alpha=0.5)
    for ax in AXES:
        ch = cfg.get('gradient_mapping', '%s_channel' % ax, 'v' + ax)
        t, v = fd['grad_' + ch]
        step(axs[1], t, v * vfs, label='G%s -> %s (V at OCRA1)' % (ax, ch))
    step(axs[2], *fd['rx0_en'], label='rx0_en (ADC)')
    if 'rx_gate' in fd:
        step(axs[2], fd['rx_gate'][0], fd['rx_gate'][1] * 0.8, label='rx_gate x0.8')
    step(axs[3], *fd['tx_gate'], label='tx_gate (TXGATE BNC)')
    if 'trig_out' in fd:
        step(axs[3], fd['trig_out'][0], fd['trig_out'][1] * 0.6, label='trig_out x0.6')
    for a, yl in zip(axs, ('TX (fraction FS)', 'OCRA1 out (V)', 'RX', 'gates')):
        a.set_ylabel(yl)
        a.grid(True)
        a.legend(loc='upper right', fontsize=8)
    axs[-1].set_xlabel('time from sequence start (ms)')
    axs[-1].set_xlim(t_lo / 1000, t_hi / 1000)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    if show:
        plt.show()


# --------------------------------------------------------------------------
def make_device(cfg, rx_t, offline):
    add_vendor_paths()
    from device import Device
    kw = dict(ip_address=cfg.get('network', 'ip_address'), port=cfg.int('network', 'port'),
              fpga_clk_freq_MHz=cfg.float('hardware', 'fpga_clk_freq_MHz'),
              grad_board=cfg.get('hardware', 'grad_board'),
              lo_freq=cfg.larmor_hz() / 1e6, rx_t=rx_t,
              grad_max_update_rate=cfg.float('hardware', 'grad_max_update_rate'),
              grad_latency=cfg.float('hardware', 'grad_latency_us', 0),
              auto_leds=cfg.bool('run', 'auto_leds', 'yes'),
              print_infos=True, assert_errors=False)
    if offline:
        kw.update(prev_socket=object(), init_gpa=False, halt_and_reset=False)
    else:
        kw.update(init_gpa=cfg.bool('hardware', 'init_ocra1', 'yes'),
                  halt_and_reset=cfg.bool('hardware', 'halt_and_reset', 'yes'))
    return Device(**kw)


def compile_check(cfg, fd, rx_t):
    add_vendor_paths()
    from marmachine import MarGradWarning
    dev = make_device(cfg, rx_t, offline=True)
    dev.add_flodict(fd)
    t0 = time.time()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        dev.compile()
    grad_w = [x for x in w if issubclass(x.category, MarGradWarning)]
    other = [x for x in w if not issubclass(x.category, MarGradWarning)]
    # marcompile compares the FIRST gradient update against a fictitious update at
    # cycle 0; with the default initial wait (1 + 1/rate us) minus the 268-cycle OCRA1
    # latency this always trips one MSB + one LSB warning that has no effect. Discount it.
    clk = cfg.float('hardware', 'fpga_clk_freq_MHz')
    rate = cfg.float('hardware', 'grad_max_update_rate')
    gk = [k for k in fd if k.startswith('grad_')]
    if gk and grad_w:
        t_first = min(fd[k][0][0] for k in gk)
        first_cyc = round((t_first + 1 + 1 / rate) * clk) - 268
        if first_cyc < ocra1_min_spacing_us(cfg) * clk:
            grad_w = grad_w[2:]
    print('MaRCoS compile OK: %d instructions (%.1f MB) in %.1f s'
          % (len(dev._machine_code), dev._machine_code.nbytes / 1e6, time.time() - t0))
    if grad_w:
        print('!! %d OCRA1 update-rate warnings: gradient samples would be dropped. '
              'Increase [run] grad_t_us or [hardware] grad_max_update_rate.' % len(grad_w))
    for x in other[:10]:
        print('compiler warning:', x.message)
    return not grad_w


def run_hw(cfg, seq_file, fd, params, n_rep):
    outdir = pkg_path(cfg.get('run', 'output_dir', 'data'))
    os.makedirs(outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(seq_file))[0]
    order_csv = os.path.splitext(seq_file)[0] + '_order.csv'
    nexp = params['readout_number']
    seq = pulseq_io.read(seq_file)
    adc_lens = [seq.adc[b['adc']]['num'] for b in seq.blocks if b['adc']]
    pause = cfg.float('run', 'repeat_pause_s', 0)
    for k in range(n_rep):
        dev = make_device(cfg, params['rx_t'] or 10, offline=False)
        dev.add_flodict(fd)
        print('[%d/%d] running %s (%.1f s) ...' % (k + 1, n_rep, name,
                                                  max(v[0][-1] for v in fd.values()) * 1e-6))
        t0 = time.time()
        rxd, msgs = dev.run()
        print('    done in %.1f s' % (time.time() - t0))
        for kind in ('errors', 'warnings'):
            for m in msgs.get(kind, []):
                print('    server %s: %s' % (kind[:-1], m))
        rx = rxd.get('rx0', np.zeros(0, complex))
        print('    received %d samples (expected %d)' % (len(rx), nexp))
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        f = os.path.join(outdir, '%s_%s_rep%d.npz' % (name, stamp, k))
        extra = {}
        if len(set(adc_lens)) == 1 and len(rx) >= nexp and nexp:
            extra['rx0_adc'] = rx[:nexp].reshape(len(adc_lens), adc_lens[0])
            ovs = int(float(seq.definitions.get('adc_oversampling', '1')))
            if ovs > 1 and adc_lens[0] % ovs == 0:
                # boxcar-average groups of ovs samples -> original dwell / sample count
                extra['rx0_adc_decimated'] = extra['rx0_adc'].reshape(
                    len(adc_lens), adc_lens[0] // ovs, ovs).mean(axis=2)
        elif nexp and len(rx) != nexp:
            print('    !! sample count mismatch: raw data saved unreshaped')
        np.savez(f, rx0=rx, rx1=rxd.get('rx1', np.zeros(0, complex)), rx_t_us=params['rx_t'],
                 larmor_Hz=cfg.larmor_hz(), seq_file=seq_file,
                 config=open(cfg.path).read(), params=json.dumps(params, default=str),
                 server_msgs=json.dumps(msgs, default=str), **extra)
        print('    saved %s' % os.path.relpath(f))
        if os.path.isfile(order_csv):
            print('    acquisition order: %s' % os.path.relpath(order_csv))
        del dev
        if k + 1 < n_rep and pause:
            time.sleep(pause)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=('info', 'plot', 'compile', 'run'))
    ap.add_argument('seq', nargs='?', help='.seq file (default [run] seq_file)')
    ap.add_argument('--config')
    ap.add_argument('--set', action='append', metavar='SECTION.KEY=VALUE')
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()

    if a.config:
        os.environ['OSII_CONFIG'] = os.path.abspath(a.config)
    cfg = Config(a.config)
    cfg.override(a.set)
    seq_file = pkg_path(a.seq or cfg.get('run', 'seq_file'))
    if not os.path.isfile(seq_file) and a.seq and os.path.isfile(a.seq):
        seq_file = os.path.abspath(a.seq)
    if not os.path.isfile(seq_file):
        sys.exit('No such .seq file: %s (run tools/make_seq.py all first?)' % seq_file)

    out, params = interpret(cfg, seq_file)
    fd = build_flodict(cfg, out)
    trig = scope_triggers(cfg, seq_file)
    if trig is not None:
        fd['trig_out'] = trig
    summarize(cfg, seq_file, out, params, fd)

    rep = pkg_path(cfg.get('run', 'reports_dir', 'reports'))
    name = os.path.splitext(os.path.basename(seq_file))[0]
    t_lo = cfg.float('run', 'plot_start_ms', 0) * 1000
    t_hi = cfg.float('run', 'plot_stop_ms', 40) * 1000
    tt = os.path.join(rep, name + '_timing.csv')
    n = timing_table(cfg, out, fd, tt, t_lo, t_hi)
    print('timing table        : %s (%d events in %g-%g ms)' % (os.path.relpath(tt), n, t_lo / 1e3, t_hi / 1e3))

    if a.mode == 'plot':
        png = os.path.join(rep, name + '_plot.png')
        plot(cfg, out, fd, png, t_lo, t_hi, a.show)
        print('plot                : %s' % os.path.relpath(png))
    elif a.mode == 'compile':
        ok = compile_check(cfg, fd, params['rx_t'] or 10)
        sys.exit(0 if ok else 2)
    elif a.mode == 'run':
        run_hw(cfg, seq_file, fd, params, cfg.int('run', 'repeat', 1))


if __name__ == '__main__':
    main()
