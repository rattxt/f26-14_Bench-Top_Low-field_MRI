# local_config.py for the vendored marcos_client.
#
# Upstream marcos_client expects you to edit this file by hand. In this package it
# simply reads ../../config.ini (or the file named in the OSII_CONFIG environment
# variable), so config.ini is the only file you need to edit.
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', 'tools'))
from common import Config as _Config  # noqa: E402

_cfg = _Config()
ip_address = _cfg.get('network', 'ip_address')
port = _cfg.int('network', 'port', 11111)
fpga_clk_freq_MHz = _cfg.float('hardware', 'fpga_clk_freq_MHz', 122.88)
grad_board = _cfg.get('hardware', 'grad_board', 'ocra1')
gpa_fhdo_current_per_volt = 2.5
