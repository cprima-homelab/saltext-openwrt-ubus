"""
classify_export(): annotate a config_export() dict with sensitivity classifications.

The returned classified state preserves all option values unchanged.
Projections (project.py) decide what to expose per surface.
"""

from __future__ import annotations

from saltext.uci_ubus.sensitivity.contracts import data_contract
from saltext.uci_ubus.sensitivity.model import Classification, SensitivityProfile, max_taint


@data_contract(
    inputs=("uci.raw",),
    outputs=("uci.classified",),
    surfaces=("internal",),
    handles_secrets=True,
    emits_secrets=True,
)
def classify_export(
    export_dict: dict,
    *,
    package: str,
    profile: SensitivityProfile,
) -> dict:
    """Annotate a config_export() result with per-section _sensitivity metadata.

    Every non-_-prefixed option is classified. Values are not modified.
    Returns a new dict; the input is not mutated.

    The classified state structure per named/singleton section::

        {
            "_type": "interface",
            "_sensitivity": {
                "taint": "secret",          # max_taint() of all option classifications
                "fields": {
                    "proto":       "internal",
                    "private_key": "secret",
                }
            },
            "proto": "wireguard",           # value preserved
            "private_key": "gHcb...",       # value preserved; projections decide what to do
        }

    Multi-instance (_items) sections get _sensitivity on each item and a container
    _sensitivity whose taint is the max of all item taints.
    """
    result: dict = {}
    for sec_name, sec_data in export_dict.items():
        if "_items" in sec_data:
            result[sec_name] = _classify_multi(sec_data, package=package, profile=profile)
        else:
            section_type = sec_data.get("_type", "")
            classified, _ = _classify_section(sec_data, package=package, section_type=section_type, profile=profile)
            result[sec_name] = classified
    return result


def _classify_multi(container: dict, *, package: str, profile: SensitivityProfile) -> dict:
    section_type = container.get("_type", "")
    classified_items: list[dict] = []
    item_taints: list[Classification] = []

    for item in container.get("_items", []):
        classified_item, taint = _classify_section(item, package=package, section_type=section_type, profile=profile)
        classified_items.append(classified_item)
        item_taints.append(taint)

    container_taint = max_taint(item_taints) if item_taints else Classification.PUBLIC

    result = {k: v for k, v in container.items() if k != "_items"}
    result["_sensitivity"] = {"taint": container_taint.value, "fields": {}}
    result["_items"] = classified_items
    return result


def _classify_section(
    section: dict,
    *,
    package: str,
    section_type: str,
    profile: SensitivityProfile,
) -> tuple[dict, Classification]:
    """Classify all non-_ options; return (annotated_section, taint)."""
    fields: dict[str, str] = {}
    for key in section:
        if not key.startswith("_"):
            cl = profile.classify(package, section_type, key)
            fields[key] = cl.value

    taint = max_taint(Classification(v) for v in fields.values()) if fields else Classification.PUBLIC

    classified = {**section, "_sensitivity": {"taint": taint.value, "fields": fields}}
    return classified, taint
