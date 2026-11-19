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
  if (p.slot === "IR" || hasFlag(p, "IR")) return "IR";
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
// opts.detail (Lineup view only) adds the floor to ceiling bar, the too-few-games note and a row you tap to open details.
// Without opts.detail the row is the same one Waivers and Trade have always had.
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
  if (opts.detail) top.appendChild(el("span", "caret"));
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
    if (opts.detail) nums.appendChild(track(p));
  } else if (opts.detail && eligible) {
    nums.appendChild(el("div", "range few", "Too few games for a range"));
  }
  if (opts.gain !== undefined) nums.appendChild(el("div", "gainline", "→ " + signed(opts.gain)));

  row.append(body, nums);
  return opts.detail ? expandable(row, p) : row;
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
    wrap.appendChild(playerRow(s.current, { chip: s.slot, rowCls: "cur", struck: true, detail: true }));
    if (s.recommended) {
      const rec = s.recommended;
      // A locked player is never styled as a recommended move
      wrap.appendChild(playerRow(rec, { chip: s.slot, rowCls: rec.locked ? "" : "rec", gain: rec.locked ? undefined : gainOf(s), detail: true }));
    }
  } else {
    wrap.appendChild(playerRow(s.current || s.recommended, { chip: s.slot, detail: true }));
  }
  const cc = closeCallText(s);
  if (cc) wrap.appendChild(el("div", "close", cc));
  return wrap;
}

// Floor to ceiling bar on one fixed 0 to 40 point axis, so every row compares. The tick is the projection.
const AXIS_MAX = 40;
function axisPct(x) {
  return isNum(x) ? Math.min(AXIS_MAX, Math.max(0, x)) / AXIS_MAX * 100 : 0;
}
function track(p) {
  const t = el("div", "track");
  t.setAttribute("aria-hidden", "true");
  const fill = el("span", "fill");
  fill.style.left = axisPct(p.floor) + "%";
  fill.style.width = (axisPct(p.ceiling) - axisPct(p.floor)) + "%";
  t.appendChild(fill);
  if (isNum(p.points)) {
    const tick = el("span", "tick");
    tick.style.left = axisPct(p.points) + "%";
    t.appendChild(tick);
  }
  return t;
}

// Turns a row into a button that opens the detail panel under it. Works with Enter and Space.
let detailSeq = 0;
function expandable(row, p) {
  const id = "pd" + (++detailSeq);
  row.setAttribute("role", "button");
  row.tabIndex = 0;
  row.setAttribute("aria-expanded", "false");
  row.setAttribute("aria-controls", id);
  const panel = el("div", "pdetail");
  panel.id = id;
  panel.hidden = true;
  const lines = detailLines(p, Date.now());
  if (!lines.length) panel.appendChild(el("div", "muted", "Nothing more to show for this player."));
  lines.forEach(function (x) {
    const d = el("div", "dline");
    d.appendChild(el("span", "label", x[0]));
    d.appendChild(el("div", null, x[1]));
    panel.appendChild(d);
  });
  function toggle() {
    const open = row.getAttribute("aria-expanded") !== "true";
    row.setAttribute("aria-expanded", String(open));
    panel.hidden = !open;
  }
  row.addEventListener("click", toggle);
  row.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
  });
  const wrap = el("div", "pwrap");
  wrap.append(row, panel);
  return wrap;
}

// ---------------------------------------------------------------- S2 pure helpers (node tests in tests/test_site_lineup.py)
// Slots a player can fill besides their own position. Same table as FLEX_ELIGIBLE in pipeline/scoring.py.
const FLEX_FILLS = { FLEX: ["RB", "WR", "TE"], REC_FLEX: ["WR", "TE"], WRRB_FLEX: ["RB", "WR"], SUPER_FLEX: ["QB", "RB", "WR", "TE"] };
function canFill(slot, pos) {
  return slot === pos || (FLEX_FILLS[slot] || []).indexOf(pos) >= 0;
}
// Upside box: up to 3 bench players (eligible, not locked, with a ceiling) whose ceiling beats the ceiling of a
// starter they could replace at a slot they fit. Each one names the starter with the biggest gap.
function upsideOptions(slots, bench) {
  const found = [];
  bench.forEach(function (p) {
    if (!isEligible(p) || p.locked || !isNum(p.ceiling)) return;
    let best = null;
    slots.forEach(function (s) {
      const st = s.recommended;
      if (!st || st.locked || !isNum(st.ceiling) || !canFill(s.slot, p.pos)) return;
      const gap = p.ceiling - st.ceiling;
      if (gap > 0 && (!best || gap > best.gap)) best = { player: p, starter: st, slot: s.slot, gap: gap };
    });
    if (best) found.push(best);
  });
  found.sort(function (a, b) { return b.gap - a.gap; });
  return found.slice(0, 3);
}
// Bench split: playable (eligible, not on bye, out, IR or taxi) first, the rest folds away
function benchSplit(list) {
  const playable = [];
  const out = [];
  list.forEach(function (p) {
    const ok = isEligible(p) && !p.locked && !hasFlag(p, "BYE") && !hasFlag(p, "OUT") && !hasFlag(p, "IR") &&
      p.slot !== "IR" && p.slot !== "TAXI";
    (ok ? playable : out).push(p);
  });
  return { playable: playable, out: out };
}
// "Close call. Next best X, 1.6 behind." when the starter's next best is within 2 points. Empty otherwise.
function closeCallText(s) {
  const st = s.recommended;
  const nb = s.nextBest;
  if (!st || !nb || !nb.name || st.locked || !isEligible(st) || !isNum(st.points) || !isNum(nb.points)) return "";
  const margin = st.points - nb.points;
  if (margin < 0 || margin > 2) return "";
  return "Close call. Next best " + nb.name + ", " + margin.toFixed(1) + " behind.";
}
// "updated 3h ago" from an ISO time. Empty when the time is missing or unreadable.
function relativeAgo(iso, now) {
  const t = iso ? Date.parse(iso) : NaN;
  if (isNaN(t)) return "";
  const mins = Math.floor((now - t) / 60000);
  if (mins < 1) return "updated just now";
  if (mins < 60) return "updated " + mins + "m ago";
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return "updated " + hrs + "h ago";
  return "updated " + Math.floor(hrs / 24) + "d ago";
}
// Label and value rows for the detail panel. Only the parts the build has.
function detailLines(p, now) {
  const out = [];
  const proj = [];
  if (isNum(p.espn)) proj.push("ESPN " + p.espn.toFixed(1));
  if (isNum(p.rotowire)) proj.push("Rotowire " + p.rotowire.toFixed(1));
  if (proj.length) out.push(["Projections", proj.join(" · ")]);
  const g = p.game || {};
  const game = [];
  if (isNum(g.implied)) game.push("team total " + g.implied.toFixed(1));
  if (isNum(g.spread)) game.push("spread " + (g.spread > 0 ? "+" : "") + g.spread.toFixed(1));
  if (isNum(g.oppImplied)) game.push("opponent total " + g.oppImplied.toFixed(1));
  if (game.length) out.push(["Game", game.join(" · ")]);
  if (Array.isArray(p.recent)) {
    const rs = p.recent.filter(function (r) { return isNum(r.pts); }).map(function (r) { return "W" + r.week + " " + r.pts.toFixed(1); });
    out.push(["Recent", rs.length ? rs.join(" · ") : "No games played yet"]);
  }
  if (p.injuryNotes) {
    const ago = relativeAgo(p.newsUpdated, now);
    out.push(["Injury note", p.injuryNotes + (ago ? " (" + ago + ")" : "")]);
  }
  return out;
}
// Lines under a watch or alert note. The backup is the best eligible bench player for the slot.
// Each line is { text, late }. A late line is the red warning when the flagged player plays after every backup.
function backupLines(item) {
  const out = [];
  if (!("backup" in item)) return out;   // older builds have no backup at all, so say nothing
  const b = item.backup;
  if (!b) return [{ text: "No eligible backup on your bench.", late: false }];
  const pts = isNum(b.points) ? b.points.toFixed(1) : "";
  const k = shortWhen(b.kickoff);
  const where = [pts, k].filter(Boolean).join(", ");
  out.push({ text: "If he sits, start " + b.name + (where ? " (" + where + ")" : "") + ".", late: false });
  if (item.lateRisk) {
    let t = "He plays after every backup, so there is no swap left if he is ruled out late.";
    if (k) t += " Decide before " + k + ".";
    out.push({ text: t, late: true });
  }
  return out;
}
// This week's game from the standings block. Null for ESPN leagues and during a bye.
function thisGame(league) {
  const st = league.standings;
  if (!st || !Array.isArray(st.myGames)) return null;
  return st.myGames.filter(function (g) { return g.week === league.week; })[0] || null;
}
// Win pct color: green at 60 or more, red at 40 or less
function winClass(x) {
  if (!isNum(x)) return "";
  return x >= 60 ? "good" : x <= 40 ? "bad" : "";
}
function pctText(x) {
  return isNum(x) ? Math.round(x) + "%" : "";
}
// "Playoff odds 81% with a win, 48% with a loss". Empty when the build has neither.
function oddsText(g) {
  const parts = [];
  if (isNum(g.ifWin)) parts.push(pctText(g.ifWin) + " with a win");
  if (isNum(g.ifLose)) parts.push(pctText(g.ifLose) + " with a loss");
  return parts.length ? "Playoff odds " + parts.join(", ") : "";
}
// Recap lines. Any part that is null is left out.
function recapLines(r) {
  const out = [];
  if (!r) return out;
  if (isNum(r.actual)) out.push("You scored " + r.actual.toFixed(1));
  if (isNum(r.optimal)) out.push("Best possible with hindsight " + r.optimal.toFixed(1));
  if (isNum(r.recommended)) out.push("Board's lineup " + r.recommended.toFixed(1));
  return out;
}
// Older pipeline output could name a source's scoring in engineer terms. Reword those, keep anything else as is.
function scoringNoteText(n) {
  const s = String(n);
  const ids = /^ESPN scoring ids with points but no Rotowire equivalent, ignored for Rotowire: \[([^\]]*)\]$/.exec(s);
  if (ids) return "ESPN gives points for stats (ids " + ids[1] + ") that Rotowire does not have, so Rotowire projections leave them out.";
  if (/^D\/ST scored with ESPN's default values/.test(s)) {
    return "Defense scoring uses ESPN's default values. This league's own defense settings are not in the roster file yet.";
  }
  return s;
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
  (league.scoringNotes || []).forEach(function (n) { sc.appendChild(el("div", "muted aside", scoringNoteText(n))); });
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

// Sidebar card for this week's game. Hidden when there is no game this week.
function matchupCard(league, g) {
  if (!g) return null;
  const card = el("div", "card matchup");
  card.appendChild(el("div", "mhead", "Week " + league.week + " vs " + String(g.opp || "").trim()));
  if (isNum(g.winPct)) {
    const box = el("div", "wpbox");
    box.appendChild(el("div", "label", "Win chance"));
    box.appendChild(el("div", "wp " + winClass(g.winPct), pctText(g.winPct)));
    card.appendChild(box);
  }
  if (isNum(g.myMean) && isNum(g.oppMean)) {
    card.appendChild(el("div", "muted", "You " + g.myMean.toFixed(1) + " · them " + g.oppMean.toFixed(1)));
  }
  const odds = oddsText(g);
  if (odds) card.appendChild(el("div", "muted", odds));
  return card;
}

// Sidebar card for last week. Null when the build has no recap or every part is empty.
function recapCard(r) {
  const lines = recapLines(r);
  if (!lines.length) return null;
  const card = el("div", "card recap");
  card.appendChild(el("div", "mhead", isNum(r.week) ? "Week " + r.week + " recap" : "Last week recap"));
  lines.forEach(function (t) { card.appendChild(el("div", "rline", t)); });
  return card;
}

// Underdog box, shown when this week's win chance is under 40. Context only, the lineup is still the projection's.
function upsideCard(list) {
  const card = el("div", "card upside");
  card.appendChild(el("div", "mhead", "Underdog this week. Upside options:"));
  if (!list.length) card.appendChild(el("div", "muted", "No bench player has a higher ceiling than a starter they can replace."));
  list.forEach(function (o) {
    const d = el("div", "opt");
    d.appendChild(el("span", "name", o.player.name));
    d.appendChild(document.createTextNode(", ceiling " + o.player.ceiling.toFixed(1) + " vs " + o.starter.name + " " + o.starter.ceiling.toFixed(1)));
    card.appendChild(d);
  });
  card.appendChild(el("div", "muted aside", "Context only. The projection still recommends the lineup below."));
  return card;
}

function benchRow(p) {
  const wrap = el("div", "slot");
  wrap.appendChild(playerRow(p, { chip: benchChip(p), detail: true }));
  return wrap;
}

function renderLeague(league, meta) {
  const lu = league.lineup;
  const game = thisGame(league);
  const secSum = el("section", "s-sum");
  const secMoves = el("section", "s-moves");
  const secLineup = el("section", "s-lineup");
  const secBench = el("section", "s-bench");

  const inRec = new Set(lu.slots.filter(function (s) { return s.recommended; }).map(function (s) { return s.recommended.id; }));
  const bench = league.roster.filter(function (p) { return !inRec.has(p.id); });

  const mc = matchupCard(league, game);
  if (mc) secSum.appendChild(mc);

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
    const box = el("div", "alert");
    box.appendChild(el("div", null, a.player + " is starting at " + a.slot + " and is " + flags.toLowerCase() + "."));
    backupLines(a).forEach(function (x) { box.appendChild(el("div", x.late ? "late" : "line", x.text)); });
    secSum.appendChild(box);
  });

  (lu.watch || []).forEach(function (w) {
    const first = (w.flags || [])[0];
    const word = first ? (FLAG_TEXT[first] || first).toLowerCase() : "flagged";
    let t = w.player + " (" + w.slot + ") is " + word + ".";
    const k = shortWhen(w.kickoff);
    if (k) t += " Kickoff " + k + ".";
    const note = el("div", "warn");
    note.appendChild(el("div", null, t));
    backupLines(w).forEach(function (x) { note.appendChild(el("div", x.late ? "late" : "line", x.text)); });
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

  const side = [secSum, secMoves];
  const rc = recapCard(league.recap);
  if (rc) {
    const secRecap = el("section", "s-recap");
    secRecap.appendChild(rc);
    side.push(secRecap);
  }
  side.push(sourcesSection(league, meta));

  const ub = game && isNum(game.winPct) && game.winPct < 40 ? upsideCard(upsideOptions(lu.slots, bench)) : null;
  secLineup.appendChild(el("h2", null, "Lineup by slot"));
  if (ub) secLineup.appendChild(ub);
  const slots = el("div", "card list");
  lu.slots.forEach(function (s) { slots.appendChild(slotGroup(s)); });
  secLineup.appendChild(slots);

  secBench.appendChild(el("h2", null, "Bench"));
  const bc = el("div", "card list");
  const split = benchSplit(bench);
  split.playable.forEach(function (p) { bc.appendChild(benchRow(p)); });
  if (split.out.length) {
    const fold = el("details", "fold outs");
    fold.appendChild(el("summary", null, "Show " + split.out.length + " out, on bye or on IR"));
    split.out.forEach(function (p) { fold.appendChild(benchRow(p)); });
    bc.appendChild(fold);
  }
  if (!bench.length) bc.appendChild(el("div", "slot muted", "Nobody on the bench."));
  secBench.appendChild(bc);

  return columns(side, [secLineup, secBench]);
}

// v2 waivers: free agents ranked by how much they raise your best lineup this week
// A gain under 1.0 is a small gain. Those rows are muted and labeled.
const SMALL_GAIN = 1;
const PICKUP_ROWS = 8;
function isSmallGain(x) { return isNum(x) && x < SMALL_GAIN; }
// A horizon counts only when it has weeks. The summary and the lists use the same rule.
function horizonOf(h) { return h && h.weeks && h.weeks.length ? h : null; }
// Marks a target row with a small gain. playerRow is not changed: the row gets a class and a label after it.
function markSmallGain(wrap, gain) {
  if (!isSmallGain(gain)) return;
  wrap.classList.add("small");
  wrap.appendChild(el("div", "smallgain", "small gain"));
}
function statBox(label, value) {
  const d = el("div");
  d.appendChild(el("span", "label", label));
  d.appendChild(el("b", null, value));
  return d;
}

// Best pickups: one row per player across the three lists, merged by player id. Pure, so a test can run it.
// Rest of season gain sorts the rows, this week's gain is the fallback. Lists that are not in use do not count.
function pickupRows(w) {
  const st = horizonOf(w.stretch), lt = horizonOf(w.longTerm);
  const lists = [["week", w.targets], ["stretch", st && st.targets], ["playoffs", lt && lt.targets]];
  const byId = {}, order = [];
  lists.forEach(function (pair) {
    (pair[1] || []).forEach(function (t) {
      const id = String(t.player.id);
      if (!byId[id]) {
        byId[id] = {id: id, name: t.player.name, pos: t.player.pos || "", week: null, stretch: null, playoffs: null, ros: null, bid: null};
        order.push(id);
      }
      const r = byId[id];
      r[pair[0]] = isNum(t.gain) ? t.gain : null;
      if (r.ros === null && isNum(t.rosGain)) r.ros = t.rosGain;
      if (r.bid === null && isNum(t.bid)) r.bid = t.bid;
    });
  });
  function key(r) { return isNum(r.ros) ? r.ros : isNum(r.week) ? r.week : -Infinity; }
  return order.map(function (id) { return byId[id]; }).sort(function (a, b) {
    const ka = key(a), kb = key(b);
    if (ka !== kb) return kb > ka ? 1 : -1;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  }).slice(0, PICKUP_ROWS);
}

// The Best pickups table. Stretch and playoff columns only exist when that horizon is in use.
// Rest of season only shows when some row has it. The bid column only shows in FAAB leagues.
function pickupsCard(w) {
  const st = horizonOf(w.stretch), lt = horizonOf(w.longTerm);
  const rows = pickupRows(w);
  const card = el("div", "card tablecard");
  if (!rows.length) {
    card.appendChild(el("div", "slot", "No free agent beats your lineup in these lists."));
    return card;
  }
  const cols = [{label: "This week", key: "week"}];
  if (st) cols.push({label: "Stretch", key: "stretch", wide: true});
  if (lt) cols.push({label: "Playoffs", key: "playoffs", wide: true});
  if (rows.some(function (r) { return isNum(r.ros); })) cols.push({label: "Rest of season", key: "ros"});
  if (w.faab) cols.push({label: "FAAB bid", key: "bid", money: true});
  const t = el("table", "pickups");
  const hr = el("tr");
  hr.appendChild(el("th", null, "Player"));
  cols.forEach(function (c) { hr.appendChild(el("th", c.wide ? "pk-wide" : null, c.label)); });
  const thead = el("thead");
  thead.appendChild(hr);
  t.appendChild(thead);
  const tb = el("tbody");
  rows.forEach(function (r) {
    const tr = el("tr");
    const name = el("td", "pk-name");
    name.appendChild(document.createTextNode(r.name));
    if (r.pos) name.appendChild(el("span", "pk-pos", r.pos));
    tr.appendChild(name);
    cols.forEach(function (c) {
      const v = r[c.key];
      const cls = [];
      if (c.wide) cls.push("pk-wide");
      if (c.money) cls.push("pk-bid");
      else if (isSmallGain(v)) cls.push("small");
      const txt = !isNum(v) ? "" : c.money ? "$" + v : signed(v);
      tr.appendChild(el("td", cls.join(" "), txt));
    });
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  card.appendChild(t);
  return card;
}

// FAAB budget and the most any team in the league has left. Only in FAAB leagues.
function faabCard(faab) {
  const c = el("div", "card");
  const sum = el("div", "summary");
  if (isNum(faab.left)) sum.appendChild(statBox("FAAB left", "$" + faab.left + (isNum(faab.budget) ? " of $" + faab.budget : "")));
  if (isNum(faab.leagueMaxLeft)) sum.appendChild(statBox("Most left in the league", "$" + faab.leagueMaxLeft));
  c.appendChild(sum);
  c.appendChild(el("div", "muted faabnote", "Bids are a rough guide, not tested against real bids. Bigger rest of season gain means a bigger share of what you have left, capped at 40 percent."));
  return c;
}

function renderWaivers(league, meta) {
  const w = league.waivers;
  const secSum = el("section", "s-sum");
  const secDrop = el("section", "s-moves");
  const secTargets = el("section", "s-lineup");
  const secPos = el("section", "s-bench");

  const head = el("div", "card");
  head.appendChild(el("div", "muted", league.league.teamName + ", week " + league.week));
  const best = w.targets.length ? w.targets[0] : null;
  const lt = horizonOf(w.longTerm);
  const bestLt = lt && lt.targets.length ? lt.targets[0] : null;
  const st = horizonOf(w.stretch);
  const bestSt = st && st.targets.length ? st.targets[0] : null;
  const sum = el("div", "summary");
  const thisWeek = best ? best.player.name + " " + signed(best.gain) + (isNum(best.bid) ? ", bid $" + best.bid : "") : "None";
  const rows = [["This week", thisWeek]];
  if (st) rows.push(["Stretch run", bestSt ? bestSt.player.name + " " + signed(bestSt.gain) : "None"]);
  rows.push(["Playoffs", lt ? (bestLt ? bestLt.player.name + " " + signed(bestLt.gain) : "None") : noFutureWeeks(league.seasonPhase)]);
  rows.forEach(function (x) { sum.appendChild(statBox(x[0], x[1])); });
  head.appendChild(sum);
  secSum.appendChild(head);
  if (w.faab) secSum.appendChild(faabCard(w.faab));
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

  secTargets.appendChild(el("h2", null, "Best pickups"));
  secTargets.appendChild(el("div", "muted", "Each player once across the lists below. Blank means the player is not in that list. Sorted by rest of season gain."));
  secTargets.appendChild(pickupsCard(w));

  secTargets.appendChild(el("h2", null, "Short term, week " + league.week));
  secTargets.appendChild(el("div", "muted", "Projected points each player adds to your best lineup this week. Two per position at most."));
  const tc = el("div", "card list");
  if (!w.targets.length) tc.appendChild(el("div", "slot", "No free agent beats your starters this week."));
  w.targets.forEach(function (t) {
    const wrap = el("div", "slot");
    const extra = "Starts at " + t.slot + (t.replaces ? " and sends " + t.replaces.name + " to the bench." : ".");
    wrap.appendChild(playerRow(t.player, { chip: t.player.pos, gain: t.gain, ppg: true, extra: extra }));
    markSmallGain(wrap, t.gain);
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
    markSmallGain(wrap, t.gain);
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
// Both sides of a trade. give and get are sets of ids. Pick ids (see pickId) are not players, so they are left out.
function tradeResult(td, mine, theirs, give, get) {
  const giveP = playerIdsOf(give), getP = playerIdsOf(get);
  const out = mine.filter(function (p) { return giveP.has(p.id); });
  const inn = theirs.filter(function (p) { return getP.has(p.id); });
  const myAfter = mine.filter(function (p) { return !giveP.has(p.id); }).concat(inn);
  const thAfter = theirs.filter(function (p) { return !getP.has(p.id); }).concat(out);
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

// ---------------------------------------------------------------- S4 trade helpers (the pure ones are tested in node)
const TRADE_POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"];
const TRADE_FILTERS = ["ALL", "QB", "RB", "WR", "TE"];
const PICK_PREFIX = "pick:";
// Picks share the give and get sets with players. Their ids start with PICK_PREFIX, which no player id does.
function pickId(p) { return PICK_PREFIX + [p.season, p.round, p.from || ""].join("|"); }
function isPickId(id) { return String(id).indexOf(PICK_PREFIX) === 0; }
// "2027 1st", plus the team it came from when it was traded
function pickLabel(p) { return p.label + (p.from ? " (from " + p.from + ")" : ""); }
function playerIdsOf(set) { return new Set(Array.from(set).filter(function (id) { return !isPickId(id); })); }
function countPlayers(set) { return Array.from(set).filter(function (id) { return !isPickId(id); }).length; }
// Sign class for a number in the result card and the sticky bar. Zero is neutral
function signClass(x) { return x > 0 ? "pos" : x < 0 ? "neg" : ""; }

// The standings row for a team name, or null. Standings is null on ESPN until its sync carries it.
function standingFor(standings, name) {
  if (!standings || !standings.teams) return null;
  return standings.teams.filter(function (t) { return t.name === name; })[0] || null;
}
function myStanding(standings) {
  if (!standings || !standings.teams) return null;
  return standings.teams.filter(function (t) { return t.isMine; })[0] || null;
}
// "100% playoffs", "under 1% playoffs", "38% playoffs"
function playoffText(x) {
  if (!isNum(x)) return null;
  return (x >= 99.95 ? "100%" : x > 0 && x < 0.5 ? "under 1%" : Math.round(x) + "%") + " playoffs";
}
// "Olav é Trois · seed 3 · 100% playoffs". Just the name when there is no standings row for the team
function partnerText(standings, name) {
  const t = standingFor(standings, name);
  if (!t) return name;
  return [name, isNum(t.seed) ? "seed " + t.seed : null, playoffText(t.playoffPct)].filter(Boolean).join(" · ");
}
// A rival is top 4 or ahead of you in the standings, and gains more from the trade than you do
function helpsRival(partnerSeed, mySeed, myGain, theirGain) {
  if (!isNum(partnerSeed) || !isNum(myGain) || !isNum(theirGain)) return false;
  const ahead = partnerSeed <= 4 || (isNum(mySeed) && partnerSeed < mySeed);
  return ahead && theirGain > myGain;
}
// Ideas with the same partner, the same players back and the same gains become one entry.
// variants keeps the original ideas in order. Tapping the entry opens variants[0].
function mergeIdeas(ideas) {
  const groups = [], seen = {};
  ideas.forEach(function (i) {
    const key = JSON.stringify([i.team, i.get.slice().sort(), i.myGain, i.theirGain]);
    if (!seen[key]) {
      seen[key] = { team: i.team, get: i.get, myGain: i.myGain, theirGain: i.theirGain, variants: [] };
      groups.push(seen[key]);
    }
    seen[key].variants.push(i);
  });
  return groups;
}
// Players in position order (QB, RB, WR, TE, K, DEF, then any other position), best rate first inside each group
function groupByPosition(players) {
  const byPos = {}, others = [];
  players.forEach(function (p) {
    const pos = p.pos || "Other";
    if (!byPos[pos]) {
      byPos[pos] = [];
      if (TRADE_POS_ORDER.indexOf(pos) < 0) others.push(pos);
    }
    byPos[pos].push(p);
  });
  return TRADE_POS_ORDER.concat(others).filter(function (pos) { return byPos[pos]; }).map(function (pos) {
    const ps = byPos[pos].slice().sort(function (a, b) {
      return (b.rate || 0) - (a.rate || 0) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    return { pos: pos, players: ps };
  });
}
// An idea shows under a position when one of the players it brings back plays there. byId is keyed team|id
function ideaHasPos(i, pos, byId) {
  return pos === "ALL" || i.get.some(function (id) { const p = byId[i.team + "|" + id]; return !!p && p.pos === pos; });
}
// The empty ideas line, with the threshold the build used
function noIdeasText(minGain) {
  return isNum(minGain) ? "No one for one trade adds at least " + minGain.toFixed(1) + " points for you and helps them too. Try the builder below."
    : "No one for one trade helps both teams right now. Try the builder below.";
}
// "Weakest spots: RB, TE", or "" when the team has no needs
function needsNote(needs, prefix) {
  return needs && needs.length ? prefix + needs.join(", ") : "";
}
function positionFilter(state, rerender) {
  const box = el("div", "posfilter");
  box.setAttribute("role", "group");
  box.setAttribute("aria-label", "Filter ideas by position");
  TRADE_FILTERS.forEach(function (f) {
    const b = el("button", "posbtn", f === "ALL" ? "All" : f);
    b.type = "button";
    b.setAttribute("aria-pressed", String(state.pos === f));
    b.addEventListener("click", function () { state.pos = f; rerender(); });
    box.appendChild(b);
  });
  return box;
}
// One row in a builder list: a checkbox, the chip, the name with badges, and an optional line
function tickRow(id, chosen, chipLabel, name, badges, sub, onChange) {
  const row = el("label", "pick");
  const cb = el("input");
  cb.type = "checkbox";
  cb.checked = chosen.has(id);
  cb.addEventListener("change", function () {
    if (cb.checked) chosen.add(id); else chosen.delete(id);
    onChange();
  });
  row.appendChild(cb);
  row.appendChild(chipNode(chipLabel));
  const body = el("div", "pbody");
  const nm = el("div", "pname");
  nm.appendChild(el("span", "name", name));
  badges.forEach(function (n) { nm.appendChild(n); });
  body.appendChild(nm);
  if (sub) body.appendChild(el("div", "psub", sub));
  row.appendChild(body);
  return row;
}

function renderTrade(league, meta, td, state, rerender) {
  const rosters = td.rosters;
  const myRoster = rosters.filter(function (r) { return r.isMine; })[0];
  const mine = myRoster.players;
  const others = rosters.filter(function (r) { return !r.isMine; });
  if (!state.team || !others.some(function (r) { return r.name === state.team; })) {
    state.team = td.ideas.length ? td.ideas[0].team : others[0].name;
    state.give = new Set(); state.get = new Set();
  }
  if (!state.pos) state.pos = "ALL";
  const partner = others.filter(function (r) { return r.name === state.team; })[0];
  const stW = td.stretchWeeks || [], poW = td.playoffWeeks || td.weeks;
  const byId = {};
  rosters.forEach(function (r) { r.players.forEach(function (p) { byId[r.name + "|" + p.id] = p; }); });
  const standings = league.standings || null;
  const mySeed = (myStanding(standings) || {}).seed;
  const myPicks = myRoster.picks || [], theirPicks = partner.picks || [];

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

  // One idea entry. Tapping it opens the first variant in the builder
  function ideaRow(g) {
    const first = g.variants[0];
    const giveText = g.variants.map(function (v) {
      return v.give.map(function (id) { return byId[myRoster.name + "|" + id].name; }).join(", ");
    }).join(" or ");
    const getText = g.get.map(function (id) { return byId[g.team + "|" + id].name; }).join(", ");
    const posText = function (team, ids) { return ids.map(function (id) { return byId[team + "|" + id].pos; }).join("/"); };
    const b = el("button", "idea");
    b.type = "button";
    const top = el("div", "pname");
    top.appendChild(el("span", "name", "Give " + giveText + " for " + getText));
    if (g.variants.some(function (v) { return v.youthFlag; })) top.appendChild(el("span", "badge warn", "Younger out"));
    const rival = standingFor(standings, g.team);
    if (helpsRival(rival ? rival.seed : null, mySeed, g.myGain, g.theirGain)) {
      const rv = el("span", "badge warn", "Helps a rival");
      rv.title = "They gain more than you and they are ahead of you in the standings.";
      top.appendChild(rv);
    }
    b.appendChild(top);
    b.appendChild(el("div", "psub", partnerText(standings, g.team) + " · " + posText(myRoster.name, first.give) + " for " + posText(g.team, g.get)));
    const split = isNum(first.stretchGain) && stW.length ? " (stretch " + signed(first.stretchGain) + ", playoffs " + signed(first.playoffGain) + ")" : "";
    const line = el("div", "extra muted-extra", "You " + signed(g.myGain) + split + ", they " + signed(g.theirGain) + " over the rest of the season. ");
    line.appendChild(el("span", first.thisWeek < 0 ? "neg" : "", "This week " + signed(first.thisWeek) + " for you."));
    b.appendChild(line);
    if (g.variants.length > 1) b.appendChild(el("div", "psub", g.variants.length + " ways to make this. Tap to open the first."));
    b.addEventListener("click", function () {
      state.team = g.team; state.give = new Set(first.give); state.get = new Set(first.get); state.scroll = true;
      rerender();
    });
    const wrap = el("div", "slot");
    wrap.appendChild(b);
    return wrap;
  }

  // Ideas
  const secIdeas = el("section", "s-lineup");
  secIdeas.appendChild(el("h2", null, "Trade ideas"));
  secIdeas.appendChild(el("div", "muted", "One for one trades that make both lineups better over the rest of the season. Tap one to open it below."));
  if (td.ideas.length >= 4) secIdeas.appendChild(positionFilter(state, rerender));
  const shown = td.ideas.filter(function (i) { return ideaHasPos(i, state.pos, byId); });
  const ic = el("div", "card list");
  if (!td.ideas.length) ic.appendChild(el("div", "slot", noIdeasText(td.minIdeaGain)));
  else if (!shown.length) ic.appendChild(el("div", "slot", "No ideas bring back a " + state.pos + " right now. Tap All to see every idea."));
  mergeIdeas(shown).forEach(function (g) { ic.appendChild(ideaRow(g)); });
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
  if (standingFor(standings, partner.name)) secBuild.appendChild(el("div", "muted aside", partnerText(standings, partner.name)));

  function compute() { return tradeResult(td, mine, partner.players, state.give, state.get); }

  // The result card. Ticking a box redraws only this card and the sticky bar, so focus and scroll stay put
  function resultCard(res) {
    const card = el("div", "card result");
    card.setAttribute("aria-live", "polite");
    if (!state.give.size && !state.get.size) {
      card.appendChild(el("div", "muted", "Tick players or picks to give and to get. The result updates as you go."));
      return card;
    }
    const rs = el("div", "summary");
    [["You, rest of season", res.myGain], ["They, rest of season", res.theirGain], ["You, this week", res.thisWeek]].forEach(function (x) {
      const d = el("div");
      d.appendChild(el("span", "label", x[0]));
      d.appendChild(el("b", "num " + signClass(x[1]), signed(x[1])));
      rs.appendChild(d);
    });
    card.appendChild(rs);
    if (res.weeks.length) {
      const part = function (ws) { return Math.round(res.weeks.filter(function (x) { return ws.indexOf(x.week) >= 0; }).reduce(function (a, x) { return a + x.gain; }, 0) * 10) / 10; };
      if (stW.length) card.appendChild(el("div", "psub", "You: stretch run " + signed(part(stW)) + " · playoffs " + signed(part(poW))));
      card.appendChild(el("div", "psub", res.weeks.map(function (x) { return "W" + x.week + " " + signed(x.gain); }).join(" · ")));
    }
    let verdict;
    if (res.myGain > 0 && res.theirGain > 0) verdict = "Both teams get better. A fair offer.";
    else if (res.myGain > 0) verdict = "You win this one. They lose " + Math.abs(res.theirGain).toFixed(1) + ", so expect a no.";
    else if (res.theirGain > 0) verdict = "This helps them more than you.";
    else verdict = "Neither lineup gets better.";
    card.appendChild(el("div", "extra" + (res.myGain > 0 && res.theirGain > 0 ? "" : " muted-extra"), verdict));
    const givePicks = myPicks.filter(function (p) { return state.give.has(pickId(p)); });
    const getPicks = theirPicks.filter(function (p) { return state.get.has(pickId(p)); });
    if (givePicks.length || getPicks.length) {
      const parts = [];
      if (givePicks.length) parts.push("you give " + givePicks.map(function (p) { return pickLabel(p); }).join(", "));
      if (getPicks.length) parts.push("you get " + getPicks.map(function (p) { return pickLabel(p); }).join(", "));
      card.appendChild(el("div", "psub", "Plus picks: " + parts.join(" · ")));
      card.appendChild(el("div", "muted", "Picks are not scored."));
    }
    // Roster room counts players only. Picks take no roster spot
    const diff = countPlayers(state.get) - countPlayers(state.give);
    if (diff > 0) card.appendChild(el("div", "note", "You get " + diff + " more than you give. Make room on your roster."));
    if (diff < 0) card.appendChild(el("div", "note", "They get " + (-diff) + " more than they give. They need roster room."));
    const yo = youngest(res.out), yi = youngest(res.inn);
    if (td.dynasty && yo !== null && yi !== null && yi - yo >= 4) card.appendChild(el("div", "note", "Dynasty: the youngest player you give is " + (yi - yo) + " years younger than anyone you get."));
    return card;
  }

  // Sticky result bar, phones only (style.css S4). It lives inside the builder, so a redraw removes it with the panel
  const bar = el("div", "tbar");
  bar.setAttribute("aria-live", "polite");
  let inView = !("IntersectionObserver" in window);   // without the observer the bar follows the ticks alone
  let lastRes = compute();
  function paintBar(res) {
    bar.replaceChildren();
    [["You", res.myGain], ["They", res.theirGain], ["This week", res.thisWeek]].forEach(function (x, k) {
      if (k) bar.appendChild(el("span", "sep", "·"));
      bar.appendChild(el("span", signClass(x[1]), x[0] + " " + signed(x[1])));
    });
    bar.hidden = !(inView && (state.give.size || state.get.size));
  }
  let rc = resultCard(lastRes);
  secBuild.appendChild(rc);
  secBuild.appendChild(bar);
  paintBar(lastRes);
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(function (entries) {
      if (!secBuild.isConnected) { io.disconnect(); return; }   // the panel was redrawn
      inView = entries[entries.length - 1].isIntersecting;
      paintBar(lastRes);
    });
    io.observe(secBuild);
  }

  function refresh() {
    lastRes = compute();
    const next = resultCard(lastRes);
    rc.replaceWith(next);
    rc = next;
    paintBar(lastRes);
  }

  // A builder list: groups by position, then the picks group when the team has picks
  function pickList(title, note, players, picks, chosen) {
    const box = el("div", "plist");
    box.appendChild(el("h3", null, title));
    if (note) box.appendChild(el("div", "muted", note));
    const card = el("div", "card list");
    groupByPosition(players).forEach(function (g) {
      const grp = el("div", "pgrp");
      grp.appendChild(el("div", "pghead", g.pos));
      g.players.forEach(function (p) {
        grp.appendChild(tickRow(p.id, chosen, POSITIONS.indexOf(p.pos) >= 0 ? p.pos : "BN", p.name, badgeNodes(p), tradePlayerLine(p, td.dynasty), refresh));
      });
      card.appendChild(grp);
    });
    if (picks.length) {
      const grp = el("div", "pgrp");
      grp.appendChild(el("div", "pghead", "Picks"));
      picks.forEach(function (p) { grp.appendChild(tickRow(pickId(p), chosen, "PICK", pickLabel(p), [], null, refresh)); });
      card.appendChild(grp);
    }
    box.appendChild(card);
    return box;
  }
  const lists = el("div", "plists");
  lists.append(
    pickList("You give", needsNote(myRoster.needs, "Your weakest spots: "), mine, myPicks, state.give),
    pickList("You get from " + partner.name, needsNote(partner.needs, "Weakest spots: "), partner.players, theirPicks, state.get));
  secBuild.appendChild(lists);

  return columns([secSum, sourcesSection(league, meta)], [secIdeas, secBuild]);
}

// ---------------------------------------------------------------- v4 standings and playoff odds
function pct(x) { return isNum(x) ? (x >= 99.95 ? "100%" : x > 0 && x < 0.5 ? "under 1%" : Math.round(x) + "%") : "n/a"; }
function record(t) { return t.wins + "-" + t.losses + (t.ties ? "-" + t.ties : ""); }

// The current-week game is the one that carries ifWin and ifLose. Null when no game has them.
function currentGame(st) {
  return st.myGames.filter(function (g) { return isNum(g.ifWin) && isNum(g.ifLose); })[0] || null;
}
// "Playoff odds 81% with a win, 48% with a loss"
function oddsLine(g) {
  return "Playoff odds " + pct(g.ifWin) + " with a win, " + pct(g.ifLose) + " with a loss";
}
// "This week swings your odds by 33 points."
function swingLine(g) {
  const n = Math.round(g.ifWin - g.ifLose);
  return "This week swings your odds by " + n + (n === 1 ? " point." : " points.");
}

function renderStandings(league, meta) {
  const st = league.standings;
  const secSum = el("section", "s-sum");
  const secGames = el("section", "s-moves");
  const secTable = el("section", "s-lineup");
  if (!st) {
    const c = el("div", "card");
    c.appendChild(el("div", null, league.league.platform === "espn"
      ? "ESPN standings show up here once the roster sync starts saving them."
      : "Standings are not available for this league right now."));
    secSum.appendChild(c);
    return columns([secSum, sourcesSection(league, meta)], []);
  }
  const me = st.teams.filter(function (t) { return t.isMine; })[0];
  const cur = currentGame(st);
  const head = el("div", "card");
  head.appendChild(el("div", "muted", league.league.teamName + ", week " + league.week));
  const sm = el("div", "summary");
  [["Record", me ? record(me) : "n/a"], ["Playoffs", me ? pct(me.playoffPct) : "n/a"], ["Bye", me ? pct(me.byePct) : "n/a"]].forEach(function (x) {
    sm.appendChild(statBox(x[0], x[1]));
  });
  head.appendChild(sm);
  if (me) head.appendChild(el("div", "psub", "Seed " + me.seed + " now. Projected " + me.projWins.toFixed(1) + " wins, average finish seed " + me.avgSeed.toFixed(1) + "."));
  if (cur) head.appendChild(el("div", "psub", swingLine(cur)));
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
    if (g === cur) body.appendChild(el("div", "psub", oddsLine(g)));
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
  // Points stays on phones. Bye is the column that goes under 400px (see style.css)
  ["", "Team", "Record", "Points", "Playoffs", "Bye"].forEach(function (h, i) {
    hr.appendChild(el("th", (i > 1 ? "num" : "") + (i === 3 ? " pf" : "") + (i === 5 ? " bye" : ""), h));
  });
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
    tr.appendChild(el("td", "num bye", pct(r.byePct)));
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
// URL hash is #league or #league/view. Unknown leagues open the first one, unknown views open lineup.
function routeFromHash(hash, leagues) {
  const parts = String(hash || "").replace(/^#/, "").split("/");
  const i = Math.max(0, leagues.findIndex(function (l) { return l.league.key === parts[0]; }));
  return { league: i, view: resolveView(leagues[i], parts[1]) };
}
function hashFor(league, view) {
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

  function show(i, v) {
    const lg = leagues[i];
    const view = resolveView(lg, v);
    route.league = i;
    route.view = view;
    Array.prototype.forEach.call(tabs.children, function (b, j) {
      b.setAttribute("aria-selected", String(i === j));
      b.tabIndex = i === j ? 0 : -1;   // roving tabindex: only the selected tab is in the Tab order
    });
    panel.setAttribute("aria-labelledby", tabs.children[i].id);
    const body = view === "waivers" ? renderWaivers(lg, meta)
      : view === "standings" ? renderStandings(lg, meta)
      : view === "trade" ? tradeBody(i, lg)
      : renderLeague(lg, meta);
    const keepY = view === "trade" ? window.scrollY : 0;
    viewbar.replaceChildren();
    if (viewsFor(lg).length > 1) viewbar.appendChild(viewSwitch(lg, view, function (nv) { show(i, nv); }));
    panel.replaceChildren(body);
    setBarHeight();
    if (view === "trade") {
      const st = tradeState[lg.league.key];
      if (st && st.scroll) { st.scroll = false; const bld = document.getElementById("builder"); if (bld) bld.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); }
      else window.scrollTo(0, keepY);
    }
    history.replaceState(null, "", hashFor(lg, view));
  }
  leagues.forEach(function (l) {
    const b = el("button", "tab");
    b.type = "button";
    b.id = "tab-" + l.league.key;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-controls", "panel");
    b.appendChild(el("span", "tname", l.league.name));
    b.appendChild(el("span", "gain" + (l.lineup.gain === 0 ? " zero" : ""), signed(l.lineup.gain)));
    b.addEventListener("click", function () { show(leagues.indexOf(l), route.view); });
    tabs.appendChild(b);
  });
  function fromHash() {
    const r = routeFromHash(location.hash, leagues);
    show(r.league, r.view);
  }
  // League tablist keys. Focus follows the arrow, so the tab that gets focus is the one that opens.
  tabs.addEventListener("keydown", function (e) {
    const cur = Array.prototype.indexOf.call(tabs.children, e.target);
    const j = nextTabIndex(cur, e.key, leagues.length);
    if (j < 0) return;
    e.preventDefault();
    tabs.children[j].focus();
    show(j, route.view);
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
