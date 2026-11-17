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

  const sub = el("div", "psub", (p.pos || "") + " " + (p.team || "FA") + " · " + gameText(p));
  const ctx = contextText(p);
  if (ctx) sub.appendChild(el("span", "ctx", " · " + ctx));
  body.appendChild(sub);
  if (p.injuryNotes && NOTE_FLAGS.some(function (f) { return hasFlag(p, f); })) {
    body.appendChild(el("div", "note", p.injuryNotes));
  }

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

function stale(meta, s) { return !s.ok || s.stale; }

function sourcesTable(league, meta) {
  const t = el("table", "sources");
  Object.keys(league.sources).forEach(function (k) {
    const s = league.sources[k];
    const tr = el("tr");
    tr.appendChild(el("td", null, SOURCE_TEXT[k] || k));
    const td = el("td");
    let txt = "Updated " + stamp(s.lastUpdated);
    if (k === "espn_rosters" && meta.espnRosters) txt = "Synced " + stamp(meta.espnRosters.syncedAt);
    td.appendChild(document.createTextNode(txt));
    const isStale = k === "espn_rosters" && meta.espnRosters ? meta.espnRosters.stale : stale(meta, s);
    if (isStale) td.appendChild(el("span", "stale", s.lastUpdated ? "  Stale" : "  Missing"));
    tr.appendChild(td);
    t.appendChild(tr);
  });
  return t;
}

function renderLeague(league, meta) {
  const lu = league.lineup;
  const secSum = el("section", "s-sum");
  const secMoves = el("section", "s-moves");
  const secLineup = el("section", "s-lineup");
  const secBench = el("section", "s-bench");
  const secSrc = el("section", "s-src");

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

  const isEspn = league.league.platform === "espn";
  const rosterStale = isEspn && meta.espnRosters && meta.espnRosters.stale;
  if (rosterStale) secSum.appendChild(el("div", "warn", "The ESPN roster sync is more than 4 days old. Lineups may be out of date. Ask Claude to sync ESPN."));
  if (isEspn && meta.espnRosters && meta.espnRosters.weekMismatch === true) {
    secSum.appendChild(el("div", "warn", "The ESPN roster file is from week " + meta.espnRosters.week + ". Ask Claude to sync ESPN."));
  }
  const staleSrc = Object.keys(league.sources).filter(function (k) { return k !== "espn_rosters" && stale(meta, league.sources[k]); });
  if (staleSrc.length) secSum.appendChild(el("div", "warn", "Stale data: " + staleSrc.map(function (k) { return SOURCE_TEXT[k] || k; }).join(", ") + ". Using the last good pull."));

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

  secSrc.appendChild(el("h2", null, "Data sources"));
  const sc = el("div", "card");
  sc.appendChild(sourcesTable(league, meta));
  secSrc.appendChild(sc);

  // Phone: one column in DOM order. Desktop: sidebar plus main column (see style.css)
  const cols = el("div", "cols");
  const side = el("div", "colA");
  side.append(secSum, secMoves, secSrc);
  const main = el("div", "colB");
  main.append(secLineup, secBench);
  cols.append(side, main);
  return cols;
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

  const tabs = document.getElementById("tabs");
  const panel = document.getElementById("panel");
  function show(i) {
    Array.prototype.forEach.call(tabs.children, function (b, j) { b.setAttribute("aria-selected", String(i === j)); });
    panel.setAttribute("aria-labelledby", tabs.children[i].id);
    panel.replaceChildren(renderLeague(leagues[i], meta));
    history.replaceState(null, "", "#" + leagues[i].league.key);
  }
  leagues.forEach(function (l) {
    const b = el("button", "tab");
    b.type = "button";
    b.id = "tab-" + l.league.key;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-controls", "panel");
    b.appendChild(el("span", "tname", l.league.name));
    b.appendChild(el("span", "gain" + (l.lineup.gain === 0 ? " zero" : ""), signed(l.lineup.gain)));
    b.addEventListener("click", function () { show(leagues.indexOf(l)); });
    tabs.appendChild(b);
  });
  function fromHash() {
    const want = leagues.findIndex(function (l) { return "#" + l.league.key === location.hash; });
    show(want >= 0 ? want : 0);
  }
  window.addEventListener("hashchange", fromHash);
  fromHash();
}

main();
