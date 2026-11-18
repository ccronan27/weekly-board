# weekly-board

A start/sit dashboard across three fantasy football leagues: Fantasizing 2026 (ESPN), HWH: The League (Sleeper) and Chicago Dynasty (Sleeper). It runs on GitHub Actions and publishes a static page on GitHub Pages. The page shows, for each league, your current lineup next to the best lineup, with the point difference, injury and bye flags, floor and ceiling, Vegas context and when each data source was last updated.

Each league also has a Waivers view (v2) with two lists. Short term ranks free agents by the projected points they add to your best possible lineup this week, so weak slots, byes and injuries are all covered by one number. Long term ranks them by the points they add across the fantasy playoff weeks still ahead (weeks 15 to 17 by default). A playoff week's rate is this week's projection for healthy players, and the season average for DEF, K and anyone hurt or on bye now. Teams off that week count 0. Playoff opponents are tagged soft or tough from points allowed to the position this season, as context only. Both lists cap at two per position. The view also shows the best three free agents at each position and suggests a drop from your bench in redraft leagues.

A Trade view (v3) does two things. Trade ideas lists 1 for 1 trades with each other team that make both teams' playoff lineups better, scored the same way as long term waivers, so the offer is one the other side has a reason to accept. Build a trade lets you pick any partner and any players on both sides and shows the change for you and for them over the playoffs and this week. The builder runs the same lineup optimizer in the browser, and a test checks it against the Python one. In dynasty leagues it shows ages and flags trades that send away a player 4 or more years younger. It does not score dynasty value, because no free source publishes one. Dynasty leagues (`dynasty: true` in `config/leagues.yaml`) get no drop suggestion, because weekly points ignore long term value. Players whose game has started are never suggested.

The only piece that needs Claude is the ESPN roster sync. Everything else runs on its own.

## How it works

```
Sleeper API ----\
ESPN leaguedefaults ---> pipeline.ingest --> data/raw/{season}/{week}/
nflverse lines --/                                   |
data/espn/rosters.json (Claude skill) ---------------+--> pipeline.build --> data/build/*.json --> site
```

- Projection is the equal average of ESPN and Rotowire (via Sleeper), each re-scored with the league's exact scoring. There is no weighting, calibration or Vegas multiplier because none of them beat the equal average out of sample. See `docs/BACKTEST.md`.
- Floor and ceiling are one weekly standard deviation below and above the projection, from the player's own games this season.
- If one source fails, the run still publishes and marks that source stale. An empty board is never published.
- ESPN league data is never fetched by Actions. It arrives only as `data/espn/rosters.json`, written by the Claude `espn-roster-sync` skill. Say "sync ESPN" to Claude to refresh it. The page warns when the sync is more than 4 days old.
- No credentials, tokens or cookies exist anywhere in this repo. The repo is public, so keep it that way.

## Run locally

Needs Python 3.12.

```bash
pip install -r requirements.txt
python -m pytest
python -m pipeline.ingest
python -m pipeline.build
python scripts/make_site.py
python -m http.server -d _site 8000
```

Then open http://localhost:8000. Live checks against the real endpoints: `python -m pytest -m live`.

Useful scripts:

- `scripts/check_scoring.py` checks the scoring engine against ESPN's own totals and Rotowire's totals.
- `scripts/record_fixtures.py` re-records the test fixtures when a source changes shape. Run it, read the diff, then fix the adapter.

## Schedule

Defined in `.github/workflows/refresh.yml`, all times America/Chicago: Tue 9:07pm, Thu 2:07pm, Fri 5:07pm, Sun 9:07am, 10:47am and 1:07pm. It also runs on the manual "Run workflow" button (works from GitHub mobile) and whenever `data/espn/**` changes. Scheduled runs only fire from the default branch.

## Setup once

1. Settings, Pages, Source: GitHub Actions.
2. Settings, Actions, General, Workflow permissions: Read and write.
3. Merge to `main`. Pages only deploys from the default branch.

## Preseason checklist

Scheduled workflows are disabled automatically after 60 days without repo activity, so the offseason turns them off.

1. Re-enable workflows in August: Actions tab, select `refresh`, Enable workflow.
2. Update the league IDs and season in `config/leagues.yaml`, and the ESPN league's `playoffWeeks` (Sleeper playoff weeks come from the API). Scoring and lineups are pulled from the platforms. Check `config/leagues/*.overrides.yaml` still apply.
3. Ask Claude to sync ESPN so `data/espn/rosters.json` is for the new league. Confirm the ESPN D/ST scoring in `config/leagues/fantasizing.overrides.yaml` still matches the league.
4. Re-run the backtest from `docs/BACKTEST.md` before any model change ships. The script is not built yet (`scripts/backtest.py` is still to do), so the method notes in that document are the reference for now.
5. Run `python -m pytest -m live`. A contract failure means a source changed shape.
6. Trigger `refresh` by hand and check that all three leagues show on the page with current stamps.

## Layout

```
pipeline/adapters/   one adapter per source, each with a contract test
pipeline/            ingest, scoring, lineup optimizer, waiver targets, trades, build
config/              league IDs and per league overrides
data/espn/           roster file written by the Claude skill
data/raw/            cached raw pulls by season and week
data/build/          what the site reads
site/                plain HTML, CSS and JS
tests/               contract, scoring, build and site tests
```
