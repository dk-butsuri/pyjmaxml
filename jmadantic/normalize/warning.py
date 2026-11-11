"""Code-based warning classification and composable selection predicates."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum, StrEnum

_LOGGER = logging.getLogger(__name__)
# Only the documented 'レベルＮ' label supplies a meteorological warning level.
# ASCII and fullwidth decimal digits are both valid in JMA labels.
_LEVEL = re.compile(r"レベル([0-9０-９]+)")


class Element(StrEnum):
    HEAVY_RAIN = "heavy_rain"
    LANDSLIDE = "landslide"
    STORM_SURGE = "storm_surge"
    STORM = "storm"
    SNOWSTORM = "snowstorm"
    HIGH_WAVE = "high_wave"
    HEAVY_SNOW = "heavy_snow"
    FLOOD = "flood"
    OTHER = "other"
    UNKNOWN = "unknown"


class Stage(IntEnum):
    ADVISORY = 1
    WARNING = 2
    DANGER_WARNING = 3
    EMERGENCY = 4


@dataclass(frozen=True)
class WarningKind:
    name: str
    code: str
    group: str
    element: Element
    stage: Stage | None
    level: int | None


# Implementation plan §0.6. Names are preserved, never used to guess a code.
_METE: dict[str, tuple[str, Element, Stage]] = {
    "10": ("VPWW55", Element.HEAVY_RAIN, Stage.ADVISORY),
    "03": ("VPWW55", Element.HEAVY_RAIN, Stage.WARNING),
    "43": ("VPWW55", Element.HEAVY_RAIN, Stage.DANGER_WARNING),
    "33": ("VPWW55", Element.HEAVY_RAIN, Stage.EMERGENCY),
    "29": ("VPWW56", Element.LANDSLIDE, Stage.ADVISORY),
    "09": ("VPWW56", Element.LANDSLIDE, Stage.WARNING),
    "49": ("VPWW56", Element.LANDSLIDE, Stage.DANGER_WARNING),
    "39": ("VPWW56", Element.LANDSLIDE, Stage.EMERGENCY),
    "19": ("VPWW57", Element.STORM_SURGE, Stage.ADVISORY),
    "08": ("VPWW57", Element.STORM_SURGE, Stage.WARNING),
    "48": ("VPWW57", Element.STORM_SURGE, Stage.DANGER_WARNING),
    "38": ("VPWW57", Element.STORM_SURGE, Stage.EMERGENCY),
    "15": ("VPWW58", Element.STORM, Stage.ADVISORY),
    "13": ("VPWW58", Element.SNOWSTORM, Stage.ADVISORY),
    "05": ("VPWW58", Element.STORM, Stage.WARNING),
    "02": ("VPWW58", Element.SNOWSTORM, Stage.WARNING),
    "35": ("VPWW58", Element.STORM, Stage.EMERGENCY),
    "32": ("VPWW58", Element.SNOWSTORM, Stage.EMERGENCY),
    "16": ("VPWW59", Element.HIGH_WAVE, Stage.ADVISORY),
    "07": ("VPWW59", Element.HIGH_WAVE, Stage.WARNING),
    "37": ("VPWW59", Element.HIGH_WAVE, Stage.EMERGENCY),
    "12": ("VPWW60", Element.HEAVY_SNOW, Stage.ADVISORY),
    "06": ("VPWW60", Element.HEAVY_SNOW, Stage.WARNING),
    "36": ("VPWW60", Element.HEAVY_SNOW, Stage.EMERGENCY),
    **{
        code: ("VPWW61", Element.OTHER, Stage.ADVISORY)
        for code in ("14", "17", "20", "21", "22", "23", "24", "25", "26", "27")
    },
}
_FLOOD: dict[str, tuple[Stage, int]] = {
    "20": (Stage.ADVISORY, 2),
    "21": (Stage.ADVISORY, 2),
    "22": (Stage.ADVISORY, 2),
    "30": (Stage.WARNING, 3),
    "31": (Stage.WARNING, 3),
    "40": (Stage.DANGER_WARNING, 4),
    "41": (Stage.DANGER_WARNING, 4),
    "51": (Stage.EMERGENCY, 5),
    "53": (Stage.EMERGENCY, 5),
}


def classify_mete(code: str, name: str) -> WarningKind:
    """Classify §0.6 codes; an unresolved group is represented by an empty string.

    Code 00 is a cancellation without an element or stage. Like an unknown
    code it cannot identify a VPWW group, but it does not emit a warning.
    """
    if code == "00":
        return WarningKind(name, code, "", Element.UNKNOWN, None, None)
    classification = _METE.get(code)
    if classification is None:
        _LOGGER.warning("Unknown meteorological warning code %r (%s)", code, name)
        return WarningKind(name, code, "", Element.UNKNOWN, None, None)
    group, element, stage = classification
    level: int | None = None
    if element in {Element.HEAVY_RAIN, Element.LANDSLIDE, Element.STORM_SURGE}:
        match = _LEVEL.search(name)
        if match is not None:
            level = int(match.group(1))
    return WarningKind(name, code, group, element, stage, level)


def classify_flood(code: str, name: str, group: str) -> WarningKind:
    """Classify §0.7 river codes, including old names with the same codes."""
    if group not in {"VXKO", "VXSU"}:
        raise ValueError("Flood warning group must be VXKO or VXSU")
    if code == "10":
        return WarningKind(name, code, group, Element.FLOOD, None, None)
    classification = _FLOOD.get(code)
    if classification is None:
        _LOGGER.warning("Unknown flood warning code %r in %s (%s)", code, group, name)
        return WarningKind(name, code, group, Element.UNKNOWN, None, None)
    stage, level = classification
    return WarningKind(name, code, group, Element.FLOOD, stage, level)


@dataclass(frozen=True)
class Predicate:
    """A callable warning predicate supporting short-circuit &, |, and ~."""

    function: Callable[[WarningKind], bool]

    def __call__(self, kind: WarningKind) -> bool:
        return self.function(kind)

    def __and__(self, other: Predicate) -> Predicate:
        return Predicate(lambda kind: self(kind) and other(kind))

    def __or__(self, other: Predicate) -> Predicate:
        return Predicate(lambda kind: self(kind) or other(kind))

    def __invert__(self) -> Predicate:
        return Predicate(lambda kind: not self(kind))


def level_at_least(n: int) -> Predicate:
    """Match only warnings whose known level is at least n."""
    return Predicate(lambda kind: kind.level is not None and kind.level >= n)


def stage_at_least(stage: Stage) -> Predicate:
    """Match only warnings whose known stage is at least stage."""
    return Predicate(lambda kind: kind.stage is not None and kind.stage >= stage)


def element_in(*elements: Element) -> Predicate:
    """Match any of the specified elements; no elements matches nothing."""
    choices = frozenset(elements)
    return Predicate(lambda kind: kind.element in choices)


def rank(kind: WarningKind) -> tuple[int, int]:
    """Return stage rank (or -1), followed by level (or zero)."""
    return (int(kind.stage) if kind.stage is not None else -1, kind.level or 0)
