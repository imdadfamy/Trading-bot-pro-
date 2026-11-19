"use strict";
const pages = ["Command Center","AI Agents","Skills Library","Market Intelligence","Trading Terminal","Session Analytics","Strategy Lab","AI Memory","Risk Center","API & Integrations","Budget Center","Settings"];
const endpoints = {
  "AI Agents":"/agents","Skills Library":"/skills","Market Intelligence":"/news/events",
  "Trading Terminal":"/signals","Session Analytics":"/sessions","Strategy Lab":"/backtests",
  "AI Memory":"/memory","Risk Center":"/dashboard","API & Integrations":"/readiness","Budget Center":"/costs"
};
const nav = document.getElementById("navigation");
const content = document.getElementById("content");
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
  "AI Agents":"Quatre spécialistes préparent des rapports ; le directeur IA synthétise. Sans fournisseur configuré, aucun agent externe ne tourne en continu.",
  "Skills Library":"Le catalogue décrit des méthodes de recherche (27 du cahier des charges et 7 propres aux indices synthétiques) ; leur présence n'atteste pas leur validation en conditions de marché.",
  "Market Intelligence":"Les données importées sont datées et peuvent être artificielles. Aucune surveillance mondiale en direct n'est active.",
  "Trading Terminal":"Les signaux affichés sont des décisions de recherche ; aucune position MT5 n'est ouverte par cette interface.",
  "Session Analytics":"Les sessions sont calculées à titre indicatif ; elles doivent être confirmées avec les horaires du courtier.",
  "Strategy Lab":"Les backtests locaux servent à vérifier le logiciel ; les exemples ne mesurent pas un rendement futur.",
  "AI Memory":"Les observations sont enregistrées pour analyse ; aucune stratégie n'est modifiée automatiquement.",
  "Risk Center":"L'arrêt des entrées est actif par défaut. Une recette de la passerelle démo est nécessaire avant tout test d'ordre.",
  "API & Integrations":"Cette page distingue la revue locale possible des conditions encore bloquantes pour les 14 jours en démo.",
  "Budget Center":"Les plafonds limitent les appels futurs ; ajouter un modèle dans les paramètres n'entraîne aucun achat ni appel automatique."
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
async function get(path, options) { const response=await fetch(path,{cache:"no-store",...options}); const result=await response.json(); if(!response.ok) throw new Error(result.error || `HTTP ${response.status}`); return result; }
function freshness(snapshot) { if(!snapshot) return "Aucune cotation"; const time=Date.parse(snapshot.observed_at); if(!Number.isFinite(time)) return "Horodatage invalide"; const age=Math.round((Date.now()-time)/1000); return age < 0 ? "Horloge incohérente" : `${age} s depuis la clôture enregistrée`; }
function chart(candles) {
  const panel=card("XAUUSD / Historique local");
  if(!candles.length) { append(panel,empty("Aucune bougie importée. Aucun flux live n’est connecté.")); return panel; }
  const series=candles.map(c=>Number(c.close)).filter(Number.isFinite);
  if(series.length<2) { append(panel,empty("Historique insuffisant")); return panel; }
  const low=Math.min(...series), high=Math.max(...series), span=high-low||1;
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("viewBox","0 0 700 230");svg.setAttribute("class","chart-svg");svg.setAttribute("role","img");svg.setAttribute("aria-label","Évolution des clôtures importées, données historiques");
  const line=document.createElementNS("http://www.w3.org/2000/svg","polyline");
  line.setAttribute("points",series.map((v,i)=>`${(i/(series.length-1)*690+5).toFixed(1)},${(215-(v-low)/span*200).toFixed(1)}`).join(" "));
  svg.appendChild(line);append(panel,svg,node("div","sub",`${series.length} clôtures · ${value(candles[0].broker)} · Historique, non live`));return panel;
}
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
  if (badge) badge.textContent = pilot && pilot.mode === "observe" ? "● OBSERVATION AUTOMATIQUE" : "● OBSERVATION";
}
function pilotCard(pilot) {
  const on = pilot.mode === "observe";
  const silent = on && !pilot.alive;
  const panel = card("Agents automatiques");
  append(panel, info(on
    ? (silent ? "Les agents sont activés mais aucun signe de vie récent : le serveur local a peut-être été arrêté. Ils reprennent seuls dès qu'il redémarre."
              : "Les agents travaillent : à chaque nouvelle bougie ils analysent, et chaque avis est journalisé. Aucun ordre n'est envoyé ; des positions simulées mesurent ce que leurs avis auraient donné.")
    : "Les agents sont arrêtés. Activez-les : ils analysent chaque bougie, de jour comme de nuit, jusqu'à ce que vous les désactiviez.", silent));
  labeled(panel, { état: on ? "EN OBSERVATION" : "ARRÊTÉ", cycles_terminés: pilot.cycles, décisions_du_jour: pilot.decisions_today,
    résultats_simulés_mesurés: pilot.shadow_outcomes, erreurs: pilot.errors, dépense_IA_usd: pilot.costs?.total_usd });
  Object.entries(pilot.last_cycle || {}).forEach(([symbol, cycle]) => append(panel, row([symbol,
    `${when(cycle.bar_close)} · ${fr("sessions", cycle.session)}`,
    cycle.halt ? "PRUDENCE : ANNONCE AMÉRICAINE" : modelNote(cycle.models)])));
  if (pilot.last_error) append(panel, info(`Dernière erreur : ${pilot.last_error}`, true));
  const actions = node("div", "pilot-actions");
  const toggle = node("button", on ? "danger" : "", on ? "Désactiver les agents" : "Activer les agents");
  toggle.type = "button";
  toggle.addEventListener("click", () => openPilotDialog(on ? "off" : "observe"));
  const demo = node("button", "", "Ordres automatiques en démo : étape suivante");
  demo.type = "button"; demo.disabled = true; demo.title = pilot.demo_auto_reason || "";
  append(actions, toggle, demo);
  append(panel, actions);
  return panel;
}
function openPilotDialog(target) {
  pilotTarget = target;
  document.getElementById("pilot-title").textContent = target === "observe" ? "Activer les agents" : "Désactiver les agents";
  document.getElementById("pilot-text").textContent = target === "observe"
    ? "Les agents analyseront chaque nouvelle bougie en continu, jour et nuit, tant que vous ne les désactivez pas. Ils n'envoient aucun ordre. Les appels IA consomment du budget (plafond réglable dans les paramètres)."
    : "Les agents s'arrêtent après le cycle en cours. Les positions simulées déjà ouvertes seront mesurées à la prochaine activation.";
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
    append(arms, row([armName(arm), `${a.trades} positions mesurées · R moyen ${num(a.mean_r)} · réussite ${pct(a.win_rate)} · abstention ${pct(a.abstention_rate)}${a.model_failures ? ` · ${a.model_failures} appels IA en échec` : ""}`, perfBadge(a)])); });
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
  return out;
}
function sessionCard(perf) {
  const panel = card("Résultats simulés par session et par méthode");
  const cells = perf.by_arm_session || [];
  if (!cells.length) append(panel, empty("Aucune position mesurée pour l'instant."));
  cells.forEach(c => append(panel, row([`${fr("sessions", c.session)} · ${armName(c.arm)}`, `${c.trades} positions · R moyen ${num(c.mean_r)} · réussite ${pct(c.win_rate)}`, perfBadge(c)])));
  return panel;
}
function decisionCard(list) {
  const panel = card("Décisions des agents automatiques (achats, ventes et pannes IA)");
  if (!Array.isArray(list) || !list.length) append(panel, empty("Aucune décision d'achat ou de vente pour l'instant."));
  else list.forEach(d => append(panel, row([`${when(d.at)} · ${d.symbol}`, `${armName(d.arm)} · ${rationale(d.rationale)}${d.skills?.length ? ` · compétences : ${d.skills.map(s => s.split("@")[0]).join(", ")}` : ""}`,
    `${action(d.action)} · ${d.result ? `${fr("outcomes", d.result)} (${num(d.r_multiple)} R)` : fr("decisionStatus", d.status)}`])));
  return panel;
}
async function dashboard(sequence) {
  const [data,history,runs,signals,pilot]=await Promise.all([get("/dashboard"),get("/market/candles"),get("/agents").catch(()=>[]),get("/signals").catch(()=>[]),get("/autopilot").catch(()=>null)]);
  if (sequence !== renderSequence) return;
  const latest={};
  (Array.isArray(runs)?runs:[]).forEach(run=>{if(typeof run.agent==="string"&&!run.agent.includes(":")&&!(run.agent in latest))latest[run.agent]=String(run.action);});
  if(Array.isArray(signals)&&signals[0]?.action)latest.director=String(signals[0].action);
  if(pilot){updateModeBadge(pilot);append(content,pilotCard(pilot));}
  append(content,info("Recherche locale sur données d'exemple. Aucun courtier, flux live ou ordre n'est connecté."));
  const snap=data.snapshot;
  if(snap) append(content,info(`Dernier instantané de marché : ${when(snap.observed_at)} · ${freshness(snap)} · ${snap.broker}`,true));
  append(content,grid("metrics",stat("Capital démo","—","Pas encore affiché ici"),stat("Valeur du compte","—","Pas encore affiché ici"),stat("Résultat réel","—","Aucun ordre exécuté"),stat("Décisions",value(data.signal_count),"Cycles de recherche")));
  const agents=card("Dernier avis de chaque rôle");
  ["graph","news","quant","risk","director"].forEach((id,i)=>append(agents,row([`${String(i+1).padStart(2,"0")}  ${role(id)}`,fr("roleHelp",id),latest[id]?action(latest[id]):"AUCUN CYCLE"])));
  append(content,grid("two",chart(history.candles||[]),agents));
  const logs=card("Journal récent");(data.events||[]).slice(0,8).forEach(e=>append(logs,row([fr("events",e.kind),when(e.at)])));if(!data.events?.length)append(logs,empty("Aucun événement"));
  const risk=card("Contrôle opérationnel");labeled(risk,{arrêt_des_nouvelles_entrées:data.kill_switch?"Actif":"À vérifier",courtier:fr("values",data.broker),mode:fr("values",data.mode),compte_réel:"Interdit"});
  append(content,grid("two",logs,risk));
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
    renderList("Analyses par cycle",data.map(e=>({who:role(e.agent),why:rationale(e.rationale),act:action(e.action)})),["who","why","act"],"Aucun cycle lancé");
    const perf=await get("/autopilot/performance").catch(()=>null);if(sequence!==renderSequence)return;
    if(perf)performanceCards(perf).forEach(panel=>append(content,panel));
  }
  if(page==="Market Intelligence") { append(content,info("Les événements d'exemple sont synthétiques. Aucune veille mondiale continue n'est active.",true));renderList("Articles reçus",data.map(item=>({headline:item.headline,label:`${item.source} · ${when(item.published_at)} · ${fr("status",item.status)} · gravité ${fr("severity",item.severity)} · pertinence ${fr("relevance",item.relevance,"non classée")}`})),["headline","label"],"Aucun article reçu");const releases=await get("/calendar/events").catch(()=>[]);if(sequence!==renderSequence)return;renderList("Calendrier économique importé",releases.map(r=>({when:when(r.scheduled_at),country:r.country,event:r.event,imp:`importance ${r.importance}/3`})),["when","country","event","imp"],"Aucun événement de calendrier importé"); }
  if(page==="Trading Terminal") { append(content,info("Journal des décisions de recherche. Aucun ordre MT5 n’a été envoyé."));renderList("Signaux",data.map(s=>({sym:`${s.symbol} · ${fr("status",s.status)}`,why:rationale(s.rationale),act:action(s.action)})),["sym","why","act"],"Aucun signal");
    const decisions=await get("/autopilot/decisions").catch(()=>[]);if(sequence!==renderSequence)return;
    append(content,decisionCard(decisions)); }
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
    const panel=card("Sessions indicatives");labeled(panel,{session_principale:data.primary,sessions_actives:data.active,horaires_courtier_vérifiés:data.broker_hours_verified,évalué_le:when(data.as_of)});append(content,panel);
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
  if(page==="Risk Center") {const panel=card("Contrôle du risque");labeled(panel,{arrêt_des_nouvelles_entrées:data.kill_switch?"ACTIF":"INCONNU",courtier:fr("values",data.broker),mode:fr("values",data.mode),ordres_à_vérifier_à_la_main:data.pending_order_intents,trading_réel_autorisé:data.live_trading});append(panel,info("Le bouton d’arrêt se trouve en haut de chaque écran. La liaison au worker MT5 reste à intégrer.",true));append(content,panel);}
  if(page==="API & Integrations") {
    const panel=card("Préparation des intégrations");labeled(panel,{revue_locale_prête:data.ready_for_local_review,démo_14_jours_prête:data.ready_for_14_day_demo,mode_d_exécution:fr("values",data.execution_mode),arrêt_des_nouvelles_entrées:data.kill_switch});
    if(data.credentials)labeled(panel,{compte_MT5_démo_renseigné:data.credentials.mt5_demo_account_configured,clé_OpenAI_présente:data.credentials.openai_key_present,clé_NewsAPI_présente:data.credentials.newsapi_key_present,clé_calendrier_présente:data.credentials.tradingeconomics_key_present,connexions_vérifiées:data.credentials.verified});
    append(panel,info("Une clé présente ne prouve pas que la connexion fonctionne.",true));append(content,panel);
    const gates=card(`Conditions encore à remplir (${(data.blocked_gates||[]).length})`);
    (data.blocked_gates||[]).forEach(id=>{const g=(L?.gates||{})[id]||[id,""];append(gates,row([g[0],g[1]]));});append(content,gates);
  }
}
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
      for(const [field,label,scale] of [["risk_per_trade","Risque par position (% du capital)",100],["max_daily_loss","Perte maximale par jour (% du capital)",100],["max_open_risk","Risque ouvert cumulé maximal (%)",100],["max_positions","Positions simultanées maximales",1],["max_spread","Écart d'achat-vente maximal (unités de prix)",1],["fixed_lot","Lot fixe (vide = calculé d'après le risque)",1],["commission_per_lot","Commission aller-retour par lot",1],["slippage_ticks","Glissement supposé (ticks)",1]]){
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
      });append(controls,save);status.textContent=`Version ${data.version} chargée · observation uniquement`;
    }catch(error){status.textContent=String(error);}
  });append(form,keyLabel,load,status,controls);append(panel,form);append(content,panel);
  const pilotPanel=card("Réglages des agents automatiques");const pilotForm=node("div","form");const pilotNote=node("div","form-note");
  get("/autopilot").then(state=>{
    const cfg=state.config||{};const fields={};
    const group=node("div","form-group");
    for(const [field,label,type] of [["symbols","Instruments (séparés par des virgules)","text"],["timeframe","Durée des bougies (M1, M5, M15, M30, H1)","text"],["model_every_minutes","Consultation de l'IA toutes les (minutes)","number"],["horizon_bars","Durée maximale d'une position simulée (bougies)","number"],["stop_atr_multiple","Stop simulé (multiple de la volatilité ATR)","number"],["reward_multiple","Objectif simulé (multiple du risque)","number"],["skill_pack_size","Compétences données à chaque analyste","number"]]){
      const current=Array.isArray(cfg[field])?cfg[field].join(", "):cfg[field];const [box,input]=formLabel(label,type,current);if(type==="number")input.step="any";fields[field]=input;append(group,box);
    }
    const save=node("button","","Enregistrer les réglages des agents");
    save.addEventListener("click",async()=>{
      const patch={symbols:fields.symbols.value.split(",").map(s=>s.trim()).filter(Boolean),timeframe:fields.timeframe.value.trim()};
      for(const f of ["model_every_minutes","horizon_bars","stop_atr_multiple","reward_multiple","skill_pack_size"])patch[f]=Number(fields[f].value);
      try{await get("/autopilot/config",{method:"PATCH",headers:{"X-Operator-Key":keyInput.value,"X-Operator-Name":"preview-local","Content-Type":"application/json"},body:JSON.stringify(patch)});pilotNote.textContent="Réglages enregistrés (clé opérateur ci-dessus). Pris en compte au prochain cycle.";}catch(error){pilotNote.textContent=String(error);}
    });
    append(pilotForm,group,save,pilotNote);
  }).catch(()=>append(pilotForm,empty("Réglages indisponibles : serveur local non joint.")));
  append(pilotPanel,pilotForm);append(content,pilotPanel);
}
async function render(page) {
  const sequence=++renderSequence;
  active=page;document.getElementById("title").textContent=labels[page];
  document.getElementById("breadcrumb").textContent=`PLATEFORME / ${labels[page].toUpperCase()}`;
  document.getElementById("subtitle").textContent="Recherche locale · Mode observation · Aucun ordre réel";
  [...nav.children].forEach(button=>{const selected=button.dataset.page===page;button.classList.toggle("active",selected);button.setAttribute("aria-current",selected?"page":"false");});
  content.replaceChildren();notice.replaceChildren();
  if(page==="Settings"){settingsPage();return;}
  const placeholder=node("div","loading-panel","Chargement des données locales…");append(content,placeholder);
  try{await ensureLabels();if(page==="Command Center")await dashboard(sequence);else await generic(page,sequence);if(sequence===renderSequence)placeholder.remove();}
  catch(error){if(sequence!==renderSequence)return;content.replaceChildren();append(notice,info(`API indisponible : ${String(error)}. Vérifiez le serveur local.`,true));}
}
pages.forEach(page=>{const button=node("button","",labels[page]);button.type="button";button.dataset.page=page;button.addEventListener("click",()=>render(page));append(nav,button);});
const dialog=document.getElementById("stop-dialog"),stopKey=document.getElementById("stop-key"),stopMessage=document.getElementById("stop-message");
document.getElementById("stop-open").addEventListener("click",()=>dialog.showModal());
document.getElementById("stop-close").addEventListener("click",()=>{stopKey.value="";stopMessage.textContent="";dialog.close();});
document.getElementById("stop-confirm").addEventListener("click",async()=>{
  try{await get("/risk/kill-switch",{method:"POST",headers:{"X-Operator-Key":stopKey.value}});stopMessage.textContent="Arrêt enregistré. Vérifiez séparément le worker avant la démo.";stopKey.value="";}
  catch(error){stopMessage.textContent=`Erreur : ${String(error)}`;}
});
const pilotDialog=document.getElementById("pilot-dialog"),pilotKey=document.getElementById("pilot-key"),pilotMessage=document.getElementById("pilot-message");
document.getElementById("pilot-close").addEventListener("click",()=>{pilotKey.value="";pilotMessage.textContent="";pilotDialog.close();});
document.getElementById("pilot-confirm").addEventListener("click",async()=>{
  try{
    const result=await get("/autopilot/mode",{method:"POST",headers:{"X-Operator-Key":pilotKey.value,"X-Operator-Name":"preview-local","Content-Type":"application/json"},body:JSON.stringify({mode:pilotTarget})});
    pilotKey.value="";pilotMessage.textContent="";pilotDialog.close();updateModeBadge(result.status);render(active);
  }catch(error){pilotMessage.textContent=`Erreur : ${String(error)}`;}
});
if(typeof setInterval==="function")setInterval(()=>{if(active==="Command Center"&&!document.hidden&&!pilotDialog.open&&!document.getElementById("stop-dialog").open)render(active);},30000);
render("Command Center");
