#!/usr/bin/env python3
"""
Build marga_pulseq / MaRCoS compatible .seq files.

  python tools/make_seq.py tse     # convert the OSII/Nexus TSE file per [sequence] in config.ini
  python tools/make_seq.py bench   # write the bench-test sequences per [bench]
  python tools/make_seq.py all     # both

Any config value can be overridden on the command line, e.g.
  python tools/make_seq.py tse --set sequence.n_tr=1 --set sequence.tr_ms=200 \
                               --set sequence.output=seq/tse_1tr.seq

Standard library only.
"""

import argparse
import copy
import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulseq_io                                    # noqa: E402
from common import Config, pkg_path                 # noqa: E402


# --------------------------------------------------------------------------
#  Intermediate representation: each block carries full event dicts, not ids
# --------------------------------------------------------------------------
def expand_blocks(seq):
    out = []
    for b in seq.blocks:
        e = dict(dur=b['dur'] * seq.block_raster_us())
        e['rf'] = copy.deepcopy(seq.rf[b['rf']]) if b['rf'] else None
        if e['rf']:
            e['rf']['src_id'] = b['rf']
        for ax in ('gx', 'gy', 'gz'):
            gid = b[ax]
            if gid and gid in seq.trap:
                e[ax] = dict(kind='trap', **seq.trap[gid])
            elif gid:
                e[ax] = dict(kind='grad', **seq.grad[gid])
            else:
                e[ax] = None
        e['adc'] = copy.deepcopy(seq.adc[b['adc']]) if b['adc'] else None
        out.append(e)
    return out


def is_empty(b):
    return not (b['rf'] or b['gx'] or b['gy'] or b['gz'] or b['adc'])


def content_end(b, src):
    """End time (us, block-relative) of the last event in an expanded block."""
    end = 0.0
    if b['rf']:
        end = max(end, b['rf']['delay'] + rf_len_us(b['rf'], src))
    for ax in ('gx', 'gy', 'gz'):
        g = b[ax]
        if g and g['kind'] == 'trap' and g['amp'] != 0:
            end = max(end, g['delay'] + g['rise'] + g['flat'] + g['fall'])
        elif g and g['kind'] == 'grad':
            raise SystemExit('Arbitrary [GRADIENTS] are not handled by this converter')
    if b['adc']:
        a = b['adc']
        end = max(end, a['delay'] + a['num'] * a['dwell'] / 1000.0)
    return end


def rf_len_us(rf, src):
    rr = float(src.definitions.get('RadiofrequencyRasterTime', '1e-06')) * 1e6
    if rf['time_id']:
        return max(src.shape_values(rf['time_id'])) * rr
    return src.shapes[rf['mag_id']][0] * rr


def trap_area(g):
    """Gradient moment of a trapezoid in 1/m."""
    if not g or g['kind'] != 'trap':
        return 0.0
    return g['amp'] * (g['rise'] / 2.0 + g['flat'] + g['fall'] / 2.0) * 1e-6


# --------------------------------------------------------------------------
#  Writer: dedupe events, assign ids, build Seq
# --------------------------------------------------------------------------
class Builder:
    def __init__(self, definitions, src=None):
        self.seq = pulseq_io.Seq()
        self.seq.definitions.update(definitions)
        self.src = src
        self._shape_map = {}

    def _shape(self, n, vals):
        key = (n, tuple(vals))
        if key not in self._shape_map:
            sid = len(self.seq.shapes) + 1
            self.seq.shapes[sid] = (n, list(vals))
            self._shape_map[key] = sid
        return self._shape_map[key]

    def _src_shape(self, sid):
        n, vals = self.src.shapes[sid]
        return self._shape(n, vals)

    @staticmethod
    def _dedupe(table, ev):
        for k, v in table.items():
            if v == ev:
                return k
        k = len(table) + 1
        table[k] = ev
        return k

    def hard_pulse(self, amp_hz, dur_us, delay_us, phase_rad=0.0):
        """Rectangular RF pulse (same representation as the OSII file)."""
        return dict(amp=float(amp_hz), delay=int(delay_us), freq=0.0, phase=float(phase_rad),
                    shapes=((2, ('1', '1')), (2, ('0', '0')), (2, ('0', str(int(dur_us))))))

    def add(self, b):
        rec = dict(dur=int(round(b['dur'])), rf=0, gx=0, gy=0, gz=0, adc=0, ext=0)
        if rec['dur'] != b['dur'] or rec['dur'] <= 0:
            raise SystemExit('Block duration %r us is not a positive integer' % b['dur'])
        rf = b.get('rf')
        if rf:
            if 'shapes' in rf:
                mag, ph, tm = (self._shape(n, v) for n, v in rf['shapes'])
            else:
                mag, ph = self._src_shape(rf['mag_id']), self._src_shape(rf['phase_id'])
                tm = self._src_shape(rf['time_id']) if rf['time_id'] else 0
            ev = dict(amp=rf['amp'], mag_id=mag, phase_id=ph, time_id=tm, delay=int(rf['delay']),
                      freq=rf['freq'], phase=rf['phase'])
            rec['rf'] = self._dedupe(self.seq.rf, ev)
        for ax in ('gx', 'gy', 'gz'):
            g = b.get(ax)
            if g:
                ev = dict(amp=g['amp'], rise=int(g['rise']), flat=int(g['flat']),
                          fall=int(g['fall']), delay=int(g['delay']))
                rec[ax] = self._dedupe(self.seq.trap, ev)
        a = b.get('adc')
        if a:
            ev = dict(num=int(a['num']), dwell=float(a['dwell']), delay=int(a['delay']),
                      freq=a['freq'], phase=a['phase'])
            rec['adc'] = self._dedupe(self.seq.adc, ev)
        self.seq.blocks.append(rec)

    def finish(self):
        total_s = self.seq.total_duration_us() * 1e-6
        self.seq.definitions['TotalDuration'] = '%.6g' % total_s
        return self.seq


def apply_tx_warmup(blocks, warmup_us, src):
    """Make every RF event start >= warmup_us after its block start, so that
    marga_pulseq can raise tx_gate warmup_us before the RF, WITHOUT moving any
    event in absolute time: the RF block is extended at its start and the
    preceding block is shortened by the same amount."""
    for i, b in enumerate(blocks):
        if not b['rf']:
            continue
        need = int(math.ceil(warmup_us - b['rf']['delay']))
        if need <= 0:
            continue
        if i == 0:
            raise SystemExit('RF in first block; a lead-in block is required')
        prev = blocks[i - 1]
        free = prev['dur'] - content_end(prev, src)
        if free < need:
            raise SystemExit(
                'tx_warmup_us=%g is too long: only %g us is free before the RF pulse in block %d. '
                'Reduce [sequence] tx_warmup_us.' % (warmup_us, free + b['rf']['delay'], i + 1))
        prev['dur'] -= need
        b['dur'] += need
        b['rf']['delay'] += need
        for ax in ('gx', 'gy', 'gz'):
            if b[ax]:
                b[ax]['delay'] += need
        if b['adc']:
            b['adc']['delay'] += need


# --------------------------------------------------------------------------
#  TSE conversion
# --------------------------------------------------------------------------
def convert_tse(cfg):
    S = 'sequence'
    src_path = pkg_path(cfg.get(S, 'source'))
    src = pulseq_io.read(src_path)
    if src.version[:2] != (1, 4):
        raise SystemExit('Only Pulseq 1.4.x sources are supported (got %s)' % (src.version,))
    blocks = expand_blocks(src)

    # ---- split into TRs at the excitation pulse (RF event of the first RF block)
    exc_id = next(b['rf']['src_id'] for b in blocks if b['rf'])
    starts = [i for i, b in enumerate(blocks) if b['rf'] and b['rf']['src_id'] == exc_id]
    preamble = blocks[:starts[0]]
    trs = [blocks[a:b] for a, b in zip(starts, starts[1:] + [len(blocks)])]
    n_src_tr = len(trs)

    first = cfg.int(S, 'first_tr', 0)
    n_tr = cfg.int(S, 'n_tr', 0) or (n_src_tr - first)
    if not (0 <= first < n_src_tr and first + n_tr <= n_src_tr):
        raise SystemExit('first_tr/n_tr out of range: source has %d TRs' % n_src_tr)
    tr_sel = list(range(first, first + n_tr))
    trs = [trs[i] for i in tr_sel]

    # ---- optional TR change: stretch/shrink the trailing pure-delay block
    tr_ms = cfg.float(S, 'tr_ms', 0)
    tr_src_us = sum(b['dur'] for b in trs[0])
    if tr_ms > 0:
        for tr in trs:
            if not is_empty(tr[-1]):
                raise SystemExit('Last block of the TR is not a pure delay; cannot change TR')
            core = sum(b['dur'] for b in tr[:-1])
            fill = tr_ms * 1000.0 - core
            if fill < 10 or fill != int(fill):
                raise SystemExit('tr_ms=%g is too short (min %.3f ms) or not a whole us'
                                 % (tr_ms, (core + 10) / 1000.0))
            tr[-1]['dur'] = fill

    # ---- per-channel scaling / disabling (bench testing)
    rf_scale = cfg.float(S, 'rf_scale', 1.0)
    gscale = {ax: cfg.float(S, '%s_scale' % ax, 1.0) for ax in ('gx', 'gy', 'gz')}
    adc_on = cfg.bool(S, 'adc_enable', 'yes')
    order_rows = []
    fov = [float(x) for x in src.definitions.get('FOV', '1 1 1').split()]
    for ti, tr in zip(tr_sel, trs):
        echo, last_pe = 0, (0.0, 0.0)
        for b in tr:
            # remember the most recent phase/partition encode (block with gy, no ADC, before ADC)
            if (b['gy'] or b['gz']) and not b['adc'] and not b['rf']:
                ay, az = trap_area(b['gy']), trap_area(b['gz'])
                if ay or az or (b['gy'] and b['gz']):
                    last_pe = (ay, az)
            if b['adc']:
                order_rows.append(dict(adc_index=len(order_rows), tr=ti, echo=echo,
                                       ky_area_per_m=round(last_pe[0], 4),
                                       kz_area_per_m=round(last_pe[1], 4),
                                       ky_index=int(round(last_pe[0] * fov[1])),
                                       kz_index=int(round(last_pe[1] * fov[2])),
                                       samples=b['adc']['num']))
                echo += 1
            if b['rf']:
                b['rf']['amp'] *= rf_scale
                if b['rf']['amp'] == 0:
                    b['rf'] = None
            for ax in ('gx', 'gy', 'gz'):
                if b[ax]:
                    b[ax]['amp'] *= gscale[ax]
                    if b[ax]['amp'] == 0:        # also removes the 0 Hz/m kz=0 partition trap
                        b[ax] = None
            if not adc_on:
                b['adc'] = None

    # ---- ADC dwell: the MaRCoS CIC decimator allows at most 4095 clocks (33.3 us at
    # 122.88 MHz). Longer dwells are replaced by N-times oversampling over the SAME
    # window (same delay, same duration); run_seq.py averages groups of N back down.
    clk = cfg.float('hardware', 'fpga_clk_freq_MHz', 122.88)
    max_dwell_ns = 4095 / clk * 1000
    ovs = cfg.int(S, 'adc_oversampling', 0)
    for b in (b for tr in trs for b in tr):
        a = b['adc']
        if not a:
            continue
        n = ovs or int(math.ceil(a['dwell'] / max_dwell_ns))
        if a['dwell'] / n > max_dwell_ns:
            raise SystemExit('adc_oversampling=%d leaves dwell %.1f us > %.2f us'
                             % (n, a['dwell'] / n / 1000, max_dwell_ns / 1000))
        a['num'] *= n
        a['dwell'] /= n
        a['oversampling'] = n
    ovs = max([b['adc'].get('oversampling', 1) for tr in trs for b in tr if b['adc']] or [1])
    for r in order_rows:
        r['samples_acquired'] = r['samples'] * ovs

    # ---- lead-in delay, then shift RF blocks to make room for the TX gate warm-up
    warm = cfg.float(S, 'tx_warmup_us')
    lead = max(cfg.float(S, 'lead_in_us', 1000), warm + 10)
    lead = float(int(math.ceil(lead)))
    out_blocks = [dict(dur=lead, rf=None, gx=None, gy=None, gz=None, adc=None)]
    out_blocks += preamble + [b for tr in trs for b in tr]
    apply_tx_warmup(out_blocks, warm, src)

    # ---- definitions: keep the standard Pulseq ones, drop label-related, add ours
    defs = {}
    for k, v in src.definitions.items():
        defs[k] = v
    name = cfg.get(S, 'name', src.definitions.get('Name', 'seq') + '_marcos')
    defs['Name'] = name
    if tr_ms > 0:
        defs['TR'] = '%.6g' % (tr_ms * 1e-3)
    defs['tx_warmup'] = '%g' % warm          # read by marga_pulseq (overrides its default)
    defs['marcos_lead_in_us'] = '%g' % lead
    defs['adc_oversampling'] = str(ovs)
    defs['source_first_tr'] = str(first)
    defs['source_n_tr'] = str(n_tr)

    bld = Builder(defs, src)
    for b in out_blocks:
        bld.add(b)
    seq = bld.finish()

    info = dict(src_path=src_path, n_src_tr=n_src_tr, n_tr=n_tr, first=first,
                tr_src_us=tr_src_us, lead_in_us=lead, warmup_us=warm, exc_id=exc_id)
    return seq, order_rows, info


def write_order_csv(rows, path):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['adc_index'])
        w.writeheader()
        w.writerows(rows)


def cmd_tse(cfg):
    seq, rows, info = convert_tse(cfg)
    out = pkg_path(cfg.get('sequence', 'output'))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    md5 = pulseq_io.write(seq, out, header_comments=(
        'Converted from %s' % os.path.basename(info['src_path']),
        'TRs %d..%d of %d, lead-in %g us, tx_gate warm-up %g us'
        % (info['first'], info['first'] + info['n_tr'] - 1, info['n_src_tr'],
           info['lead_in_us'], info['warmup_us']),
        'All RF/gradient/ADC events keep their original absolute timing (shifted by the lead-in).'))
    order = os.path.splitext(out)[0] + '_order.csv'
    write_order_csv(rows, order)
    print('wrote %s  (%d blocks, %.3f s, %d ADC events, md5 %s)'
          % (os.path.relpath(out), len(seq.blocks), seq.total_duration_us() * 1e-6, len(rows), md5))
    print('wrote %s' % os.path.relpath(order))
    return out


# --------------------------------------------------------------------------
#  Bench test sequences
# --------------------------------------------------------------------------
def std_defs(name, cfg):
    return {'tx_warmup': '%g' % cfg.float('sequence', 'tx_warmup_us'),'AdcRasterTime': '1e-06', 'BlockDurationRaster': '1e-06',
            'GradientRasterTime': '1e-06', 'RadiofrequencyRasterTime': '1e-06', 'Name': name}


def empty(dur):
    return dict(dur=float(dur), rf=None, gx=None, gy=None, gz=None, adc=None)


def write_bench(bld, name, comments):
    seq = bld.finish()
    out = pkg_path(os.path.join('seq', name + '.seq'))
    pulseq_io.write(seq, out, header_comments=comments)
    print('wrote %s  (%d blocks, %.3f s)' % (os.path.relpath(out), len(seq.blocks),
                                            seq.total_duration_us() * 1e-6))


def trap(amp, rise, flat, fall=None, delay=0):
    return dict(kind='trap', amp=float(amp), rise=int(rise), flat=int(flat),
                fall=int(rise if fall is None else fall), delay=int(delay))


def bench_gradients(cfg):
    B = 'bench'
    gmax = cfg.grad_max_hz_per_m()
    frac = cfg.float(B, 'grad_fraction')
    rise, flat = cfg.int(B, 'grad_rise_us'), cfg.int(B, 'grad_flat_us')
    gap, reps = cfg.int(B, 'grad_gap_us'), cfg.int(B, 'grad_repeats')
    lead = 1000
    # one file per axis: +trap, gap, -trap, gap ... (polarity, linearity, ramp tracking)
    for ax in ('x', 'y', 'z'):
        bld = Builder(std_defs('bench_grad_%s' % ax, cfg))
        bld.add(empty(lead))
        amp = frac * gmax[ax]
        for _ in range(reps):
            for sgn in (+1, -1):
                b = empty(2 * rise + flat)
                b['g' + ax] = trap(sgn * amp, rise, flat)
                bld.add(b)
                bld.add(empty(gap))
        f, v, a = cfg.axis_volts_amps(ax, amp)
        write_bench(bld, 'bench_grad_%s' % ax, (
            'Bipolar trapezoid test on %s: +/-%.6g Hz/m = %.3f of full scale' % (ax.upper(), amp, f),
            'Expected OCRA1 output +/-%.3f V, amplifier current +/-%.3f A' % (v, a),
            'rise/fall %d us, flat %d us, gap %d us, %d repeats' % (rise, flat, gap, reps)))
    # all axes in turn: channel-mapping / cross-talk check (X, then Y, then Z)
    bld = Builder(std_defs('bench_grad_xyz', cfg))
    bld.add(empty(lead))
    for _ in range(reps):
        for ax in ('x', 'y', 'z'):
            b = empty(2 * rise + flat)
            b['g' + ax] = trap(frac * gmax[ax], rise, flat)
            bld.add(b)
            bld.add(empty(gap))
    write_bench(bld, 'bench_grad_xyz', ('X, then Y, then Z positive trapezoids at %.3f of full scale'
                                        % frac, 'Use to verify channel mapping and cross-talk'))
    # long DC hold on each axis (thermal / droop / DC accuracy with a DMM)
    hold_ms = cfg.float(B, 'grad_hold_ms')
    for ax in ('x', 'y', 'z'):
        bld = Builder(std_defs('bench_grad_hold_%s' % ax, cfg))
        bld.add(empty(lead))
        b = empty(2 * rise + int(hold_ms * 1000))
        b['g' + ax] = trap(frac * gmax[ax], rise, int(hold_ms * 1000))
        bld.add(b)
        bld.add(empty(gap))
        f, v, a = cfg.axis_volts_amps(ax, frac * gmax[ax])
        write_bench(bld, 'bench_grad_hold_%s' % ax, (
            'DC hold on %s for %g ms at %.3f of full scale (%.3f V, %.3f A expected)'
            % (ax.upper(), hold_ms, f, v, a),))


def bench_rf(cfg):
    B = 'bench'
    rfmax = cfg.rf_amp_max_hz()
    warm = cfg.float('sequence', 'tx_warmup_us')
    frac = cfg.float(B, 'rf_fraction')
    dur = cfg.int(B, 'rf_duration_us')
    period = cfg.int(B, 'rf_period_us')
    reps = cfg.int(B, 'rf_repeats')
    dwell_ns = cfg.float(B, 'loopback_dwell_us') * 1000
    pad = cfg.int(B, 'loopback_pad_us')
    lead = 1000
    d0 = int(math.ceil(max(warm, pad))) + 10            # RF delay inside the block
    rf_blk = d0 + dur + pad + 10
    if rf_blk > period:
        raise SystemExit('[bench] rf_period_us too short')

    # RF pulse train with ADC window around every pulse (TX->attenuator->RX loopback)
    bld = Builder(std_defs('bench_rf_loopback', cfg))
    bld.add(empty(lead))
    nadc = int((dur + 2 * pad) * 1000 // dwell_ns)
    for _ in range(reps):
        b = empty(rf_blk)
        b['rf'] = bld.hard_pulse(frac * rfmax, dur, d0)
        b['adc'] = dict(num=nadc, dwell=dwell_ns, delay=d0 - pad, freq=0.0, phase=0.0)
        bld.add(b)
        bld.add(empty(period - rf_blk))
    write_bench(bld, 'bench_rf_loopback', (
        'Hard pulse %.3f of TX full scale, %d us, every %d us, %d pulses' % (frac, dur, period, reps),
        'ADC (%d samples, %g us dwell) opens %d us before and closes %d us after each pulse'
        % (nadc, dwell_ns / 1000, pad, pad),
        'tx_gate leads the RF by %g us' % warm))

    # same pulses without ADC (RFPA into dummy load / T/R switch isolation)
    bld = Builder(std_defs('bench_rf_pulses', cfg))
    bld.add(empty(lead))
    for _ in range(reps):
        b = empty(d0 + dur + 10)
        b['rf'] = bld.hard_pulse(frac * rfmax, dur, d0)
        bld.add(b)
        bld.add(empty(period - (d0 + dur + 10)))
    write_bench(bld, 'bench_rf_pulses', (
        'Hard pulse %.3f of TX full scale, %d us, every %d us, %d pulses, no ADC' %
        (frac, dur, period, reps),))


def cmd_bench(cfg):
    bench_gradients(cfg)
    bench_rf(cfg)
    # TSE derived bench files: one TR at short TR, with and without gradients
    B = 'bench'
    variants = [
        ('tse_1tr', {}),
        ('tse_1tr_rf_only', {'gx_scale': '0', 'gy_scale': '0', 'gz_scale': '0'}),
        ('tse_1tr_grad_only', {'rf_scale': '0'}),
    ]
    for name, extra in variants:
        c = copy.deepcopy(cfg)
        c.cp.set('sequence', 'n_tr', '1')
        c.cp.set('sequence', 'first_tr', cfg.get(B, 'tse_debug_tr', '0'))
        c.cp.set('sequence', 'tr_ms', cfg.get(B, 'tse_debug_tr_ms'))
        c.cp.set('sequence', 'output', os.path.join('seq', 'bench_' + name + '.seq'))
        for k, v in extra.items():
            c.cp.set('sequence', k, v)
        cmd_tse(c)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('what', choices=('tse', 'bench', 'all'))
    ap.add_argument('--config', help='config file (default: config.ini in the package folder)')
    ap.add_argument('--set', action='append', metavar='SECTION.KEY=VALUE',
                    help='override a config value (repeatable)')
    a = ap.parse_args()
    cfg = Config(a.config)
    cfg.override(a.set)
    if a.what in ('tse', 'all'):
        cmd_tse(cfg)
    if a.what in ('bench', 'all'):
        cmd_bench(cfg)


if __name__ == '__main__':
    main()
