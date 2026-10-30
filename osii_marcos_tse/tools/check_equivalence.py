#!/usr/bin/env python3
"""
Prove that a converted .seq produces the same RF / gradient / ADC events as the
original OSII (Nexus) file, as seen by marga_pulseq.

  python tools/check_equivalence.py [converted.seq] [--source source/sequence.seq]

Both files are interpreted with the same marga_pulseq settings. The original is first
made loadable (extension ids set to 0, tx_warmup 0), then every channel of the
converted file is shifted back by its lead-in and compared sample by sample.
Expected and reported differences: tx_gate (new, by design) and the ADC sampling
(oversampled; same window).
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Config, pkg_path   # noqa: E402
import pulseq_io                      # noqa: E402
import run_seq                        # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('seq', nargs='?')
    ap.add_argument('--source')
    ap.add_argument('--config')
    ap.add_argument('--set', action='append')
    a = ap.parse_args()
    cfg = Config(a.config)
    cfg.override(a.set)
    conv = pkg_path(a.seq or cfg.get('sequence', 'output'))
    src_path = pkg_path(a.source or cfg.get('sequence', 'source'))

    c = pulseq_io.read(conv)
    lead = float(c.definitions['marcos_lead_in_us'])
    first = int(c.definitions.get('source_first_tr', '0'))
    ntr = int(c.definitions.get('source_n_tr', '0'))

    # make the original loadable by marga_pulseq, keeping only the same TRs
    s = pulseq_io.read(src_path)
    for b in s.blocks:
        b['ext'] = 0
    exc = next(b['rf'] for b in s.blocks if b['rf'])
    starts = [i for i, b in enumerate(s.blocks) if b['rf'] == exc] + [len(s.blocks)]
    s.blocks = s.blocks[:starts[0]] + s.blocks[starts[first]:starts[first + ntr]]
    s.definitions['tx_warmup'] = '0'
    rep = pkg_path(cfg.get('run', 'reports_dir', 'reports'))
    os.makedirs(rep, exist_ok=True)
    tmp = os.path.join(rep, '_source_sanitized.seq')
    pulseq_io.write(s, tmp)

    print('interpreting original ...')
    o_src, p_src = run_seq.interpret(cfg, tmp)
    print('interpreting converted ...')
    o_cnv, p_cnv = run_seq.interpret(cfg, conv)
    os.remove(tmp)

    ok = True
    for ch in ('tx0', 'grad_vx', 'grad_vy', 'grad_vz', 'rx0_en'):
        ts, vs = o_src[ch]
        tc, vc = o_cnv[ch]
        tc = tc - lead
        # drop the leading t=0 sample of each and the final "zero at end" marker
        ms, mc = ts > 0, tc > 0
        ts, vs, tc, vc = ts[ms][:-1], vs[ms][:-1], tc[mc][:-1], vc[mc][:-1]
        same = len(ts) == len(tc) and np.allclose(ts, tc, atol=1e-6) and np.allclose(vs, vc, atol=1e-9)
        ok &= same
        print('%-8s %7d events  %s' % (ch, len(ts), 'IDENTICAL timing and amplitude' if same
                                       else 'DIFFERENT (%d vs %d events)' % (len(ts), len(tc))))
    tg_t, tg_v = o_cnv['tx_gate']
    rf_t, rf_v = o_cnv['tx0']
    on = tg_t[np.diff(np.concatenate([[0], tg_v])) > 0]
    rf_on = rf_t[np.diff(np.concatenate([[0], np.abs(rf_v) > 0]).astype(int)) > 0]
    print('tx_gate  %7d pulses, lead before RF: %s us (new; not in the original)'
          % (len(on), np.unique(np.round(rf_on - on, 3))))
    print('ADC      original %d samples @ %g us, converted %d samples @ %g us (same windows)'
          % (p_src['readout_number'], p_src['rx_t'], p_cnv['readout_number'], p_cnv['rx_t']))
    print('total    original %.6f s, converted %.6f s (= original + %.0f us lead-in)'
          % (s.total_duration_us() * 1e-6, c.total_duration_us() * 1e-6, lead))
    print('RESULT: %s' % ('EQUIVALENT' if ok else 'NOT EQUIVALENT'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
