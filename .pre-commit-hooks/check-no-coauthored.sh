#!/usr/bin/env bash
# Reject commits if the previous commit contains a Co-Authored-By trailer.
# This enforces the project policy of no AI authorship attribution.
if git log -1 --format="%B" 2>/dev/null | grep -qi "Co-Authored-By"; then
    echo "ERROR: Previous commit contains Co-Authored-By. Amend it before committing."
    exit 1
fi
exit 0
