#!/usr/bin/env bash
# Silently strips any Co-Authored-By trailer (AI attribution) from the
# commit message being created -- org policy is no AI authorship credit.
set -euo pipefail
msg_file="$1"
grep -v -i '^co-authored-by:' "$msg_file" > "$msg_file.tmp"
mv "$msg_file.tmp" "$msg_file"
