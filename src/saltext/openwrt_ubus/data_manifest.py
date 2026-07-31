"""
Generate a data-handling manifest combining DataContract annotations and
the sensitivity profile.

Usage::

    python -m saltext.openwrt_ubus.data_manifest           # YAML to stdout
    python -m saltext.openwrt_ubus.data_manifest --json    # JSON to stdout
    python -m saltext.openwrt_ubus.data_manifest --check   # path analysis

The manifest has four sections:

``data_types``
    Declarations of each named data namespace (e.g. ``uci.raw``,
    ``uci.classified``, ``evidence.configured_state``).  Each type records
    whether it is secret-capable, its classification stage, and which trust
    boundary it crosses when written:

    ``internal``
        Stays within the minion process; never leaves to an external system.
    ``salt-master``
        Sent to the Salt master (grains, returners).
    ``persistent-store``
        Written to disk / a file-based evidence store.
    ``cli``
        Printed to a terminal or log visible to operators.

    ``provenance_boundary`` (optional) records where a type *originated* when
    that differs from where it currently lives.  ``pillar.sections`` is
    ``boundary: internal`` (it has already been fetched onto the minion) but
    ``provenance_boundary: salt-master`` (it came from the master and may contain
    master-side secrets).

``functions``
    Every function annotated with ``@data_contract``, keyed by function name.
    Fields: module, inputs, outputs, surfaces, handles_secrets, emits_secrets,
    guards.  Semantic facts come from the declarations; reflection only
    discovers which functions exist.

``crossings``
    Derived list of every boundary transition in the function graph — every
    (input boundary → output boundary) pair where the two differ.  Each entry
    records: from, to, via (function name), guards, and result (safe /
    unknown / fail).  This is the primary artifact for architectural review.

``sensitivity_profile``
    The builtin profile's name, version, policy table (5 classifications × 5
    surfaces), and the full list of explicitly classified fields from the rules.

--check mode validates the crossings list:
  - result=unknown → WARN (path is uncharted; handles/emits_secrets is None)
  - result=fail    → FAIL (secrets reach an external boundary unguarded)
  - result=safe    → PASS (crossing is guarded; guards list names the enforcement)

Known gap: uci.diff is an implicit intermediate produced inside config_diff before
being passed to diff_projection.  The transform uci.raw → uci.diff is not yet an
annotated logical step; config_diff's guards field documents the dependency.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys

import yaml

from saltext.openwrt_ubus.sensitivity.model import Classification
from saltext.openwrt_ubus.sensitivity.model import SensitivityProfile
from saltext.openwrt_ubus.sensitivity.model import Surface

_ANNOTATED_MODULES = [
    "saltext.openwrt_ubus.sensitivity.classify",
    "saltext.openwrt_ubus.sensitivity.project",
    "saltext.openwrt_ubus.utils.ubus_ops",
]

# Boundaries that are outside the minion process.  Data written here persists
# or travels beyond the immediate computation and must cross safely.
_EXTERNAL_BOUNDARIES = frozenset({"salt-master", "persistent-store", "cli"})

# Data type declarations: each namespace in the input/output graph.
#
# secret_capable:
#   True  — may contain secret values
#   False — guaranteed secret-free (by projection or design)
#   None  — unknown / not asserted; --check emits WARN for crossings using this type
#
# boundary: trust boundary *of* this data type when written or transmitted
#   internal         — stays within the minion process
#   salt-master      — sent to the Salt master (grains, returners)
#   persistent-store — written to disk / file-based evidence store
#   cli              — printed to terminal or log visible to operators
#
# provenance_boundary (optional): where this type *originated*, when that differs
#   from boundary.  Only set when the provenance boundary is stricter than the
#   current boundary and consumers need to know.
DATA_TYPES: dict[str, dict] = {
    "uci.raw": {
        "classification": "unclassified",
        "secret_capable": True,
        "boundary": "internal",
        "description": "Raw config_export() output; option values untransformed",
    },
    "uci.classified": {
        "classification": "classified",
        "secret_capable": True,
        "boundary": "internal",
        "description": "classify_export() output; every option annotated, values preserved",
    },
    "uci.diff": {
        "classification": "unclassified",
        "secret_capable": True,
        "boundary": "internal",
        "description": "Raw diff result; may contain old/new secret values",
    },
    "pillar.sections": {
        "classification": "unclassified",
        "secret_capable": True,
        "boundary": "internal",
        "provenance_boundary": "salt-master",
        "description": (
            "Desired state already fetched to minion memory (boundary=internal); "
            "originates from Salt master (provenance_boundary=salt-master) "
            "and may carry master-side secrets"
        ),
    },
    "evidence.configured_state": {
        "classification": "projected",
        "secret_capable": False,
        "boundary": "persistent-store",
        "description": "evidence_projection() output; secret values redacted to null",
    },
    "evidence.config_diff": {
        "classification": "projected",
        "secret_capable": False,
        "boundary": "persistent-store",
        "description": "diff_projection() output; secret changes replaced with {changed: true}",
    },
    "evidence.observed_state": {
        "classification": "unclassified",
        "secret_capable": None,
        "boundary": "persistent-store",
        "description": "runtime_evidence() output; no classification layer applied yet",
    },
    "grains.configured_state": {
        "classification": "projected",
        "secret_capable": False,
        "boundary": "salt-master",
        "description": "grains_projection() output; secret/unknown keys absent",
    },
    "ubus.runtime": {
        "classification": "unclassified",
        "secret_capable": None,
        "boundary": "internal",
        "description": "Observed runtime state from ubus; secret_capable unknown",
    },
}


def collect_contracts(modules=None) -> dict:
    """Return {function_name: contract_dict} for all @data_contract-annotated functions."""
    if modules is None:
        modules = _ANNOTATED_MODULES
    result = {}
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        for name, obj in inspect.getmembers(mod, inspect.isfunction):
            if obj.__module__ != mod_name:
                continue
            contract = getattr(obj, "__data_contract__", None)
            if contract is not None:
                result[name] = {
                    "module": mod_name,
                    "inputs": list(contract.inputs),
                    "outputs": list(contract.outputs),
                    "surfaces": list(contract.surfaces),
                    "handles_secrets": contract.handles_secrets,
                    "emits_secrets": contract.emits_secrets,
                    "guards": list(contract.guards),
                }
    return result


def collect_profile_fields(profile=None) -> dict:
    """Return profile metadata, policies, and classified fields from the builtin profile."""
    if profile is None:
        profile = SensitivityProfile.load_builtin()

    policies = {}
    for cl in Classification:
        surface_policies = profile.policies.get(cl, {})
        policies[cl.value] = {
            surf.value: surface_policies[surf].value for surf in Surface if surf in surface_policies
        }

    classified_fields = []
    for rule in profile.rules:
        m = rule.match
        options = m.option if isinstance(m.option, list) else ([m.option] if m.option else [])
        section_types = (
            m.section_type
            if isinstance(m.section_type, list)
            else ([m.section_type] if m.section_type else [])
        )
        entry: dict = {"classification": rule.classification.value, "options": options}
        if m.package:
            entry["package"] = m.package
        if section_types:
            entry["section_types"] = section_types
        classified_fields.append(entry)

    return {
        "name": profile.name,
        "version": profile.version,
        "policies": policies,
        "classified_fields": classified_fields,
    }


# ---------------------------------------------------------------------------
# Crossing derivation
# ---------------------------------------------------------------------------


def _type_boundary(data_types: dict, type_name: str) -> str:
    """Return the trust boundary for a named type, defaulting to 'internal'."""
    return data_types.get(type_name, {}).get("boundary", "internal")


def _type_secret_capable(data_types: dict, type_name: str) -> bool | None:
    """Return secret_capable for a named type, or None if unknown/undeclared."""
    return data_types.get(type_name, {}).get("secret_capable", None)


def derive_crossings(manifest: dict) -> list[dict]:
    """Derive boundary transitions from the function graph.

    For every (input, output) pair where input.boundary != output.boundary, emit
    one crossing record.  The key (from, to, via) is deduplicated — a function
    with multiple inputs or outputs at the same boundary contributes one entry,
    not N × M.

    Each record::

        from: internal
        to: persistent-store
        via: config_evidence
        guards:
          - classify_export
          - evidence_projection
        result: safe | unknown | fail

    ``result`` is:
      safe    — emits_secrets=false; secrets are projected before the crossing
      unknown — handles_secrets or emits_secrets is None; path is uncharted
      fail    — emits_secrets=true into an external boundary; secrets leak

    When a function has no declared guards but emits_secrets=false, it is itself
    the projection; the guards list contains the function name to make the
    enforcement relationship explicit.
    """
    data_types = manifest.get("data_types", DATA_TYPES)
    functions = manifest.get("functions", {})

    seen: set[tuple[str, str, str]] = set()
    crossings: list[dict] = []

    for fn_name, fn in functions.items():
        handles = fn.get("handles_secrets")
        emits = fn.get("emits_secrets")
        declared_guards = fn.get("guards", [])

        for inp in fn.get("inputs", []):
            from_boundary = _type_boundary(data_types, inp)
            for out in fn.get("outputs", []):
                to_boundary = _type_boundary(data_types, out)
                if from_boundary == to_boundary:
                    continue
                key = (from_boundary, to_boundary, fn_name)
                if key in seen:
                    continue
                seen.add(key)

                # Determine result
                if handles is None or emits is None:
                    result = "unknown"
                elif emits and to_boundary in _EXTERNAL_BOUNDARIES:
                    result = "fail"
                else:
                    result = "safe"

                # Effective guards: declared, or the function itself when it IS the projection
                if declared_guards:
                    effective_guards = list(declared_guards)
                elif result == "safe":
                    effective_guards = [fn_name]
                else:
                    effective_guards = []

                crossings.append(
                    {
                        "from": from_boundary,
                        "to": to_boundary,
                        "via": fn_name,
                        "guards": effective_guards,
                        "result": result,
                    }
                )

    return crossings


def build_manifest(modules=None, profile=None) -> dict:
    """Build and return the complete data-handling manifest as a dict."""
    manifest: dict = {
        "data_types": DATA_TYPES,
        "functions": collect_contracts(modules=modules),
        "sensitivity_profile": collect_profile_fields(profile=profile),
    }
    manifest["crossings"] = derive_crossings(manifest)
    return manifest


# ---------------------------------------------------------------------------
# --check: crossing-level validation
# ---------------------------------------------------------------------------


def check_manifest(manifest: dict) -> list[tuple[str, str, str]]:
    """Validate the crossings list and return (status, via, reason) tuples.

    Status values: PASS, WARN, FAIL.

    Each crossing is one entry:
      PASS  — result=safe; guards list names the enforcement
      WARN  — result=unknown; path is uncharted (handles/emits_secrets is None)
      FAIL  — result=fail; secrets reach an external boundary unguarded
    """
    crossings = manifest.get("crossings") or derive_crossings(manifest)
    results = []

    for c in crossings:
        fn_name = c["via"]
        from_b = c["from"]
        to_b = c["to"]
        guards = c.get("guards", [])
        result = c.get("result", "unknown")

        if result == "safe":
            if guards and guards != [fn_name]:
                reason = f"{from_b} → {to_b}; " f"guarded by {guards}"
            else:
                reason = f"{from_b} → {to_b}; " "function is the projection (emits_secrets=false)"
            results.append(("PASS", fn_name, reason))
        elif result == "unknown":
            results.append(
                (
                    "WARN",
                    fn_name,
                    f"{from_b} → {to_b}; "
                    "handles_secrets or emits_secrets is null — path is uncharted",
                )
            )
        else:
            results.append(
                (
                    "FAIL",
                    fn_name,
                    f"{from_b} → {to_b}; "
                    "secrets reach external boundary with emits_secrets=true",
                )
            )

    return results


def _print_check(results: list[tuple[str, str, str]]) -> int:
    """Print check results and return exit code (0=all PASS, 1=WARN or FAIL present)."""
    width = max(len(fn) for _, fn, _ in results) if results else 20
    any_problem = False
    for status, fn_name, reason in results:
        print(f"{status:<4}  {fn_name:<{width}}  {reason}")
        if status in ("WARN", "FAIL"):
            any_problem = True
    return 1 if any_problem else 0


def main():
    args = sys.argv[1:]
    manifest = build_manifest()

    if "--check" in args:
        results = check_manifest(manifest)
        sys.exit(_print_check(results))
    elif "--json" in args:
        print(json.dumps(manifest, indent=2))
    else:
        print(yaml.dump(manifest, default_flow_style=False, sort_keys=False))


if __name__ == "__main__":
    main()
