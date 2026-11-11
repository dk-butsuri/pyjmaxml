"""Published JMA area dictionaries; importing them needs no spreadsheet reader.

AREA_CITY maps weather-warning city codes to (name, prefectural forecast code,
primary subdivision code), using the source's explicit weather-warning flag.
The pinned water-level warning table has no data rows, so its dictionary is empty.
"""

from ._area_city import AREA_CITY
from ._area_flood_forecast import AREA_FLOOD_FORECAST
from ._area_water_level_warning import AREA_WATER_LEVEL_WARNING

__all__ = ["AREA_CITY", "AREA_FLOOD_FORECAST", "AREA_WATER_LEVEL_WARNING"]
