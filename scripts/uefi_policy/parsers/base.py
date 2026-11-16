"""Parser registry and base class (avoids circular imports)."""

from __future__ import annotations

from typing import List

from uefi_policy.model import Option

_REGISTRY: dict = {}


class BaseParser:
    """Abstract parser interface."""

    def parse(self, source: str) -> List[Option]:
        raise NotImplementedError


def register(name: str, cls: type) -> None:
    _REGISTRY[name] = cls


def create(name: str):
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ValueError(f"unknown parser '{name}'; available: {sorted(_REGISTRY)}") from None


def available() -> list:
    return sorted(_REGISTRY)
