"""Warning classification and composable predicates."""

from .possibility import Possibility, PossibilityCell, WarningPossibility, warning_possibility
from .warning import (
    Element,
    Predicate,
    Stage,
    WarningKind,
    classify_flood,
    classify_mete,
    element_in,
    level_at_least,
    rank,
    stage_at_least,
)

__all__ = [
    "Element",
    "Possibility",
    "PossibilityCell",
    "Predicate",
    "Stage",
    "WarningKind",
    "WarningPossibility",
    "classify_flood",
    "classify_mete",
    "element_in",
    "level_at_least",
    "rank",
    "stage_at_least",
    "warning_possibility",
]
