#!/usr/bin/env python3
"""
Quick look at RX data saved by run_seq.py.

  python tools/view_rx.py                 # newest file in data/
  python tools/view_rx.py data/x.npz [--show]

Saves <file>_view.png next to the data:
  top    : |rx0| of the whole acquisition (all ADC windows concatenated)
  middle : first ADC windows overlaid (magnitude, real, imag)
  bottom : peak |signal| per echo, averaged over TRs (T2 decay curve for the TSE)
"""

import argparse
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import pkg_path   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file', nargs='?')
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()
    f = a.file or max(glob.glob(pkg_path('data/*.npz')) or [None], key=lambda p: os.path.getmtime(p) if p else 0)
    if not f:
        sys.exit('no data files in data/')
    d = np.load(f, allow_pickle=False)
    rx = d['rx0']
    print('%s: %d samples, dwell %s us, LO %.6f MHz' % (f, len(rx), d['rx_t_us'], float(d['larmor_Hz']) / 1e6))
    if len(rx) == 0:
        sys.exit('no samples')
    print('|rx0| max %.4g  mean %.4g  std(noise est., first 5%%) %.4g'
          % (np.abs(rx).max(), np.abs(rx).mean(), np.std(rx[:max(len(rx) // 20, 2)])))
    import matplotlib
    if not a.show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    adc = d['rx0_adc_decimated'] if 'rx0_adc_decimated' in d.files else (
        d['rx0_adc'] if 'rx0_adc' in d.files else None)
    fig, axs = plt.subplots(3 if adc is not None else 1, 1, figsize=(12, 9), squeeze=False)
    axs = axs[:, 0]
    axs[0].plot(np.abs(rx), lw=0.5)
    axs[0].set_title(os.path.basename(f))
    axs[0].set_xlabel('sample')
    axs[0].set_ylabel('|rx0|')
    if adc is not None:
        print('ADC windows: %d x %d samples' % adc.shape)
        for k in range(min(adc.shape[0], 14)):
            axs[1].plot(np.abs(adc[k]), label='win %d' % k if k < 5 else None)
        axs[1].set_ylabel('|rx0| per ADC window')
        axs[1].legend(fontsize=8)
        order = os.path.splitext(str(d['seq_file']))[0] + '_order.csv'
        if os.path.isfile(order):
            echo = np.genfromtxt(order, delimiter=',', names=True)['echo'].astype(int)[:adc.shape[0]]
            peaks = np.abs(adc).max(axis=1)
            e = np.unique(echo)
            axs[2].plot(e, [peaks[echo == k].mean() for k in e], 'o-')
            axs[2].set_xlabel('echo number')
            axs[2].set_ylabel('mean peak |rx0|')
        for ax in axs:
            ax.grid(True)
    fig.tight_layout()
    png = os.path.splitext(f)[0] + '_view.png'
    fig.savefig(png, dpi=100)
    print('saved', png)
    if a.show:
        plt.show()


if __name__ == '__main__':
    main()
