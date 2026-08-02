"""
DataContract annotation for functions that ingest, classify, transform, or emit data.

Usage::

    from saltext.uci.sensitivity.contracts import data_contract

    @data_contract(
        inputs=("uci.raw",),
        outputs=("uci.classified",),
        surfaces=("internal",),
        handles_secrets=True,
        emits_secrets=True,
    )
    def classify_export(...):
        ...

Fields
------
handles_secrets : bool | None
    True  — function receives or processes data that may contain secrets.
    False — function only processes data already known to be secret-free.
    None  — unknown; the manifest check will emit a WARN for this function.

emits_secrets : bool | None
    True  — function output may contain secret values (intermediate only;
    output data type must itself be secret_capable=True).
    False — function guarantees its output contains no secret values.
    None  — unknown; the manifest check will emit a WARN for this function.

guards : tuple[str, ...]
    Names of functions whose invocation is what makes emits_secrets=False
    believable for an otherwise secret-capable input. Used by --check to
    surface the enforcement relationship rather than merely asserting the
    resulting property.

The decorator attaches a DataContract to the function as ``__data_contract__``.
The manifest generator (``saltext.uci.data_manifest``) discovers these
at import time via ``inspect.getmembers``.

Enforcement: tests fail CI if any function in the required set lacks a contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum


class DataKind(str, Enum):
    CONFIGURED_STATE = "configured_state"
    OBSERVED_STATE = "observed_state"
    SECRET = "secret"
    SENSITIVE = "sensitive"


@dataclass(frozen=True)
class DataContract:
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    surfaces: tuple[str, ...]
    handles_secrets: bool | None = None
    emits_secrets: bool | None = None
    guards: tuple[str, ...] = field(default_factory=tuple)


def data_contract(**kwargs):
    """Decorator: attach a DataContract to a function as ``__data_contract__``."""
    contract = DataContract(**kwargs)

    def decorate(fn):
        fn.__data_contract__ = contract
        return fn

    return decorate
