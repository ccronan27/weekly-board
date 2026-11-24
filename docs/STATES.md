# State machines

Every place the board moves between named states, what the states are, what moves them, and where the code lives. Read this before changing source status, the ESPN roster file, routing or the Trade view. Each machine has one place that decides its state. Everything else reads that decision.

Tests: `tests/test_states.py` covers machines 1 to 5 (Python for the pipeline, node for the pure functions in `site/app.js`).

## 1. Source freshness

Every data source ends each run in one of three states. The decision lives in `pipeline/common.py` (`source_status`, `source_state`). Status entries also keep the older `ok` and `stale` booleans so older readers still work, but `state` is the field to read.

| State | Meaning | Reached when |
|---|---|---|
| `fresh` | Pulled this run and current | The fetch succeeded (`_run_source` in `pipeline/ingest.py`) |
| `stale` | Usable but old | The fetch failed and the last good cache is in use, or the ESPN roster sync is older than 4 days, or the ESPN roster file was unusable and the last good copy is in use |
| `missing` | Nothing usable | The fetch failed and no cache exists |

Transitions happen once per run, in ingest. Any state can go to any other on the next run.

Readers, all of which go through `state`:
- `python -m pipeline.ingest` log lines (`ok`, `STALE`, `MISSING`)
- `scripts/step_summary.py` (Actions run summary)
- `pipeline/build.py` fills `state` on entries from older `status.json` files
- `site/app.js` `sourceState()`, the sources table and `freshnessMessages()`

The essential sources (`sleeper_leagues`, `sleeper_players`, `sleeper_projections`) must not all be `missing`, or ingest exits non-zero.

## 2. ESPN roster file

`data/espn/rosters.json` is written by ingest from the public league endpoint when that pull succeeds (`espn_league` source), and can also be written by the Claude `espn-roster-sync` skill. A failed pull leaves the file as it was, so the states below still apply to whatever file is there. The decision lives in `pipeline/ingest.py` (`load_rosters`, `rosters_status`). Build calls the same two functions, so the board and the status always describe the same file.

| State | Meaning | Board behavior |
|---|---|---|
| good, current | File validates, synced within 4 days, same week | `fresh` |
| good, old | Synced more than 4 days ago | `stale`, warning on the ESPN league |
| good, wrong week | File is for another week | `fresh`, separate week warning (`weekMismatch`) |
| unusable, cached | File fails validation (for example the sync wrote `"ok": false`), and an earlier run cached a good copy | `stale`, `meta.espnRosters.fromCache` is true, warning names the sync time in use. All three leagues still publish |
| unusable, no cache | Nothing usable anywhere this season | The ESPN league is skipped and listed in `meta.skippedLeagues`. The Sleeper leagues still publish, and the page shows a warning. `meta.espnRosters.state` is `missing` |

Every run that reads a good file caches it to `data/raw/{season}/{week}/espn_rosters.json`. The fallback takes the newest valid cached copy at or before the current week.

## 3. Board freshness in the browser

The build stamps `generatedAt` and `espnRosters.syncedAt`, but a page can be open for days after its build, and scheduled runs can stop (dropped crons, the 60 day auto-disable). So the site checks the clock again on every render (`site/app.js`: `espnSync`, `rowState`, `freshnessMessages`):

- Board older than 72 hours (`BOARD_STALE_HOURS`): warns that the refresh may have stopped. The longest planned gap is Fri 5:07pm to Sun 9:07am, 40 hours.
- When the tab becomes visible again, at most once a minute, the site refetches `meta.json` and reloads when `generatedAt` changed (`refreshDue`, `shouldReload`).
- ESPN sync older than `meta.espnRosters.staleAfterDays` (4): the ESPN row and warning go stale even when the build said fresh.

## 4. Season phase

Each league file carries `seasonPhase`, decided by `season_phase()` in `pipeline/build.py` from the current week and the league's playoff weeks.

| State | When | What changes on the page |
|---|---|---|
| `regular` | Before the first playoff week | Everything shows. An empty future list here means the schedule source is missing, so the Waivers summary says `n/a`, not `Over` |
| `playoffs` | During the playoff weeks | Stretch run is empty. In the last playoff week the Waivers summary says `Final week` |
| `over` | After the last playoff week | Waivers summary says `Over`. Trades and standings explain that no weeks are left |

`noFutureWeeks()` in `site/app.js` maps phase to copy. Builds without `seasonPhase` fall back to the old `Over` text.

## 5. Site route

What is on screen is `route = { league, view }` inside `main()` in `site/app.js`. Only `show()` changes it.

- Views come from one registry, `VIEWS`. Each entry says whether a league's build carries it: Lineup always, Waivers when `waivers` is set, Trade when `trade` is set, Standings whenever the key exists (null shows an explanation, used when the ESPN roster file has no standings), Shotguns when `shotguns` is set (leagues with `shotguns: true` in config).
- `resolveView()` sends any view a league does not carry to Lineup. `viewSwitch()` shows exactly the registry's views, and only when there is more than one.
- The URL hash mirrors the route: `#league` for Lineup, `#league/view` otherwise (`hashFor`, `routeFromHash`). `#all` is the All route. An unknown league opens the first one. An unknown view opens Lineup. `show()` writes the hash with `replaceState`, so the back button leaves the page instead of stepping through views.
- Switching league keeps the current view when the new league has it.

- The All tab is the first tab. Its route is `{ league: -1, view: "all" }` (`ALL` in the code), hash `#all`. It has no views, so the view switch and the app link are hidden on it. `hashFor(null)` gives `#all`. A bare hash still opens the first league, not All.
- Leaving All for a league opens it on the view it last showed (`leagueView` in `main()`), or Lineup if none.
- The arrow, Home and End keys move across All and the leagues (`nextTabIndex` counts every tab). All renders with `renderAll`, a to-do list, the players in more than one lineup, and the data freshness lines. Its helpers are `leagueTodos`, `exposure`, `leagueFreshness`.
- League tabs show `tabStatus()` in place of the gain: `Out` with a red dot when a starter is out, the gain when moves are pending, `n Q` for questionable starters, and a check mark `Set` otherwise. The All tab shows `allStatus()`, the count of to-dos or Set.

## 6. Trade file loading

Trade files are large, so each league's loads the first time its Trade view opens (`loadTrade` in `site/app.js`).

```
(none) --open Trade--> loading --> ready
                              \--> error --Try again--> loading
```

Only the Try again button leaves `error`, so a failing file never refetches in a loop. A load that finishes while you are on another view does not redraw anything. The data is used next time you open Trade.

## 7. Trade builder

Per league, kept while you switch views (`tradeState` in `main()`): partner team, players to give, players to get, and a one shot `scroll` flag.

- First open: partner is the best idea's team, or the first other team. Picks empty.
- Pick a partner: picks reset.
- Tap an idea: partner and picks set from the idea, `scroll` set, so the next draw scrolls to the builder and clears the flag.
- Tick a box: only the result card redraws, so focus and scroll stay put.

The result card has five outcomes from `renderTrade`: nothing picked, both better, you better, they better, neither better.

## 8. Player availability

Decided per player in `player_record()` in `pipeline/build.py`, read by the optimizer and the site.

- `flags`: `BYE` plus one injury status from `normalize_status()` (`OUT`, `IR`, `DOUBTFUL`, `QUESTIONABLE`, `SUSPENDED`, `INACTIVE`).
- `eligible`: false on bye, any out status, in an IR or taxi slot, or locked on the bench.
- `locked`: the player's game has kicked off. A locked starter keeps the slot (`fixed` in the optimizer). A locked bench player cannot move in.

Starters with an out flag go to `lineup.alerts`, starters who are questionable or doubtful go to `lineup.watch`.

Each alert and watch entry carries `backup`, the best eligible, unlocked, non-starting player for that slot, or null when there is none (`backup_for` in `pipeline/lineup.py`). Watch entries also carry `lateRisk`, true only when backups exist and the flagged player kicks off after every one of them (`late_risk`). No backup at all is shown as its own message, never as a late risk.

## 9. Lineup changes

Per slot, `changed` is true when the recommended player differs from the current one. Each move from `lineup.moves()` is one of three kinds, told apart by which keys are set: `in` and `out` (swap), `out` only (no eligible replacement), `in` only (fill an empty slot).

## 10. Publish gate

`refresh.yml` runs code tests, ingest, build, summary, commit, assemble, deploy. Data tests (pytest marker `data`, the ones that read `data/raw` or `data/build`) run in their own job after build, against the data that run committed. The gates that stop a bad board from going live:

- Code tests fail: nothing runs.
- Data tests fail: the run shows red, but deploy still goes. They never block publishing, so a test that leans on one week's injuries cannot freeze the board.
- Ingest exits non-zero when every essential source is `missing`.
- Build raises `BuildError` on an empty or worse-than-current lineup, or a missing Sleeper league. It refuses only when no league at all can be built. With no usable ESPN roster file the ESPN league is skipped (machine 2) and the other leagues still publish. When build refuses, nothing is committed or deployed, and the last good site stays live.
- `scripts/make_site.py` refuses an empty `data/build`.
- Two runs can overlap, for example a merge that starts one and the Run workflow button that starts another. When both save data, the later run's data wins (`git pull --rebase -X theirs` in the Commit data step). That commit only touches data, so code is never changed.
- Deploy runs only on the default branch.
