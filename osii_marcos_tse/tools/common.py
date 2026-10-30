"""
Shared helpers: package paths, config.ini loading and hardware calibration maths.
Standard library only (numpy is NOT needed here).
"""

import configparser
import os
import sys

GAMMA_HZ_PER_T = 42.577478e6          # 1H gyromagnetic ratio

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(PKG_DIR, 'config.ini')
VENDOR_DIR = os.path.join(PKG_DIR, 'vendor')


def pkg_path(p):
    """Resolve a path from config.ini: absolute paths are kept, relative ones are
    taken relative to the package folder (not the current working directory)."""
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(PKG_DIR, p)


class Config:
    """Thin wrapper around configparser with typed getters and clear errors."""

    def __init__(self, path=None):
        self.path = os.path.abspath(path or os.environ.get('OSII_CONFIG', DEFAULT_CONFIG))
        if not os.path.isfile(self.path):
            sys.exit('Config file not found: %s' % self.path)
        self.cp = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
        self.cp.optionxform = str
        self.cp.read(self.path)

    def get(self, sec, key, default=None):
        if self.cp.has_option(sec, key):
            return self.cp.get(sec, key).strip()
        if default is None:
            sys.exit('config.ini: missing [%s] %s' % (sec, key))
        return default

    def float(self, sec, key, default=None):
        v = self.get(sec, key, None if default is None else str(default))
        try:
            return float(v)
        except ValueError:
            sys.exit('config.ini: [%s] %s = %r is not a number' % (sec, key, v))

    def int(self, sec, key, default=None):
        return int(round(self.float(sec, key, default)))

    def bool(self, sec, key, default=None):
        v = self.get(sec, key, None if default is None else str(default)).lower()
        if v in ('1', 'yes', 'true', 'on'):
            return True
        if v in ('0', 'no', 'false', 'off'):
            return False
        sys.exit('config.ini: [%s] %s = %r is not yes/no' % (sec, key, v))

    def list(self, sec, key, default=None):
        return [x for x in self.get(sec, key, default).replace(',', ' ').split() if x]

    def override(self, items):
        """Apply 'section.key=value' overrides given on the command line."""
        for it in items or []:
            if '=' not in it or '.' not in it.split('=')[0]:
                sys.exit('Bad --set %r, use section.key=value' % it)
            k, v = it.split('=', 1)
            sec, key = k.split('.', 1)
            if not self.cp.has_section(sec):
                self.cp.add_section(sec)
            self.cp.set(sec, key, v)

    # ------------------------------------------------------------ calibration
    def grad_max_hz_per_m(self):
        """Gradient (Hz/m) produced when the OCRA1 channel is at +full-scale,
        per logical axis. This is the number marga_pulseq divides by."""
        mode = self.get('gradient_calibration', 'mode').lower()
        out = {}
        for ax in ('x', 'y', 'z'):
            if mode == 'direct':
                out[ax] = self.float('gradient_calibration', 'g%s_max_Hz_per_m' % ax)
            elif mode == 'physical':
                vfs = self.float('gradient_calibration', 'ocra1_full_scale_V')
                gain = self.float('gradient_calibration', 'amp_gain_A_per_V')
                eff = self.float('gradient_calibration', '%s_efficiency_mT_per_m_per_A' % ax)
                out[ax] = GAMMA_HZ_PER_T * eff * 1e-3 * gain * vfs
            else:
                sys.exit("config.ini: [gradient_calibration] mode must be 'physical' or 'direct'")
        return out

    def axis_volts_amps(self, ax, hz_per_m):
        """Convert a gradient amplitude (Hz/m) on a logical axis into
        (DAC fraction, OCRA1 volts, amplifier amps) for the printed expectations."""
        gmax = self.grad_max_hz_per_m()[ax]
        frac = hz_per_m / gmax
        vfs = self.float('gradient_calibration', 'ocra1_full_scale_V', 10.0)
        gain = self.float('gradient_calibration', 'amp_gain_A_per_V', 1.0)
        return frac, frac * vfs, frac * vfs * gain

    def rf_amp_max_hz(self):
        """B1 (Hz) produced at TX full-scale. marga_pulseq divides RF amplitudes by this."""
        mode = self.get('rf_calibration', 'mode').lower()
        if mode == 'direct':
            return self.float('rf_calibration', 'rf_amp_max_Hz')
        if mode == 'flip90':
            frac = self.float('rf_calibration', 'rf_90_fraction')
            dur = self.float('rf_calibration', 'rf_90_duration_us')
            b1_90 = 0.25 / (dur * 1e-6)        # hard pulse: flip = 360 deg * B1 * T
            return b1_90 / frac
        sys.exit("config.ini: [rf_calibration] mode must be 'flip90' or 'direct'")

    def larmor_hz(self):
        return self.float('hardware', 'larmor_freq_Hz')


def add_vendor_paths():
    """Make the vendored marcos_client and marga_pulseq importable."""
    for p in (os.path.join(VENDOR_DIR, 'marcos_client'), VENDOR_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
