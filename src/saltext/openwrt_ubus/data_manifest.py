"""
Generate a data-handling manifest combining DataContract annotations and
the sensitivity profile.

Usage::

    python -m saltext.openwrt_ubus.data_manifest           # YAML to stdout
    python -m saltext.openwrt_ubus.data_manifest --json    # JSON to stdout
    python -m saltext.openwrt_ubus.data_manifest --check   # path analysis

The manifest has three sections:

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

``functions``
    Every function annotated with ``@data_contract``, keyed by function name.
    Fields: module, inputs, outputs, surfaces, handles_secrets, emits_secrets,
    guards.  Semantic facts come from the declarations; reflection only
    discovers which functions exist.

``sensitivity_profile``
    The builtin profile's name, version, policy table (5 classifications × 5
    surfaces), and the full list of explicitly classified fields from the rules.

--check mode builds a graph from inputs/outputs and validates that every path
from a secret_capable=true source to a non-internal boundary crosses a function
that declares emits_secrets=false:

  - handles_secrets or emits_secrets is None → WARN (unknown path)
  - secret_capable input reaching external boundary with emits_secrets=true → FAIL
  - secret_capable input reaching external boundary with emits_secrets=false → PASS
    (reason includes guards list when present)

Known gap: uci.diff is an implicit intermediate produced inside config_diff before
being passed to diff_projection. The transform uci.raw → uci.diff is not yet an
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

# Data type declarations: each namespace in the input/output graph.
#
# secret_capable:
#   True  — may contain secret values
#   False — guaranteed secret-free (by projection or design)
#   None  — unknown / not asserted; --check emits WARN for functions using this type
#
# boundary: trust boundary crossed when this data type is written or transmitted
#   internal        — stays within the minion process
#   salt-master     — sent to the Salt master (grains, returners)
#   persistent-store — written to disk / file-based evidence store
#   cli             — printed to terminal or log visible to operators
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
        "description": "Desired state from Salt pillar; already fetched to minion memory",
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


def _tri(value: bool | None) -> str:
    """Serialize bool | None as true / false / null for YAML/JSON clarity."""
    if value is None:
        return "null"
    return str(value).lower()


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


def build_manifest(modules=None, profile=None) -> dict:
    """Build and return the complete data-handling manifest as a dict."""
    return {
        "data_types": DATA_TYPES,
        "functions": collect_contracts(modules=modules),
        "sensitivity_profile": collect_profile_fields(profile=profile),
    }


# ---------------------------------------------------------------------------
# --check: boundary-aware data-flow path analysis
# ---------------------------------------------------------------------------

# Boundaries that are outside the minion process; data written here persists
# or travels beyond the immediate computation.
_EXTERNAL_BOUNDARIES = frozenset({"salt-master", "persistent-store", "cli"})


def _type_secret_capable(data_types: dict, type_name: str) -> bool | None:
    """Return secret_capable for a named type, or None if unknown/undeclared."""
    return data_types.get(type_name, {}).get("secret_capable", None)


def _type_boundary(data_types: dict, type_name: str) -> str:
    """Return the trust boundary for a named type, defaulting to 'internal'."""
    return data_types.get(type_name, {}).get("boundary", "internal")


def check_manifest(manifest: dict) -> list[tuple[str, str, str]]:
    """Analyse the function graph and return (status, function_name, reason) tuples.

    Status values: PASS, WARN, FAIL.

    The check asks one question per function:

        "Does this function move secret-capable data across a trust boundary
         without declaring emits_secrets=false?"

    Rules applied in order:
    1. handles_secrets or emits_secrets is None → WARN (path is uncharted)
    2. Any input is secret_capable != False AND any output crosses an external
       boundary AND emits_secrets=True → FAIL (secrets leak to external surface)
    3. Any input is secret_capable != False AND any output crosses an external
       boundary AND emits_secrets=False → PASS (crossing is guarded)
    4. emits_secrets=True with all outputs staying internal → PASS (intermediate)
    5. No secret-capable input → PASS (clean path)
    """
    functions = manifest["functions"]
    data_types = manifest.get("data_types", DATA_TYPES)
    results = []

    for fn_name, fn in functions.items():
        handles = fn.get("handles_secrets")
        emits = fn.get("emits_secrets")
        guards = fn.get("guards", [])

        # Rule 1: unknown declaration → WARN
        if handles is None or emits is None:
            results.append(
                (
                    "WARN",
                    fn_name,
                    "handles_secrets or emits_secrets is null (unknown); "
                    "no classification layer declared for this path",
                )
            )
            continue

        inputs = fn.get("inputs", [])
        outputs = fn.get("outputs", [])

        input_secret = any(_type_secret_capable(data_types, inp) is not False for inp in inputs)
        external_outputs = [
            out for out in outputs if _type_boundary(data_types, out) in _EXTERNAL_BOUNDARIES
        ]

        if input_secret and external_outputs:
            boundary_labels = ", ".join(
                f"{o} ({_type_boundary(data_types, o)})" for o in external_outputs
            )
            if emits:
                # Rule 2: secrets reach external boundary
                results.append(
                    (
                        "FAIL",
                        fn_name,
                        f"secret-capable input reaches external boundary "
                        f"with emits_secrets=true: {boundary_labels}",
                    )
                )
            elif guards:
                # Rule 3a: guarded projection
                results.append(
                    (
                        "PASS",
                        fn_name,
                        f"secret-capable input → {boundary_labels}; " f"guarded by {guards}",
                    )
                )
            else:
                # Rule 3b: function is itself the projection
                results.append(
                    (
                        "PASS",
                        fn_name,
                        f"secret-capable input → {boundary_labels}; "
                        "function is the projection (emits_secrets=false)",
                    )
                )
        elif emits:
            # Rule 4: emits secrets but all outputs stay internal
            results.append(
                (
                    "PASS",
                    fn_name,
                    f"emits secrets to internal output "
                    f"({', '.join(outputs)}); stays within process boundary",
                )
            )
        else:
            # Rule 5: no secret-capable input or no external output, clean path
            results.append(("PASS", fn_name, "no secret-capable input reaching external boundary"))

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
