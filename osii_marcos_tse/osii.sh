#!/usr/bin/env bash
# Wrapper: ./osii.sh make  all|tse|bench           [--set sec.key=val ...]
#          ./osii.sh info|plot|compile|run [file.seq] [--set ...] [--show]
#          ./osii.sh check  [converted.seq]          (equivalence with the original)
#          ./osii.sh view   [data/file.npz]          (quick look at RX data)
cd "$(dirname "$0")"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
cmd=$1; shift
case "$cmd" in
  make)                   exec "$PY" tools/make_seq.py "$@" ;;
  info|plot|compile|run)  exec "$PY" tools/run_seq.py "$cmd" "$@" ;;
  check)                  exec "$PY" tools/check_equivalence.py "$@" ;;
  view)                   exec "$PY" tools/view_rx.py "$@" ;;
  *) sed -n '2,6p' "$0"; exit 1 ;;
esac
