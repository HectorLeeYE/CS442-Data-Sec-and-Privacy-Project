"""Loads taxonomy.yaml. Everything policy-shaped comes from that file."""

from functools import lru_cache
from pathlib import Path

import yaml

PATH = Path(__file__).resolve().parent.parent / "taxonomy.yaml"


@lru_cache
def load() -> dict:
    return yaml.safe_load(PATH.read_text())


def tiers() -> list[str]:
    return load()["tiers"]


def rank(tier: str) -> int:
    return tiers().index(tier)


def class_of(etype: str) -> str:
    return load()["types"][etype]["class"]


def harm(etype: str) -> int:
    return load()["classes"][class_of(etype)]["harm"]


def action(etype: str, tier: str) -> str:
    t = load()["types"][etype]
    return t.get("actions", {}).get(tier) or load()["classes"][t["class"]]["actions"][tier]


def matrix() -> dict:
    """{type: {tier: action}} — the policy as the UI and report show it."""
    return {e: {t: action(e, t) for t in tiers()} for e in load()["types"]}
