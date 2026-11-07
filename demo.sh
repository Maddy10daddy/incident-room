#!/usr/bin/env bash
# One-command demo driver.
#   ./demo.sh up      shop v1.0 on :8081, ops panel on :8090, steady traffic, ops-sentinel watching
#   ./demo.sh break   push update v1.1 (the buggy release), same as the panel's red button
#   ./demo.sh fix     BACKUP: ship the prepared fix v1.1.1 (skips the agents)
#   ./demo.sh status  what is running now
#   ./demo.sh down    stop everything
#   ./demo.sh reset   down + wipe run/ so the next take starts clean
set -euo pipefail
cd "$(dirname "$0")"
RUN="${INCIDENT_RUN_DIR:-$PWD/run}"
mkdir -p "$RUN"

alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }

start_bg() {  # name, command...
  local name=$1; shift
  alive "$name" && return
  nohup "$@" >"$RUN/$name.out" 2>&1 &
  echo $! >"$RUN/$name.pid"
}

stop_bg() {
  for name in loadgen sentinel panel shop; do
    if [ -f "$RUN/$name.pid" ]; then kill "$(cat "$RUN/$name.pid")" 2>/dev/null || true; rm -f "$RUN/$name.pid"; fi
  done
}

case "${1:-}" in
  up)
    python3 deployctl.py init
    start_bg panel python3 ops/panel.py
    start_bg loadgen python3 loadgen.py
    start_bg sentinel python3 sentinel/sentinel.py
    echo "shop:  http://localhost:${PORT:-8081}"
    echo "panel: http://localhost:${PANEL_PORT:-8090}"
    ;;
  break)  python3 deployctl.py push v1.1 ;;
  fix)    python3 deployctl.py push v1.1.1 ;;
  status) python3 deployctl.py status; tail -2 "$RUN/sentinel.out" 2>/dev/null || true ;;
  down)   stop_bg ;;
  reset)  stop_bg; rm -rf "$RUN"; echo "reset" ;;
  *) sed -n 2,9p "$0"; exit 1 ;;
esac
