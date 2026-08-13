#!/bin/bash
# Starts a private Xvfb display, activates the billing-bot conda env, runs
# the given command inside it, and tears the display down afterward.
#
# Needed on servers where Xvfb was installed via
# `conda install -c conda-forge xorg-xvfb-server` — that package ships the
# Xvfb binary but not the `xvfb-run` wrapper script, so we replicate the
# "start a display, run inside it, clean up" behavior ourselves.
#
# Usage: run_with_xvfb.sh <command> [args...]
set -eo pipefail

CONDA_BASE="${CONDA_BASE:-$HOME/anaconda3}"
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate billing-bot

DISPLAY_NUM=""
for n in $(seq 90 199); do
    if [ ! -e "/tmp/.X${n}-lock" ]; then
        DISPLAY_NUM=$n
        break
    fi
done
if [ -z "$DISPLAY_NUM" ]; then
    echo "run_with_xvfb: no free X display found in range 90-199" >&2
    exit 1
fi

Xvfb ":${DISPLAY_NUM}" -screen 0 1280x800x24 &
XVFB_PID=$!
trap 'kill "$XVFB_PID" 2>/dev/null || true' EXIT

sleep 2

export DISPLAY=":${DISPLAY_NUM}"
"$@"
