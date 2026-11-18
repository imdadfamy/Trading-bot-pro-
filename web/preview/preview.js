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
  "Command Center":"Vue d'ensemble", "AI Agents":"Agents IA", "Skills Library":"27 compétences",
  "Market Intelligence":"Actualités et marché", "Trading Terminal":"Journal des signaux",
  "Session Analytics":"Sessions", "Strategy Lab":"Backtests", "AI Memory":"Mémoire collective",
  "Risk Center":"Gestion des risques", "API & Integrations":"Intégrations", "Budget Center":"Budget IA", "Settings":"Paramètres"
};
const explanations = {
  "AI Agents":"Quatre spécialistes préparent des rapports ; le directeur IA synthétise. Sans fournisseur configuré, aucun agent externe ne tourne en continu.",
  "Skills Library":"Le catalogue décrit 27 méthodes de recherche ; leur présence n'atteste pas leur validation en conditions de marché.",
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
async function dashboard(sequence) {
  const [data,history,runs,signals]=await Promise.all([get("/dashboard"),get("/market/candles"),get("/agents").catch(()=>[]),get("/signals").catch(()=>[])]);
  if (sequence !== renderSequence) return;
  const latest={};
  (Array.isArray(runs)?runs:[]).forEach(run=>{if(typeof run.agent==="string"&&!run.agent.includes(":")&&!(run.agent in latest))latest[run.agent]=String(run.action);});
  if(Array.isArray(signals)&&signals[0]?.action)latest.director=String(signals[0].action);
  append(content,info("Recherche locale sur données d'exemple. Aucun courtier, flux live ou ordre n'est connecté."));
  const snap=data.snapshot;
  if(snap) append(content,info(`Dernier instantané de marché : ${when(snap.observed_at)} · ${freshness(snap)} · ${snap.broker}`,true));
  append(content,grid("metrics",stat("Capital démo","—","Compte non connecté"),stat("Valeur du compte","—","Aucun compte démo"),stat("Résultat réel","—","Aucun ordre exécuté"),stat("Décisions",value(data.signal_count),"Cycles de recherche")));
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
  if(page==="Skills Library") { append(content,info("Catalogue versionné : spécifications, pas 27 stratégies validées."));renderList("27 compétences",data.map(e=>({...e,roleName:role(e.owner),stateLabel:"spécification"})),["name","roleName","stateLabel"],"Catalogue vide"); }
  if(page==="AI Agents") renderList("Analyses par cycle",data.map(e=>({who:role(e.agent),why:rationale(e.rationale),act:action(e.action)})),["who","why","act"],"Aucun cycle lancé");
  if(page==="Market Intelligence") { append(content,info("Les événements d'exemple sont synthétiques. Aucune veille mondiale continue n'est active.",true));renderList("Articles reçus",data.map(item=>({headline:item.headline,label:`${item.source} · ${when(item.published_at)} · ${fr("status",item.status)} · gravité ${fr("severity",item.severity)} · pertinence ${fr("relevance",item.relevance,"non classée")}`})),["headline","label"],"Aucun article reçu");const releases=await get("/calendar/events").catch(()=>[]);if(sequence!==renderSequence)return;renderList("Calendrier économique importé",releases.map(r=>({when:when(r.scheduled_at),country:r.country,event:r.event,imp:`importance ${r.importance}/3`})),["when","country","event","imp"],"Aucun événement de calendrier importé"); }
  if(page==="Trading Terminal") { append(content,info("Journal des décisions de recherche. Aucun ordre MT5 n’a été envoyé."));renderList("Signaux",data.map(s=>({sym:`${s.symbol} · ${fr("status",s.status)}`,why:rationale(s.rationale),act:action(s.action)})),["sym","why","act"],"Aucun signal"); }
  if(page==="AI Memory") renderList("Désaccords, pannes et recommandations",data,["cause","recommendation"],"Aucune mémoire enregistrée");
  if(page==="Strategy Lab") {
    append(content,info("Les chiffres de l’exemple synthétique ne mesurent aucune performance de marché.",true));
    const panel=card("Backtests locaux"); if(!data.length)append(panel,empty("Aucun backtest enregistré"));
    else data.forEach(item=>append(panel,row([item.dataset,`${value(item.result?.metrics?.trades)} trades`,"RECHERCHE UNIQUEMENT"])));append(content,panel);
    const studies=await get("/synthetic/reports").catch(()=>[]);if(sequence!==renderSequence)return;
    append(content,info("Indices synthétiques : statistiques descriptives hors ligne. Elles ne prédisent rien, ne produisent aucun signal et ne sont reliées à aucun ordre.",true));
    const study=card("Études d'indices synthétiques");if(!studies.length)append(study,empty("Aucune étude enregistrée (commande analyze-synthetic --save)"));
    else studies.forEach(item=>{const r=item.report||{};const f=r.all?.absolute_jump_frequency;append(study,row([`${item.symbol} · ${fr("families",item.family)}`,`${value(r.all?.observations)} bougies · ${value(r.all?.absolute_jump_count)} sauts brusques (${f===null||f===undefined?"—":(Math.round(f*10000)/100).toLocaleString("fr-FR")} %) : ${value(r.all?.up_jump_count)} à la hausse, ${value(r.all?.down_jump_count)} à la baisse`,r.statistically_sufficient?"ÉCHANTILLON SUFFISANT":"ÉCHANTILLON INSUFFISANT"]));});
    append(content,study);
  }
  if(page==="Session Analytics") {const panel=card("Sessions indicatives");labeled(panel,{session_principale:data.primary,sessions_actives:data.active,horaires_courtier_vérifiés:data.broker_hours_verified,évalué_le:when(data.as_of)});append(content,panel);}
  if(page==="Budget Center") {const panel=card("Coûts IA enregistrés");labeled(panel,{dépense_totale_usd:data.total_usd,dépense_du_jour_usd:data.today_usd,plafond_quotidien_usd:data.daily_limit_usd,plafond_expérience_usd:data.experiment_limit_usd,appels:data.calls,nouveaux_appels_bloqués:data.new_model_calls_blocked});append(content,panel);}
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
      const save=node("button","",`Enregistrer la version ${data.version+1}`);
      save.addEventListener("click",async()=>{
        const payload={mode:"observation",model_by_agent:{},daily_ai_limit_usd:Number(inputs.daily_ai_limit_usd.value),experiment_ai_limit_usd:Number(inputs.experiment_ai_limit_usd.value),quote_max_age_seconds:Number(inputs.quote_max_age_seconds.value)};
        ["graph","news","quant","risk","director"].forEach(agent=>{if(inputs[agent].value.trim())payload.model_by_agent[agent]=inputs[agent].value.trim();});
        try{const saved=await get("/settings",{method:"PATCH",headers:{"X-Operator-Key":keyInput.value,"X-Operator-Name":"preview-local","Content-Type":"application/json"},body:JSON.stringify({settings:payload,expected_version:data.version})});status.textContent=`Version ${saved.version} enregistrée. Rechargez pour toute nouvelle modification.`;save.disabled=true;keyInput.value="";}catch(error){status.textContent=String(error);}
      });append(controls,save);status.textContent=`Version ${data.version} chargée · observation uniquement`;
    }catch(error){status.textContent=String(error);}
  });append(form,keyLabel,load,status,controls);append(panel,form);append(content,panel);
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
render("Command Center");
