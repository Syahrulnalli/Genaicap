"""Backward-compatible wrapper for the explicit safe demo reset command.

This script no longer inserts unowned demo records. It delegates to the same
backup-first command as ``flask --app app reset-demo-data`` and requires
``--confirm-reset`` before it can replace complaint data.
"""

import sys

from app import app


if __name__ == "__main__":
    app.cli.main(args=["reset-demo-data", *sys.argv[1:]], prog_name="python seed.py")
