"""Contract shared by every metric tool.

A tool is a module with TOOL_NAME, DESCRIPTION (written for the model choosing
tools), a `Params` model and `run(match, params) -> ToolResult`. `run` is a pure
function of the metadata and the events up to `params.as_of_seq`.

Numbers reach a narrative only through `Fact.display`: a pre-rounded string the
narrative must quote. Build facts with `fact()` / `minute_fact()` so value and
display always agree. `ToolResult.table` is for rendering only; anything a
narrative may quote must also be a fact.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pitchside.events.match import Match

Unit = Literal[
    "count", "decimal", "pct", "share", "m", "km/h", "score", "per_min", "seconds", "minute",
    "formation", "scoreline", "label",
]
# Units whose value is a string shown as is. `label` is words only (a window state);
# digit groups must be a `formation` (ordered) or a `scoreline` (unordered pair).
TEXT_UNITS = frozenset({"formation", "scoreline", "label"})

# Decimals and suffix of the display string, per unit. `pct` is a rate (completion),
# `share` a split of a whole (possession), `score` a 0-100 index.
_DECIMALS: dict[str, int] = {
    "count": 0, "decimal": 1, "pct": 1, "share": 0, "m": 1, "km/h": 1, "score": 0,
    "per_min": 1, "seconds": 1,
}
_SUFFIX: dict[str, str] = {
    "count": "", "decimal": "", "pct": "%", "share": "%", "m": " m", "km/h": " km/h",
    "score": "", "per_min": "/min", "seconds": " s",
}
EVIDENCE_ID_PATTERN = r"^[a-z][a-z_]*[.:][A-Za-z0-9_.:@+\-]+$"
MINUTE_DISPLAY_RE = re.compile(r"^\d{1,3}(\+\d{1,2})?'$")
_TEXT_DISPLAY_RE = {
    "formation": re.compile(r"^\d(?:-\d){2,4}$"),
    "scoreline": re.compile(r"^\d{1,2}-\d{1,2}$"),
    "label": re.compile(r"^[^\d]+$"),
}
MAX_TABLE_ROWS = 20


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- display ------------------------------------------------------------------

def round_value(value: float, unit: Unit) -> int | float:
    """Round half away from zero (83.65 -> 83.7) to the unit's display precision."""
    decimals = _DECIMALS[unit]
    rounded = Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)
    return int(rounded) if decimals == 0 else float(rounded)


def format_display(value: float, unit: Unit) -> str:
    decimals = _DECIMALS[unit]
    return f"{round_value(value, unit):.{decimals}f}{_SUFFIX[unit]}"


def minute_display(minute: int, added: int = 0) -> str:
    """Football minute mark: 63' or, in added time, 45+2'."""
    return f"{minute}+{added}'" if added else f"{minute}'"


# --- facts and results ----------------------------------------------------------

class Fact(_Strict):
    evidence_id: Annotated[str, Field(pattern=EVIDENCE_ID_PATTERN)]
    label: str
    value: int | float | str
    unit: Unit
    display: str

    @model_validator(mode="after")
    def _display_matches_value(self) -> Fact:
        if self.unit in TEXT_UNITS:
            ok = (
                isinstance(self.value, str)
                and self.display == self.value
                and bool(_TEXT_DISPLAY_RE[self.unit].match(self.display))
            )
        elif self.unit == "minute":
            ok = isinstance(self.value, int) and bool(MINUTE_DISPLAY_RE.match(self.display))
        else:
            ok = not isinstance(self.value, str) and (
                self.display == format_display(self.value, self.unit)
                and self.value == round_value(self.value, self.unit)
            )
        if not ok:
            raise ValueError(f"display {self.display!r} does not match value {self.value!r}")
        return self


def fact(evidence_id: str, label: str, value: float | str, unit: Unit) -> Fact:
    if unit in TEXT_UNITS:
        return Fact(evidence_id=evidence_id, label=label, value=str(value), unit=unit,
                    display=str(value))
    if unit == "minute":
        raise ValueError("use minute_fact() for minute marks")
    assert not isinstance(value, str)
    rounded = round_value(value, unit)
    return Fact(evidence_id=evidence_id, label=label, value=rounded, unit=unit,
                display=format_display(rounded, unit))


def minute_fact(evidence_id: str, label: str, minute: int, added: int = 0) -> Fact:
    """`value` is the minute plus added time (for ordering); `display` the minute mark."""
    return Fact(evidence_id=evidence_id, label=label, value=minute + added, unit="minute",
                display=minute_display(minute, added))


class Table(_Strict):
    columns: tuple[str, ...]
    rows: tuple[tuple[str | int | float | None, ...], ...]

    @model_validator(mode="after")
    def _shape(self) -> Table:
        if len(self.rows) > MAX_TABLE_ROWS:
            raise ValueError(f"table has {len(self.rows)} rows; max is {MAX_TABLE_ROWS}")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("every table row must have one cell per column")
        return self


class ToolResult(_Strict):
    tool_name: str
    params: dict[str, Any]
    as_of_seq: Annotated[int, Field(ge=0)]
    facts: tuple[Fact, ...]
    table: Table | None = None
    sample_size: Annotated[int, Field(ge=0)]
    method: Annotated[str, Field(min_length=1)]
    caveats: tuple[str, ...] = ()
    cannot_tell: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _unique_evidence_ids(self) -> ToolResult:
        ids = [f.evidence_id for f in self.facts]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate evidence ids: {dupes}")
        return self


# --- tools ----------------------------------------------------------------------

class ToolParams(BaseModel):
    """Base for every tool's Params. Subclasses use Literal for choices."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of_seq: Annotated[int, Field(
        ge=0,
        description="Seq of the latest event the tool may see (inclusive). "
        "Pass the replay's current seq; later events are never read.",
    )]


ToolErrorCode = Literal["as_of_out_of_range", "unknown_team", "unknown_player", "invalid_params"]


class ToolError(Exception):
    """A call the agent can fix (bad id, seq out of range). `str(err)` is safe to show it."""

    def __init__(self, code: ToolErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: type[ToolParams]
    run: Callable[[Match, Any], ToolResult]
