"use strict";
const pages = ["Command Center","AI Agents","Skills Library","Market Intelligence","Trading Terminal","Session Analytics","Strategy Lab","AI Memory","Risk Center","API & Integrations","Budget Center","Settings"];
const endpoints = {
  "AI Agents":"/autopilot/analyses","Skills Library":"/skills","Market Intelligence":"/news/events",
  "Trading Terminal":"/signals","Session Analytics":"/sessions","Strategy Lab":"/backtests",
  "AI Memory":"/memory","Risk Center":"/dashboard","API & Integrations":"/readiness","Budget Center":"/costs"
};
const nav = document.getElementById("navigation");
const liveContent = document.getElementById("content");
// During a refresh of the page already on screen, content points to an offscreen stage and the old content stays
// visible until the new one is complete: the page never collapses, blinks or jumps while data reloads.
let content = liveContent;
let loadedPage = null;
const notice = document.getElementById("notice");
let active = "Command Center";
let renderSequence = 0;
let L = null;
async function ensureLabels() {
  if (L) return L;
  try { L = await (await fetch("/labels.json", { cache: "no-store" })).json(); }
  catch { L = { roles: {}, roleHelp: {}, actions: {}, status: {}, severity: {}, relevance: {}, values: {}, events: {}, gates: {}, rationales: {}, rationalePatterns: [] }; }
  return L;
}
const fr = (table, key, fallback) => (typeof key === "string" && key) ? ((L?.[table] || {})[key] ?? fallback ?? key) : (fallback ?? "—");
const role = agent => fr("roles", agent);
const action = value => fr("actions", value);
function rationale(text) {
  if (typeof text !== "string" || !text) return "—";
  const known = L?.rationales?.[text];
  if (known) return known;
  for (const [pattern, replacement] of (L?.rationalePatterns || [])) {
    const match = new RegExp(pattern).exec(text);
    if (match) return replacement.replace(/\$(\d)/g, (_, n) => match[Number(n)] ?? "");
  }
  return text;
}
function when(iso) {
  const date = new Date(iso);
  return (typeof iso === "string" && !Number.isNaN(date.getTime())) ? date.toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC" : "—";
}
const labels = {
  "Command Center":"Vue d'ensemble", "AI Agents":"Agents IA", "Skills Library":"Compétences",
  "Market Intelligence":"Actualités et marché", "Trading Terminal":"Journal des signaux",
  "Session Analytics":"Sessions", "Strategy Lab":"Backtests", "AI Memory":"Mémoire collective",
  "Risk Center":"Gestion des risques", "API & Integrations":"Intégrations", "Budget Center":"Budget IA", "Settings":"Paramètres"
};
const explanations = {
  "AI Agents":"Les analystes IA (graphique, quantitatif, et veilleur pour l'or) donnent leur avis à chaque consultation ; le directeur tranche. Voici ce qu'ils ont dit, « attente » compris, puis ce que leurs avis ont donné.",
  "Skills Library":"Le catalogue décrit des méthodes de recherche (27 du cahier des charges et 7 propres aux indices synthétiques) ; leur présence n'atteste pas leur validation en conditions de marché.",
  "Market Intelligence":"Les données importées sont datées et peuvent être artificielles. Aucune surveillance mondiale en direct n'est active.",
  "Trading Terminal":"Décisions des agents et ordres automatiques. Cette interface n'envoie jamais d'ordre elle-même : seul le pilote le fait, uniquement en mode « démo automatique », sur le compte démo.",
  "Session Analytics":"Les sessions sont calculées à titre indicatif ; elles doivent être confirmées avec les horaires du courtier.",
  "Strategy Lab":"Les backtests locaux servent à vérifier le logiciel ; les exemples ne mesurent pas un rendement futur.",
  "AI Memory":"Les observations sont enregistrées pour analyse ; aucune stratégie n'est modifiée automatiquement.",
  "Risk Center":"L'arrêt des nouvelles entrées est actif par défaut et se lève seulement quand tu actives les ordres automatiques. Les limites de risque se règlent dans Paramètres.",
  "API & Integrations":"Cette page distingue la revue locale possible des conditions encore bloquantes pour les 14 jours en démo.",
  "Budget Center":"Quand les agents sont activés, chaque consultation de l'IA consomme du budget : la dépense réelle est mesurée ici. Un plafond peut être rétabli dans Paramètres."
};
function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = String(text);
  return item;
}
function append(parent, ...children) { children.forEach(c => parent.appendChild(c)); return parent; }
function value(input) { if (input === null || input === undefined || input === "") return "—"; if (typeof input === "boolean") return input ? "Oui" : "Non"; if (typeof input === "number") return Number.isFinite(input) ? input.toLocaleString("fr-FR",{maximumFractionDigits:3}) : "—"; if (Array.isArray(input)) return input.map(value).join(", ") || "—"; return String(input); }
function card(title) { const item=node("section","card"); append(item,node("h2","",title)); return item; }
function row(parts) { const item=node("div","row"); parts.forEach((p,i)=>append(item,node(i===0?"strong":"span",i===parts.length-1?"badge":"",value(p)))); return item; }
function empty(text) { return node("div","empty",text); }
function grid(kind,...items) { const result=node("div",`grid ${kind}`); append(result,...items); return result; }
function stat(label,number,detail) { const result=card(""); result.firstChild.remove(); append(result,node("div","label",label),node("div","metric",number),node("div","sub",detail)); return result; }
function info(text,warning=false) { return node("div",warning?"warn":"info",text); }
function labeled(container, values) { const section=node("div","stats"); for (const [label,actual] of Object.entries(values)) { const item=node("div","stat"); append(item,node("span","label",label.replaceAll("_"," ")),node("strong","",value(actual))); append(section,item); } append(container,section); }
function friendly(error) {
  const text = String(error && error.message ? error.message : error);
  if (text.includes("Operator authentication")) return "Clé opérateur manquante ou incorrecte : copie-la depuis la fenêtre noire ouverte par Lancer-Application.bat (elle change à chaque lancement) et colle-la dans le champ « Clé opérateur ».";
  if (text.startsWith("basket")) return "Réglage du panier refusé : le nombre de positions doit être entre 2 et 50, le gain cible entre 1 et 100 000 $, et les instruments une liste de noms.";
  if (text.includes("Confirmation phrase")) return "Phrase de confirmation absente ou fausse : recopie-la exactement.";
  return text;
}
async function get(path, options) { const response=await fetch(path,{cache:"no-store",...options}); const result=await response.json(); if(!response.ok) throw new Error(result.error || `HTTP ${response.status}`); return result; }
function freshness(snapshot) { if(!snapshot) return "Aucune cotation"; const time=Date.parse(snapshot.observed_at); if(!Number.isFinite(time)) return "Horodatage invalide"; const age=Math.round((Date.now()-time)/1000); return age < 0 ? "Horloge incohérente" : `${age} s depuis la clôture enregistrée`; }
let chartSymbol = null;

function svgEl(tag, attrs) { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, String(v)); return e; }
function setStyle(el, props) { if (el && el.style) Object.assign(el.style, props); }
const ACT_SHORT = { BUY: "ACHAT", SELL: "VENTE", WAIT: "ATTENTE" };
const FAMILY = { gold: "OR", volatility: "VOLATILITÉ", boom: "BOOM", crash: "CRASH", drift: "DRIFT" };
const STATUS_DOT = { ok: "live", no_new_bar: "live", halted: "warn", stale: "warn", waiting: "", data_error: "bad" };
const STATUS_TEXT = { ok: "analyse à jour", no_new_bar: "analyse à jour", halted: "annonce américaine : prudence", stale: "marché fermé ou données anciennes", waiting: "pas encore analysé", data_error: "données indisponibles" };
const tone = n => (typeof n === "number" ? (n > 0 ? "pos" : n < 0 ? "neg" : "") : "");
function signed(n, digits = 2) { return typeof n === "number" ? (n > 0 ? "+" : "") + n.toLocaleString("fr-FR", { maximumFractionDigits: digits }) : "—"; }
function tile(label, val, sub, kind, valueClass) {
  const item = node("div", `tile ${kind || ""}`);
  append(item, node("div", "t-label", label), node("div", `t-value ${valueClass || ""}`, val), node("div", "t-sub", sub || ""));
  return item;
}
function sparkline(values, up) {
  const svg = svgEl("svg", { viewBox: "0 0 200 54", class: "spark", preserveAspectRatio: "none", "aria-hidden": "true" });
  if (!Array.isArray(values) || values.length < 2) return svg;
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1) * 200).toFixed(1)},${(50 - (v - low) / span * 46).toFixed(1)}`);
  const color = up ? "#22c58b" : "#ef4444";
  svg.appendChild(svgEl("polygon", { points: `0,54 ${pts.join(" ")} 200,54`, fill: color }));
  svg.appendChild(svgEl("polyline", { points: pts.join(" "), stroke: color }));
  return svg;
}
function voteChip(label, vote) {
  const act = vote ? vote.action : null;
  const kind = act === "BUY" ? "buy" : act === "SELL" ? "sell" : act === "WAIT" ? "wait" : "";
  const mark = act === "BUY" ? "▲" : act === "SELL" ? "▼" : act === "WAIT" ? "•" : "–";
  const chip = node("span", `chip ${kind}`, `${label} ${mark}`);
  chip.title = act ? `${label} : ${action(act)} (${when(vote.at)})` : `${label} : pas encore d'avis`;
  return chip;
}
function instrumentCard(inst, selected, onPick) {
  const button = node("button", `inst${selected ? " selected" : ""}`);
  button.type = "button";
  const head = node("div", "i-head");
  const name = node("div", "i-name"); append(name, node("span", `dot ${STATUS_DOT[inst.status] ?? ""}`), node("span", "", inst.symbol));
  append(head, name, node("span", "tag", FAMILY[inst.family] || inst.family.toUpperCase()));
  const price = node("div", "i-price");
  append(price, node("strong", "", typeof inst.price === "number" ? inst.price.toLocaleString("fr-FR", { maximumFractionDigits: 3 }) : "—"),
    node("span", tone(inst.change_pct), typeof inst.change_pct === "number" ? `${signed(inst.change_pct, 2)} %` : ""));
  const chips = node("div", "chips");
  [["G", "graph"], ["Q", "quant"], ["N", "news"], ["Vote", "director"], ["IA", "ai_director"]].forEach(([label, key]) => {
    if (key === "news" && inst.family !== "gold") return;
    append(chips, voteChip(label, (inst.votes || {})[key]));
  });
  const foot = node("div", "i-foot");
  const real = (inst.real_positions || []).map(p => `${ACT_SHORT[p.side] || p.side} ${value(p.volume)} lot`).join(" · ");
  foot.textContent = `${STATUS_TEXT[inst.status] || inst.status} · ${inst.timeframe}${inst.session ? ` · ${fr("sessions", inst.session)}` : ""}` +
    (inst.shadow_open ? ` · ${inst.shadow_open} position(s) simulée(s)` : "") + (real ? ` · ORDRE DÉMO OUVERT : ${real}` : "");
  append(button, head, price, (inst.closes || []).length > 1 ? sparkline(inst.closes, (inst.change_pct || 0) >= 0) : node("div", "spark-empty", "en attente des premières bougies"), chips, foot);
  button.addEventListener("click", () => onPick(inst.symbol));
  return button;
}
function candleChart(history, symbols, onPick) {
  const candles = history.candles || [];
  const panel = card(`${history.symbol || "Instrument"} · bougies ${history.timeframe || ""}`);
  if (symbols.length) {
    const pick = node("div", "pick");
    symbols.forEach(s => { const b = node("button", s === history.symbol ? "on" : "", s); b.type = "button"; b.addEventListener("click", () => onPick(s)); pick.appendChild(b); });
    append(panel, pick);
  }
  if (candles.length < 2) { append(panel, empty("Aucune bougie enregistrée pour cet instrument : elles apparaissent quand les agents travaillent.")); return panel; }
  const W = 760, H = 300, left = 8, right = 62, top = 10, bottom = 22;
  const lo = Math.min(...candles.map(c => Number(c.low))), hi = Math.max(...candles.map(c => Number(c.high))), span = hi - lo || 1;
  const y = v => top + (hi - v) / span * (H - top - bottom);
  const step = (W - left - right) / candles.length, bodyW = Math.max(1.5, step * 0.62);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "candles", role: "img", "aria-label": "Bougies enregistrées de l'instrument choisi" });
  for (let k = 0; k <= 4; k++) {
    const v = hi - span * k / 4, yy = y(v);
    svg.appendChild(svgEl("line", { x1: left, x2: W - right, y1: yy, y2: yy, class: "gridline" }));
    const label = svgEl("text", { x: W - right + 6, y: yy + 3 }); label.textContent = v.toLocaleString("fr-FR", { maximumFractionDigits: 2 }); svg.appendChild(label);
  }
  candles.forEach((c, i) => {
    const x = left + step * i + step / 2, o = Number(c.open), cl = Number(c.close), upc = cl >= o, cls = upc ? "up" : "down";
    svg.appendChild(svgEl("line", { x1: x, x2: x, y1: y(Number(c.high)), y2: y(Number(c.low)), class: cls }));
    svg.appendChild(svgEl("rect", { x: x - bodyW / 2, y: Math.min(y(o), y(cl)), width: bodyW, height: Math.max(1, Math.abs(y(o) - y(cl))), class: cls }));
  });
  const last = Number(candles[candles.length - 1].close);
  svg.appendChild(svgEl("line", { x1: left, x2: W - right, y1: y(last), y2: y(last), class: "last" }));
  const tag = svgEl("text", { x: W - right + 6, y: y(last) - 4 }); tag.textContent = last.toLocaleString("fr-FR", { maximumFractionDigits: 3 }); svg.appendChild(tag);
  append(panel, svg, node("div", "sub", `${candles.length} bougies · ${history.source || ""} · dernière clôture : ${when(candles[candles.length - 1].closed_at)}`));
  return panel;
}
function eventLook(kind) {
  if (kind.includes("order_sent")) return ["▲", "ok"];
  if (kind.includes("order_closed")) return ["✓", "ok"];
  if (kind.includes("refused") || kind.includes("uncertain") || kind.includes("unprotected") || kind.startsWith("alert")) return ["!", "bad"];
  if (kind.includes("kill_switch")) return ["⛔", "bad"];
  if (kind.includes("opposite")) return ["⇄", "bad"];
  if (kind.includes("close_all") || kind.includes("close_requested")) return ["■", "bad"];
  if (kind.includes("mode_changed") || kind.includes("settings") || kind.includes("config")) return ["⚙", "info"];
  return ["•", ""];
}
function eventDetail(e) {
  let p = {}; try { p = JSON.parse(e.payload || "{}"); } catch (err) { p = {}; }
  if (e.kind === "autopilot.mode_changed") return `${fr("values", p.from)} → ${fr("values", p.to)}`;
  if (e.kind === "autopilot.order_refused") return `${p.symbol || ""} · ${fr("refusals", p.code)}`;
  if (e.kind === "autopilot.order_closed") return `${p.symbol || ""} · ${signed(p.profit)} $ · sortie : ${p.reason || "—"}`;
  if (e.kind === "autopilot.opposite_signal") return `${p.symbol || ""} · ${ACT_SHORT[p.signal] || p.signal} contre ${ACT_SHORT[p.position] || p.position} · ${POLICY_TEXT[p.policy] || p.policy} → ${CONFLICT_RESULT[p.action] || p.action}`;
  if (e.kind === "autopilot.close_all") return `${p.positions ?? 0} position(s)`;
  if (e.kind === "autopilot.order_sent") return `${p.symbol || ""} · ${ACT_SHORT[p.side] || p.side} · ${value(p.volume)} lot`;
  if (e.kind === "autopilot.error" || e.kind === "autopilot.data_error") return (p.message || p.error || "").slice(0, 90);
  return "";
}
function timelineCard(events) {
  const panel = card("Activité récente");
  if (!events.length) { append(panel, empty("Aucun événement important pour l'instant.")); return panel; }
  const list = node("ul", "timeline");
  events.slice(0, 10).forEach(e => {
    const [icon, kind] = eventLook(e.kind);
    const item = node("li"), body = node("div");
    append(body, node("div", "", fr("events", e.kind)));
    const detail = eventDetail(e);
    append(body, node("small", "", `${when(e.at)}${detail ? ` · ${detail}` : ""}`));
    append(item, node("span", `t-icon ${kind}`, icon), body);
    list.appendChild(item);
  });
  append(panel, list);
  return panel;
}
function barRow(label, text, stat, scale, badgeText) {
  const r = node("div", "row");
  append(r, node("strong", "", label));
  const bar = node("div", "mbar"); bar.appendChild(node("div", "zero"));
  if (stat && typeof stat.mean_r === "number") {
    const m = stat.mean_r, w = Math.min(50, Math.abs(m) / scale * 50), fill = node("div", "fill");
    setStyle(fill, { left: (m >= 0 ? 50 : 50 - w) + "%", width: w + "%", background: m >= 0 ? "var(--gain)" : "var(--loss)" });
    bar.appendChild(fill);
    if (Array.isArray(stat.mean_r_interval)) {
      const a = Math.max(0, Math.min(100, 50 + stat.mean_r_interval[0] / scale * 50)), b = Math.max(0, Math.min(100, 50 + stat.mean_r_interval[1] / scale * 50)), ci = node("div", "ci");
      setStyle(ci, { left: a + "%", width: Math.max(1, b - a) + "%" }); bar.appendChild(ci);
    }
  }
  append(r, bar, node("span", "rtext", text), node("span", "badge", badgeText));
  return r;
}
const barScale = stats => Math.max(0.5, ...Object.values(stats || {}).flatMap(s => [Math.abs(s.mean_r || 0), ...(s.mean_r_interval || []).map(Math.abs)]));
const armName = arm => fr("arms", arm);
const pct = x => (typeof x === "number" ? (Math.round(x * 1000) / 10).toLocaleString("fr-FR") + " %" : "—");
const num = x => (typeof x === "number" ? x.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) : "—");
const MODEL_NOTES = { "ran": "IA consultée", "not due": "IA : prochaine consultation pas encore due", "not configured": "IA non configurée" };
let pilotTarget = "observe";
function modelNote(text) {
  if (!text) return "";
  if (MODEL_NOTES[text]) return MODEL_NOTES[text];
  if (text.startsWith("models unavailable")) return text.includes("no model chosen") ? "IA indisponible : aucun modèle choisi dans les paramètres" : "IA indisponible : clé ou tarifs manquants (voir Intégrations)";
  if (text.startsWith("model not configured")) return "IA indisponible : modèle non choisi pour un des analystes";
  return text;
}
function updateModeBadge(pilot) {
  const badge = document.getElementById("mode-badge");
  if (badge) badge.textContent = pilot && pilot.mode === "demo_auto" ? "● DÉMO AUTOMATIQUE · ORDRES" : pilot && pilot.mode === "observe" ? "● OBSERVATION AUTOMATIQUE" : "● OBSERVATION";
  const demo = document.getElementById("demo-badge");
  if (demo && pilot) demo.textContent = pilot.alive && pilot.mode !== "off" ? "COMPTE DÉMO · AGENTS AU TRAVAIL" : "COMPTE DÉMO · AGENTS ARRÊTÉS";
  const sub = document.getElementById("subtitle");
  if (sub && pilot) sub.textContent = pilot.mode === "demo_auto" ? "Ordres automatiques sur le compte démo · aucun argent réel." : pilot.mode === "observe" ? "Analyse automatique sans ordre · compte démo en lecture." : "Compte démo uniquement · aucun argent réel.";
  const side = document.getElementById("side-status");
  if (side && pilot) side.textContent = pilot.kill_switch === false ? "ORDRES AUTOMATIQUES ACTIFS (DÉMO)" : "ARRÊT DES NOUVELLES ENTRÉES ACTIF";
}
function pilotCard(pilot) {
  const auto = pilot.mode === "demo_auto";
  const on = pilot.mode === "observe" || auto;
  const silent = on && !pilot.alive;
  const panel = card("Agents automatiques");
  const strip = node("div", "pilot-strip");
  append(strip, node("span", `dot ${on ? (silent ? "warn" : "live") : ""}`), node("strong", "", auto ? "DÉMO AUTOMATIQUE" : on ? "EN OBSERVATION" : "ARRÊTÉS"),
    node("span", "sub", `arrêt des nouvelles entrées : ${pilot.kill_switch ? "ACTIF" : "levé"}`),
    node("span", "sub", pilot.keep_awake ? "· Windows ne se met pas en veille tant que les agents travaillent" : on ? "· attention : la mise en veille de Windows arrêterait les agents" : ""));
  append(panel, strip);
  append(panel, info(auto && pilot.kill_switch
    ? "ARRÊT D'URGENCE ACTIF : le pilote analyse toujours, mais aucune nouvelle entrée n'est tentée. Les positions déjà ouvertes gardent leur stop et leur objectif chez le courtier et restent suivies. Pour reprendre, clique sur « Reprendre les ordres »."
    : auto
    ? (silent ? "Ordres automatiques activés mais aucun signe de vie récent : le serveur local a peut-être été arrêté. Les positions ouvertes gardent leur stop chez le courtier."
              : "Les agents travaillent ET envoient des ordres sur le compte DÉMO (jamais de l'argent réel) : un seul par instrument, avec stop et objectif chez le courtier, dans les limites de risque des paramètres. « Trading algo » doit rester allumé dans MetaTrader.")
    : on
    ? (silent ? "Les agents sont activés mais aucun signe de vie récent : le serveur local a peut-être été arrêté. Ils reprennent seuls dès qu'il redémarre."
              : "Les agents travaillent : à chaque nouvelle bougie ils analysent, et chaque avis est journalisé. Aucun ordre n'est envoyé ; des positions simulées mesurent ce que leurs avis auraient donné.")
    : "Les agents sont arrêtés. Activez-les : ils analysent chaque bougie, de jour comme de nuit, jusqu'à ce que vous les désactiviez.", silent));
  const actions = node("div", "pilot-actions");
  const toggle = node("button", on ? "danger" : "", on ? "Désactiver les agents" : "Activer les agents (observation)");
  toggle.type = "button";
  toggle.addEventListener("click", () => openPilotDialog(on ? "off" : "observe"));
  append(actions, toggle);
  const second = node("button", auto ? "danger" : "", auto ? "Repasser en observation (plus d'ordres)" : "Activer les ordres automatiques en démo");
  second.type = "button";
  second.disabled = !pilot.demo_auto_available;
  second.title = pilot.demo_auto_reason || "";
  second.addEventListener("click", () => openPilotDialog(auto ? "observe" : "demo_auto"));
  append(actions, second);
  if (auto && pilot.kill_switch) {
    const resume = node("button", "", "Reprendre les ordres (lever l'arrêt)");
    resume.type = "button";
    resume.addEventListener("click", () => openPilotDialog("demo_auto"));
    append(actions, resume);
  }
  append(panel, actions);
  const more = node("details", "more");
  append(more, node("summary", "", "Détails du pilote"));
  labeled(more, { cycles_terminés: pilot.cycles, décisions_du_jour: pilot.decisions_today, résultats_simulés_mesurés: pilot.shadow_outcomes, erreurs: pilot.errors, dépense_IA_usd: pilot.costs?.total_usd });
  Object.entries(pilot.last_cycle || {}).forEach(([symbol, cycle]) => append(more, row([symbol,
    `${when(cycle.bar_close)} · ${fr("sessions", cycle.session)}`,
    cycle.halt ? "PRUDENCE : ANNONCE AMÉRICAINE" : modelNote(cycle.models)])));
  if (pilot.last_error) append(more, info(`Dernière erreur : ${pilot.last_error}`, true));
  append(panel, more);
  return panel;
}
const DEMO_PHRASE = "ACTIVER LES ORDRES AUTOMATIQUES DEMO";
const CLOSE_PHRASE = "FERMER TOUTES LES POSITIONS DEMO";
function openPilotDialog(target) {
  pilotTarget = target;
  const titles = { observe: "Activer les agents (observation)", off: "Désactiver les agents", demo_auto: "Activer les ordres automatiques en démo", close_all: "Fermer toutes les positions" };
  const texts = {
    observe: "Les agents analyseront chaque nouvelle bougie en continu, jour et nuit, sans envoyer aucun ordre. Si des ordres automatiques étaient actifs, ils s'arrêtent : les positions déjà ouvertes gardent leur stop et leur objectif chez le courtier.",
    off: "Les agents s'arrêtent après le cycle en cours. Si des ordres automatiques étaient actifs, les nouvelles entrées s'arrêtent aussi ; les positions ouvertes gardent leur stop et leur objectif chez le courtier et restent suivies.",
    close_all: "Toutes les positions ouvertes par les agents sont fermées au prix du marché, avec leur gain ou leur perte du moment. L'arrêt des nouvelles entrées est ensuite activé pour que rien ne se rouvre aussitôt ; il se lève avec « Reprendre les ordres ». Les positions que tu as ouvertes toi-même ne sont pas touchées.",
    demo_auto: "Les agents enverront eux-mêmes des ordres sur le compte DÉMO, sans confirmation à chaque ordre : un seul par instrument, stop et objectif chez le courtier, limites de risque et de perte du jour des paramètres. « Trading algo » doit être allumé dans MetaTrader (ton geste). L'arrêt d'urgence bloque aussitôt les nouvelles entrées. Aucun argent réel."
  };
  document.getElementById("pilot-title").textContent = titles[target];
  document.getElementById("pilot-text").textContent = texts[target];
  const phrase = document.getElementById("pilot-phrase-label");
  phrase.hidden = target !== "demo_auto" && target !== "close_all";
  document.getElementById("pilot-phrase-hint").textContent = target === "close_all" ? CLOSE_PHRASE : DEMO_PHRASE;
  document.getElementById("pilot-phrase").value = "";
  document.getElementById("pilot-message").textContent = "";
  document.getElementById("pilot-dialog").showModal();
}
function perfBadge(item) {
  if (item.significantly_positive) return "RÉSULTAT SIGNIFICATIF";
  return item.small_sample ? "ÉCHANTILLON INSUFFISANT" : "NON SIGNIFICATIF";
}
function performanceCards(perf) {
  const out = [];
  const arms = card("Résultats simulés par méthode");
  const names = Object.keys(perf.arms || {});
  append(arms, info("Chaque avis « achat » ou « vente » ouvre une position simulée sur les vraies bougies suivantes (écart d'achat-vente inclus). R = gain ou perte exprimé en multiple du risque initial. Peu de positions ne prouvent rien : deux semaines servent de diagnostic."));
  if (!names.length) append(arms, empty("Aucune décision enregistrée. Activez les agents depuis la Vue d'ensemble."));
  names.forEach(arm => { const a = perf.arms[arm];
    append(arms, barRow(armName(arm), `${a.trades} position${a.trades > 1 ? "s" : ""} · R moyen ${num(a.mean_r)} · réussite ${pct(a.win_rate)} · abstention ${pct(a.abstention_rate)}${a.model_failures ? ` · ${a.model_failures} appels IA en échec` : ""}`, a, barScale(perf.arms), perfBadge(a))); });
  out.push(arms);
  const skills = card("Les compétences aident-elles ?");
  const agents = Object.entries(perf.skills_vs_plain || {});
  if (!agents.length) append(skills, empty("Pas encore de données : il faut des positions avec et sans compétences."));
  agents.forEach(([agent, d]) => append(skills, row([role(agent),
    `avec : R moyen ${num(d.mean_r_with)} (${d.n_with}) · sans : ${num(d.mean_r_without)} (${d.n_without})${d.difference_interval ? ` · écart ${num(d.difference)} [${num(d.difference_interval[0])} ; ${num(d.difference_interval[1])}]` : ""}`,
    d.clearly_helps ? "LES COMPÉTENCES AIDENT" : d.clearly_hurts ? "LES COMPÉTENCES NUISENT" : d.underpowered ? "TROP PEU DE DONNÉES" : "INCERTAIN"])));
  (perf.skill_effects || []).slice(0, 12).forEach(e => append(skills, row([e.skill,
    `avec ${e.n_with} positions (R ${num(e.mean_r_with)}) · sans ${e.n_without} (R ${num(e.mean_r_without)}) · écart ${num(e.difference)}`,
    e.clearly_helps ? "AIDE" : e.clearly_hurts ? "NUIT" : e.underpowered ? "TROP PEU DE DONNÉES" : "INCERTAIN"])));
  out.push(skills);
  const basketArms = Object.entries((perf.basket || {}).arms || {});
  if (basketArms.length) {
    const basketCard = card("Panier en simulation contre position seule");
    append(basketCard, info("Chaque avis d'achat ou de vente d'une méthode d'exécution ouvre aussi, sur les vraies bougies, un panier de positions identiques (mêmes stop et objectif que la position seule) qui se ferme en bloc quand son gain atteint la cible en dollars. Un seul panier à la fois par instrument. Le risque total du panier est celui d'une position. Simulation : aucun ordre."));
    basketArms.forEach(([name, b]) => { const p = b.paired || {};
      append(basketCard, row([`${armName(b.arm)} · panier de ${b.positions ?? "?"} à +${num(b.target_usd)} $`,
        `${b.trades} panier${b.trades > 1 ? "s" : ""} fermé${b.trades > 1 ? "s" : ""} (cible ${b.ended_on.target} · stop ${b.ended_on.stop} · délai ${b.ended_on.timeout}) · R moyen ${num(b.mean_r)} · ${num(b.usd_mean)} $ par panier · total ${num(b.usd_total)} $${b.still_open ? ` · ${b.still_open} en cours` : ""}` +
        (p.n ? ` · même décision, position seule : R moyen ${num(p.mean_r_single)} contre panier ${num(p.mean_r_basket)} (${p.n} paires)${p.difference_interval ? ` · écart ${num(p.difference)} [${num(p.difference_interval[0])} ; ${num(p.difference_interval[1])}]` : ""}` : ""),
        p.clearly_helps ? "LE PANIER FAIT MIEUX" : p.clearly_hurts ? "LE PANIER FAIT PIRE" : (p.underpowered || b.small_sample) ? "TROP PEU DE DONNÉES" : "INDISTINGUABLE"])); });
    out.push(basketCard);
  }
  const dir = perf.direction || { arms: {}, forced_vs_random: {}, observations: 0 };
  const direction = card("Qualité de la direction à horizon fixe");
  append(direction, info("Pour chaque avis d'achat ou de vente d'un cycle d'analyse, on mesure le mouvement du prix après un délai égal à l'intervalle entre deux consultations de l'IA, en distances de stop et après l'écart d'achat-vente. Sans position bloquée, ces observations sont bien plus nombreuses que les positions simulées."));
  const dirNames = Object.keys(dir.arms || {});
  if (!dirNames.length) append(direction, empty("Aucune observation mesurée pour l'instant (premiers résultats après un délai d'analyse)."));
  dirNames.forEach(arm => { const a = dir.arms[arm]; append(direction, barRow(armName(arm), `${a.trades} observation${a.trades > 1 ? "s" : ""} · mouvement moyen ${num(a.mean_r)} · direction juste ${pct(a.win_rate)}`, a, barScale(dir.arms), perfBadge(a))); });
  out.push(direction);
  const forced = card("La direction forcée bat-elle la pièce de monnaie ?");
  append(forced, info("Variante de recherche : l'analyste doit choisir achat ou vente à chaque cycle. On la compare à un tirage à pile ou face, la référence du hasard. Un résultat n'est crédible qu'avec au moins 30 positions et un écart dont l'intervalle reste au-dessus de zéro."));
  const duels = Object.entries((dir.observations && Object.values(dir.forced_vs_random || {}).some(d => d.n_without > 0)) ? dir.forced_vs_random : (perf.forced_vs_random || {}));
  if (!duels.length) append(forced, empty("Pas encore de données."));
  duels.forEach(([agent, d]) => append(forced, row([role(agent),
    `forcée : R moyen ${num(d.mean_r_with)} (${d.n_with}) · pile ou face : ${num(d.mean_r_without)} (${d.n_without})${d.difference_interval ? ` · écart ${num(d.difference)} [${num(d.difference_interval[0])} ; ${num(d.difference_interval[1])}]` : ""}`,
    d.clearly_helps ? "BAT LE HASARD" : d.clearly_hurts ? "PIRE QUE LE HASARD" : d.underpowered ? "TROP PEU DE DONNÉES" : "INDISTINGUABLE DU HASARD"])));
  out.push(forced);
  const useDir = dir.ai_director_vs && Object.keys(dir.ai_director_vs).length;
  const duel = useDir ? dir.ai_director_vs : (perf.ai_director_vs || {});
  const aiCard = card("Le directeur IA fait-il mieux que le vote ?");
  append(aiCard, info("Le directeur IA lit tous les rapports de la consultation (et un court historique pour l'or et les Drift Switch). On le compare au directeur par vote (deux analystes d'accord) et au pile ou face. Aucune avance n'est accordée : il faut au moins 30 observations et un intervalle au-dessus de zéro."));
  const duelRows = [["vs_vote", "contre le directeur par vote"], ["vs_coin", "contre le pile ou face"]];
  if (!Object.keys(duel).length) append(aiCard, empty("Pas encore de données."));
  duelRows.forEach(([key, label]) => { const d = duel[key]; if (!d) return;
    append(aiCard, row([`Directeur IA ${label}`, `directeur IA : ${num(d.mean_r_with)} (${d.n_with}) · autre : ${num(d.mean_r_without)} (${d.n_without})${d.difference_interval ? ` · écart ${num(d.difference)} [${num(d.difference_interval[0])} ; ${num(d.difference_interval[1])}]` : ""}`,
      d.clearly_helps ? "MEILLEUR" : d.clearly_hurts ? "PIRE" : d.underpowered ? "TROP PEU DE DONNÉES" : "INDISTINGUABLE"])); });
  out.push(aiCard);
  return out;
}
function sessionCard(perf) {
  const panel = card("Résultats simulés par session et par méthode");
  const cells = perf.by_arm_session || [];
  if (!cells.length) append(panel, empty("Aucune position mesurée pour l'instant."));
  cells.forEach(c => append(panel, row([`${fr("sessions", c.session)} · ${armName(c.arm)}`, `${c.trades} positions · R moyen ${num(c.mean_r)} · réussite ${pct(c.win_rate)}`, perfBadge(c)])));
  return panel;
}
function ordersCard(data) {
  const panel = card("Ordres automatiques en démo");
  const s = data.summary || {};
  append(panel, info(`Compte DÉMO uniquement. Ordres clôturés : ${s.closed ?? 0} · résultat net : ${num(s.net_profit)} $ · réussite : ${pct(s.win_rate)}. Chaque ordre est relié à une décision journalisée et protégé par un stop chez le courtier.`));
  const list = data.orders || [];
  if (!list.length) append(panel, empty("Aucun ordre pour l'instant : les ordres partent seulement en mode « démo automatique »."));
  list.forEach(o => { let why = ""; try { const code = JSON.parse(o.detail || "{}").code; if (code) why = ` · ${fr("refusals", code)}`; } catch (e) { why = ""; }
    append(panel, row([`${when(o.opened_at)} · ${o.symbol}`, `${armName(o.arm)} · ${action(o.side)}${o.volume ? ` · lot ${o.volume}` : ""}${o.close_reason ? ` · sortie : ${o.close_reason}` : ""}`,
      `${fr("orderStates", o.state, o.state)}${typeof o.profit === "number" ? ` · ${num(o.profit)} $` : ""}${why}`])); });
  return panel;
}
function decisionCard(list) {
  const panel = card("Décisions des agents automatiques (achats, ventes et pannes IA)");
  if (!Array.isArray(list) || !list.length) append(panel, empty("Aucune décision d'achat ou de vente pour l'instant."));
  else list.forEach(d => append(panel, row([`${when(d.at)} · ${d.symbol}`, `${armName(d.arm)} · ${rationale(d.rationale)}${d.skills?.length ? ` · compétences : ${d.skills.map(s => s.split("@")[0]).join(", ")}` : ""}`,
    `${action(d.action)} · ${d.result ? `${fr("outcomes", d.result)} (${num(d.r_multiple)} R)` : fr("decisionStatus", d.status)}`])));
  return panel;
}

function duration(seconds) {
  if (typeof seconds !== "number") return "—";
  const s = Math.abs(Math.round(seconds)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return (seconds < 0 ? "dépassé de " : "") + (h ? `${h} h ${String(m).padStart(2, "0")} min` : `${m} min`);
}
const POLICY_TEXT = { ignore: "ignorer (la position garde son stop)", close_if_profit: "fermer si la position est en gain", close: "fermer la position" };
const CONFLICT_RESULT = { ignored: "ignoré", closed: "position fermée" };
function positionCount(list) { return list.reduce((n, p) => n + (p.basket ? p.basket.members : 1), 0); }
function positionsCard(data) {
  const list = data.positions || [];
  const panel = card("Positions ouvertes");
  const head = node("div", "pos-head");
  const total = typeof data.floating_profit === "number" ? `${signed(data.floating_profit)} $` : "—";
  const left = node("div"); append(left, node("div", `big ${tone(data.floating_profit)}`, list.length ? `${positionCount(list)} position${positionCount(list) > 1 ? "s" : ""}${list.some(p => p.basket) ? ` dont ${list.filter(p => p.basket).length} panier${list.filter(p => p.basket).length > 1 ? "s" : ""}` : ""} · ${total}` : "Aucune position ouverte"),
    node("div", "sub", list.length ? "Résultat en cours (non encore réalisé), lu chez le courtier toutes les 10 secondes. Chaque position a son stop et son objectif chez le courtier." : "Les ordres automatiques apparaissent ici dès qu'ils sont pris."));
  const close = node("button", "danger wide", data.close_requested ? "Fermeture en cours…" : "Fermer toutes les positions");
  close.type = "button"; close.disabled = !list.length || !!data.close_requested;
  close.addEventListener("click", () => openPilotDialog("close_all"));
  append(head, left, close); append(panel, head);
  list.forEach(p => {
    const item = node("div", "posn");
    const who = node("div", "who"); append(who, node("strong", "", p.symbol), node("span", `chip ${p.side === "BUY" ? "buy" : "sell"}`, `${ACT_SHORT[p.side] || p.side} · ${value(p.volume)} lot${p.basket ? ` · panier de ${p.basket.members}` : ""}`));
    const first = node("div"); append(first, who, node("small", "", `${armName(p.arm)} · ouverte ${when(p.opened_at)}`));
    const price = node("div"); append(price, node("div", "big", typeof p.price_current === "number" ? num(p.price_current) : "—"), node("small", "", `entrée ${num(p.entry)}${p.live ? "" : " · cours en attente"}`));
    const gain = node("div"); append(gain, node("div", `big ${tone(p.profit)}`, typeof p.profit === "number" ? `${signed(p.profit)} $` : "—"), node("small", "", p.basket ? `panier : ${signed(p.basket.total)} $ sur +${num(p.basket.target_usd)} $ visés${p.basket.realised ? ` (dont ${signed(p.basket.realised)} $ déjà encaissés)` : ""}` : "résultat en cours"));
    const levels = node("div"); append(levels, node("div", "levels", `stop ${num(p.stop_loss)} · objectif ${num(p.take_profit)}`),
      node("small", "", p.seconds_left === null || p.seconds_left === undefined ? "pas de délai de fermeture" : (p.seconds_left < 0 ? `délai dépassé de ${duration(-p.seconds_left)} : fermeture au prochain contrôle` : `fermeture automatique dans ${duration(p.seconds_left)}`)));
    if (typeof p.seconds_left === "number" && p.max_age_seconds) { const bar = node("div", "left"), fill = node("i"); setStyle(fill, { width: Math.max(0, Math.min(100, 100 - p.seconds_left / p.max_age_seconds * 100)) + "%" }); bar.appendChild(fill); levels.appendChild(bar); }
    append(item, first, price, gain, levels);
    if (p.conflict) {
      const c = p.conflict;
      append(item, node("div", "conflict", `Signal contraire reçu : ${ACT_SHORT[c.signal] || c.signal} (${armName(c.arm)}, ${when(c.at)}) alors que cette position est ${ACT_SHORT[c.position_side] || c.position_side}. Règle choisie : ${POLICY_TEXT[c.policy] || c.policy} → ${CONFLICT_RESULT[c.action] || c.action}. Aucune position inverse n'est ouverte en même temps.`));
    }
    append(panel, item);
  });
  return panel;
}
async function dashboard(sequence) {
  const query = chartSymbol ? `?symbol=${encodeURIComponent(chartSymbol)}` : "";
  const [data, overview, history, pilot, positions] = await Promise.all([get("/dashboard"), get("/market/overview").catch(() => ({ instruments: [] })),
    get("/market/candles" + query), get("/autopilot").catch(() => null), get("/autopilot/positions").catch(() => ({ positions: [] }))]);
  if (sequence !== renderSequence) return;
  if (pilot) updateModeBadge(pilot);
  const account = data.account, net = pilot && pilot.orders ? pilot.orders.net_profit : null;
  const delta = account ? account.equity - account.balance : null;
  const working = pilot && pilot.alive && pilot.mode !== "off";
  const tiles = node("div", "tiles");
  append(tiles,
    tile(`Capital du compte démo${account && account.currency ? ` (${account.currency})` : ""}`, account ? num(account.balance) : "—", account ? `lu à ${when(account.at)}` : "visible quand le serveur lit MetaTrader"),
    tile(`Équité du compte${account && account.currency ? ` (${account.currency})` : ""}`, account ? num(account.equity) : "—", delta === null ? "—" : `${signed(delta)} ${account.currency || ""} de positions ouvertes`, delta > 0 ? "gain" : delta < 0 ? "loss" : "", tone(delta)),
    tile("Résultat des ordres démo", net === null ? "—" : `${signed(net)} $`, pilot && pilot.orders && pilot.orders.closed ? `${pilot.orders.closed} ordres clôturés` : "aucun ordre clôturé", net > 0 ? "gain" : net < 0 ? "loss" : "", tone(net)),
    tile("Coût IA du jour", `${num(data.costs?.today_usd)} $`, `total depuis le début : ${num(data.costs?.total_usd)} $`),
    tile("Agents", working ? (pilot.mode === "demo_auto" ? "ORDRES" : "AU TRAVAIL") : "ARRÊTÉS", working ? `${pilot.cycles} cycles · ${pilot.decisions_today} décisions aujourd'hui` : "activez-les ci-dessous", working ? "gain" : "idle"));
  append(content, tiles);
  if (pilot) append(content, pilotCard(pilot));
  append(content, positionsCard(positions));
  const instruments = overview.instruments || [];
  const pick = symbol => { chartSymbol = symbol; render("Command Center"); };
  const heading = node("div", "section-title"); append(heading, node("h2", "", "Instruments suivis"), node("span", "", "un clic affiche ses bougies"));
  append(content, heading);
  const grid2 = node("div", "inst-grid");
  instruments.forEach(inst => grid2.appendChild(instrumentCard(inst, inst.symbol === history.symbol, pick)));
  if (!instruments.length) append(grid2, empty("Aucun instrument configuré (voir Paramètres)."));
  append(content, grid2);
  const agents = card("Dernier avis de chaque rôle");
  [["graph", "01"], ["news", "02"], ["quant", "03"], ["risk", "04"], ["director", "05"], ["ai_director", "06"]].forEach(([id, n]) => {
    const vote = (data.latest_votes || {})[id];
    const title = id === "ai_director" ? armName("ai:director") : id === "director" ? "Directeur par vote" : role(id);
    const help = id === "ai_director" ? "Lit tous les rapports de la consultation" : id === "director" ? "Vote : deux analystes d'accord" : fr("roleHelp", id);
    const item = node("div", "vote"), left = node("div");
    append(left, node("div", "", `${n} · ${title}`), node("small", "", vote ? `${help} · ${vote.symbol}` : help));
    const kind = vote ? (vote.action === "BUY" ? "buy" : vote.action === "SELL" ? "sell" : "wait") : "";
    append(item, left, node("span", `chip ${kind}`, id === "risk" ? "VETO PAR LE CODE" : vote ? ACT_SHORT[vote.action] || vote.action : "AUCUN CYCLE"));
    append(agents, item);
  });
  append(content, grid("two", candleChart(history, history.symbols || [], pick), agents));
  const risk = card("Contrôle opérationnel");
  labeled(risk, { arrêt_des_nouvelles_entrées: data.kill_switch ? "Actif" : "Levé (ordres automatiques possibles)", courtier: fr("values", data.broker), mode: fr("values", data.mode), compte_réel: "Interdit" });
  append(content, grid("two", timelineCard(data.events || []), risk));
}
function renderList(title, list, fields, missing) {
  const panel=card(title);
  if(!Array.isArray(list)||!list.length)append(panel,empty(missing));
  else list.slice(0,100).forEach(entry=>append(panel,row(fields.map(field=>entry[field]))));
  append(content,panel);
}
async function generic(page,sequence) {
  const data=await get(endpoints[page]);
  if (sequence !== renderSequence) return;
  if(explanations[page])append(content,info(explanations[page]));
  if(page==="Skills Library") { append(content,info("Catalogue versionné : spécifications, pas des stratégies validées."));renderList(`Compétences (${data.length})`,data.map(e=>({...e,roleName:role(e.owner)+(e.scope==="synthetic"?" · indices synthétiques":""),stateLabel:"spécification"})),["name","roleName","stateLabel"],"Catalogue vide"); }
  if(page==="AI Agents") {
    renderList("Dernières analyses des agents",data.map(a=>({who:`${when(a.at)} · ${a.symbol}`,why:`${armName(a.arm)} · ${rationale(a.rationale)}`,act:action(a.action)})),["who","why","act"],"Aucune analyse : activez les agents depuis la Vue d'ensemble.");
    const perf=await get("/autopilot/performance").catch(()=>null);if(sequence!==renderSequence)return;
    if(perf)performanceCards(perf).forEach(panel=>append(content,panel));
  }
  if(page==="Market Intelligence") { append(content,info("Les événements d'exemple sont synthétiques. Aucune veille mondiale continue n'est active.",true));renderList("Articles reçus",data.map(item=>({headline:item.headline,label:`${item.source} · ${when(item.published_at)} · ${fr("status",item.status)} · gravité ${fr("severity",item.severity)} · pertinence ${fr("relevance",item.relevance,"non classée")}`})),["headline","label"],"Aucun article reçu");const releases=await get("/calendar/events").catch(()=>[]);if(sequence!==renderSequence)return;renderList("Calendrier économique importé",releases.map(r=>({when:when(r.scheduled_at),country:r.country,event:r.event,imp:`importance ${r.importance}/3`})),["when","country","event","imp"],"Aucun événement de calendrier importé"); }
  if(page==="Trading Terminal") { renderList("Signaux liés aux ordres (un par ordre tenté)",data.map(s=>({sym:`${s.symbol} · ${fr("status",s.status)}`,why:rationale(s.rationale),act:action(s.action)})),["sym","why","act"],"Aucun ordre tenté pour l'instant");
    const decisions=await get("/autopilot/decisions").catch(()=>[]);if(sequence!==renderSequence)return;
    append(content,decisionCard(decisions));
    const orders=await get("/autopilot/orders").catch(()=>null);if(sequence!==renderSequence)return;
    if(orders)append(content,ordersCard(orders)); }
  if(page==="AI Memory") renderList("Désaccords, pannes et recommandations",data,["cause","recommendation"],"Aucune mémoire enregistrée");
  if(page==="Strategy Lab") {
    append(content,info("Les chiffres de l’exemple synthétique ne mesurent aucune performance de marché.",true));
    const panel=card("Backtests locaux"); if(!data.length)append(panel,empty("Aucun backtest enregistré"));
    else data.forEach(item=>append(panel,row([item.dataset,`${value(item.result?.metrics?.trades)} trades`,"RECHERCHE UNIQUEMENT"])));append(content,panel);
    const studies=await get("/synthetic/reports").catch(()=>[]);if(sequence!==renderSequence)return;
    append(content,info("Indices synthétiques : statistiques descriptives hors ligne. Elles ne prédisent rien, ne produisent aucun signal et ne sont reliées à aucun ordre.",true));
    const study=card("Études d'indices synthétiques");if(!studies.length)append(study,empty("Aucune étude enregistrée (commande analyze-synthetic --save)"));
    else studies.forEach(item=>{const r=item.report||{};const f=r.all?.absolute_jump_frequency;append(study,row([`${item.symbol} · ${fr("families",item.family)}`,`${value(r.all?.observations)} bougies · ${value(r.all?.absolute_jump_count)} sauts brusques (${f===null||f===undefined?"—":(Math.round(f*10000)/100).toLocaleString("fr-FR")} %) : ${value(r.all?.up_jump_count)} à la hausse, ${value(r.all?.down_jump_count)} à la baisse${typeof r.execution_cost?.spread_as_share_of_a_typical_bar_move==="number"?` · écart d'achat-vente ≈ ${r.execution_cost.spread_as_share_of_a_typical_bar_move.toLocaleString("fr-FR",{maximumFractionDigits:2})} × le mouvement typique d'une bougie`:""}`,r.statistically_sufficient?"ÉCHANTILLON SUFFISANT":"ÉCHANTILLON INSUFFISANT"]));});
    append(content,study);
  }
  if(page==="Session Analytics") {
    const panel=card("Sessions indicatives");labeled(panel,{session_principale:fr("sessions",data.primary),sessions_actives:(data.active||[]).map(s=>fr("sessions",s)),horaires_courtier_vérifiés:data.broker_hours_verified,évalué_le:when(data.as_of)});append(content,panel);
    const perf=await get("/autopilot/performance").catch(()=>null);if(sequence!==renderSequence)return;
    if(perf)append(content,sessionCard(perf));
    const ann=await get("/announcements").catch(()=>null);if(sequence!==renderSequence)return;
    if(ann){
      append(content,info("Dans la fenêtre indiquée autour de chaque annonce américaine programmée, aucune nouvelle entrée n'est autorisée. Les annonces imprévues ne figurent dans aucun calendrier : elles sont couvertes par l'arrêt sur actualité critique et la limite d'écart."));
      if(ann.blackout)append(content,info(`Fenêtre de prudence active : ${fr("usKinds",ann.blackout.kind)}, jusqu'à ${when(ann.blackout.until_utc)}.`,true));
      if(Object.values(ann.coverage||{}).some(c=>c.status!=="ok"))append(content,info("Le calendrier des annonces expire bientôt ou est périmé. Mettre à jour avec « refresh-us-events » (voir la documentation).",true));
      const list=card("Annonces américaines programmées");
      (ann.upcoming||[]).forEach(e=>{const d=Math.round((new Date(e.at_utc).getTime()-Date.now())/86400000);append(list,row([`${fr("usKinds",e.kind)} · ${when(e.at_utc)}`,`Fenêtre de prudence : ${when(e.window_start_utc)} → ${when(e.window_end_utc)}`,d<=0?"AUJOURD'HUI":`DANS ${d} J`]));});
      if(!(ann.upcoming||[]).length)append(list,empty("Aucune annonce à venir dans le calendrier"));append(content,list);
      const valid=card("Validité du calendrier");Object.entries(ann.coverage||{}).forEach(([kind,c])=>append(valid,row([fr("usKinds",kind),`dernière date connue : ${value(c.last_event)}`,fr("coverage",c.status).toUpperCase()])));append(content,valid);
    }
  }
  if(page==="Budget Center") {const panel=card("Coûts IA enregistrés");labeled(panel,{dépense_totale_usd:data.total_usd,dépense_du_jour_usd:data.today_usd,plafond_actif:data.cap_enabled,plafond_quotidien_usd:data.daily_limit_usd,plafond_expérience_usd:data.experiment_limit_usd,appels:data.calls,nouveaux_appels_bloqués:data.new_model_calls_blocked});if(data.cap_enabled===false)append(panel,info("Aucun plafond : les agents ne s'arrêtent jamais faute de budget. La dépense reste mesurée ici et peut être limitée à tout moment dans les paramètres."));append(content,panel);}
  if(page==="Risk Center") {const panel=card("Contrôle du risque");labeled(panel,{arrêt_des_nouvelles_entrées:data.kill_switch?"ACTIF":"INCONNU",courtier:fr("values",data.broker),mode:fr("values",data.mode),ordres_à_vérifier_à_la_main:data.pending_order_intents,trading_réel_autorisé:data.live_trading});append(panel,info("Le bouton ARRÊT D’URGENCE (en haut de chaque écran) bloque aussitôt toute nouvelle entrée du pilote ; les positions déjà ouvertes gardent leur stop et leur objectif chez le courtier et restent suivies."));append(content,panel);}
  if(page==="API & Integrations") {
    const panel=card("Préparation des intégrations");labeled(panel,{revue_locale_prête:data.ready_for_local_review,démo_14_jours_prête:data.ready_for_14_day_demo,mode_d_exécution:fr("values",data.execution_mode),arrêt_des_nouvelles_entrées:data.kill_switch});
    if(data.credentials)labeled(panel,{compte_MT5_démo_renseigné:data.credentials.mt5_demo_account_configured,clé_OpenAI_présente:data.credentials.openai_key_present,clé_NewsAPI_présente:data.credentials.newsapi_key_present,clé_calendrier_présente:data.credentials.tradingeconomics_key_present,connexions_vérifiées:data.credentials.verified});
    append(panel,info("Une clé présente ne prouve pas que la connexion fonctionne.",true));append(content,panel);
    const gates=card(`Conditions encore à remplir (${(data.blocked_gates||[]).length})`);
    (data.blocked_gates||[]).forEach(id=>{const g=(L?.gates||{})[id]||[id,""];append(gates,row([g[0],g[1]]));});append(content,gates);
  }
}
function checkLabel(text,checked) {const label=node("label","check");const box=node("input");box.type="checkbox";box.checked=!!checked;append(label,box,node("span","",text));return [label,box];}
function formLabel(text,type,valueNow) {const label=node("label","",text);const input=node("input");input.type=type;input.value=valueNow??"";append(label,input);return [label,input];}
function settingsPage() {
  append(content,info("Les clés des fournisseurs restent côté serveur. La clé opérateur saisie ici n’est pas enregistrée."));
  const panel=card("Configuration versionnée");const form=node("div","form");
  const [keyLabel,keyInput]=formLabel("Clé opérateur locale","password","");keyInput.autocomplete="off";
  const load=node("button","","Charger les paramètres");const status=node("div","form-note");const controls=node("div","form");
  load.addEventListener("click",async()=>{
    controls.replaceChildren();status.textContent="";
    try{
      const data=await get("/settings",{headers:{"X-Operator-Key":keyInput.value}});
      const settings=data.settings;const inputs={};
      const models=node("div","form-group");
      ["graph","news","quant","risk","director"].forEach(agent=>{const [label,input]=formLabel(`Modèle · ${agent}`,"text",settings.model_by_agent?.[agent]||"");inputs[agent]=input;append(models,label);});
      append(controls,models);
      const budgets=node("div","form-group");
      for(const [field,label] of [["daily_ai_limit_usd","Budget IA quotidien (USD)"],["experiment_ai_limit_usd","Budget expérience (USD)"],["quote_max_age_seconds","Fraîcheur cotation (s)"]]){
        const [box,input]=formLabel(label,"number",settings[field]);input.step="0.01";input.min="0";inputs[field]=input;append(budgets,box);
      }
      append(controls,budgets);
      const capLabel=node("label","","Limiter le budget IA (décoché : aucun plafond, la dépense reste mesurée)");const capBox=node("input");capBox.type="checkbox";capBox.checked=settings.ai_cap_enabled!==false;append(capLabel,capBox);append(controls,capLabel);
      const risk=settings.risk||{};const riskInputs={};
      const riskGroup=node("div","form-group");
      for(const [field,label,scale] of [["risk_per_trade","Risque par position (% du capital)",100],["max_daily_loss","Perte maximale par jour (% du capital)",100],["max_open_risk","Risque ouvert cumulé maximal (%)",100],["max_positions","Positions simultanées maximales",1],["max_spread","Écart d'achat-vente maximal (unités de prix ; 0 = automatique : 20 % du stop)",1],["fixed_lot","Lot fixe (vide = calculé d'après le risque)",1],["commission_per_lot","Commission aller-retour par lot",1],["slippage_ticks","Glissement supposé (ticks)",1]]){
        const raw=risk[field];const shown=(raw===null||raw===undefined)?"":Math.round(raw*scale*10000)/10000;
        const [box,input]=formLabel(label,"number",shown);input.step="any";input.min="0";riskInputs[field]=[input,scale];append(riskGroup,box);
      }
      append(controls,node("div","form-note","Niveau de risque : valeurs initiales du cahier des charges 0,5 % par position, 2 % par jour, 1 % cumulé, 2 positions. Ces réglages s'appliquent aux prochains ordres démo ; la simulation des agents mesure en R et n'en dépend pas."));
      append(controls,riskGroup);
      const save=node("button","",`Enregistrer la version ${data.version+1}`);
      save.addEventListener("click",async()=>{
        const payload={mode:"observation",model_by_agent:{},daily_ai_limit_usd:Number(inputs.daily_ai_limit_usd.value),experiment_ai_limit_usd:Number(inputs.experiment_ai_limit_usd.value),quote_max_age_seconds:Number(inputs.quote_max_age_seconds.value),ai_cap_enabled:capBox.checked,risk:{}};
        for(const [field,[input,scale]] of Object.entries(riskInputs)){payload.risk[field]=input.value.trim()===""?(field==="fixed_lot"?null:0):Number(input.value)/scale;}
        ["graph","news","quant","risk","director"].forEach(agent=>{if(inputs[agent].value.trim())payload.model_by_agent[agent]=inputs[agent].value.trim();});
        try{const saved=await get("/settings",{method:"PATCH",headers:{"X-Operator-Key":keyInput.value,"X-Operator-Name":"preview-local","Content-Type":"application/json"},body:JSON.stringify({settings:payload,expected_version:data.version})});status.textContent=`Version ${saved.version} enregistrée. Rechargez pour toute nouvelle modification.`;save.disabled=true;keyInput.value="";}catch(error){status.textContent=String(error);}
      });append(controls,save);status.textContent=`Version ${data.version} chargée · chaque enregistrement crée une nouvelle version`;
    }catch(error){status.textContent=String(error);}
  });append(form,keyLabel,load,status,controls);append(panel,form);append(content,panel);
  const pilotPanel=card("Réglages des agents automatiques");const pilotForm=node("div","form");const pilotNote=node("div","form-note");
  const [agentKeyLabel,agentKey]=formLabel("Clé opérateur (affichée dans la fenêtre noire)","password","");agentKey.autocomplete="off";
  keyInput.addEventListener("input",()=>{agentKey.value=keyInput.value;});agentKey.addEventListener("input",()=>{keyInput.value=agentKey.value;});
  append(pilotForm,agentKeyLabel);
  get("/autopilot").then(state=>{
    const cfg=state.config||{};const fields={};
    const group=node("div","form-group");
    // one tick box per instrument: ticked = analysed, unticked = left alone (open positions are still followed)
    const analysed=new Set(cfg.symbols||[]);const known=Array.isArray(state.known_symbols)&&state.known_symbols.length?state.known_symbols:[...analysed];
    const symbolBox=node("div","symbol-checks");append(symbolBox,node("div","label","Instruments analysés (décocher = ne plus analyser)"));
    const symbolList=node("div","pick");const checks=known.map(name=>{const l=node("label","check");const c=node("input");c.type="checkbox";c.checked=analysed.has(name);c.dataset.symbol=name;append(l,c,node("span","",name));append(symbolList,l);return c;});
    const [extraLabel,extra]=formLabel("Autre instrument (nom exact, séparés par des virgules)","text","");
    fields.symbols={get value(){return [...checks.filter(c=>c.checked).map(c=>c.dataset.symbol),...extra.value.split(",").map(s=>s.trim()).filter(Boolean)].join(",");}};
    append(symbolBox,symbolList,extraLabel);append(pilotForm,symbolBox);
    for(const [field,label,type] of [["timeframe","Durée des bougies (M1, M5, M15, M30, H1)","text"],["model_every_minutes","Consultation de l'IA toutes les (minutes)","number"],["horizon_bars","Durée maximale d'une position simulée (bougies)","number"],["stop_atr_multiple","Stop simulé (multiple de la volatilité ATR)","number"],["reward_multiple","Objectif simulé (multiple du risque)","number"],["skill_pack_size","Compétences données à chaque analyste","number"],["execution_arms","Méthodes dont les avis deviennent des ordres démo (séparées par des virgules ; ex. skills:director, forced:director, det:graph)","text"],["opposite_signal_policy","Signal contraire pendant qu'une position est ouverte : ignore, close_if_profit (fermer si en gain) ou close (fermer)","text"]]){
      const current=Array.isArray(cfg[field])?cfg[field].join(", "):cfg[field];const [box,input]=formLabel(label,type,current);if(type==="number")input.step="any";fields[field]=input;append(group,box);
    }
    // basket mode: several identical positions opened together and closed together at a money target
    const bk=cfg.basket||{};const basketBox=node("div","symbol-checks basket-box");
    append(basketBox,node("div","label","Mode panier (positions groupées, fermées ensemble à un gain cible)"),
      node("small","","Un panier ouvre plusieurs positions identiques en même temps, chacune avec son stop et son objectif comme d'habitude, et les ferme toutes quand leur total atteint le gain cible. Le risque total du panier est celui d'une position (partagé entre elles). Un seul panier à la fois par instrument. Compte démo uniquement."));
    const basketPick=node("div","pick");const basketOn=new Set(bk.symbols||[]);
    const basketChecks=known.map(name=>{const l=node("label","check");const c=node("input");c.type="checkbox";c.checked=basketOn.has(name);c.dataset.symbol=name;append(l,c,node("span","",name));append(basketPick,l);return c;});
    const [simLabel,simBox]=checkLabel("Panier simulé : comparer, sans aucun ordre, le panier à la position seule (page Agents IA)",bk.simulate!==false);
    const [realLabel,realBox]=checkLabel("Panier RÉEL sur le compte démo : remplace l'ordre simple sur les instruments cochés ci-dessus",!!bk.enabled);
    const basketFlags=node("div","pick");append(basketFlags,simLabel,realLabel);
    const [posLabel,posInput]=formLabel("Nombre de positions par panier (2 à 50)","number",bk.positions??20);
    const [tgtLabel,tgtInput]=formLabel("Gain cible du panier en dollars","number",bk.target_usd??50);tgtInput.step="any";
    const basketNums=node("div","form-group");append(basketNums,posLabel,tgtLabel);
    append(basketBox,node("div","label","Instruments du panier"),basketPick,basketFlags,basketNums);
    append(group,basketBox);
    const save=node("button","","Enregistrer les réglages des agents");
    save.addEventListener("click",async()=>{
      const patch={symbols:fields.symbols.value.split(",").map(s=>s.trim()).filter(Boolean),timeframe:fields.timeframe.value.trim(),execution_arms:fields.execution_arms.value.split(",").map(s=>s.trim()).filter(Boolean),opposite_signal_policy:fields.opposite_signal_policy.value.trim()};
      for(const f of ["model_every_minutes","horizon_bars","stop_atr_multiple","reward_multiple","skill_pack_size"])patch[f]=Number(fields[f].value);
      if(!patch.symbols.length){pilotNote.textContent="Coche au moins un instrument à analyser.";return;}
      patch.basket={symbols:basketChecks.filter(c=>c.checked).map(c=>c.dataset.symbol),positions:Number(posInput.value),target_usd:Number(tgtInput.value),simulate:simBox.checked,enabled:realBox.checked};
      if(patch.basket.enabled&&!bk.enabled){
        if(!patch.basket.symbols.length){pilotNote.textContent="Coche au moins un instrument pour le panier réel.";return;}
        if(typeof confirm==="function"&&!confirm(`Activer le panier RÉEL (compte démo) ? Chaque décision d'achat ou de vente sur ${patch.basket.symbols.join(", ")} ouvrira ${patch.basket.positions} positions, fermées ensemble à +${patch.basket.target_usd} $. Les ordres automatiques doivent aussi être activés.`))return;
      }
      try{await get("/autopilot/config",{method:"PATCH",headers:{"X-Operator-Key":agentKey.value||keyInput.value,"X-Operator-Name":"preview-local","Content-Type":"application/json"},body:JSON.stringify(patch)});pilotNote.textContent="Réglages enregistrés. Ils sont pris en compte au prochain cycle d'analyse.";}catch(error){pilotNote.textContent=friendly(error);}
    });
    append(pilotForm,group,save,pilotNote);
  }).catch(()=>append(pilotForm,empty("Réglages indisponibles : serveur local non joint.")));
  append(pilotPanel,pilotForm);append(content,pilotPanel);
}
async function render(page) {
  const sequence=++renderSequence;
  const refresh=page===loadedPage&&liveContent.children.length>0;
  active=page;document.getElementById("title").textContent=labels[page];
  document.getElementById("breadcrumb").textContent=`PLATEFORME / ${labels[page].toUpperCase()}`;
  if(page!=="Command Center")document.getElementById("subtitle").textContent="Compte démo uniquement · aucun argent réel.";
  [...nav.children].forEach(button=>{const selected=button.dataset.page===page;button.classList.toggle("active",selected);button.setAttribute("aria-current",selected?"page":"false");});
  const stage=refresh?node("div"):null;
  content=refresh?stage:liveContent;
  if(!refresh){liveContent.replaceChildren();notice.replaceChildren();if(typeof window!=="undefined"&&window.scrollTo)window.scrollTo(0,0);}
  const finish=()=>{
    if(sequence!==renderSequence)return;
    if(refresh){const y=typeof window!=="undefined"?window.scrollY:0;notice.replaceChildren();liveContent.replaceChildren(...[...stage.children]);if(typeof window!=="undefined"&&window.scrollTo)window.scrollTo(0,y);}
    content=liveContent;loadedPage=page;
  };
  if(page==="Settings"){settingsPage();finish();return;}
  const placeholder=refresh?null:node("div","loading-panel","Chargement des données locales…");
  if(placeholder)append(content,placeholder);
  try{await ensureLabels();if(page==="Command Center")await dashboard(sequence);else await generic(page,sequence);if(sequence===renderSequence&&placeholder)placeholder.remove();finish();}
  catch(error){if(sequence!==renderSequence)return;content=liveContent;if(!refresh)liveContent.replaceChildren();notice.replaceChildren();append(notice,info(`API indisponible : ${String(error)}. Vérifiez le serveur local.`,true));}
}
pages.forEach(page=>{const button=node("button","",labels[page]);button.type="button";button.dataset.page=page;button.addEventListener("click",()=>render(page));append(nav,button);});
const dialog=document.getElementById("stop-dialog"),stopKey=document.getElementById("stop-key"),stopMessage=document.getElementById("stop-message");
document.getElementById("stop-open").addEventListener("click",()=>dialog.showModal());
document.getElementById("stop-close").addEventListener("click",()=>{stopKey.value="";stopMessage.textContent="";dialog.close();});
document.getElementById("stop-confirm").addEventListener("click",async()=>{
  try{await get("/risk/kill-switch",{method:"POST",headers:{"X-Operator-Key":stopKey.value}});stopMessage.textContent="Arrêt enregistré. Vérifiez séparément le worker avant la démo.";stopKey.value="";}
  catch(error){stopMessage.textContent=`Erreur : ${friendly(error)}`;}
});
const pilotDialog=document.getElementById("pilot-dialog"),pilotKey=document.getElementById("pilot-key"),pilotMessage=document.getElementById("pilot-message");
document.getElementById("pilot-close").addEventListener("click",()=>{pilotKey.value="";pilotMessage.textContent="";pilotDialog.close();});
document.getElementById("pilot-confirm").addEventListener("click",async()=>{
  try{
    const phraseValue=document.getElementById("pilot-phrase").value,headers={"X-Operator-Key":pilotKey.value,"X-Operator-Name":"preview-local","Content-Type":"application/json"};
    if(pilotTarget==="close_all"){await get("/autopilot/close-all",{method:"POST",headers,body:JSON.stringify({confirm:phraseValue})});pilotKey.value="";pilotMessage.textContent="";pilotDialog.close();render(active);return;}
    const result=await get("/autopilot/mode",{method:"POST",headers,body:JSON.stringify({mode:pilotTarget,confirm:pilotTarget==="demo_auto"?phraseValue:undefined})});
    pilotKey.value="";pilotMessage.textContent="";pilotDialog.close();updateModeBadge(result.status);render(active);
  }catch(error){pilotMessage.textContent=`Erreur : ${friendly(error)}`;}
});
if(typeof setInterval==="function")setInterval(()=>{if(active==="Command Center"&&!document.hidden&&!pilotDialog.open&&!document.getElementById("stop-dialog").open)render(active);},30000);
render("Command Center");
