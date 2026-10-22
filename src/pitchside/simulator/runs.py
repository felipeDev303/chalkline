"""Planted off-ball runs: the cause the attribution engine must find on its own.

Three kinds, so that naive heuristics fail somewhere:
- direct, free: the runner moves into space, the marker stays; the runner receives.
- decoy: the runner drags the marker away and a teammate receives in the space left.
  "Credit the recipient" gets these wrong.
- direct, tracked: the marker follows; lots of movement, no space created.
  "Credit whoever moved most" gets these wrong.

Labels go to the truth sidecar only; the event stream carries positions, never labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pitchside.simulator.pitch import XY

RunKind = Literal["direct", "decoy"]


@dataclass
class ActiveRun:
    side: int
    kind: RunKind
    runner: int  # formation slot, attacking side
    marker: int  # formation slot, defending side
    beneficiary: int  # who the run frees: the runner (direct) or a teammate (decoy)
    target: XY  # runner's position during the run, attacking frame
    follows: bool  # the marker goes with the runner
    label_index: int


class RunLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: str
    player_id: str  # the runner: who should get the credit when the run worked
    kind: RunKind
    tracked: bool  # the marker followed (always true for a decoy)
    effective: bool  # the run freed someone: a decoy, or a direct run the marker let go
    marker_id: str
    beneficiary_id: str
    start_seq: int  # first event whose frame shows the run
    pass_seq: int | None = None  # the pass played while the run was on, if any
    pass_to_beneficiary: bool | None = None
    pass_outcome: str | None = None
