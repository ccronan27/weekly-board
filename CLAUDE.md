# weekly-board

Conor's cross-league fantasy football start/sit dashboard. Read `docs/SPEC.md` (what to build) and `docs/BACKTEST.md` (why the model is what it is) before changing anything.

## Hard rules
- No credentials, tokens or cookies anywhere: repo, workflows, logs or site. The repo is public
- Never call ESPN league endpoints from Actions. ESPN league data arrives only as `data/espn/rosters.json`, written by the Claude `espn-roster-sync` skill. ESPN default projections (leaguedefaults) need no login and are fine to fetch
- No owners' real names in data or UI. Team names only
- Site must ship a noindex meta tag and a robots.txt that disallows everything
- Projection model is the equal average of ESPN + Rotowire. Do not add weighting, calibration or a Vegas multiplier unless it beats the equal average in the cross-season backtest (fit last season, score this season)
- UI copy: no em dashes, no semicolons, plain and direct
- Times shown in Central (America/Chicago)

## Build principles (this should run for years with little care)
- Few dependencies. Python 3.12 + requests/pandas for the pipeline. Plain HTML/CSS/JS for the site, no build step
- One adapter per source in `pipeline/adapters/`, each with a contract test that fails loudly when a source changes shape
- If one source fails, the run still publishes with that source marked stale. Never publish an empty board
- Raw pulls cached to `data/raw/{season}/{week}/`, built outputs to `data/build/`, site reads only `data/build/`
- League settings come from the APIs, overrides in `config/leagues/*.overrides.yaml`
- Every output carries `generatedAt` and per-source `lastUpdated`

## Workflows
- `refresh.yml`: schedule (see SPEC refresh table, `timezone: America/Chicago`), `workflow_dispatch`, and push on `data/espn/**`. Fetch, build, commit data, deploy Pages
- Pages source is set to GitHub Actions. Workflow permissions are read and write

## Done means
- Tests pass, a manual `workflow_dispatch` run succeeds, and the live page shows all 3 leagues with correct starters and last-updated stamps
- README covers: what it is, how to run locally, preseason checklist (re-enable workflows, update league IDs, re-run backtest)
