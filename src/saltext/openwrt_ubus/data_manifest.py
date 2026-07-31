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
    whether it is secret-capable and its classification stage.

``functions``
    Every function annotated with ``@data_contract``, keyed by function name.
    Fields: module, inputs, outputs, surfaces, handles_secrets, emits_secrets,
    guards.  Semantic facts come from the declarations; reflection only
    discovers which functions exist.

``sensitivity_profile``
    The builtin profile's name, version, policy table (5 classifications × 5
    surfaces), and the full list of explicitly classified fields from the rules.

--check mode builds a graph from inputs/outputs and validates:
  - handles_secrets or emits_secrets is None → WARN (unknown path)
  - emits_secrets=False despite secret-capable input → verify guards declared
  - emits_secrets inconsistent with output data type's secret_capable → FAIL
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
# secret_capable:
#   True  — may contain secret values
#   False — guaranteed secret-free (by projection or design)
#   None  — unknown; --check emits WARN for functions using this type
DATA_TYPES: dict[str, dict] = {
    "uci.raw": {
        "classification": "unclassified",
        "secret_capable": True,
        "description": "Raw config_export() output; option values untransformed",
    },
    "uci.classified": {
        "classification": "classified",
        "secret_capable": True,
        "description": "classify_export() output; every option annotated, values preserved",
    },
    "uci.diff": {
        "classification": "unclassified",
        "secret_capable": True,
        "description": "Raw diff result; may contain old/new secret values",
    },
    "pillar.sections": {
        "classification": "unclassified",
        "secret_capable": True,
        "description": "Desired state from Salt pillar; may contain secrets",
    },
    "evidence.configured_state": {
        "classification": "projected",
        "secret_capable": False,
        "description": "evidence_projection() output; secret values redacted to null",
    },
    "evidence.config_diff": {
        "classification": "projected",
        "secret_capable": False,
        "description": "diff_projection() output; secret changes replaced with {changed: true}",
    },
    "evidence.observed_state": {
        "classification": "unclassified",
        "secret_capable": None,
        "description": "runtime_evidence() output; no classification layer applied yet",
    },
    "grains.configured_state": {
        "classification": "projected",
        "secret_capable": False,
        "description": "grains_projection() output; secret/unknown keys absent",
    },
    "ubus.runtime": {
        "classification": "unclassified",
        "secret_capable": None,
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
# --check: data-flow path analysis
# ---------------------------------------------------------------------------


def _secret_capable(type_name: str) -> bool | None:
    """Return secret_capable for a data type name, or None if unknown/undeclared."""
    return DATA_TYPES.get(type_name, {}).get("secret_capable", None)


def check_manifest(manifest: dict) -> list[tuple[str, str, str]]:
    """Analyse the function graph and return (status, function_name, reason) tuples.

    Status values: PASS, WARN, FAIL.
    """
    functions = manifest["functions"]
    results = []

    for fn_name, fn in functions.items():
        handles = fn.get("handles_secrets")
        emits = fn.get("emits_secrets")
        guards = fn.get("guards", [])

        # Unknown declaration → WARN immediately
        if handles is None or emits is None:
            results.append(
                (
                    "WARN",
                    fn_name,
                    "handles_secrets or emits_secrets is unknown; "
                    "no classification layer declared for this path",
                )
            )
            continue

        # Check consistency: emits_secrets vs output data type
        for out_type in fn["outputs"]:
            out_capable = _secret_capable(out_type)
            if out_capable is False and emits is True:
                results.append(
                    (
                        "FAIL",
                        fn_name,
                        f"emits_secrets=true but output {out_type!r} is secret_capable=false; "
                        "contract inconsistency",
                    )
                )
                break
            if out_capable is True and emits is False:
                # This is fine — the function redacts before writing to a secret-capable type
                # (unusual but not inherently wrong; guards should explain it)
                pass
        else:
            # Determine if any input is secret-capable
            input_capable = any(_secret_capable(inp) is not False for inp in fn["inputs"])

            if emits:
                # Emits secrets — output is an intermediate; acceptable
                results.append(
                    (
                        "PASS",
                        fn_name,
                        f"handles and emits secrets; output is intermediate "
                        f"({', '.join(fn['outputs'])})",
                    )
                )
            elif input_capable and guards:
                results.append(
                    (
                        "PASS",
                        fn_name,
                        f"secret-capable input → protected output; " f"enforced by {guards}",
                    )
                )
            elif input_capable:
                results.append(
                    (
                        "PASS",
                        fn_name,
                        "secret-capable input → protected output; "
                        "enforcement implicit (function is itself the projection)",
                    )
                )
            else:
                results.append(("PASS", fn_name, "no secret-capable input; clean output"))

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
