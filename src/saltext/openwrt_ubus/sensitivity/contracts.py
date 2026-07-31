"""
DataContract annotation for functions that ingest, classify, transform, or emit data.

Usage::

    from saltext.openwrt_ubus.sensitivity.contracts import data_contract

    @data_contract(
        inputs=("uci.raw",),
        outputs=("uci.classified",),
        surfaces=("internal",),
        may_contain_secrets=True,
    )
    def classify_export(...):
        ...

The decorator attaches a DataContract to the function as ``__data_contract__``.
The manifest generator (``saltext.openwrt_ubus.data_manifest``) discovers these
at import time via ``inspect.getmembers``.

Enforcement: tests fail CI if any function in the required set lacks a contract.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    may_contain_secrets: bool = False


def data_contract(**kwargs):
    """Decorator: attach a DataContract to a function as ``__data_contract__``."""
    contract = DataContract(**kwargs)

    def decorate(fn):
        fn.__data_contract__ = contract
        return fn

    return decorate
