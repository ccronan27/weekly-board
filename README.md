# weekly-board

A start/sit dashboard across three fantasy football leagues: Fantasizing 2026 (ESPN), HWH: The League (Sleeper) and Chicago Dynasty (Sleeper). It runs on GitHub Actions and publishes a static page on GitHub Pages. The page shows, for each league, your current lineup next to the best lineup, with the point difference, injury and bye flags, floor and ceiling, Vegas context and when each data source was last updated.

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
2. Update the league IDs and season in `config/leagues.yaml`. Scoring and lineups are pulled from the platforms. Check `config/leagues/*.overrides.yaml` still apply.
3. Ask Claude to sync ESPN so `data/espn/rosters.json` is for the new league. Confirm the ESPN D/ST scoring in `config/leagues/fantasizing.overrides.yaml` still matches the league.
4. Re-run the backtest before any model change ships: `python scripts/backtest.py` (this season to date, fit on last season weeks 1-17). It prints the Part 1 and Part 3 tables in `docs/BACKTEST.md` format, so paste them in to refresh the doc. Use `--part 1` for the weekly source check and `--season 2026 --weeks 1-10` to pin the range. Raw pulls are cached in `data/raw/{season}/{week}/` and `--offline` reruns from the cache. Keep the equal average unless a model's week-bootstrap range vs M0 is above zero.
5. Run `python -m pytest -m live`. A contract failure means a source changed shape.
6. Trigger `refresh` by hand and check that all three leagues show on the page with current stamps.

## Layout

```
pipeline/adapters/   one adapter per source, each with a contract test
pipeline/            ingest, scoring, lineup optimizer, build
config/              league IDs and per league overrides
data/espn/           roster file written by the Claude skill
data/raw/            cached raw pulls by season and week
data/build/          what the site reads
site/                plain HTML, CSS and JS
tests/               contract, scoring, build and site tests
```
