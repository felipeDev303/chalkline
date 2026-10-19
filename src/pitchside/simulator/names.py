"""Fictional clubs and players.

A club's squad depends only on its index, so the same player appears in every
match that club plays. Surnames are built from invented syllables to stay clear
of real players.
"""

from __future__ import annotations

from typing import Literal

from pitchside.events.schema import Player, Team
from pitchside.simulator.rng import Rng

# (name, short_name, home ground)
CLUBS: tuple[tuple[str, str, str], ...] = (
    ("Corvane United", "COR", "Millrace Ground"),
    ("Brindlemoor FC", "BRM", "Heathside Park"),
    ("Halvesham Town", "HAL", "The Saltings"),
    ("Quillon Rovers", "QUI", "Lanternfield"),
    ("Westerlake City", "WLC", "Westerlake Arena"),
    ("Fernhallow Albion", "FER", "Fernhallow Lane"),
    ("Dravenport Athletic", "DRV", "Quayside Stadium"),
    ("Oskaby Wanderers", "OSK", "Oskaby Common"),
)

# 4-3-3 slots, in order: GK, LB, LCB, RCB, RB, LCM, CM, RCM, LW, ST, RW.
POSITIONS: tuple[Literal["GK", "DF", "MF", "FW"], ...] = (
    "GK", "DF", "DF", "DF", "DF", "MF", "MF", "MF", "FW", "FW", "FW",
)
SHIRTS: tuple[int, ...] = (1, 3, 5, 4, 2, 8, 6, 10, 11, 9, 7)
GK = 0
MIDFIELDERS = (5, 6, 7)
FORWARDS = (8, 9, 10)
ST = 9

FIRST_NAMES = (
    "Aaron", "Adel", "Anders", "Bastien", "Bruno", "Callum", "Cyril", "Dario",
    "Dmitri", "Elias", "Emeka", "Enzo", "Felix", "Femi", "Gael", "Goran",
    "Hamza", "Hugo", "Idris", "Ilan", "Ivo", "Jasper", "Jonah", "Kai",
    "Kasper", "Kofi", "Leon", "Lorenzo", "Luca", "Marek", "Mateo", "Milan",
    "Nico", "Noah", "Omar", "Oskar", "Owen", "Pablo", "Rafael", "Ruben",
    "Samir", "Soren", "Tariq", "Theo", "Tomas", "Victor", "Yusuf", "Zane",
)
SURNAME_HEADS = (
    "Ald", "Bren", "Cor", "Dal", "Ess", "Fen", "Gal", "Har", "Ister", "Jor",
    "Kel", "Lun", "Mar", "Nor", "Orr", "Pell", "Quen", "Ros", "Sal", "Tor",
    "Ul", "Vane", "Wes", "Yar",
)
SURNAME_TAILS = (
    "ane", "bury", "dell", "ero", "ford", "ic", "ito", "kov", "lund", "mont",
    "ni", "ova", "quist", "rell", "sen", "ton", "uro", "vic", "wick", "zari",
)


def make_team(index: int) -> Team:
    name, short_name, _ = CLUBS[index]
    team_id = f"T{index + 1:02d}"
    rng = Rng(10_000 + index)
    used: set[str] = set()
    players = []
    for position, shirt in zip(POSITIONS, SHIRTS, strict=True):
        surname = rng.choice(SURNAME_HEADS) + rng.choice(SURNAME_TAILS)
        while surname in used:
            surname = rng.choice(SURNAME_HEADS) + rng.choice(SURNAME_TAILS)
        used.add(surname)
        players.append(Player(
            player_id=f"{team_id}-{shirt:02d}",
            name=f"{rng.choice(FIRST_NAMES)} {surname}",
            shirt_number=shirt,
            position=position,
        ))
    return Team(team_id=team_id, name=name, short_name=short_name, players=tuple(players))
