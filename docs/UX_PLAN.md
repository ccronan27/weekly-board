# UX plan (11/19/26, shipped as v5)

The end-user review of the live board found the gaps below. This file is the plan and the data contract that every work package codes against. Pipeline packages add fields. Site packages read them. Every new field is optional on the site: when a field is absent (older build, ESPN league), the site hides that piece and never breaks.

## Rules every package follows
- Read `CLAUDE.md`, `docs/SPEC.md`, `docs/STATES.md` first. Hard rules there win over this file
- UI copy: no em dashes, no semicolons, plain and direct. Times in Central. `tests/test_site.py` enforces some of this
- No `https://` URL inside any file in `site/` (test enforced). Outbound links come from data in `data/build/`
- No new dependencies. Plain JS (ES2017, `function` style like the existing code), no build step. Python 3.12 + requests/pandas/pyyaml
- Projection model does not change. New numbers are display context only
- Every string from data goes in with `textContent`, never HTML
- Each package adds tests for what it adds (pytest, and node-run pure functions the way `tests/test_states.py` does)
- `python -m pytest` passes before you commit
- Do not commit changes under `data/` (run `git checkout -- data/ && git clean -fd data/` before committing). Do not edit README.md or SPEC.md. The integrator updates docs and data
- Commit on your worktree branch with a clear message. Do not push

## Data contract (new fields)

### League file `data/build/{league}.json`
| Field | Package | Shape |
|---|---|---|
| `league.appUrl` | P1 | Sleeper: `https://sleeper.com/leagues/{leagueId}/team`. ESPN: `https://fantasy.espn.com/football/team?leagueId={id}&teamId={espnTeamId}` |
| `league.appName` | P1 | `"Sleeper"` or `"ESPN"` |
| team names | P1 | A Sleeper team with no name set is `"Team {rosterId} (no name set)"` everywhere (standings, trades) |
| player record `newsUpdated` | P1 | ISO string or null (Sleeper `news_updated` is epoch ms, convert) |
| player record `recent` | P1 | Last 4 played weeks in this league's scoring, oldest first: `[{"week": 9, "pts": 14.2}]`. Empty list when none |
| `lineup.slots[i].nextBest` | P1 | Best eligible, unlocked player NOT in the recommended lineup who could fill this slot: `{"id","name","pos","points"}` or null |
| `lineup.watch[i].backup`, `lineup.alerts[i].backup` | P1 | Best eligible, unlocked, non-starting player for that slot: `{"id","name","points","kickoff","gain"}` or null. `gain` = backup points minus the flagged player's points (alerts: minus 0) |
| `lineup.watch[i].lateRisk` | P1 | true when the flagged player kicks off after every eligible backup for the slot, so no swap is left if he is ruled out late. False when there is no backup at all (backup is null, the site says so) |
| `recap` | P3 | Last week, or null: `{"week": 10, "actual": 118.4, "optimal": 131.0, "recommended": 125.2, "left": 12.6}`. `actual` from the platform score (Sleeper matchups), `optimal` = best lineup from actual stats, `recommended` = actual points of the lineup the board recommended in its last run of that week. Any part can be null. ESPN: null until data exists |
| `waivers.faab` | P2 | `{"budget": 100, "left": 62, "leagueMaxLeft": 88, "teams": [{"name","left"}]}` or null (non-FAAB or ESPN) |
| `waivers.targets[i].rosGain`, `waivers.targets[i].bid` | P2 | Also on `stretch.targets` and `longTerm.targets`. `rosGain` = points added to your best lineup over all remaining weeks (stretch + playoffs). `bid` = whole dollars, `round(left * min(0.4, rosGain / (rosGain + 40)))`, at least 1 when rosGain > 0, null when no FAAB |
| `standings.myGames[i].ifWin`, `.ifLose` | P2 | Only on the game for the current week: your playoff pct if you win or lose it, from the same simulation. Other games omit them |

### Trade file `data/build/trade-{league}.json`
| Field | Package | Shape |
|---|---|---|
| `ideas` | P4 | Only ideas with `myGain >= MIN_IDEA_GAIN` (2.0) and `theirGain > 0` |
| `rosters[i].needs` | P4 | Up to 2 positions where that team's starters are weakest versus the league, for example `["TE","RB"]` |
| `rosters[i].picks` | P4 | Dynasty only. Draft picks the team owns for the next 2 drafts: `[{"season": "2027", "round": 1, "label": "2027 1st", "from": "Team name or null"}]`. Not scored |
| `minIdeaGain` | P4 | The threshold used |

### `data/build/meta.json`
| Field | Package | Shape |
|---|---|---|
| `nextRefresh` | P1 | ISO string of the next scheduled Actions run after `generatedAt`, from one table in `pipeline/common.py` that mirrors `refresh.yml` |

## Work packages

### Wave 1 (parallel)
- **P1 Lineup data** (`pipeline/build.py` lineup and player sections, `pipeline/lineup.py`, `pipeline/common.py`, `pipeline/adapters/sleeper.py` team name only, `config/leagues.yaml` read only): appUrl, appName, team name placeholder, newsUpdated, recent, nextBest, backup, lateRisk, nextRefresh. Also add two refresh runs to `.github/workflows/refresh.yml` for night game inactives: Sun 5:47pm and Mon 5:47pm Central, and keep the common.py table in sync with a test that parses refresh.yml
- **P2 FAAB and odds swing** (`pipeline/adapters/sleeper.py` normalize_league for `waiver_type`, `waiver_budget`, roster `waiver_budget_used`, `pipeline/waivers.py`, `pipeline/odds.py`, waivers and standings blocks in `pipeline/build.py`): faab, rosGain, bid, ifWin, ifLose. Update the Sleeper contract test and fixtures as needed
- **P3 Recap** (new `pipeline/recap.py`, a small hook in `pipeline/build.py`): every build writes the recommended lineup (player ids per slot) to `data/raw/{season}/{week}/recommended-{league}.json`, overwriting earlier runs that week. The next week's build reads the previous week's file plus that week's cached `sleeper_stats` and matchups to fill `recap`
- **P4 Trades** (`pipeline/trades.py`, trade section of `pipeline/build.py`, a new `fetch_traded_picks` in `pipeline/adapters/sleeper.py` and its use in `pipeline/ingest.py` inside the `sleeper_leagues` source, with `draft_rounds` from league settings): MIN_IDEA_GAIN, needs, picks
- **S1 Site shell** (`site/index.html`, new `site/manifest.webmanifest` and `site/icon.svg`, `style.css` header and tabs, `main()` in `site/app.js`): sticky league tabs and view switch on phones, arrow key / Home / End support on the league tablist, add to home screen (manifest, icon, theme-color, apple-touch-icon pointing at the SVG), refetch `meta.json` when the tab becomes visible and reload the board when `generatedAt` changed, header line "Next refresh Sun 10:47 AM" from `meta.nextRefresh`

### Wave 2 (parallel, after wave 1 is merged and data rebuilt)
- **S2 Lineup view** (owns `renderLeague`, `playerRow`, `slotGroup`, `sourcesSection`, `sourcesTable` and helpers they use): this week's matchup card (opponent, both expected scores, win pct, ifWin/ifLose when present, from `standings.myGames` for `league.week`), backup line on Q/D/out warnings ("If out, start X (+n, Sun 3:25 PM)") and a red late-risk line, close-call margin on starters ("Next best X, 1.2 behind") when within 2 points, "Underdog this week" box when win pct < 40 listing bench players with a higher ceiling than a starter they can replace, "Too few games for a range" when a projection has no floor/ceiling, bench sorted playable first with unplayable folded behind "Show n out, bye or IR", IR/Taxi chips from flags as well as slot, tap a player row to expand details (ESPN/RW split, total, spread, recent weeks, injury note with "updated 3h ago"), thin floor to ceiling bar, scoring notes shown under Data sources, recap card in the sidebar
- **S3 Waivers and Standings** (owns `renderWaivers`, `horizonSection`, `matchupText`, `noFutureWeeks`, `weekSpan`, `renderStandings`, `pct`, `record`): "Best pickups" table merging the three horizons per player (this week, stretch, playoffs, FAAB bid), FAAB card (your left, league max, bid note "Rough guide, not tested against real bids"), dim gains under 1.0, odds swing line, Points column kept on phones (drop Bye column instead under 400px), plain ESPN empty-state copy ("ESPN standings arrive once the roster sync starts saving them.")
- **S4 Trade** (owns `renderTrade` and trade helpers): partner seed and playoff pct on each idea and in the builder (from the league file's `standings`), "Helps a rival" badge when partner is a top 4 seed or above you, merge ideas with the same partner, same get and same gains into "Give A or B for C", position filter chips, partner roster grouped by position with their `needs` line, picks as unscored tick boxes in dynasty ("Picks are not scored"), sticky result bar at the bottom on phones while the builder is on screen
- **S5 All leagues and tabs** (owns `VIEWS`, routing helpers, `viewSwitch`, `show`, the tab loop in `main()`): an "All" tab first in the tablist (`#all`) showing every pending move, alert and watch across leagues with a jump link to each, and an exposure list of players starting in 2 or more leagues. League tabs show status instead of the gain: "Set" (muted check), "+n.n" when moves are pending, "n Q" for questionable starters, red dot for an out or bye starter. "Open in Sleeper" / "Open in ESPN" link next to the view switch from `league.appUrl`. Update `docs/STATES.md` section 5 for the new route

### Wave 3 (integrator)
Merge, rebuild data, run tests and screenshots at phone and desktop, update README, SPEC roadmap and STATES, push.

## Out of scope
- ESPN standings and schedule. The `espn-roster-sync` skill has to write them (SPEC optional keys). The site already uses them when present
