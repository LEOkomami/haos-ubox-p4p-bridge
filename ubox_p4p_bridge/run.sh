#!/usr/bin/env bash
set -euo pipefail
umask 077
exec /opt/venv/bin/python3 /opt/bridge/supervisor.py

