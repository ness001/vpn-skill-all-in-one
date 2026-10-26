#!/usr/bin/env bash
# Fresh-server entry point; no remote execution or cloud provisioning.
set -Eeuo pipefail
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if command -v python3 >/dev/null 2>&1 && python3 -B -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1 && python -B -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    PYTHON=python
else
    printf 'ERROR: Python 3.10+ is required (included in standard Ubuntu 22.04/24.04 images).\n' >&2
    exit 1
fi
exec "$PYTHON" -B "$SCRIPT_DIR/installer/install.py" "$@"
