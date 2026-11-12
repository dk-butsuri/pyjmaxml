"""Warning classification and composable predicates."""

from .forecast import ForecastCell, ForecastElement, WeatherForecast, weather_forecast
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
    "ForecastCell",
    "ForecastElement",
    "Possibility",
    "PossibilityCell",
    "Predicate",
    "Stage",
    "WarningKind",
    "WarningPossibility",
    "WeatherForecast",
    "classify_flood",
    "classify_mete",
    "element_in",
    "level_at_least",
    "rank",
    "stage_at_least",
    "warning_possibility",
    "weather_forecast",
]
