"""Print a markdown table of per-source status for the Actions run summary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import BUILD, read_json, source_state  # noqa: E402

meta = read_json(BUILD / "meta.json")
print(f"### Week {meta['week']}, built {meta['generatedAt']}\n")
print("| Source | Status | Last updated |\n|---|---|---|")
for k, v in sorted(meta["sources"].items()):
    if k.startswith(("sleeper_stats_w", "espn_lineups_w")):
        continue
    status = {"fresh": "ok", "stale": "STALE", "missing": "MISSING"}[source_state(v)]
    print(f"| {k} | {status}{' ' + v['error'] if v['error'] else ''} | {v['lastUpdated'] or '-'} |")
r = meta["espnRosters"]
if r["syncedAt"] is None or r["ageDays"] is None:
    print("\nESPN rosters: none usable\n")
else:
    cached = ", the roster file was unusable so the last good sync is in use" if r.get("fromCache") else ""
    print(f"\nESPN rosters: {r['syncedAt']} ({r['ageDays']} days old{', STALE' if r['stale'] else ''}{cached})\n")
for l in meta["leagues"]:
    lg = read_json(BUILD / l["file"])
    best = (lg.get("waivers") or {}).get("targets") or []
    add = f", best add {best[0]['player']['name']} {best[0]['gain']:+.1f}" if best else ""
    tf = BUILD / ((lg.get("trade") or {}).get("file") or "none")
    ideas = read_json(tf)["ideas"] if tf.exists() else []
    idea = f", {len(ideas)} trade idea{"s" if len(ideas) != 1 else ""} (best {ideas[0]['myGain']:+.1f} for you)" if ideas else ""
    print(f"- {l['name']}: lineup change {l['gain']:+.1f}{add}{idea}")
for s in meta.get("skippedLeagues", []):
    print(f"- {s['name']}: skipped, {s['reason']}")
