"use strict";

// Reads only data/build/. Every string from the data goes in with textContent, never as HTML.
const TZ = "America/Chicago";
const WHEN = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const FLAG_TEXT = {
  BYE: "Bye week", OUT: "Out", IR: "Injured reserve", DOUBTFUL: "Doubtful", QUESTIONABLE: "Questionable",
  SUSPENDED: "Suspended", INACTIVE: "Inactive",
};
const HARD_FLAGS = new Set(["BYE", "OUT", "IR", "SUSPENDED", "INACTIVE"]);
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
function when(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? WHEN.format(d) : "never";
}
function num(x) { return x === null || x === undefined ? "n/a" : x.toFixed(1); }
function signed(x) { return (x > 0 ? "+" : "") + x.toFixed(1); }

function badges(flags) {
  const box = el("div", "badges");
  (flags || []).forEach(function (f) {
    box.appendChild(el("span", "badge" + (HARD_FLAGS.has(f) ? " out" : ""), FLAG_TEXT[f] || f));
  });
  return box;
}

function gameLine(p) {
  if ((p.flags || []).indexOf("BYE") >= 0) return "Bye week";
  const g = p.game;
  if (!g) return "No game info";
  const parts = [(g.home ? "vs " : "at ") + g.opp];
  if (g.kickoff) parts.push(when(g.kickoff));
  if (g.implied !== null) parts.push("team total " + g.implied.toFixed(1));
  if (g.spread !== null) parts.push("spread " + (g.spread > 0 ? "+" : "") + g.spread.toFixed(1));
  return parts.join(", ");
}

function pickCard(p, cls, label) {
  const card = el("div", "pick " + cls);
  card.appendChild(el("div", "label", label));
  if (!p) {
    card.appendChild(el("div", "name", "Empty slot"));
    return card;
  }
  const row = el("div", "row");
  const nm = el("span", "name", p.name);
  const pts = el("span", "pts", p.eligible ? num(p.points) : "0.0");
  row.append(nm, pts);
  card.appendChild(row);
  card.appendChild(el("div", "sub", p.pos + " " + (p.team || "FA") +
    (p.floor !== null && p.floor !== undefined ? ", range " + p.floor.toFixed(1) + " to " + p.ceiling.toFixed(1) : "")));
  card.appendChild(el("div", "sub", gameLine(p)));
  card.appendChild(badges(p.flags));
  return card;
}

function stale(meta, s) { return !s.ok || s.stale; }

function sourcesTable(league, meta) {
  const t = el("table", "sources");
  Object.keys(league.sources).forEach(function (k) {
    const s = league.sources[k];
    const tr = el("tr");
    tr.appendChild(el("td", null, SOURCE_TEXT[k] || k));
    const td = el("td");
    let txt = "Updated " + when(s.lastUpdated);
    if (k === "espn_rosters" && meta.espnRosters) txt = "Synced " + when(meta.espnRosters.syncedAt);
    td.appendChild(document.createTextNode(txt));
    const isStale = k === "espn_rosters" && meta.espnRosters ? meta.espnRosters.stale : stale(meta, s);
    if (isStale) td.appendChild(el("span", "stale", s.lastUpdated ? "  Stale" : "  Missing"));
    tr.appendChild(td);
    t.appendChild(tr);
  });
  return t;
}

function renderLeague(league, meta) {
  const root = document.createDocumentFragment();
  const lu = league.lineup;

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
  root.appendChild(head);

  const rosterStale = league.league.platform === "espn" && meta.espnRosters && meta.espnRosters.stale;
  if (rosterStale) root.appendChild(el("div", "warn", "The ESPN roster sync is more than 4 days old. Lineups may be out of date. Ask Claude to sync ESPN."));
  const staleSrc = Object.keys(league.sources).filter(function (k) { return k !== "espn_rosters" && stale(meta, league.sources[k]); });
  if (staleSrc.length) root.appendChild(el("div", "warn", "Stale data: " + staleSrc.map(function (k) { return SOURCE_TEXT[k] || k; }).join(", ") + ". Using the last good pull."));

  lu.alerts.forEach(function (a) {
    const flags = a.flags.map(function (f) { return FLAG_TEXT[f] || f; }).join(", ");
    root.appendChild(el("div", "alert", a.player + " is starting at " + a.slot + " and is " + flags.toLowerCase() + "."));
  });

  root.appendChild(el("h2", null, "Moves"));
  const moves = el("div", "card");
  if (!lu.moves.length) moves.appendChild(el("div", null, "No changes. Your lineup is already the best one."));
  lu.moves.forEach(function (m) {
    let t;
    if (m.in && m.out) t = "Start " + m.in.name + " over " + m.out.name + " at " + m.slot + ". " + signed(m.gain);
    else if (m.out) t = "Remove " + m.out.name + " from " + m.slot + ". No eligible replacement. " + signed(m.gain);
    else t = "Start " + m.in.name + " at " + m.slot + ". " + signed(m.gain);
    moves.appendChild(el("div", "move", t));
  });
  root.appendChild(moves);

  root.appendChild(el("h2", null, "Lineup by slot"));
  const slots = el("div", "card");
  lu.slots.forEach(function (s) {
    const row = el("div", "slot");
    row.appendChild(el("div", "slotname", s.slot));
    const picks = el("div", "picks");
    picks.appendChild(pickCard(s.current, "cur" + (s.changed ? " changed" : ""), "Now"));
    if (s.changed) picks.appendChild(pickCard(s.recommended, "rec", "Start"));
    else picks.appendChild(el("div", "keep", "Keep"));
    row.appendChild(picks);
    slots.appendChild(row);
  });
  root.appendChild(slots);

  const inRec = new Set(lu.slots.filter(function (s) { return s.recommended; }).map(function (s) { return s.recommended.id; }));
  const bench = league.roster.filter(function (p) { return !inRec.has(p.id); });
  root.appendChild(el("h2", null, "Bench"));
  const bc = el("div", "card bench");
  bench.forEach(function (p) {
    const card = pickCard(p, "", p.slot === "IR" ? "Injured reserve" : "Bench");
    bc.appendChild(card);
  });
  root.appendChild(bc);

  root.appendChild(el("h2", null, "Data sources"));
  const sc = el("div", "card");
  sc.appendChild(sourcesTable(league, meta));
  root.appendChild(sc);
  return root;
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
    panel.replaceChildren(renderLeague(leagues[i], meta));
    history.replaceState(null, "", "#" + leagues[i].league.key);
  }
  leagues.forEach(function (l, i) {
    const b = el("button", "tab", l.league.name);
    b.setAttribute("role", "tab");
    const g = el("span", "gain" + (l.lineup.gain === 0 ? " zero" : ""), signed(l.lineup.gain));
    b.appendChild(g);
    b.addEventListener("click", function () { show(i); });
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
