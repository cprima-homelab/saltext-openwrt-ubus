"""
Surface projections for classified UCI state.

Each projection takes a classified state dict (from classify_export()) and
returns a new dict suitable for the target surface. Values in the classified
state are never mutated.

Policy application per surface (from builtin.yaml defaults):
  evidence:     SECRET/SENSITIVE/UNKNOWN → value=null, key kept  (REDACT_VALUE)
  grains:       SECRET/UNKNOWN → key absent (DENY_VALUE); SENSITIVE → value=null
  config_diff:  SECRET/SENSITIVE/UNKNOWN option changes → {changed: true} (REPORT_CHANGE)

_sensitivity metadata is retained in all projections. The fields dict is
compacted: only non-PUBLIC/non-INTERNAL entries are shown, reducing noise
while preserving actionable classification data.
"""

from __future__ import annotations

from saltext.openwrt_ubus.sensitivity.model import Classification
from saltext.openwrt_ubus.sensitivity.model import Surface

_COMPACT_HIDE = frozenset({Classification.PUBLIC.value, Classification.INTERNAL.value})

_DENY_CLASSIFICATIONS = frozenset({Classification.SECRET.value, Classification.UNKNOWN.value})
_REDACT_CLASSIFICATIONS = frozenset(
    {Classification.SECRET.value, Classification.SENSITIVE.value, Classification.UNKNOWN.value}
)


def project(  # pylint: disable=unused-argument
    classified: dict,
    *,
    surface: Surface,
    profile=None,
) -> dict:
    """Apply the appropriate projection for the given surface.

    For surfaces not yet implemented (logs, cli_output), returns the
    evidence projection as a conservative default.
    """
    if surface == Surface.EVIDENCE:
        return evidence_projection(classified)
    if surface == Surface.GRAINS:
        return grains_projection(classified)
    # logs and cli_output: default to evidence-style redaction
    return evidence_projection(classified)


def _compact_fields(fields: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in fields.items() if v not in _COMPACT_HIDE}


def _project_section_evidence(section: dict) -> dict:
    fields = section.get("_sensitivity", {}).get("fields", {})
    result: dict = {}
    for key, value in section.items():
        if key.startswith("_"):
            result[key] = value
            continue
        cl_str = fields.get(key, Classification.UNKNOWN.value)
        if cl_str in _REDACT_CLASSIFICATIONS:
            result[key] = None
        else:
            result[key] = value
    sensitivity = section.get("_sensitivity", {})
    result["_sensitivity"] = {
        "taint": sensitivity.get("taint"),
        "fields": _compact_fields(fields),
    }
    return result


def evidence_projection(classified: dict) -> dict:
    """Project classified state for the evidence surface.

    SECRET/SENSITIVE/UNKNOWN option values become null; key is retained.
    _sensitivity.fields is compacted to non-public/non-internal entries only.
    """
    result: dict = {}
    for sec_name, sec_data in classified.items():
        if "_items" in sec_data:
            projected_items = [_project_section_evidence(item) for item in sec_data["_items"]]
            container: dict = {}
            for key, value in sec_data.items():
                if key == "_items":
                    continue
                if key == "_sensitivity":
                    sensitivity = value
                    container["_sensitivity"] = {
                        "taint": sensitivity.get("taint"),
                        "fields": _compact_fields(sensitivity.get("fields", {})),
                    }
                else:
                    container[key] = value
            container["_items"] = projected_items
            result[sec_name] = container
        else:
            result[sec_name] = _project_section_evidence(sec_data)
    return result


def _project_section_grains(section: dict) -> dict:
    fields = section.get("_sensitivity", {}).get("fields", {})
    result: dict = {}
    for key, value in section.items():
        if key.startswith("_"):
            result[key] = value
            continue
        cl_str = fields.get(key, Classification.UNKNOWN.value)
        if cl_str in _DENY_CLASSIFICATIONS:
            continue  # DENY_VALUE: key absent
        if cl_str == Classification.SENSITIVE.value:
            result[key] = None  # REDACT_VALUE: key present, value null
        else:
            result[key] = value
    sensitivity = section.get("_sensitivity", {})
    result["_sensitivity"] = {
        "taint": sensitivity.get("taint"),
        "fields": _compact_fields(fields),
    }
    return result


def grains_projection(classified: dict) -> dict:
    """Project classified state for the grains surface.

    SECRET/UNKNOWN: key absent from section (DENY_VALUE).
    SENSITIVE: key present, value null (REDACT_VALUE).
    _sensitivity is retained for introspection.
    """
    result: dict = {}
    for sec_name, sec_data in classified.items():
        if "_items" in sec_data:
            projected_items = [_project_section_grains(item) for item in sec_data["_items"]]
            container: dict = {}
            for key, value in sec_data.items():
                if key == "_items":
                    continue
                if key == "_sensitivity":
                    sensitivity = value
                    container["_sensitivity"] = {
                        "taint": sensitivity.get("taint"),
                        "fields": _compact_fields(sensitivity.get("fields", {})),
                    }
                else:
                    container[key] = value
            container["_items"] = projected_items
            result[sec_name] = container
        else:
            result[sec_name] = _project_section_grains(sec_data)
    return result


def diff_projection(
    diff_result: dict,
    *,
    package: str,
    profile,
    section_types: dict[str, str] | None = None,
) -> dict:
    """Apply sensitivity redaction to a config_diff() result.

    For changed/new sections: option changes where the option is classified
    SECRET/SENSITIVE/UNKNOWN are replaced with {changed: true}.
    For removed/reordered sections: sensitive option values are set to null
    (same policy as evidence projection, but applied to raw get() section dicts).
    summary is passed through unchanged.
    """
    if section_types is None:
        section_types = {}

    result = {}

    result["changed"] = _project_diff_changes(
        diff_result.get("changed", {}),
        package=package,
        section_types=section_types,
        profile=profile,
    )
    result["new"] = _project_diff_changes(
        diff_result.get("new", {}), package=package, section_types=section_types, profile=profile
    )
    result["removed"] = _project_diff_raw_sections(
        diff_result.get("removed", {}), package=package, profile=profile
    )
    result["reordered"] = _project_diff_raw_sections(
        diff_result.get("reordered", {}), package=package, profile=profile
    )
    result["summary"] = diff_result.get("summary", {})

    return result


def _project_diff_changes(
    section_changes: dict,
    *,
    package: str,
    section_types: dict[str, str],
    profile,
) -> dict:
    """Redact changed/new option diff entries whose values should not be exposed."""
    result: dict = {}
    for sec_name, option_diffs in section_changes.items():
        section_type = section_types.get(sec_name, "")
        projected: dict = {}
        for option, diff_entry in option_diffs.items():
            cl = profile.classify(package, section_type, option)
            if cl.value in _REDACT_CLASSIFICATIONS:
                projected[option] = {"changed": True}
            else:
                projected[option] = diff_entry
        result[sec_name] = projected
    return result


def _project_diff_raw_sections(
    sections: dict,
    *,
    package: str,
    profile,
) -> dict:
    """Redact sensitive values from removed/reordered raw get() section dicts."""
    result: dict = {}
    for sec_name, sec_data in sections.items():
        section_type = sec_data.get("_type", "")
        projected: dict = {}
        for key, value in sec_data.items():
            if key.startswith("_"):
                projected[key] = value
                continue
            cl = profile.classify(package, section_type, key)
            if cl.value in _REDACT_CLASSIFICATIONS:
                projected[key] = None
            else:
                projected[key] = value
        result[sec_name] = projected
    return result


def assert_grains_safe(grains_dict: dict) -> None:
    """Assert the grains invariant: no SECRET/SENSITIVE/UNKNOWN value is non-null.

    Raises AssertionError if any option in the grains dict has a non-null value
    with a classification of secret, sensitive, or unknown.
    Intended for use in tests and optional runtime guards.
    """
    bad = frozenset(
        {
            Classification.SECRET.value,
            Classification.SENSITIVE.value,
            Classification.UNKNOWN.value,
        }
    )
    for sec_name, section in grains_dict.items():
        if not isinstance(section, dict):
            continue
        fields = section.get("_sensitivity", {}).get("fields", {})
        for option, value in section.items():
            if option.startswith("_"):
                continue
            if value is None:
                continue
            cl_str = fields.get(option)
            if cl_str in bad:
                raise AssertionError(
                    f"Grains invariant violated: section {sec_name!r} option {option!r} "
                    f"has classification {cl_str!r} but appears with non-null value"
                )
