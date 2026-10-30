"""
Minimal, dependency-free Pulseq 1.4.x reader / writer.

Only the subset of the format that marga_pulseq understands is supported:
[VERSION] [DEFINITIONS] [BLOCKS] [RF] [GRADIENTS] [TRAP] [ADC] [SHAPES].
[EXTENSIONS] are read (kept as raw text) but are never written, because
marga_pulseq rejects any block whose extension id is non-zero.

Units follow the Pulseq 1.4 file format:
  block duration : integer multiples of BlockDurationRaster (normally 1 us)
  RF amplitude    : Hz            RF delay  : us (int)
  TRAP amplitude  : Hz/m          rise/flat/fall/delay : us
  ADC dwell       : ns            ADC delay : us (int)
"""

import hashlib
from collections import OrderedDict


class Seq:
    def __init__(self):
        self.version = (1, 4, 2)
        self.definitions = OrderedDict()   # name -> string value (as written)
        self.blocks = []                   # list of dicts: dur rf gx gy gz adc ext
        self.rf = OrderedDict()            # id -> dict amp mag_id phase_id time_id delay freq phase
        self.grad = OrderedDict()          # id -> dict amp shape_id time_id delay   (arbitrary grads)
        self.trap = OrderedDict()          # id -> dict amp rise flat fall delay
        self.adc = OrderedDict()           # id -> dict num dwell delay freq phase
        self.shapes = OrderedDict()        # id -> (num_samples, [raw values as written])
        self.extensions_raw = []           # raw lines (informational only)

    # ------------------------------------------------------------------ helpers
    def block_raster_us(self):
        return float(self.definitions.get('BlockDurationRaster', '1e-06')) * 1e6

    def block_starts_us(self):
        """Absolute start time (us) of every block plus the total duration."""
        r = self.block_raster_us()
        t, starts = 0.0, []
        for b in self.blocks:
            starts.append(t)
            t += b['dur'] * r
        return starts, t

    def shape_values(self, shape_id):
        """Decompress a shape (Pulseq run-length/derivative compression)."""
        n, raw = self.shapes[shape_id]
        vals = [float(v) for v in raw]
        if len(vals) == n:
            return vals
        out, x, prev, i = [], 0.0, None, 0
        while len(out) < n:
            d = vals[i]; i += 1
            x += d; out.append(x)
            if prev is not None and d == prev:
                r = int(vals[i]); i += 1
                for _ in range(r):
                    x += d; out.append(x)
                prev = None
            else:
                prev = d
        return out

    def rf_duration_us(self, rf_id):
        """Duration of the RF waveform itself (excluding delay)."""
        ev = self.rf[rf_id]
        rr = float(self.definitions.get('RadiofrequencyRasterTime', '1e-06')) * 1e6
        if ev['time_id']:
            return max(self.shape_values(ev['time_id'])) * rr
        return self.shapes[ev['mag_id']][0] * rr

    def block_content_end_us(self, b):
        """Latest end time of any event inside block b (relative to block start)."""
        end = 0.0
        if b['rf']:
            ev = self.rf[b['rf']]
            end = max(end, ev['delay'] + self.rf_duration_us(b['rf']))
        for ax in ('gx', 'gy', 'gz'):
            gid = b[ax]
            if gid and gid in self.trap:
                t = self.trap[gid]
                if t['amp'] != 0:
                    end = max(end, t['delay'] + t['rise'] + t['flat'] + t['fall'])
            elif gid and gid in self.grad:
                g = self.grad[gid]
                gr = float(self.definitions.get('GradientRasterTime', '1e-05')) * 1e6
                end = max(end, g['delay'] + len(self.shape_values(g['shape_id'])) * gr)
        if b['adc']:
            a = self.adc[b['adc']]
            end = max(end, a['delay'] + a['num'] * a['dwell'] / 1000.0)
        return end

    def total_duration_us(self):
        return self.block_starts_us()[1]


# ---------------------------------------------------------------------- reading
def _clean(line):
    i = line.find('#')
    if i >= 0:
        line = line[:i]
    return line.strip()


def read(path):
    seq = Seq()
    section = None
    lines = open(path, 'r').read().split('\n')
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = _clean(raw)
        i += 1
        if s.startswith('['):
            section = s
            continue
        if not s and section != '[SHAPES]':
            continue
        t = s.split()
        if section == '[VERSION]':
            if t[0] == 'major':
                seq.version = (int(t[1]),) + seq.version[1:]
            elif t[0] == 'minor':
                seq.version = (seq.version[0], int(t[1]), seq.version[2])
            elif t[0] == 'revision':
                seq.version = seq.version[:2] + (int(t[1]),)
        elif section == '[DEFINITIONS]':
            seq.definitions[t[0]] = ' '.join(t[1:])
        elif section == '[BLOCKS]':
            v = [int(x) for x in t] + [0] * (8 - len(t))
            seq.blocks.append(dict(dur=v[1], rf=v[2], gx=v[3], gy=v[4], gz=v[5], adc=v[6], ext=v[7]))
        elif section == '[RF]':
            seq.rf[int(t[0])] = dict(amp=float(t[1]), mag_id=int(t[2]), phase_id=int(t[3]),
                                     time_id=int(t[4]), delay=int(t[5]), freq=float(t[6]),
                                     phase=float(t[7]))
        elif section == '[GRADIENTS]':
            seq.grad[int(t[0])] = dict(amp=float(t[1]), shape_id=int(t[2]), time_id=int(t[3]),
                                       delay=int(t[4]) if len(t) > 4 else 0)
        elif section == '[TRAP]':
            seq.trap[int(t[0])] = dict(amp=float(t[1]), rise=int(t[2]), flat=int(t[3]),
                                       fall=int(t[4]), delay=int(float(t[5])) if len(t) > 5 else 0)
        elif section == '[ADC]':
            seq.adc[int(t[0])] = dict(num=int(t[1]), dwell=float(t[2]), delay=int(t[3]),
                                      freq=float(t[4]), phase=float(t[5]))
        elif section == '[EXTENSIONS]':
            seq.extensions_raw.append(s)
        elif section == '[SHAPES]':
            if t and t[0] == 'shape_id':
                sid = int(t[1])
                n = int(_clean(lines[i]).split()[1]); i += 1
                vals = []
                while i < len(lines):
                    v = _clean(lines[i])
                    if not v or v.startswith('['):
                        break
                    vals.append(v); i += 1
                seq.shapes[sid] = (n, vals)
    return seq


# ---------------------------------------------------------------------- writing
def _fmt(x):
    """Compact number formatting, integers written without decimals."""
    if float(x).is_integer():
        return str(int(x))
    return '%.9g' % x


def write(seq, path, header_comments=()):
    o = []
    o.append('# Pulseq sequence file')
    o.append('# Written by osii_marcos_tse/tools/pulseq_io.py (marga_pulseq compatible)')
    for c in header_comments:
        o.append('# ' + c)
    o.append('')
    o.append('[VERSION]')
    o.append('major %d' % seq.version[0])
    o.append('minor %d' % seq.version[1])
    o.append('revision %d' % seq.version[2])
    o.append('')
    o.append('[DEFINITIONS]')
    for k, v in seq.definitions.items():
        o.append('%s %s' % (k, v))
    o.append('')
    o.append('# Format of blocks:')
    o.append('# NUM DUR RF  GX  GY  GZ  ADC  EXT')
    o.append('[BLOCKS]')
    for n, b in enumerate(seq.blocks, 1):
        o.append('%d %d %d %d %d %d %d %d' % (n, b['dur'], b['rf'], b['gx'], b['gy'], b['gz'],
                                             b['adc'], b['ext']))
    o.append('')
    if seq.rf:
        o.append('# Format of RF events:')
        o.append('# id amplitude mag_id phase_id time_shape_id delay freq phase')
        o.append('# ..        Hz   ....     ....          ....    us   Hz   rad')
        o.append('[RF]')
        for k, r in seq.rf.items():
            o.append('%d %s %d %d %d %d %s %s' % (k, _fmt(r['amp']), r['mag_id'], r['phase_id'],
                                                  r['time_id'], r['delay'], _fmt(r['freq']),
                                                  _fmt(r['phase'])))
        o.append('')
    if seq.grad:
        o.append('# Format of arbitrary gradients:')
        o.append('# id amplitude amp_shape_id time_shape_id delay')
        o.append('[GRADIENTS]')
        for k, g in seq.grad.items():
            o.append('%d %s %d %d %d' % (k, _fmt(g['amp']), g['shape_id'], g['time_id'], g['delay']))
        o.append('')
    if seq.trap:
        o.append('# Format of trapezoid gradients:')
        o.append('# id amplitude rise flat fall delay')
        o.append('# ..      Hz/m   us   us   us    us')
        o.append('[TRAP]')
        for k, t in seq.trap.items():
            o.append('%d %s %d %d %d %d' % (k, _fmt(t['amp']), t['rise'], t['flat'], t['fall'],
                                            t['delay']))
        o.append('')
    if seq.adc:
        o.append('# Format of ADC events:')
        o.append('# id num dwell delay freq phase')
        o.append('# ..  ..    ns    us   Hz   rad')
        o.append('[ADC]')
        for k, a in seq.adc.items():
            o.append('%d %d %s %d %s %s' % (k, a['num'], _fmt(a['dwell']), a['delay'],
                                            _fmt(a['freq']), _fmt(a['phase'])))
        o.append('')
    if seq.shapes:
        o.append('# Sequence Shapes')
        o.append('[SHAPES]')
        o.append('')
        for k, (n, vals) in seq.shapes.items():
            o.append('shape_id %d' % k)
            o.append('num_samples %d' % n)
            o.extend(str(v) for v in vals)
            o.append('')     # marga_pulseq needs a blank line after every shape
    body = '\n'.join(o) + '\n'
    # Pulseq signature: md5 of everything before the newline that precedes [SIGNATURE]
    md5 = hashlib.md5(body.encode()).hexdigest()
    sig = ('\n[SIGNATURE]\n'
           '# This is the hash of the Pulseq file, calculated right before the [SIGNATURE] section was added\n'
           '# It can be reproduced/verified with md5sum if the file trimmed to the position right above [SIGNATURE]\n'
           '# The new line character preceding [SIGNATURE] BELONGS to the signature (and needs to be stripped away for recalculating/verification)\n'
           'Type md5\n'
           'Hash %s\n' % md5)
    with open(path, 'w', newline='\n') as f:
        f.write(body + sig)
    return md5
