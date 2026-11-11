"""Typed access to JMA disaster prevention XML."""

from .kinds import data_type_code
from .parse import (
    Body,
    Control,
    Head,
    MeteBody,
    ParseError,
    Report,
    SeisBody,
    UnknownBody,
    VolcBody,
    parse,
)

__all__ = [
    "Body",
    "Control",
    "Head",
    "MeteBody",
    "ParseError",
    "Report",
    "SeisBody",
    "UnknownBody",
    "VolcBody",
    "data_type_code",
    "parse",
]
