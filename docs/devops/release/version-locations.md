# Version Number Locations

Where version numbers live in this project. Update these when cutting a release.

## Automatically derived (do not edit)

| Location | Mechanism |
|----------|-----------|
| Python package version | `setuptools_scm` derives from git tags |
| `saltext_openwrt_ubus-*.dist-info/` | Built by pip from setuptools_scm |

Tag a release with `git tag v0.2.1` and the version propagates automatically.

## Must be updated manually

| File | What to update |
|------|----------------|
| `CHANGELOG.md` | Add new version section with date and changes |
| `openwrt/ROADMAP.md` | Mark completed milestones, update `(current)` marker |
| `docs/adr/*.md` | Context lines referencing the version that introduced a decision |

## References that mention versions (typically leave as-is)

These mention versions as historical context, not as the current version.
Only update if the meaning has changed.

| File | Line | Context |
|------|------|---------|
| `docs/devops/plan/10-jsonrpc-vs-cli.md:19` | `v0.2 Approach` | Historical: describes when JSON-RPC was adopted |
| `docs/devops/plan/10-jsonrpc-vs-cli.md:147` | `Recommendation for v0.2` | Historical |
| `docs/devops/code/07-ubus-object-inventory.md:105` | `Primary (v0.2 scope)` | Historical |
| `openwrt/ROADMAP.md` | `v0.2.0`, `v0.3.0`, `v1.0.0` | OpenWrt package milestones (separate from saltext version) |

## Not project versions (ignore)

| File | What |
|------|------|
| `.github/workflows/*.yml` | GitHub Actions versions (`actions/checkout@v6.0.2`, etc.) |
| `CHANGELOG.md:12` | `salt-extension-copier v0.8.0` -- scaffolding tool version |
