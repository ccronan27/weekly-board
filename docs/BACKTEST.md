# Projection Backtest (run 11/17/26)

## Bottom line
- v1 model = simple average of ESPN + Rotowire (Sleeper), re-scored per league
- Vegas lines are display context only. A Vegas multiplier fit on 2025 made 2026 start/sit picks WORSE out of sample
- Public projections top out around 62-64% start/sit pair accuracy. The dashboard's edge is inactives/injury timing, cross-league speed, and waivers (v2), not model tuning

## Definitions
- Relevant = average projection 5+ pts. Startable = 8+ pts
- Start/sit accuracy = for every pair of startable players at the same position in the same week, how often the higher projection scored more
- FLEX pick = same, but pairs RB/WR/TE across positions
- MAE = average absolute miss in fantasy points

## Part 1: ESPN vs Rotowire, 2026 Weeks 1-10 (ESPN league scoring)
1,907 relevant player-weeks, 1,408 startable.

| Source | MAE | r | Start/sit | Bias |
|---|---|---|---|---|
| ESPN | 5.65 | 0.544 | 63.5% | +0.41 |
| Rotowire | 5.61 | 0.548 | 63.7% | +0.33 |
| Average | **5.60** | **0.553** | **63.9%** | n/a |

Source disagreement does NOT predict boom/bust (low vs high spread quartiles: outcome SD 6.90 vs 6.89).

## Part 2: Vegas, fit within 2026 (Weeks 3-6 vs 7-10, 2-fold)
- Avg 5.606 MAE / 63.7% vs Vegas-adjusted 5.596 / 63.7%. No real gain
- Projections already correlate 0.26 with implied team total. Leftover miss correlates only 0.055

## Part 3: Fit on 2025 (Weeks 1-17), scored on 2026 (Weeks 1-10)
- Sources: ESPN default PPR projections + Rotowire. Lines: nflverse closing spread/total
- Train 3,202 relevant player-weeks (2025). Test 1,775 relevant, 1,210 startable (2026)
- Implied total scaled against the 2025 league mean (22.44), so no 2026 information leaks in

### Fitted on 2025
| Parameter | Value |
|---|---|
| Vegas exponent b, all players | 0.25 |
| b by position | QB 0.20, RB 0.35, WR 0.25, TE 0.20 |
| M3 ESPN weight | 0.70 |
| M3 calibration | QB 0.92, RB 0.85, WR 0.85, TE 0.87 |

### Results
| Model | 2025 start/sit (in sample) | 2026 MAE | 2026 r | 2026 start/sit | 2026 FLEX pick |
|---|---|---|---|---|---|
| **M0 Equal average** | 62.54% | **5.721** | 0.497 | **62.57%** | **63.27%** |
| M1 + Vegas, one b | 62.99% | 5.724 | 0.498 | 62.22% | 62.89% |
| M2 + Vegas, b by position | 62.90% | 5.726 | 0.497 | 62.17% | 62.91% |
| M3 + weights + calibration | 62.73% | 5.721 | 0.465 | 61.74% | 62.09% |

- M2 minus M0, 2026 start/sit, week-bootstrap 95% range: -0.77 to -0.11 points
- M2 beat M0 on MAE in 5 of 10 weeks

### Findings
1. The Vegas multiplier helps in the season it is fit on and hurts the next. Overfitting, not signal
2. Extra tuning (M3) overfits worst, especially for FLEX decisions
3. Plain equal average is the most robust choice

## Method notes (to rebuild as `scripts/backtest.py`)
- Player match: normalized name + position (see SPEC.md)
- ESPN weekly projection: `statSourceId == 1`, `statSplitTypeId == 1`, `scoringPeriodId == week`. Actual: `statSourceId == 0`
- Rotowire: Sleeper projections `stats.pts_ppr`
- Re-run Part 1 weekly. Re-run Part 3 each offseason before any model change ships

## Script rerun (11/18/26, `scripts/backtest.py`)

### Part 1, 2026 Weeks 1-10 (ESPN league scoring)
Reproduces the table above. 1,905 relevant player-weeks, 1,406 startable.

| Source | MAE | r | Start/sit | Bias |
|---|---|---|---|---|
| ESPN | 5.65 | 0.545 | 63.5% | +0.41 |
| Rotowire | 5.59 | 0.549 | 63.7% | +0.22 |
| Average | **5.59** | **0.554** | **64.0%** | n/a |

### Part 3, fit 2025, score 2026
Does not reproduce the original numbers. The script's 2026 test set is 1,905 relevant and 1,407 startable player-weeks against 1,775 and 1,210 above, so the original study filtered something the method notes do not describe. Fits: b 0.25, b by position QB 0.65 RB 0.20 WR 0.25 TE 0.25, M3 ESPN weight 0.90.

| Model | 2025 start/sit (in sample) | 2026 MAE | 2026 r | 2026 start/sit | 2026 FLEX pick |
|---|---|---|---|---|---|
| M0 Equal average | 62.5% | 5.599 | 0.553 | 64.0% | 64.6% |
| M1 + Vegas, one b | 63.0% | 5.588 | 0.556 | 64.1% | 64.9% |
| M2 + Vegas, b by position | 63.1% | 5.599 | 0.555 | 64.1% | 64.8% |
| M3 + weights + calibration | 62.6% | 5.570 | 0.545 | 63.9% | 64.4% |

- Week-bootstrap 95% range against M0, 2026 start/sit: M1 -0.39 to +0.57, M2 -0.33 to +0.60, M3 -0.60 to +0.45 points
- No variant beats M0 with the whole range above zero, so the equal average stays. The original finding (Vegas hurts out of sample) softens to "no reliable gain either way"
- Script choices where the notes were silent: b is fit by grid search (0 to 1, step 0.05) for best train start/sit, M3's ESPN weight the same way, M3 calibration is a least squares slope through zero per position, actuals are ESPN's own (statSourceId 0)
