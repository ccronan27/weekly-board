"use strict";

// Reads only data/build/. Every string from the data goes in with textContent, never as HTML.
const TZ = "America/Chicago";
const WHEN = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const SHORT_WHEN = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ, weekday: "short", hour: "numeric", minute: "2-digit",
});
const FLAG_TEXT = {
  BYE: "Bye week", OUT: "Out", IR: "Injured reserve", DOUBTFUL: "Doubtful", QUESTIONABLE: "Questionable",
  SUSPENDED: "Suspended", INACTIVE: "Inactive",
};
// Short codes like ESPN. Amber for game-day doubts, red for anything that keeps a player out.
const FLAG_BADGE = {
  QUESTIONABLE: { code: "Q", cls: "warn" }, DOUBTFUL: { code: "D", cls: "warn" }, OUT: { code: "O", cls: "out" },
  IR: { code: "IR", cls: "out" }, BYE: { code: "BYE", cls: "out" }, SUSPENDED: { code: "SUS", cls: "out" },
  INACTIVE: { code: "INA", cls: "out" },
};
const NOTE_FLAGS = ["QUESTIONABLE", "DOUBTFUL", "OUT"];
const POSITIONS = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"];
const SOURCE_TEXT = {
  sleeper_projections: "Rotowire projections", espn_defaults: "ESPN projections", nflverse_lines: "Vegas lines",
  sleeper_leagues: "Sleeper rosters", sleeper_players: "Sleeper injuries", espn_rosters: "ESPN rosters",
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}
// Full stamp with date and zone, for the header
function when(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? WHEN.format(d) : "never";
}
// Short stamp for rows and the sources table: "Sun 3:05 PM". Central, no date, no zone.
function shortWhen(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? SHORT_WHEN.format(d).replace(/ /g, " ") : "";
}
function stamp(iso) { return shortWhen(iso) || "never"; }
function isNum(x) { return typeof x === "number" && !isNaN(x); }
function num(x) { return isNum(x) ? x.toFixed(1) : "n/a"; }
function signed(x) { return (x > 0 ? "+" : "") + x.toFixed(1); }
function hasFlag(p, f) { return (p.flags || []).indexOf(f) >= 0; }
function isEligible(p) { return p.eligible !== false; }

// Matchup text for the small line under a name
function gameText(p) {
  if (hasFlag(p, "BYE")) return "Bye week";
  const g = p.game;
  if (!g) return "No game info";
  let t = (g.home ? "vs " : "at ") + g.opp;
  const k = shortWhen(g.kickoff);
  if (k) t += " " + k;
  return t;
}
// Projection sources, shown in the tooltip on the projection
function sourceText(p) {
  const parts = [];
  if (isNum(p.espn)) parts.push("ESPN " + p.espn.toFixed(1));
  if (isNum(p.rotowire)) parts.push("RW " + p.rotowire.toFixed(1));
  return parts.join(" · ");
}
// Extra context, shown on wide screens only
function contextText(p) {
  const parts = [];
  const src = sourceText(p);
  if (src) parts.push(src);
  const g = p.game || {};
  if (isNum(g.implied)) parts.push("total " + g.implied.toFixed(1));
  if (isNum(g.spread)) parts.push("spread " + (g.spread > 0 ? "+" : "") + g.spread.toFixed(1));
  return parts.join(" · ");
}

function chipNode(label) {
  const isPos = POSITIONS.indexOf(label) >= 0;
  return el("span", "chip " + (isPos ? "pos-" + label.toLowerCase() : "neutral"), label);
}
function benchChip(p) {
  if (p.slot === "IR") return "IR";
  if (p.slot === "TAXI") return "Taxi";
  return "BN";
}
function badgeNodes(p) {
  const out = [];
  (p.flags || []).forEach(function (f) {
    const b = FLAG_BADGE[f];
    if (!b) return;
    const title = (FLAG_TEXT[f] || f) + (p.injuryNotes ? ": " + p.injuryNotes : "");
    const n = el("span", "badge " + b.cls, b.code);
    n.title = title;
    n.setAttribute("aria-label", title);
    out.push(n);
  });
  if (p.locked) out.push(el("span", "badge locked", "Locked"));
  return out;
}

// One compact row: slot chip, name with badges, a small matchup line, then the projection.
// opts.chip is the chip label. opts.rowCls is "cur" or "rec" in a changed slot. opts.struck dims the current player.
// opts.gain (rec rows only) adds the arrow and point gain.
function playerRow(p, opts) {
  const row = el("div", "prow" + (opts.rowCls ? " " + opts.rowCls : ""));
  row.appendChild(chipNode(opts.chip));
  const body = el("div", "pbody");
  if (!p) {
    body.appendChild(el("div", "pname empty", "Empty slot"));
    row.append(body, el("div", "pnums"));
    return row;
  }
  const eligible = isEligible(p);
  const top = el("div", "pname");
  top.appendChild(el("span", "name" + (opts.struck ? " struck" : ""), p.name));
  badgeNodes(p).forEach(function (n) { top.appendChild(n); });
  body.appendChild(top);

  let subText = (p.pos || "") + " " + (p.team || "FA") + " · " + gameText(p);
  if (opts.ppg && isNum(p.ppg)) subText += " · " + p.ppg.toFixed(1) + " a game";
  const sub = el("div", "psub", subText);
  const ctx = contextText(p);
  if (ctx) sub.appendChild(el("span", "ctx", " · " + ctx));
  body.appendChild(sub);
  if (p.injuryNotes && NOTE_FLAGS.some(function (f) { return hasFlag(p, f); })) {
    body.appendChild(el("div", "note", p.injuryNotes));
  }
  if (opts.extra) body.appendChild(el("div", "extra" + (opts.extraMuted ? " muted-extra" : ""), opts.extra));

  const nums = el("div", "pnums");
  const src = sourceText(p);
  if (src) nums.title = src;
  if (!eligible && !isNum(p.points)) {
    nums.appendChild(el("div", "pts", "-"));
  } else if (!eligible) {
    nums.appendChild(el("div", "pts dim strike", p.points.toFixed(1)));
  } else {
    nums.appendChild(el("div", "pts" + (opts.struck ? " dim" : ""), num(p.points)));
  }
  if (eligible && isNum(p.floor) && isNum(p.ceiling)) {
    nums.appendChild(el("div", "range", p.floor.toFixed(1) + " to " + p.ceiling.toFixed(1)));
  }
  if (opts.gain !== undefined) nums.appendChild(el("div", "gainline", "→ " + signed(opts.gain)));

  row.append(body, nums);
  return row;
}

// Points gained by starting the recommended player over the current one. An ineligible current player counts as 0.
function gainOf(s) {
  const cur = s.current && isEligible(s.current) && isNum(s.current.points) ? s.current.points : 0;
  const rec = isNum(s.recommended.points) ? s.recommended.points : 0;
  return rec - cur;
}

function slotGroup(s) {
  const wrap = el("div", "slot" + (s.changed ? " changed" : ""));
  if (s.changed) {
    wrap.appendChild(playerRow(s.current, { chip: s.slot, rowCls: "cur", struck: true }));
    if (s.recommended) {
      const rec = s.recommended;
      // A locked player is never styled as a recommended move
      wrap.appendChild(playerRow(rec, { chip: s.slot, rowCls: rec.locked ? "" : "rec", gain: rec.locked ? undefined : gainOf(s) }));
    }
  } else {
    wrap.appendChild(playerRow(s.current || s.recommended, { chip: s.slot }));
  }
  return wrap;
}

// ---------------------------------------------------------------- source freshness (docs/STATES.md)
// Each source is fresh, stale or missing. The pipeline writes state. Older builds only carry the booleans.
function sourceState(s) {
  if (s.state) return s.state;
  return !s.lastUpdated ? "missing" : (!s.ok || s.stale) ? "stale" : "fresh";
}
// Rules that depend on the clock are checked again here, because a page can outlive its build by days.
const BOARD_STALE_HOURS = 72;   // the longest planned gap between refreshes is Sun 1:07pm to Tue 9:07pm, 56 hours
function hoursSince(iso, now) {
  const t = iso ? Date.parse(iso) : NaN;
  return isNaN(t) ? Infinity : (now - t) / 3600000;
}
function espnSync(meta, now) {
  const r = meta.espnRosters;
  if (!r) return null;
  const limit = isNum(r.staleAfterDays) ? r.staleAfterDays : 4;
  return {
    syncedAt: r.syncedAt, week: r.week, limit: limit, fromCache: r.fromCache === true, weekMismatch: r.weekMismatch === true,
    old: r.stale === true || hoursSince(r.syncedAt, now) > limit * 24,
  };
}
// State of one row in the sources table. ESPN rosters also go stale with age.
function rowState(k, s, meta, now) {
  const st = sourceState(s);
  const sync = k === "espn_rosters" ? espnSync(meta, now) : null;
  return st === "fresh" && sync && (sync.old || sync.fromCache) ? "stale" : st;
}
const STATE_TEXT = { stale: "Stale", missing: "Missing" };

function sourcesTable(league, meta) {
  const now = Date.now();
  const t = el("table", "sources");
  Object.keys(league.sources).forEach(function (k) {
    const s = league.sources[k];
    const tr = el("tr");
    tr.appendChild(el("td", null, SOURCE_TEXT[k] || k));
    const td = el("td");
    let txt = "Updated " + stamp(s.lastUpdated);
    if (k === "espn_rosters" && meta.espnRosters) txt = "Synced " + stamp(meta.espnRosters.syncedAt);
    td.appendChild(document.createTextNode(txt));
    const st = rowState(k, s, meta, now);
    if (STATE_TEXT[st]) td.appendChild(el("span", "stale", "  " + STATE_TEXT[st]));
    if (s.error && st !== "fresh") td.title = s.error;
    tr.appendChild(td);
    t.appendChild(tr);
  });
  return t;
}

// Warnings for the open league, worst first. Pure, so a test can run it without a page.
function freshnessMessages(league, meta, now) {
  const out = [];
  const age = hoursSince(meta.generatedAt, now);
  if (age > BOARD_STALE_HOURS && age !== Infinity) {
    out.push("This board was built " + Math.floor(age / 24) + " days ago, so the scheduled refresh may have stopped. Run the refresh workflow on GitHub.");
  }
  (meta.skippedLeagues || []).forEach(function (s) { out.push(s.name + " is not shown because there is no usable ESPN roster file. Ask Claude to sync ESPN."); });
  const sync = league.league.platform === "espn" ? espnSync(meta, now) : null;
  if (sync && sync.fromCache) out.push("The last ESPN sync did not save a usable roster file. Showing the sync from " + stamp(sync.syncedAt) + ". Ask Claude to sync ESPN.");
  else if (sync && sync.old) out.push("The ESPN roster sync is more than " + sync.limit + " days old. Lineups may be out of date. Ask Claude to sync ESPN.");
  if (sync && sync.weekMismatch) out.push("The ESPN roster file is from week " + sync.week + ". Ask Claude to sync ESPN.");
  const bad = Object.keys(league.sources).filter(function (k) { return k !== "espn_rosters" && sourceState(league.sources[k]) !== "fresh"; });
  const missing = bad.filter(function (k) { return sourceState(league.sources[k]) === "missing"; });
  const stale = bad.filter(function (k) { return missing.indexOf(k) < 0; });
  const names = function (ks) { return ks.map(function (k) { return SOURCE_TEXT[k] || k; }).join(", "); };
  if (missing.length) out.push("Missing data: " + names(missing) + ". Nothing has loaded from it yet.");
  if (stale.length) out.push("Stale data: " + names(stale) + ". Using the last good pull.");
  return out;
}
// Shown on every view
function freshnessWarnings(league, meta, box) {
  freshnessMessages(league, meta, Date.now()).forEach(function (m) { box.appendChild(el("div", "warn", m)); });
}

function sourcesSection(league, meta) {
  const sec = el("section", "s-src");
  sec.appendChild(el("h2", null, "Data sources"));
  const sc = el("div", "card");
  sc.appendChild(sourcesTable(league, meta));
  sec.appendChild(sc);
  return sec;
}

// Phone: one column in DOM order. Desktop: sidebar plus main column (see style.css)
function columns(sideSecs, mainSecs) {
  const cols = el("div", "cols");
  const side = el("div", "colA");
  side.append.apply(side, sideSecs);
  const main = el("div", "colB");
  main.append.apply(main, mainSecs);
  cols.append(side, main);
  return cols;
}

function renderLeague(league, meta) {
  const lu = league.lineup;
  const secSum = el("section", "s-sum");
  const secMoves = el("section", "s-moves");
  const secLineup = el("section", "s-lineup");
  const secBench = el("section", "s-bench");

  const head = el("div", "card");
  head.appendChild(el("div", "muted", league.league.teamName + ", week " + league.week));
  const sum = el("div", "summary");
  [["Current", num(lu.currentPoints)], ["Recommended", num(lu.recommendedPoints)], ["Change", signed(lu.gain)]].forEach(function (x) {
    const d = el("div");
    d.appendChild(el("span", "label", x[0]));
    d.appendChild(el("b", null, x[1]));
    sum.appendChild(d);
  });
  head.appendChild(sum);
  secSum.appendChild(head);

  freshnessWarnings(league, meta, secSum);

  (lu.alerts || []).forEach(function (a) {
    const flags = a.flags.map(function (f) { return FLAG_TEXT[f] || f; }).join(", ");
    secSum.appendChild(el("div", "alert", a.player + " is starting at " + a.slot + " and is " + flags.toLowerCase() + "."));
  });

  (lu.watch || []).forEach(function (w) {
    const first = (w.flags || [])[0];
    const word = first ? (FLAG_TEXT[first] || first).toLowerCase() : "flagged";
    let t = w.player + " (" + w.slot + ") is " + word + ".";
    const k = shortWhen(w.kickoff);
    if (k) t += " Kickoff " + k + ".";
    const note = el("div", "warn", t);
    if (w.injuryNotes) note.title = w.injuryNotes;
    secSum.appendChild(note);
  });

  secMoves.appendChild(el("h2", null, "Moves"));
  const moves = el("div", "card");
  if (!lu.moves.length) moves.appendChild(el("div", null, "No changes. Your lineup is already the best one."));
  lu.moves.forEach(function (m) {
    let t;
    if (m.in && m.out) t = "Start " + m.in.name + " over " + m.out.name + " at " + m.slot + ". " + signed(m.gain);
    else if (m.out) t = "Remove " + m.out.name + " from " + m.slot + ". No eligible replacement. " + signed(m.gain);
    else t = "Start " + m.in.name + " at " + m.slot + ". " + signed(m.gain);
    moves.appendChild(el("div", "move", t));
  });
  secMoves.appendChild(moves);

  secLineup.appendChild(el("h2", null, "Lineup by slot"));
  const slots = el("div", "card list");
  lu.slots.forEach(function (s) { slots.appendChild(slotGroup(s)); });
  secLineup.appendChild(slots);

  const inRec = new Set(lu.slots.filter(function (s) { return s.recommended; }).map(function (s) { return s.recommended.id; }));
  const bench = league.roster.filter(function (p) { return !inRec.has(p.id); });
  secBench.appendChild(el("h2", null, "Bench"));
  const bc = el("div", "card list");
  bench.forEach(function (p) {
    const wrap = el("div", "slot");
    wrap.appendChild(playerRow(p, { chip: benchChip(p) }));
    bc.appendChild(wrap);
  });
  secBench.appendChild(bc);

  return columns([secSum, secMoves, sourcesSection(league, meta)], [secLineup, secBench]);
}

// v2 waivers: free agents ranked by how much they raise your best lineup this week
function renderWaivers(league, meta) {
  const w = league.waivers;
  const secSum = el("section", "s-sum");
  const secDrop = el("section", "s-moves");
  const secTargets = el("section", "s-lineup");
  const secPos = el("section", "s-bench");

  const head = el("div", "card");
  head.appendChild(el("div", "muted", league.league.teamName + ", week " + league.week));
  const best = w.targets.length ? w.targets[0] : null;
  const lt = w.longTerm && w.longTerm.weeks && w.longTerm.weeks.length ? w.longTerm : null;
  const bestLt = lt && lt.targets.length ? lt.targets[0] : null;
  const st = w.stretch && w.stretch.weeks && w.stretch.weeks.length ? w.stretch : null;
  const bestSt = st && st.targets.length ? st.targets[0] : null;
  const sum = el("div", "summary");
  const rows = [["This week", best ? best.player.name + " " + signed(best.gain) : "None"]];
  if (st) rows.push(["Stretch run", bestSt ? bestSt.player.name + " " + signed(bestSt.gain) : "None"]);
  rows.push(["Playoffs", lt ? (bestLt ? bestLt.player.name + " " + signed(bestLt.gain) : "None") : noFutureWeeks(league.seasonPhase)]);
  rows.forEach(function (x) {
    const d = el("div");
    d.appendChild(el("span", "label", x[0]));
    d.appendChild(el("b", null, x[1]));
    sum.appendChild(d);
  });
  head.appendChild(sum);
  secSum.appendChild(head);
  freshnessWarnings(league, meta, secSum);
  if (league.league.platform === "espn") secSum.appendChild(el("p", "muted aside", "ESPN does not say who is on waivers, so some of these may need a claim."));

  secDrop.appendChild(el("h2", null, "Drop idea"));
  const dc = el("div", "card list");
  if (w.dynasty) {
    dc.appendChild(el("div", "slot", "Dynasty league. Weekly points ignore long term value, so pick your own drop."));
  } else if (w.drop) {
    const wrap = el("div", "slot");
    wrap.appendChild(playerRow(w.drop, { chip: "BN", ppg: true, extraMuted: true, extra: "Lowest of this week's projection and season average on your bench." }));
    dc.appendChild(wrap);
  } else {
    dc.appendChild(el("div", "slot", "No bench player to drop."));
  }
  secDrop.appendChild(dc);

  secTargets.appendChild(el("h2", null, "Short term, week " + league.week));
  secTargets.appendChild(el("div", "muted", "Projected points each player adds to your best lineup this week. Two per position at most."));
  const tc = el("div", "card list");
  if (!w.targets.length) tc.appendChild(el("div", "slot", "No free agent beats your starters this week."));
  w.targets.forEach(function (t) {
    const wrap = el("div", "slot");
    const extra = "Starts at " + t.slot + (t.replaces ? " and sends " + t.replaces.name + " to the bench." : ".");
    wrap.appendChild(playerRow(t.player, { chip: t.player.pos, gain: t.gain, ppg: true, extra: extra }));
    tc.appendChild(wrap);
  });
  secTargets.appendChild(tc);
  if (st) secTargets.appendChild(horizonSection(st, "Stretch run, " + weekSpan(st.weeks),
    "Points each player adds to your best lineup over the regular season weeks left after this one. Byes count, so this is where bye coverage shows up."));
  if (lt) secTargets.appendChild(horizonSection(lt, "Long term, playoffs " + weekSpan(lt.weeks),
    "Points each player adds to your best lineup over the playoff weeks."));

  // Reference list, folded so the page stays short on phones
  const fold = el("details", "fold");
  fold.appendChild(el("summary", null, "Best available by position"));
  secPos.appendChild(fold);
  const pc = el("div", "card list");
  // Lineup order, not the sorted order the JSON keys arrive in
  POSITIONS.filter(function (pos) { return w.byPosition[pos]; }).forEach(function (pos) {
    const list = w.byPosition[pos];
    if (!list.length) return;
    list.forEach(function (p) {
      const wrap = el("div", "slot");
      wrap.appendChild(playerRow(p, { chip: pos, ppg: true }));
      pc.appendChild(wrap);
    });
  });
  fold.appendChild(pc);

  return columns([secSum, secDrop, sourcesSection(league, meta)], [secTargets, secPos]);
}

// Soft and tough: the 8 defenses that allow the most and the fewest points to the position
function matchupText(x, teams) {
  if (!x.opp) return "W" + x.week + " bye";
  let t = "W" + x.week + " " + (x.home ? "vs " : "at ") + x.opp;
  if (isNum(x.rank) && x.rank <= 8) t += " (soft)";
  else if (isNum(x.rank) && x.rank > teams - 8) t += " (tough)";
  return t;
}

// What to say when a future-weeks list is empty. seasonPhase is regular, playoffs or over (older builds leave it out).
// Regular with no list means the schedule source is missing, not that the season ended.
function noFutureWeeks(phase) {
  if (phase === "playoffs") return "Final week";
  if (phase === "regular") return "n/a";
  return "Over";
}

function weekSpan(weeks) {
  if (!weeks || !weeks.length) return "";
  return weeks.length > 1 ? "weeks " + weeks[0] + " to " + weeks[weeks.length - 1] : "week " + weeks[0];
}

// A ranked list over future weeks (stretch run or playoffs)
function horizonSection(lt, title, intro) {
  const sec = el("div", "lt");
  sec.appendChild(el("h2", null, title));
  sec.appendChild(el("div", "muted", intro + " A week's rate is this week's projection for healthy players, and the season average for DEF, K and anyone hurt or on bye now. Soft and tough show the 8 defenses that allow the most and the fewest points to the position. Context only, not in the score."));
  const c = el("div", "card list");
  if (!lt.targets.length) c.appendChild(el("div", "slot", "No free agent beats your lineup over these weeks."));
  lt.targets.forEach(function (t) {
    const wrap = el("div", "slot");
    const rate = isNum(t.rate) ? t.rate.toFixed(1) + " a week, " + (t.rateFrom === "season" ? "season average" : "this week's projection") + ". " : "";
    const sched = t.weeks.map(function (x) { return matchupText(x, lt.teams || 32); }).join(" · ");
    wrap.appendChild(playerRow(t.player, { chip: t.player.pos, gain: t.gain, ppg: true, extra: rate + sched }));
    c.appendChild(wrap);
  });
  sec.appendChild(c);
  return sec;
}

// ---------------------------------------------------------------- v3 trades
// Same greedy optimizer as pipeline/lineup.py: fill the narrowest slots first with the best player left.
// Slot eligibility nests (position, then FLEX, then SUPER_FLEX), so this is the best lineup.
function bestTotal(slots, flexE, players) {
  const pool = players.filter(function (p) { return p.ok; }).sort(function (a, b) {
    return b.pts - a.pts || (String(a.id) < String(b.id) ? -1 : String(a.id) > String(b.id) ? 1 : 0);
  });
  function width(s) { return flexE[s] ? flexE[s].length : 1; }
  const order = slots.map(function (_, i) { return i; }).sort(function (a, b) { return width(slots[a]) - width(slots[b]) || a - b; });
  const taken = new Set();
  let total = 0;
  order.forEach(function (i) {
    const s = slots[i];
    for (let k = 0; k < pool.length; k++) {
      const p = pool[k];
      if (!taken.has(p.id) && (p.pos === s || (flexE[s] || []).indexOf(p.pos) >= 0)) { taken.add(p.id); total += p.pts; break; }
    }
  });
  return Math.round(total * 10) / 10;
}
// Best lineup summed over the playoff weeks. A player counts in a week his team plays.
function playoffWeeks(td, players) {
  return td.weeks.map(function (w) {
    const playing = new Set(td.plays[String(w)] || []);
    return bestTotal(td.slots, td.flexEligible, players.map(function (p) {
      return { id: p.id, pos: p.pos, pts: p.rate || 0, ok: !!p.rate && playing.has(p.team) };
    }));
  });
}
function sum(xs) { return Math.round(xs.reduce(function (a, b) { return a + b; }, 0) * 10) / 10; }
function thisWeekTotal(td, players) {
  return bestTotal(td.slots, td.flexEligible, players.map(function (p) {
    return { id: p.id, pos: p.pos, pts: p.points || 0, ok: p.eligible !== false && !!p.points };
  }));
}
// Both sides of a trade. give and get are sets of player ids.
function tradeResult(td, mine, theirs, give, get) {
  const out = mine.filter(function (p) { return give.has(p.id); });
  const inn = theirs.filter(function (p) { return get.has(p.id); });
  const myAfter = mine.filter(function (p) { return !give.has(p.id); }).concat(inn);
  const thAfter = theirs.filter(function (p) { return !get.has(p.id); }).concat(out);
  const myB = playoffWeeks(td, mine), myA = playoffWeeks(td, myAfter);
  return {
    myGain: Math.round((sum(myA) - sum(myB)) * 10) / 10,
    theirGain: Math.round((sum(playoffWeeks(td, thAfter)) - sum(playoffWeeks(td, theirs))) * 10) / 10,
    thisWeek: Math.round((thisWeekTotal(td, myAfter) - thisWeekTotal(td, mine)) * 10) / 10,
    weeks: td.weeks.map(function (w, i) { return { week: w, gain: Math.round((myA[i] - myB[i]) * 10) / 10 }; }),
    out: out, inn: inn,
  };
}
function youngest(ps) {
  const ages = ps.map(function (p) { return p.age; }).filter(isNum);
  return ages.length ? Math.min.apply(null, ages) : null;
}
function tradePlayerLine(p, dynasty) {
  let t = (p.pos || "") + " " + (p.team || "FA");
  if (isNum(p.rate) && p.rate > 0) t += " · " + p.rate.toFixed(1) + " a week";
  else t += " · no playoff rate";
  if (dynasty && isNum(p.age)) t += " · age " + p.age + (isNum(p.yearsExp) ? ", year " + (p.yearsExp + 1) : "");
  return t;
}

function renderTrade(league, meta, td, state, rerender) {
  const rosters = td.rosters;
  const mine = rosters.filter(function (r) { return r.isMine; })[0].players;
  const others = rosters.filter(function (r) { return !r.isMine; });
  if (!state.team || !others.some(function (r) { return r.name === state.team; })) {
    state.team = td.ideas.length ? td.ideas[0].team : others[0].name;
    state.give = new Set(); state.get = new Set();
  }
  const partner = others.filter(function (r) { return r.name === state.team; })[0];
  const stW = td.stretchWeeks || [], poW = td.playoffWeeks || td.weeks;
  const byId = {};
  rosters.forEach(function (r) { r.players.forEach(function (p) { byId[r.name + "|" + p.id] = p; }); });

  const secSum = el("section", "s-sum");
  const head = el("div", "card");
  head.appendChild(el("div", "muted", league.league.teamName + ", week " + league.week));
  const sm = el("div", "summary");
  const best = td.ideas[0];
  [["Best idea", best ? signed(best.myGain) + " for you" : "None"], ["Ideas", String(td.ideas.length)], ["Teams", String(others.length)]].forEach(function (x) {
    const d = el("div");
    d.appendChild(el("span", "label", x[0]));
    d.appendChild(el("b", null, x[1]));
    sm.appendChild(d);
  });
  head.appendChild(sm);
  secSum.appendChild(head);
  freshnessWarnings(league, meta, secSum);
  secSum.appendChild(el("p", "muted aside", !td.weeks.length ? "No weeks are left after this one, so trades show no change over the rest of the season. The this week number still counts." :
    "Trades are scored by how much each team's best lineup changes over the rest of the season, " + weekSpan(td.weeks) +
    ", with every week counted the same. That is the stretch run" + (stW.length ? " (" + weekSpan(stW) + ")" : "") + (poW.length ? " and the playoffs (" + weekSpan(poW) + ")" : "") + ". A week's rate is this week's projection for healthy players, and the season average for DEF, K and anyone hurt or on bye now."));
  if (td.dynasty) secSum.appendChild(el("div", "warn", "Dynasty league. Scores only cover the rest of this season. Ages are shown, and trades that send away a player 4 or more years younger are flagged."));

  // Ideas
  const secIdeas = el("section", "s-lineup");
  secIdeas.appendChild(el("h2", null, "Trade ideas"));
  secIdeas.appendChild(el("div", "muted", "One for one trades that make both lineups better over the rest of the season. Tap one to open it below."));
  const ic = el("div", "card list");
  if (!td.ideas.length) ic.appendChild(el("div", "slot", "No one for one trade helps both teams right now. Try the builder below."));
  td.ideas.forEach(function (i) {
    const give = i.give.map(function (id) { return mine.filter(function (p) { return p.id === id; })[0]; });
    const get = i.get.map(function (id) { return byId[i.team + "|" + id]; });
    const b = el("button", "idea");
    b.type = "button";
    const top = el("div", "pname");
    top.appendChild(el("span", "name", "Give " + give.map(function (p) { return p.name; }).join(", ") + " for " + get.map(function (p) { return p.name; }).join(", ")));
    if (i.youthFlag) top.appendChild(el("span", "badge warn", "Younger out"));
    b.appendChild(top);
    b.appendChild(el("div", "psub", "With " + i.team + " · " + give.map(function (p) { return p.pos; }).join("/") + " for " + get.map(function (p) { return p.pos; }).join("/")));
    const split = isNum(i.stretchGain) && stW.length ? " (stretch " + signed(i.stretchGain) + ", playoffs " + signed(i.playoffGain) + ")" : "";
    const line = el("div", "extra muted-extra", "You " + signed(i.myGain) + split + ", they " + signed(i.theirGain) + " over the rest of the season. ");
    line.appendChild(el("span", i.thisWeek < 0 ? "neg" : "", "This week " + signed(i.thisWeek) + " for you."));
    b.appendChild(line);
    b.addEventListener("click", function () {
      state.team = i.team; state.give = new Set(i.give); state.get = new Set(i.get); state.scroll = true;
      rerender();
    });
    const wrap = el("div", "slot");
    wrap.appendChild(b);
    ic.appendChild(wrap);
  });
  secIdeas.appendChild(ic);

  // Builder
  const secBuild = el("section", "s-bench");
  secBuild.id = "builder";
  secBuild.appendChild(el("h2", null, "Build a trade"));
  const pick = el("select", "teampick");
  pick.setAttribute("aria-label", "Trade partner");
  others.forEach(function (r) {
    const o = el("option", null, r.name);
    o.value = r.name;
    if (r.name === state.team) o.selected = true;
    pick.appendChild(o);
  });
  pick.addEventListener("change", function () { state.team = pick.value; state.give = new Set(); state.get = new Set(); rerender(); });
  secBuild.appendChild(pick);

  // Ticking a box redraws only this card, so focus and scroll stay put
  function resultCard() {
  const res = tradeResult(td, mine, partner.players, state.give, state.get);
  const rc = el("div", "card result");
  rc.setAttribute("aria-live", "polite");
  if (!state.give.size && !state.get.size) {
    rc.appendChild(el("div", "muted", "Tick players to give and to get. The result updates as you go."));
  } else {
    const rs = el("div", "summary");
    [["You, rest of season", signed(res.myGain)], ["They, rest of season", signed(res.theirGain)], ["You, this week", signed(res.thisWeek)]].forEach(function (x) {
      const d = el("div");
      d.appendChild(el("span", "label", x[0]));
      d.appendChild(el("b", "num " + (x[1].charAt(0) === "-" ? "neg" : (x[1] === "0.0" ? "" : "pos")), x[1]));
      rs.appendChild(d);
    });
    rc.appendChild(rs);
    if (res.weeks.length) {
      const part = function (ws) { return Math.round(res.weeks.filter(function (x) { return ws.indexOf(x.week) >= 0; }).reduce(function (a, x) { return a + x.gain; }, 0) * 10) / 10; };
      if (stW.length) rc.appendChild(el("div", "psub", "You: stretch run " + signed(part(stW)) + " · playoffs " + signed(part(poW))));
      rc.appendChild(el("div", "psub", res.weeks.map(function (x) { return "W" + x.week + " " + signed(x.gain); }).join(" · ")));
    }
    let verdict;
    if (res.myGain > 0 && res.theirGain > 0) verdict = "Both teams get better. A fair offer.";
    else if (res.myGain > 0) verdict = "You win this one. They lose " + Math.abs(res.theirGain).toFixed(1) + ", so expect a no.";
    else if (res.theirGain > 0) verdict = "This helps them more than you.";
    else verdict = "Neither lineup gets better.";
    rc.appendChild(el("div", "extra" + (res.myGain > 0 && res.theirGain > 0 ? "" : " muted-extra"), verdict));
    const diff = state.get.size - state.give.size;
    if (diff > 0) rc.appendChild(el("div", "note", "You get " + diff + " more than you give. Make room on your roster."));
    if (diff < 0) rc.appendChild(el("div", "note", "They get " + (-diff) + " more than they give. They need roster room."));
    const yo = youngest(res.out), yi = youngest(res.inn);
    if (td.dynasty && yo !== null && yi !== null && yi - yo >= 4) rc.appendChild(el("div", "note", "Dynasty: the youngest player you give is " + (yi - yo) + " years younger than anyone you get."));
  }
  return rc;
  }
  let rc = resultCard();
  secBuild.appendChild(rc);

  function pickList(title, players, chosen) {
    const box = el("div", "plist");
    box.appendChild(el("h3", null, title));
    const card = el("div", "card list");
    players.forEach(function (p) {
      const row = el("label", "pick");
      const cb = el("input");
      cb.type = "checkbox";
      cb.checked = chosen.has(p.id);
      cb.addEventListener("change", function () {
        if (cb.checked) chosen.add(p.id); else chosen.delete(p.id);
        const next = resultCard();
        rc.replaceWith(next);
        rc = next;
      });
      row.appendChild(cb);
      row.appendChild(chipNode(POSITIONS.indexOf(p.pos) >= 0 ? p.pos : "BN"));
      const body = el("div", "pbody");
      const nm = el("div", "pname");
      nm.appendChild(el("span", "name", p.name));
      badgeNodes(p).forEach(function (n) { nm.appendChild(n); });
      body.appendChild(nm);
      body.appendChild(el("div", "psub", tradePlayerLine(p, td.dynasty)));
      row.appendChild(body);
      card.appendChild(row);
    });
    box.appendChild(card);
    return box;
  }
  const lists = el("div", "plists");
  lists.append(pickList("You give", mine, state.give), pickList("You get from " + partner.name, partner.players, state.get));
  secBuild.appendChild(lists);

  return columns([secSum, sourcesSection(league, meta)], [secIdeas, secBuild]);
}

// ---------------------------------------------------------------- v4 standings and playoff odds
function pct(x) { return isNum(x) ? (x >= 99.95 ? "100%" : x > 0 && x < 0.5 ? "under 1%" : Math.round(x) + "%") : "n/a"; }
function record(t) { return t.wins + "-" + t.losses + (t.ties ? "-" + t.ties : ""); }

function renderStandings(league, meta) {
  const st = league.standings;
  const secSum = el("section", "s-sum");
  const secGames = el("section", "s-moves");
  const secTable = el("section", "s-lineup");
  if (!st) {
    const c = el("div", "card");
    c.appendChild(el("div", null, league.league.platform === "espn"
      ? "ESPN standings are not in the roster file yet. Once the espn-roster-sync skill saves standings and schedule (see docs/SPEC.md), odds show up here on the next run."
      : "Standings are not available for this league right now."));
    secSum.appendChild(c);
    return columns([secSum, sourcesSection(league, meta)], []);
  }
  const me = st.teams.filter(function (t) { return t.isMine; })[0];
  const head = el("div", "card");
  head.appendChild(el("div", "muted", league.league.teamName + ", week " + league.week));
  const sm = el("div", "summary");
  [["Record", me ? record(me) : "n/a"], ["Playoffs", me ? pct(me.playoffPct) : "n/a"], ["Bye", me ? pct(me.byePct) : "n/a"]].forEach(function (x) {
    const d = el("div");
    d.appendChild(el("span", "label", x[0]));
    d.appendChild(el("b", null, x[1]));
    sm.appendChild(d);
  });
  head.appendChild(sm);
  if (me) head.appendChild(el("div", "psub", "Seed " + me.seed + " now. Projected " + me.projWins.toFixed(1) + " wins, average finish seed " + me.avgSeed.toFixed(1) + "."));
  secSum.appendChild(head);
  freshnessWarnings(league, meta, secSum);
  secSum.appendChild(el("p", "muted aside", (st.weeksLeft.length
    ? "Odds come from playing out the rest of the regular season (" + weekSpan(st.weeksLeft) + ") " + st.sims.toLocaleString("en-US") +
      " times. Each team's expected score is its own best lineup under the board's projections, with a spread of " + st.sd.toFixed(1) +
      " points, the typical week to week swing in this league. "
    : "The regular season is over, so the odds are the final standings. ") +
    "Top " + st.playoffTeams + " make the playoffs and top " + st.byes + " get a bye." +
    (st.divisions ? " Assumes division winners take the top seeds." : "")));

  secGames.appendChild(el("h2", null, "Your games"));
  const gc = el("div", "card list");
  st.myGames.forEach(function (g) {
    const row = el("div", "slot");
    const pr = el("div", "prow");
    pr.appendChild(el("span", "chip neutral", "W" + g.week));
    const body = el("div", "pbody");
    body.appendChild(el("div", "pname", "vs " + g.opp));
    body.appendChild(el("div", "psub", "You " + g.myMean.toFixed(1) + " · them " + g.oppMean.toFixed(1) + " expected"));
    pr.appendChild(body);
    const nums = el("div", "pnums");
    nums.appendChild(el("div", "pts " + (g.winPct >= 60 ? "good" : g.winPct <= 40 ? "bad" : ""), pct(g.winPct)));
    nums.appendChild(el("div", "range", "to win"));
    pr.appendChild(nums);
    row.appendChild(pr);
    gc.appendChild(row);
  });
  if (!st.myGames.length) gc.appendChild(el("div", "slot", "No regular season games left."));
  secGames.appendChild(gc);

  secTable.appendChild(el("h2", null, "Standings"));
  const card = el("div", "card tablecard");
  const t = el("table", "standings");
  const hr = el("tr");
  ["", "Team", "Record", "Points", "Playoffs", "Bye"].forEach(function (h, i) { hr.appendChild(el("th", (i > 1 ? "num" : "") + (i === 3 ? " pf" : ""), h)); });
  const thead = el("thead");
  thead.appendChild(hr);
  t.appendChild(thead);
  const tb = el("tbody");
  st.teams.forEach(function (r) {
    const tr = el("tr", (r.isMine ? "mine" : "") + (r.seed === st.playoffTeams ? " cutline" : ""));
    tr.appendChild(el("td", "seed", String(r.seed)));
    const name = el("td", "tname");
    name.appendChild(document.createTextNode(r.name));
    if (st.divisions && isNum(r.division)) name.appendChild(el("span", "div", " D" + r.division));
    tr.appendChild(name);
    tr.appendChild(el("td", "num", record(r)));
    tr.appendChild(el("td", "num pf", r.pointsFor.toFixed(1)));
    tr.appendChild(el("td", "num strong", pct(r.playoffPct)));
    tr.appendChild(el("td", "num", pct(r.byePct)));
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  card.appendChild(t);
  secTable.appendChild(card);
  secTable.appendChild(el("div", "muted", "The line marks the last playoff spot today. Seeds use record, then points for."));

  return columns([secSum, secGames, sourcesSection(league, meta)], [secTable]);
}

// ---------------------------------------------------------------- views and routing (docs/STATES.md)
// Every view a league can open, in button order. The test says whether this build carries it.
// Standings is listed whenever the key exists, even when null, so the ESPN league can say why it is empty.
const VIEWS = [
  ["lineup", "Lineup", function () { return true; }],
  ["waivers", "Waivers", function (league) { return !!league.waivers; }],
  ["trade", "Trade", function (league) { return !!league.trade; }],
  ["standings", "Standings", function (league) { return "standings" in league; }],
];
function viewsFor(league) {
  return VIEWS.filter(function (v) { return v[2](league); });
}
// A view this league can open, or lineup
function resolveView(league, view) {
  return viewsFor(league).some(function (v) { return v[0] === view; }) ? view : "lineup";
}
// The All route. Its league index is ALL (-1). It has no views of its own.
const ALL = -1;
// URL hash is #all, #league or #league/view. Unknown leagues open the first one, unknown views open lineup.
function routeFromHash(hash, leagues) {
  const parts = String(hash || "").replace(/^#/, "").split("/");
  if (parts[0] === "all") return { league: ALL, view: "all" };
  const i = Math.max(0, leagues.findIndex(function (l) { return l.league.key === parts[0]; }));
  return { league: i, view: resolveView(leagues[i], parts[1]) };
}
// hashFor(null) is the All route
function hashFor(league, view) {
  if (!league) return "#all";
  return "#" + league.league.key + (view === "lineup" ? "" : "/" + view);
}

function viewSwitch(league, view, go) {
  const box = el("div", "views");
  box.setAttribute("role", "group");
  box.setAttribute("aria-label", "View");
  viewsFor(league).forEach(function (v) {
    const b = el("button", "view", v[1]);
    b.type = "button";
    b.setAttribute("aria-pressed", String(view === v[0]));
    b.addEventListener("click", function () { go(v[0]); });
    box.appendChild(b);
  });
  return box;
}

// ---------------------------------------------------------------- S5 All leagues and tabs
// Plain lines for the To do list, worded like the Lineup view. Each keeps its kind for styling.
function moveLine(m) {
  if (m.in && m.out) return "Start " + m.in.name + " over " + m.out.name + " at " + m.slot + ". " + signed(m.gain);
  if (m.out) return "Remove " + m.out.name + " from " + m.slot + ". No eligible replacement. " + signed(m.gain);
  return "Start " + m.in.name + " at " + m.slot + ". " + signed(m.gain);
}
function alertLine(a) {
  const flags = a.flags.map(function (f) { return FLAG_TEXT[f] || f; }).join(", ").toLowerCase();
  let t = a.player + " is starting at " + a.slot + " and is " + flags + ".";
  if (a.backup) t += " If he sits, start " + a.backup.name + ".";
  return t;
}
function watchLine(w) {
  const first = (w.flags || [])[0];
  let t = w.player + " (" + w.slot + ") is " + (first ? (FLAG_TEXT[first] || first).toLowerCase() : "flagged") + ".";
  const k = shortWhen(w.kickoff);
  if (k) t += " Kickoff " + k + ".";
  if (w.backup) t += " If he sits, start " + w.backup.name + ".";
  return t;
}
// Every pending move, alert and watch in one league, in that order
function leagueTodos(league) {
  const lu = league.lineup;
  const out = [];
  (lu.moves || []).forEach(function (m) { out.push({ kind: "move", text: moveLine(m) }); });
  (lu.alerts || []).forEach(function (a) { out.push({ kind: "alert", text: alertLine(a) }); });
  (lu.watch || []).forEach(function (w) { out.push({ kind: "watch", text: watchLine(w) }); });
  return out;
}
// The status on a league tab, in place of the gain. cls picks the color. "out" also gets a red dot.
function tabStatus(league) {
  const lu = league.lineup;
  if ((lu.alerts || []).length) return { text: "Out", cls: "out" };
  if (lu.gain > 0) return { text: signed(lu.gain), cls: "good" };
  if ((lu.watch || []).length) return { text: lu.watch.length + " Q", cls: "warn" };
  return { text: "✓ Set", cls: "muted" };
}
// The All tab: the total count of to-dos across leagues, or Set
function allStatus(leagues) {
  const n = leagues.reduce(function (a, lg) { return a + leagueTodos(lg).length; }, 0);
  return n ? { text: n + " to do", cls: "warn" } : { text: "✓ Set", cls: "muted" };
}
// Players recommended to start in 2 or more leagues. Matched by name and position, since ESPN and Sleeper ids differ.
// Most leagues first, then the earliest kickoff, then name.
function exposure(leagues) {
  const byKey = {};
  leagues.forEach(function (lg) {
    const seen = {};
    (lg.lineup.slots || []).forEach(function (s) {
      const p = s.recommended;
      if (!p) return;
      const key = p.name + "|" + p.pos;
      if (seen[key]) return;
      seen[key] = true;
      const e = byKey[key] || (byKey[key] = { name: p.name, pos: p.pos, leagues: [], kickoff: null });
      e.leagues.push(lg.league.name);
      const k = p.game && p.game.kickoff;
      if (k && (!e.kickoff || Date.parse(k) < Date.parse(e.kickoff))) e.kickoff = k;
    });
  });
  return Object.keys(byKey).map(function (k) { return byKey[k]; })
    .filter(function (e) { return e.leagues.length > 1; })
    .sort(function (a, b) {
      if (b.leagues.length !== a.leagues.length) return b.leagues.length - a.leagues.length;
      const ka = a.kickoff ? Date.parse(a.kickoff) : Infinity;
      const kb = b.kickoff ? Date.parse(b.kickoff) : Infinity;
      if (ka !== kb) return ka < kb ? -1 : 1;
      return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });
}
// Freshness lines for one league. Board-wide lines (old build, skipped leagues) are left out, since the All view shows them once.
function leagueFreshness(league, meta, now) {
  const shared = freshnessMessages({ league: { platform: "" }, sources: {} }, meta, now);
  return freshnessMessages(league, meta, now).filter(function (m) { return shared.indexOf(m) < 0; });
}
// Label and address of the league's app, from league.appUrl and appName in the data. Only https links. Null when absent.
function appLinkInfo(league) {
  const url = league.league.appUrl;
  const name = league.league.appName;
  if (!url || !name) return null;
  try { if (new URL(url).protocol !== "https:") return null; } catch (e) { return null; }
  return { label: "Open in " + name, href: url };
}
function appLink(league) {
  const info = appLinkInfo(league);
  if (!info) return null;
  const a = el("a", "applink", info.label);
  a.href = info.href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
// A tab's status line. A red dot comes first for Out.
function tabStatusNode(st) {
  const n = el("span", "tstat " + st.cls);
  if (st.cls === "out") {
    const dot = el("span", "dot");
    dot.setAttribute("aria-hidden", "true");
    n.appendChild(dot);
  }
  n.appendChild(document.createTextNode(st.text));
  return n;
}
function todoNode(it) {
  return el("div", it.kind === "alert" ? "alert" : it.kind === "watch" ? "warn" : "move", it.text);
}

// The All view. Every to-do grouped by league (league names open that league's Lineup), players starting in
// more than one league, and data warnings. go(i) opens league i on its Lineup view.
function renderAll(leagues, meta, go) {
  const now = Date.now();
  const secTodo = el("section", "s-sum");
  const secExpo = el("section", "s-moves");
  const secFresh = el("section", "s-src");

  secTodo.appendChild(el("h2", null, "To do"));
  const todo = el("div", "card");
  leagues.forEach(function (lg, i) {
    const block = el("div", "todo-league");
    const items = leagueTodos(lg);
    if (!items.length) {
      block.appendChild(el("div", "todo-set", lg.league.name + ": set, nothing to do."));
    } else {
      const jump = el("button", "jump", lg.league.name);
      jump.type = "button";
      jump.addEventListener("click", function () { go(i); });
      block.appendChild(jump);
      items.forEach(function (it) { block.appendChild(todoNode(it)); });
    }
    todo.appendChild(block);
  });
  if (!todo.children.length) todo.appendChild(el("div", "todo-set", "No leagues to show."));
  secTodo.appendChild(todo);

  secExpo.appendChild(el("h2", null, "Players in more than one lineup"));
  secExpo.appendChild(el("div", "muted", "Recommended starters in two or more leagues. One injury or bye hits each of those lineups."));
  const ec = el("div", "card list");
  const ex = exposure(leagues);
  if (!ex.length) ec.appendChild(el("div", "slot", "No player starts in more than one league."));
  ex.forEach(function (e) {
    const wrap = el("div", "slot");
    const row = el("div", "prow");
    row.appendChild(chipNode(e.pos || ""));
    const body = el("div", "pbody");
    body.appendChild(el("div", "pname", e.name));
    let sub = "Starts in " + e.leagues.length + " leagues: " + e.leagues.join(", ") + ".";
    const k = shortWhen(e.kickoff);
    if (k) sub += " First kickoff " + k + ".";
    body.appendChild(el("div", "psub", sub));
    row.appendChild(body);
    wrap.appendChild(row);
    ec.appendChild(wrap);
  });
  secExpo.appendChild(ec);

  secFresh.appendChild(el("h2", null, "Data freshness"));
  const shared = freshnessMessages({ league: { platform: "" }, sources: {} }, meta, now);
  shared.forEach(function (m) { secFresh.appendChild(el("div", "warn", m)); });
  let any = shared.length > 0;
  leagues.forEach(function (lg) {
    const msgs = leagueFreshness(lg, meta, now);
    if (!msgs.length) return;
    any = true;
    const box = el("div", "warn");
    box.appendChild(el("span", "fresh-name", lg.league.name));
    msgs.forEach(function (m) { box.appendChild(el("div", null, m)); });
    secFresh.appendChild(box);
  });
  if (!any) secFresh.appendChild(el("div", "muted", "Every source is fresh."));

  // Phones stack To do first. Wide screens put To do in the main column, with the list and warnings beside it.
  return columns([secExpo, secFresh], [secTodo]);
}

function fail(msg) {
  const panel = document.getElementById("panel");
  panel.replaceChildren(el("div", "error", msg));
  document.getElementById("stamp").textContent = "No data";
}

async function getJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(path + " returned " + r.status);
  return r.json();
}

// Trade files load the first time the Trade view opens. Per league: loading, then ready or error.
// Only Try again moves error back to loading, so a failed file never refetches in a loop.
function loadTrade(store, league, settled) {
  const t = { status: "loading", data: null };
  store[league.league.key] = t;
  getJSON("data/build/" + league.trade.file).then(function (td) { t.status = "ready"; t.data = td; }, function () { t.status = "error"; })
    .then(function () { if (store[league.league.key] === t) settled(); });
  return t;
}

// ---------------------------------------------------------------- S1 shell: keys, refresh on return, next refresh line
// The tab the arrow, Home or End key moves to, or -1 for any other key. Arrows wrap at the ends.
function nextTabIndex(current, key, count) {
  if (count < 1 || current < 0) return -1;
  if (key === "ArrowRight") return (current + 1) % count;
  if (key === "ArrowLeft") return (current - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return -1;
}
// meta.json is refetched when the page comes back into view, at most once a minute
function refreshDue(lastMs, nowMs) { return nowMs - lastMs >= 60000; }
// Reload when the build changed since this page loaded. A missing or unreadable fresh stamp never reloads.
function shouldReload(loadedIso, freshIso) {
  if (isNaN(Date.parse(freshIso))) return false;
  return Date.parse(loadedIso) !== Date.parse(freshIso);
}
// Header line, or "" when the build has no nextRefresh (older builds, and the ESPN league until the field ships)
function nextRefreshText(iso) {
  const t = shortWhen(iso);
  return t ? "Next refresh " + t : "";
}
// The sticky bar's height, so the builder scrolls to a spot below it (style.css, #builder)
function setBarHeight() {
  const bar = document.querySelector(".bar");
  if (bar) document.documentElement.style.setProperty("--bar-h", bar.offsetHeight + "px");
}

async function main() {
  let meta, leagues;
  try {
    meta = await getJSON("data/build/meta.json");
    leagues = await Promise.all(meta.leagues.map(function (l) { return getJSON("data/build/" + l.file); }));
  } catch (e) {
    fail("The board data could not be loaded. Try again in a few minutes.");
    return;
  }
  if (!leagues.length) { fail("The board has no leagues. Nothing to show."); return; }
  document.getElementById("stamp").textContent = "Week " + meta.week + ", built " + when(meta.generatedAt);
  const nextLine = nextRefreshText(meta.nextRefresh);
  const nextEl = document.getElementById("next");
  nextEl.textContent = nextLine;
  nextEl.hidden = !nextLine;

  const tabs = document.getElementById("tabs");
  const viewbar = document.getElementById("viewbar");
  const panel = document.getElementById("panel");
  const route = { league: 0, view: "lineup" };   // what is on screen. Only show() changes it
  let leagueView = "lineup";   // the view a league tab reopens with, so All and back keeps your place
  const tradeLoads = {};   // league key -> { status, data }, see loadTrade
  const tradeState = {};   // league key -> builder picks, kept while you switch views

  function tradeBody(i, lg) {
    const key = lg.league.key;
    const load = tradeLoads[key] || loadTrade(tradeLoads, lg, function () {
      if (route.league === i && route.view === "trade") show(i, "trade");
    });
    if (load.status === "loading") return el("div", "card", "Loading trades");
    if (load.status === "error") {
      const box = el("div", "error", "The trade data could not be loaded. ");
      const retry = el("button", "retry", "Try again");
      retry.type = "button";
      retry.addEventListener("click", function () { delete tradeLoads[key]; show(i, "trade"); });
      box.appendChild(retry);
      return box;
    }
    const st = tradeState[key] || (tradeState[key] = { give: new Set(), get: new Set() });
    return renderTrade(lg, meta, load.data, st, function () { show(i, "trade"); });
  }

  // i is a league index, or ALL for the All tab. v is a view name, and All has none.
  function show(i, v) {
    const onAll = i === ALL;
    const lg = onAll ? null : leagues[i];
    const view = onAll ? "all" : resolveView(lg, v);
    route.league = i;
    route.view = view;
    if (!onAll) leagueView = view;
    Array.prototype.forEach.call(tabs.children, function (b, j) {
      const on = j === i + 1;   // tab 0 is All, tab j + 1 is league j
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;   // roving tabindex: only the selected tab is in the Tab order
    });
    panel.setAttribute("aria-labelledby", tabs.children[i + 1].id);
    let body;
    if (onAll) body = renderAll(leagues, meta, function (k) { show(k, "lineup"); });
    else body = view === "waivers" ? renderWaivers(lg, meta)
      : view === "standings" ? renderStandings(lg, meta)
      : view === "trade" ? tradeBody(i, lg)
      : renderLeague(lg, meta);
    const keepY = view === "trade" ? window.scrollY : 0;
    viewbar.replaceChildren();
    if (!onAll) {
      if (viewsFor(lg).length > 1) viewbar.appendChild(viewSwitch(lg, view, function (nv) { show(i, nv); }));
      const app = appLink(lg);
      if (app) viewbar.appendChild(app);
    }
    panel.replaceChildren(body);
    setBarHeight();
    if (view === "trade") {
      const st = tradeState[lg.league.key];
      if (st && st.scroll) { st.scroll = false; const bld = document.getElementById("builder"); if (bld) bld.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); }
      else window.scrollTo(0, keepY);
    }
    history.replaceState(null, "", hashFor(lg, view));
  }
  // All comes first and is not a league. Each league tab shows its status in place of the gain.
  const allTab = el("button", "tab");
  allTab.type = "button";
  allTab.id = "tab-all";
  allTab.setAttribute("role", "tab");
  allTab.setAttribute("aria-controls", "panel");
  allTab.appendChild(el("span", "tname", "All"));
  allTab.appendChild(tabStatusNode(allStatus(leagues)));
  allTab.addEventListener("click", function () { show(ALL, "all"); });
  tabs.appendChild(allTab);
  leagues.forEach(function (l) {
    const b = el("button", "tab");
    b.type = "button";
    b.id = "tab-" + l.league.key;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-controls", "panel");
    b.appendChild(el("span", "tname", l.league.name));
    b.appendChild(tabStatusNode(tabStatus(l)));
    b.addEventListener("click", function () { show(leagues.indexOf(l), leagueView); });
    tabs.appendChild(b);
  });
  function fromHash() {
    const r = routeFromHash(location.hash, leagues);
    show(r.league, r.view);
  }
  // Tablist keys, All included. Focus follows the arrow, so the tab that gets focus is the one that opens.
  tabs.addEventListener("keydown", function (e) {
    const cur = Array.prototype.indexOf.call(tabs.children, e.target);
    const j = nextTabIndex(cur, e.key, tabs.children.length);
    if (j < 0) return;
    e.preventDefault();
    tabs.children[j].focus();
    if (j === 0) show(ALL, "all");
    else show(j - 1, leagueView);
  });
  window.addEventListener("resize", setBarHeight);
  window.addEventListener("hashchange", fromHash);
  fromHash();

  // Refresh on return: a build that finished while the page was in the background reloads the board in place
  const loadedAt = meta.generatedAt;
  let lastCheck = Date.now();
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState !== "visible") return;
    const now = Date.now();
    if (!refreshDue(lastCheck, now)) return;
    lastCheck = now;
    getJSON("data/build/meta.json").then(function (fresh) {
      if (shouldReload(loadedAt, fresh.generatedAt)) location.reload();   // keeps the hash route
    }, function () { /* offline or failed: keep the board on screen */ });
  });
}

main();
