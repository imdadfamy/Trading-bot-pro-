"use client";
import { useEffect, useState } from "react";
import SettingsPanel from "./settings-panel";

const endpoint: Record<string, string> = {
  "AI Agents": "/agents", "Skills Library": "/skills", "Market Intelligence": "/news/events",
  "Trading Terminal": "/signals", "Session Analytics": "/sessions", "Strategy Lab": "/backtests",
  "AI Memory": "/memory", "Risk Center": "/dashboard", "API & Integrations": "/readiness",
  "Budget Center": "/costs", "Settings": "/dashboard"
};
const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Row = Record<string, unknown>;
function isRow(value: unknown): value is Row { return !!value && typeof value === "object" && !Array.isArray(value); }
export const pageLabels: Record<string, string> = {
  "Command Center": "Vue d'ensemble", "AI Agents": "Agents IA", "Skills Library": "27 compétences",
  "Market Intelligence": "Actualités et marché", "Trading Terminal": "Journal des signaux",
  "Session Analytics": "Sessions", "Strategy Lab": "Backtests", "AI Memory": "Mémoire collective",
  "Risk Center": "Gestion des risques", "API & Integrations": "Intégrations", "Budget Center": "Budget IA",
  "Settings": "Paramètres"
};
const fieldLabels: Record<string, string> = {
  as_of: "Évalué le", active: "Sessions actives", primary: "Session principale", broker_hours_verified: "Horaires du courtier vérifiés",
  total_usd: "Total (USD)", today_usd: "Aujourd'hui (USD)", daily_limit_usd: "Plafond quotidien (USD)",
  experiment_limit_usd: "Plafond de l'expérience (USD)", calls: "Appels", new_model_calls_blocked: "Nouveaux appels IA bloqués",
  kill_switch: "Arrêt des entrées", broker: "Courtier", pending_order_intents: "Intentions d'ordre à examiner",
  live_trading: "Trading réel", mode: "Mode", ready_for_local_review: "Prêt pour la revue locale",
  ready_for_14_day_demo: "Prêt pour la démo de 14 jours", execution_mode: "Mode d'exécution",
  blocked_gates: "Conditions bloquantes", mt5_demo_account_configured: "Compte MT5 DEMO renseigné",
  openai_key_present: "Clé OpenAI présente", newsapi_key_present: "Clé NewsAPI présente",
  tradingeconomics_key_present: "Clé Trading Economics présente", verified: "Connexion vérifiée"
};
function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Oui" : "Non";
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString("fr-FR", { maximumFractionDigits: 3 }) : "—";
  if (Array.isArray(value)) return value.map(show).join(", ") || "—";
  return JSON.stringify(value);
}
function tiles(row: Row, keys: string[]) {
  return <div className="detail-grid">{keys.map(key => {
    const raw = row[key];
    const label = (fieldLabels[key] ?? key.replaceAll("_", " ")).toUpperCase();
    if (Array.isArray(raw) && raw.length > 1) {
      return <div className="detail wide" key={key}><span>{label} ({raw.length})</span><ul className="gate-list">{raw.map((item, i) => <li key={i}>{show(item)}</li>)}</ul></div>;
    }
    return <div className="detail" key={key}><span>{label}</span><strong>{show(raw)}</strong></div>;
  })}</div>;
}
export default function ModuleView({ page }: { page: string }) {
  const [value, setValue] = useState<unknown>(null);
  const [studies, setStudies] = useState<unknown[]>([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(false);setValue(null);setStudies([]);
    if (page === "Strategy Lab") {
      fetch(base + "/synthetic/reports", { cache: "no-store", signal: controller.signal })
        .then(r => (r.ok ? r.json() : [])).then(result => { if (!controller.signal.aborted && Array.isArray(result)) setStudies(result); })
        .catch(() => undefined);
    }
    fetch(base + (endpoint[page] ?? "/health"), { cache: "no-store", signal: controller.signal })
      .then(r => { if (!r.ok) throw new Error("Unavailable"); return r.json(); })
      .then(result => { if (!controller.signal.aborted) setValue(result); })
      .catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page]);
  const list = Array.isArray(value) ? value : [];
  return <section className="card page-card"><div className="eyebrow">{(pageLabels[page] ?? page).toUpperCase()}</div><h2>{pageLabels[page] ?? page}</h2>
    {loading && <p>Chargement des données locales…</p>}
    {error && <div className="alert">API locale indisponible. Aucun état de marché ne peut être affiché.</div>}
    {!loading && !error && <>
      {page === "Skills Library" && <><p>27 spécifications de recherche versionnées. Les implémentations restent à valider.</p><div className="items">{list.map((entry, i) => { const r=isRow(entry)?entry:{}; return <div className="item" key={i}><span className="item-num">{String(i+1).padStart(2,"0")}</span><strong>{show(r.name)}</strong><span>{show(r.owner)}</span><em>{show(r.version)}</em></div>; })}</div></>}
      {page === "AI Agents" && <><p>Analyses enregistrées par cycle, sans accès au courtier.</p><div className="items">{list.length ? list.slice(0,30).map((entry,i) => {const r=isRow(entry)?entry:{};return <div className="item" key={i}><strong>{show(r.agent)}</strong><span>{show(r.action)}</span><span>{show(r.rationale)}</span></div>;}) : <div className="empty-small">Aucune analyse enregistrée</div>}</div></>}
      {page === "Market Intelligence" && <><p>Sources horodatées et statuts de vérification. Aucun flux externe n’est connecté.</p><div className="items">{list.length ? list.map((entry,i) => {const r=isRow(entry)?entry:{};return <div className="item" key={i}><strong>{show(r.headline)}</strong><span>{show(r.status)} · {show(r.severity)} · pertinence {show(r.relevance ?? "non classée")}</span></div>;}) : <div className="empty-small">Aucun événement reçu</div>}</div></>}
      {page === "Trading Terminal" && <><p>Journal des signaux de recherche. Exécution MT5 désactivée.</p><div className="items">{list.length ? list.slice(0,30).map((entry,i) => {const r=isRow(entry)?entry:{};return <div className="item" key={i}><strong>{show(r.action)}</strong><span>{show(r.symbol)} · {show(r.status)}</span><span>{show(r.rationale)}</span></div>;}) : <div className="empty-small">Aucun signal</div>}</div></>}
      {page === "Strategy Lab" && <><p>Backtests locaux distincts des performances réelles. Le jeu fourni est synthétique.</p><div className="items">{list.length ? list.map((entry,i) => {const r=isRow(entry)?entry:{}; const result=isRow(r.result)?r.result:{}; const metrics=isRow(result.metrics)?result.metrics:{};return <div className="item" key={i}><strong>{show(r.dataset)}</strong><span>{show(metrics.trades)} trades · P&L {show(metrics.net_pnl)} USD</span><em>RECHERCHE</em></div>;}) : <div className="empty-small">Aucun backtest enregistré</div>}</div></>}
      {page === "Strategy Lab" && <><p>Indices synthétiques : statistiques descriptives hors ligne, sans signal ni lien avec les ordres.</p><div className="items">{studies.length ? studies.map((entry, i) => { const r = isRow(entry) ? entry : {}; const rep = isRow(r.report) ? r.report : {}; const all = isRow(rep.all) ? rep.all : {}; const freq = typeof all.absolute_jump_frequency === "number" ? `${(all.absolute_jump_frequency * 100).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %` : "—"; return <div className="item" key={i}><strong>{show(r.symbol)} · {show(r.family)}</strong><span>{show(all.observations)} bougies · sauts {show(all.absolute_jump_count)} ({freq})</span><em>{rep.statistically_sufficient ? "ÉCHANTILLON SUFFISANT" : "ÉCHANTILLON INSUFFISANT"}</em></div>; }) : <div className="empty-small">Aucune étude enregistrée (analyze-synthetic --save)</div>}</div></>}
      {page === "AI Memory" && <><p>Causes, preuves et recommandations versionnées. Aucune modification automatique de stratégie.</p><div className="items">{list.length ? list.map((entry,i)=>{const r=isRow(entry)?entry:{};return <div className="item" key={i}><strong>{show(r.cause)}</strong><span>{show(r.recommendation)}</span></div>;}) : <div className="empty-small">Aucune observation enregistrée</div>}</div></>}
      {page === "Session Analytics" && isRow(value) && <><p>Sessions indicatives, indépendantes des horaires du courtier.</p>{tiles(value,["as_of","active","primary","broker_hours_verified"])}</>}
      {page === "Budget Center" && isRow(value) && <><p>Coûts IA enregistrés ; le budget expérimental est bloquant dans l’adaptateur.</p>{tiles(value,["total_usd","today_usd","daily_limit_usd","experiment_limit_usd","calls","new_model_calls_blocked"])}</>}
      {page === "Risk Center" && isRow(value) && <><p>Les entrées restent désactivées tant que le connecteur démo et la recette ne sont pas validés.</p>{tiles(value,["kill_switch","broker","pending_order_intents","live_trading","mode"])}</>}
      {page === "API & Integrations" && isRow(value) && <><p>API locale de recherche. Une clé présente ne prouve pas qu'une connexion a été vérifiée.</p>{tiles(value,["ready_for_local_review","ready_for_14_day_demo","execution_mode","blocked_gates"])}{isRow(value.credentials) && tiles(value.credentials,["mt5_demo_account_configured","openai_key_present","newsapi_key_present","tradingeconomics_key_present","verified"])}</>}
      {page === "Settings" && <SettingsPanel/>}
    </>}
  </section>;
}
