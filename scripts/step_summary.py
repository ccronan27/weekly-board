"""Print a markdown table of per-source status for the Actions run summary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import BUILD, read_json  # noqa: E402

meta = read_json(BUILD / "meta.json")
print(f"### Week {meta['week']}, built {meta['generatedAt']}\n")
print("| Source | Status | Last updated |\n|---|---|---|")
for k, v in sorted(meta["sources"].items()):
    if k.startswith("sleeper_stats_w"):
        continue
    status = "ok" if v["ok"] and not v["stale"] else ("STALE" if v["lastUpdated"] else "MISSING")
    print(f"| {k} | {status}{' ' + v['error'] if v['error'] else ''} | {v['lastUpdated'] or '-'} |")
r = meta["espnRosters"]
print(f"\nESPN roster sync: {r['syncedAt']} ({r['ageDays']} days old{', STALE' if r['stale'] else ''})\n")
for l in meta["leagues"]:
    print(f"- {l['name']}: lineup change {l['gain']:+.1f}")
