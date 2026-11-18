# Weekly Board: Spec (updated 11/17/26)

## Goal
A self-updating start/sit dashboard across all of Conor's fantasy leagues. Runs on GitHub Actions and GitHub Pages. The only Claude-dependent piece is the ESPN roster sync.

## Accounts
- GitHub: ccronan27, repo `weekly-board` (public)
- Sleeper user: conorcronan (user_id 865460014343634944)
- ESPN: Conor's team is teamId 14 in league 125685129

## Leagues
| League | Platform | ID | Teams | Scoring | Starters | Access |
|---|---|---|---|---|---|---|
| Fantasizing 2026 | ESPN | 125685129 | 14 | Full PPR | QB, RB, 2 WR, TE, 2 FLEX, D/ST, K. 4 BN, 2 IR | Rosters + settings from `data/espn/rosters.json`, written by the Claude `espn-roster-sync` skill. League is private. Actions never logs in to ESPN |
| HWH: The League | Sleeper | 1389389185361653760 | 12 | Full PPR, no bonuses | QB, 2 RB, 2 WR, TE, 2 FLEX, K, DEF | Public Sleeper API |
| Chicago Dynasty | Sleeper | 1335703355086893056 | 12 | Half PPR, TE premium +0.5/rec, 400 pass / 200 rush / 200 rec yd bonuses, 50+ yd TD bonuses, custom K scoring | QB, 2 RB, 2 WR, TE, 3 FLEX, K (no DEF) | Public Sleeper API |

## League settings
- Pulled automatically from each platform every run
- `config/leagues/<league>.overrides.yaml` for anything the APIs miss
- Season rollover = update league IDs only

## Data sources
| Source | Endpoint | Auth | Notes |
|---|---|---|---|
| Sleeper leagues, rosters, users | `api.sleeper.app/v1/...` | None | Official, read-only. Ask under 1000 req/min |
| Sleeper projections | `api.sleeper.app/projections/nfl/{season}/{week}?season_type=regular&position[]=QB` (repeat per position) | None | Unofficial. Provider: Rotowire (`company` field). Raw stat lines in `stats`, re-scorable |
| Sleeper actual stats | `api.sleeper.app/stats/nfl/{season}/{week}?season_type=regular&position[]=QB` | None | Unofficial. `pts_ppr` etc. |
| ESPN default projections | `lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3?view=kona_player_info&scoringPeriodId={week}` with header `X-Fantasy-Filter: {"players":{"limit":1200,"filterSlotIds":{"value":[0,2,4,6]},"sortPercOwned":{"sortAsc":false,"sortPriority":1}}}` | None (verified 11/17 without cookies, from a browser. Verify from Actions runners) | Weekly projection = stat with `scoringPeriodId == week`, `statSourceId == 1`, `statSplitTypeId == 1`. Actual = `statSourceId == 0`. `appliedTotal` is default PPR. Raw stats in `stats` map keyed by ESPN stat id |
| ESPN league rosters + settings | `data/espn/rosters.json` | n/a | Written by Claude skill. See schema below |
| Vegas lines | `raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv` | None | `spread_line` = home expected margin, `total_line`. Implied home = (total + spread) / 2, away = (total - spread) / 2. Team codes: nflverse `LA` = Sleeper `LAR` |
| Injuries / news | Sleeper player fields `injury_status`, `injury_notes`, `news_updated` | None | v1 starting point |

Player matching across sources: normalize name (lowercase, strip `.'’-`, drop jr/sr/ii/iii/iv/v suffixes, collapse spaces) + position. Backtest matched 3,450 player-weeks this way. Build a persistent ID map (Sleeper id <-> ESPN id) to replace name matching over time.

## `data/espn/rosters.json` schema (written by Claude skill)
```json
{
  "ok": true, "platform": "espn", "leagueId": 125685129, "season": 2026, "week": 11,
  "syncedAt": "ISO-8601",
  "settings": { "name": "...", "teams": 14, "lineupSlotCounts": { "0": 1, "2": 1, "4": 2, "6": 1, "16": 1, "17": 1, "20": 4, "21": 2, "23": 2 }, "scoringByStatId": { "53": 1 } },
  "teams": [ { "teamId": 14, "name": "...", "roster": [ { "espnId": 3054211, "name": "...", "pos": "RB", "proTeamId": 25, "slot": "RB", "injuryStatus": "ACTIVE" } ] } ]
}
```
Slot ids: 0 QB, 2 RB, 4 WR, 6 TE, 16 D/ST, 17 K, 20 BN, 21 IR, 23 FLEX.

## Projection model (see docs/BACKTEST.md)
- Re-score every source's raw stat projections with each league's exact scoring
- Core = equal average of ESPN + Rotowire
- NO Vegas multiplier, NO accuracy weighting, NO calibration. All three overfit in the cross-season test
- Show implied team total + spread on player cards as context only
- Volatility (boom/bust) = player's own weekly scoring SD this season, not source disagreement
- Any model change must beat the equal average in the cross-season backtest (fit on last season, score on this season) before it ships

## Refresh schedule (America/Chicago, off the top of the hour)
| Run | Who | Why |
|---|---|---|
| Tue 9:07pm | Actions | Post-MNF baseline, before Wed 3am waivers |
| Wed 7:13am | Claude skill | ESPN roster sync after waivers |
| Thu 2:07pm | Actions | TNF injury reports |
| Fri 5:07pm | Actions | Final injury designations |
| Sun 9:07am | Claude skill + Actions | ESPN roster sync + morning news |
| Sun 10:47am | Actions | Inactives for noon games |
| Sun 1:07pm | Actions | Inactives for late games |
| On demand | Both | `workflow_dispatch` button (GitHub mobile), or "sync ESPN" to Claude |

Actions should also run when `data/espn/rosters.json` changes (push trigger on that path).

## Hosting and security
- GitHub Pages via Actions, public repo
- No credentials, tokens or cookies anywhere in the repo, workflows or site
- noindex meta tag + robots.txt Disallow all
- No owners' real names. Team names only
- Every section shows "last updated" per data source, and flags stale data (ESPN sync older than 4 days)

## Known GitHub risks
- Scheduled workflows auto-disable after 60 days of no repo activity (offseason). Preseason checklist: re-enable in August
- Cron runs can be delayed or dropped under load. Off-minute times, staleness stamps, manual button

## Roadmap
- v1: start/sit per league. Consensus projection, floor/ceiling from weekly SD, Vegas context, injury/inactive alerts, flag any starter who is OUT/IR/bye
- v2 (shipped 11/18/26): waiver targets per league, scored against each team's weakest starting slots, byes and injuries. Short term: the gain in your best lineup this week. Long term: the gain summed over the fantasy playoff weeks, using this week's projection as the rate for healthy skill players and the season average for DEF, K and players hurt or on bye now. Playoff matchup strength is display context only. See `pipeline/waivers.py`
- v3 (shipped 11/18/26): trade analyzer (dynasty-aware for Chicago Dynasty). Ideas are 1 for 1 trades that raise both teams' playoff lineups. The site builder handles any trade. Dynasty awareness is ages plus a flag when you send away a player 4 or more years younger. See `pipeline/trades.py`
- v1 stores full league player pools so v2 needs no rework
