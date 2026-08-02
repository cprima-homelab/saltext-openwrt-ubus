"""
Sensitivity classification model for UCI field data.

Three core concepts:
  classification  — property of a field (option):  PUBLIC / INTERNAL / UNKNOWN / SENSITIVE / SECRET
  taint           — property of a container (section): max_taint(option classifications)
  policy          — per-surface rule: ALLOW / REDACT_VALUE / DENY_VALUE / REPORT_CHANGE

UNKNOWN is NOT ordered between PUBLIC and INTERNAL in any severity chain.
Its conservatism comes from explicit policy entries in the profile.
Use TAINT_RANK for any ranking comparison that includes UNKNOWN.
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

import yaml


class Classification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    UNKNOWN = "unknown"
    SENSITIVE = "sensitive"
    SECRET = "secret"


TAINT_RANK: dict[Classification, int] = {
    Classification.PUBLIC: 0,
    Classification.INTERNAL: 1,
    Classification.UNKNOWN: 2,
    Classification.SENSITIVE: 3,
    Classification.SECRET: 4,
}


def max_taint(classifications: Iterable[Classification]) -> Classification:
    """Return the classification with the highest taint rank."""
    return max(classifications, key=lambda cl: TAINT_RANK[cl], default=Classification.PUBLIC)


class Surface(str, Enum):
    GRAINS = "grains"
    EVIDENCE = "evidence"
    LOGS = "logs"
    CLI_OUTPUT = "cli_output"
    CONFIG_DIFF = "config_diff"


class Policy(str, Enum):
    ALLOW = "allow"
    REDACT_VALUE = "redact"
    DENY_VALUE = "deny"
    REPORT_CHANGE = "report-change"


@dataclass(frozen=True)
class PolicyDecision:
    classification: Classification
    policy: Policy


_SURFACE_KEY_MAP: dict[str, Surface] = {
    "grains": Surface.GRAINS,
    "evidence": Surface.EVIDENCE,
    "logs": Surface.LOGS,
    "cli_output": Surface.CLI_OUTPUT,
    "config_diff": Surface.CONFIG_DIFF,
}


@dataclass(frozen=True)
class MatchCriteria:
    package: str | None = None
    section_type: str | list[str] | None = None
    option: str | list[str] | None = None

    def specificity(self) -> int:
        """1 = option-only, 2 = two dimensions, 3 = all three."""
        return sum(x is not None for x in (self.package, self.section_type, self.option))

    def matches(self, package: str, section_type: str, option: str) -> bool:
        if self.package is not None and self.package != package:
            return False
        if self.section_type is not None:
            types = (
                self.section_type if isinstance(self.section_type, list) else [self.section_type]
            )
            if section_type not in types:
                return False
        if self.option is not None:
            opts = self.option if isinstance(self.option, list) else [self.option]
            if option not in opts:
                return False
        return True


@dataclass
class ClassificationRule:
    match: MatchCriteria
    classification: Classification


@dataclass
class SensitivityProfile:
    name: str
    version: str
    rules: list[ClassificationRule]
    policies: dict[Classification, dict[Surface, Policy]]

    def classify(self, package: str, section_type: str, option: str) -> Classification:
        """Return classification for an option.

        Highest specificity wins; at equal specificity, last matching rule wins.
        Unmatched options default to UNKNOWN.
        """
        best_spec = -1
        result = Classification.UNKNOWN
        for rule in self.rules:
            if rule.match.matches(package, section_type, option):
                spec = rule.match.specificity()
                if spec >= best_spec:
                    best_spec = spec
                    result = rule.classification
        return result

    def policy(self, classification: Classification, surface: Surface) -> Policy:
        return self.policies[classification][surface]

    def evaluate(
        self, package: str, section_type: str, option: str, surface: Surface
    ) -> PolicyDecision:
        cl = self.classify(package, section_type, option)
        return PolicyDecision(cl, self.policy(cl, surface))

    def overlay(self, other: SensitivityProfile) -> SensitivityProfile:
        """Return new profile: other's rules appended, policies merged (other wins), other's identity."""
        merged: dict[Classification, dict[Surface, Policy]] = {}
        for cl in Classification:
            merged[cl] = {**self.policies.get(cl, {}), **other.policies.get(cl, {})}
        return SensitivityProfile(
            name=other.name,
            version=other.version,
            rules=self.rules + other.rules,
            policies=merged,
        )

    @classmethod
    def load_builtin(cls) -> SensitivityProfile:
        pkg = importlib.resources.files("saltext.uci.sensitivity")
        text = pkg.joinpath("builtin.yaml").read_text(encoding="utf-8")
        return cls._from_yaml(text)

    @classmethod
    def _from_yaml(cls, text: str) -> SensitivityProfile:
        data = yaml.safe_load(text)
        rules: list[ClassificationRule] = []
        for r in data.get("rules", []):
            m = r["match"]
            criteria = MatchCriteria(
                package=m.get("package"),
                section_type=m.get("section_type"),
                option=m.get("option"),
            )
            rules.append(
                ClassificationRule(
                    match=criteria,
                    classification=Classification(r["classification"]),
                )
            )
        raw_policies = data.get("policies", {})
        policies: dict[Classification, dict[Surface, Policy]] = {}
        for cl_str, surface_map in raw_policies.items():
            cl = Classification(cl_str)
            policies[cl] = {}
            for surf_str, pol_str in surface_map.items():
                surf = _SURFACE_KEY_MAP[surf_str]
                policies[cl][surf] = Policy(pol_str)
        return cls(
            name=data["name"],
            version=str(data["version"]),
            rules=rules,
            policies=policies,
        )
