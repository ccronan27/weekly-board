"""Match players across sources. Name + position (+ team to break ties), per docs/SPEC.md.

A persistent ESPN id to Sleeper id map lives in data/idmap.json so name matching only has to
run for new players. Manual fixes go in config/idmap.overrides.yaml as {espnId: sleeperId}.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from pipeline.common import CONFIG, DATA, norm_pos, norm_team, normalize_name

IDMAP_PATH = DATA / "idmap.json"
OVERRIDES_PATH = CONFIG / "idmap.overrides.yaml"
SKILL = {"QB", "RB", "WR", "TE"}


def index_sleeper(players: dict) -> dict:
    """(normalized name, pos) -> [sleeper ids]. DEF is keyed by team code."""
    idx: dict = {}
    for pid, p in players.items():
        key = (p["team"] or pid, "DEF") if p["pos"] == "DEF" else (normalize_name(p["name"]), p["pos"])
        idx.setdefault(key, []).append(pid)
    return idx


def match_one(name: str, pos: str, team: str | None, players: dict, idx: dict) -> str | None:
    """Return the Sleeper id for a player, or None if there is no single confident match."""
    pos, team = norm_pos(pos), norm_team(team)
    if pos == "DEF":
        return team if team in players and players[team]["pos"] == "DEF" else None
    cands = idx.get((normalize_name(name), pos), [])
    if len(cands) > 1:
        by_team = [c for c in cands if players[c]["team"] == team]
        cands = by_team if by_team else [c for c in cands if players[c]["active"]] or cands
        if len(cands) > 1:
            by_team = [c for c in cands if players[c]["team"] == team]
            cands = by_team or cands
    if len(cands) == 1:
        return cands[0]
    if not cands and pos in SKILL:
        # position can differ between platforms (RB vs WR). Accept a unique same-name, same-team skill player
        alt = [c for p2 in SKILL - {pos} for c in idx.get((normalize_name(name), p2), []) if players[c]["team"] == team]
        if len(alt) == 1:
            return alt[0]
    return None


def load_idmap() -> dict:
    out = {}
    if IDMAP_PATH.exists():
        out = {int(k): v for k, v in json.loads(IDMAP_PATH.read_text(encoding="utf-8")).items()}
    if OVERRIDES_PATH.exists():
        ov = yaml.safe_load(OVERRIDES_PATH.read_text(encoding="utf-8")) or {}
        out.update({int(k): str(v) for k, v in ov.items()})
    return out


def save_idmap(m: dict, path: Path = IDMAP_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({str(k): v for k, v in sorted(m.items())}, indent=0, sort_keys=False) + "\n", encoding="utf-8")


def resolve_espn(entries: list, players: dict, idmap: dict) -> tuple[dict, list]:
    """entries: dicts with espnId, name, pos, team. Returns (updated idmap, unmatched entries).

    Existing map entries win while the Sleeper id still exists. New ones come from name matching.
    """
    idx = index_sleeper(players)
    out, unmatched = {}, []
    for e in entries:
        eid = e["espnId"]
        known = idmap.get(eid)
        if known is not None and known in players:
            out[eid] = known
            continue
        pid = match_one(e["name"], e["pos"], e.get("team"), players, idx)
        if pid is None:
            unmatched.append(e)
        else:
            out[eid] = pid
    # keep map entries for ids not seen this run
    for k, v in idmap.items():
        out.setdefault(k, v)
    return out, unmatched
