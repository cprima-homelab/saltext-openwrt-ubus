"""
Wrapper for the nox lint pre-commit hooks in a monorepo layout.

noxfile.py chdirs to its own directory (packages/uci-ssh/) at import time --
pre-commit passes file paths relative to the git repo root, so those paths
need the "packages/uci-ssh/" prefix stripped before being handed to nox as
posargs, or pylint looks for a doubled-up path that doesn't exist.
"""

import subprocess
import sys

PREFIX = "packages/uci-ssh/"

session = sys.argv[1]
paths = [a[len(PREFIX) :] if a.startswith(PREFIX) else a for a in sys.argv[2:]]

raise SystemExit(
    subprocess.call(
        ["nox", "--noxfile", "packages/uci-ssh/noxfile.py", "-e", session, "--", *paths]
    )
)
