"""
UCI sensitivity classification for saltext-uci-ubus.

Quick-start::

    from saltext.uci.sensitivity import (
        SensitivityProfile, Surface,
        classify_export, project, assert_grains_safe,
    )

    profile = SensitivityProfile.load_builtin()
    classified = classify_export(raw_export, package="wireless", profile=profile)
    evidence = project(classified, surface=Surface.EVIDENCE, profile=profile)
    grains = project(classified, surface=Surface.GRAINS, profile=profile)
    assert_grains_safe(grains)
"""

from saltext.uci.sensitivity.classify import classify_export
from saltext.uci.sensitivity.contracts import DataContract
from saltext.uci.sensitivity.contracts import DataKind
from saltext.uci.sensitivity.contracts import data_contract
from saltext.uci.sensitivity.model import TAINT_RANK
from saltext.uci.sensitivity.model import Classification
from saltext.uci.sensitivity.model import Policy
from saltext.uci.sensitivity.model import PolicyDecision
from saltext.uci.sensitivity.model import SensitivityProfile
from saltext.uci.sensitivity.model import Surface
from saltext.uci.sensitivity.model import max_taint
from saltext.uci.sensitivity.project import assert_grains_safe
from saltext.uci.sensitivity.project import diff_projection
from saltext.uci.sensitivity.project import evidence_projection
from saltext.uci.sensitivity.project import grains_projection
from saltext.uci.sensitivity.project import project

__all__ = [
    "Classification",
    "DataContract",
    "DataKind",
    "Policy",
    "PolicyDecision",
    "SensitivityProfile",
    "Surface",
    "TAINT_RANK",
    "data_contract",
    "max_taint",
    "classify_export",
    "project",
    "evidence_projection",
    "grains_projection",
    "diff_projection",
    "assert_grains_safe",
]
