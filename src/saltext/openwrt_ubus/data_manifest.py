"""
Generate a data-handling manifest combining DataContract annotations and
the sensitivity profile.

Usage::

    python -m saltext.openwrt_ubus.data_manifest           # YAML to stdout
    python -m saltext.openwrt_ubus.data_manifest --json    # JSON to stdout

The manifest has two sections:

``functions``
    Every function annotated with ``@data_contract``, keyed by function name,
    showing its declared inputs, outputs, surfaces, and whether it may carry
    secrets. This is derived from static code annotations — reflection discovers
    the functions automatically but the semantic facts come from the declarations.

``sensitivity_profile``
    The builtin profile's name, version, policy table (5 classifications × 5
    surfaces), and the full list of explicitly classified fields from the rules.

Together these answer: which data flows through this code, what transformations
are applied, and what each option is classified as and what any output surface
is permitted to expose.
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


def collect_contracts(modules=None):
    """Return {function_name: contract_dict} for all @data_contract-annotated functions."""
    if modules is None:
        modules = _ANNOTATED_MODULES
    result = {}
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        for name, obj in inspect.getmembers(mod, inspect.isfunction):
            if obj.__module__ != mod_name:
                continue  # skip functions imported from other modules
            contract = getattr(obj, "__data_contract__", None)
            if contract is not None:
                result[name] = {
                    "module": mod_name,
                    "inputs": list(contract.inputs),
                    "outputs": list(contract.outputs),
                    "surfaces": list(contract.surfaces),
                    "may_contain_secrets": contract.may_contain_secrets,
                }
    return result


def collect_profile_fields(profile=None):
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
        entry = {"classification": rule.classification.value, "options": options}
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


def build_manifest(modules=None, profile=None):
    """Build and return the complete data-handling manifest as a dict."""
    return {
        "functions": collect_contracts(modules=modules),
        "sensitivity_profile": collect_profile_fields(profile=profile),
    }


def main():
    as_json = "--json" in sys.argv
    manifest = build_manifest()
    if as_json:
        print(json.dumps(manifest, indent=2))
    else:
        print(yaml.dump(manifest, default_flow_style=False, sort_keys=False))


if __name__ == "__main__":
    main()
