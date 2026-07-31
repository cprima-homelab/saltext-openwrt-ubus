"""
UCI sensitivity classification for saltext-openwrt-ubus.

Quick-start::

    from saltext.openwrt_ubus.sensitivity import (
        SensitivityProfile, Surface,
        classify_export, project, assert_grains_safe,
    )

    profile = SensitivityProfile.load_builtin()
    classified = classify_export(raw_export, package="wireless", profile=profile)
    evidence = project(classified, surface=Surface.EVIDENCE, profile=profile)
    grains = project(classified, surface=Surface.GRAINS, profile=profile)
    assert_grains_safe(grains)
"""

from saltext.openwrt_ubus.sensitivity.classify import classify_export
from saltext.openwrt_ubus.sensitivity.model import TAINT_RANK
from saltext.openwrt_ubus.sensitivity.model import Classification
from saltext.openwrt_ubus.sensitivity.model import Policy
from saltext.openwrt_ubus.sensitivity.model import PolicyDecision
from saltext.openwrt_ubus.sensitivity.model import SensitivityProfile
from saltext.openwrt_ubus.sensitivity.model import Surface
from saltext.openwrt_ubus.sensitivity.model import max_taint
from saltext.openwrt_ubus.sensitivity.project import assert_grains_safe
from saltext.openwrt_ubus.sensitivity.project import diff_projection
from saltext.openwrt_ubus.sensitivity.project import evidence_projection
from saltext.openwrt_ubus.sensitivity.project import grains_projection
from saltext.openwrt_ubus.sensitivity.project import project

__all__ = [
    "Classification",
    "Policy",
    "PolicyDecision",
    "SensitivityProfile",
    "Surface",
    "TAINT_RANK",
    "max_taint",
    "classify_export",
    "project",
    "evidence_projection",
    "grains_projection",
    "diff_projection",
    "assert_grains_safe",
]
