"""The refresh schedule in .github/workflows/refresh.yml and the table in pipeline/common.py must agree."""
import re
from datetime import datetime, timezone
from pathlib import Path

from pipeline import common

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "refresh.yml"
CRON_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]   # cron day-of-week 0 to 6


def workflow_runs():
    """(day, hour, minute, timezone) for every cron line, read from the workflow file."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    runs = []
    for i, line in enumerate(lines):
        m = re.match(r'\s*-\s*cron:\s*"(\d+) (\d+) \* \* (\d)"', line)
        if not m:
            continue
        tz = re.match(r'\s*timezone:\s*"([^"]+)"', lines[i + 1])
        runs.append((CRON_DAYS[int(m.group(3))], int(m.group(2)), int(m.group(1)), tz.group(1) if tz else None))
    return runs


def test_every_workflow_cron_is_in_the_common_table_and_back():
    runs = workflow_runs()
    assert runs, "no cron lines found in refresh.yml"
    assert all(tz == common.REFRESH_TZ for _, _, _, tz in runs)
    assert sorted((d, h, m) for d, h, m, _ in runs) == sorted(common.REFRESH_RUNS)


def test_sunday_and_monday_night_inactive_runs_exist():
    runs = {(d, h, m) for d, h, m, _ in workflow_runs()}
    assert ("Sun", 17, 47) in runs and ("Mon", 17, 47) in runs


def test_next_refresh_is_the_next_scheduled_run_in_utc():
    # Thu 2026-11-19 12:00 Central (CST, UTC-6) is 18:00Z. Next run is Thu 2:07pm Central = 20:07Z
    assert common.next_refresh("2026-11-19T18:00:00Z") == "2026-11-19T20:07:00Z"
    # Thu 2:30pm Central is past that run, next is Fri 5:07pm Central = 23:07Z
    assert common.next_refresh("2026-11-19T20:30:00Z") == "2026-11-20T23:07:00Z"
    # Sun 5:00pm Central, before the SNF run at 5:47pm
    assert common.next_refresh(datetime(2026, 11, 22, 23, 0, tzinfo=timezone.utc)) == "2026-11-22T23:47:00Z"
    # Sun 6:00pm Central, after SNF inactives, next is Mon 5:47pm Central
    assert common.next_refresh("2026-11-23T00:00:00Z") == "2026-11-23T23:47:00Z"


def test_next_refresh_is_strictly_after_generated_at():
    assert common.next_refresh("2026-11-19T20:07:00Z") > "2026-11-19T20:07:00Z"
