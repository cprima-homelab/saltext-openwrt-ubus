#!/usr/bin/env bash
# Reject commits if the previous commit contains a Co-Authored-By trailer.
# This enforces the project policy of no AI authorship attribution.
# Only match actual trailer lines (starts with "Co-Authored-By:"), not mentions in body text.
if git log -1 --format="%(trailers:key=Co-Authored-By,valueonly)" 2>/dev/null | grep -q .; then
    echo "ERROR: Previous commit contains Co-Authored-By trailer. Amend it before committing."
    exit 1
fi
exit 0
