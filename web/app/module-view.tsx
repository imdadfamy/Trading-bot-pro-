"use client";
import { useEffect, useState } from "react";
import SettingsPanel from "./settings-panel";
import { action, fr, gate, rationale, role, when } from "./labels";

const endpoint: Record<string, string> = {
  "AI Agents": "/agents", "Skills Library": "/skills", "Market Intelligence": "/news/events",
  "Trading Terminal": "/signals", "Session Analytics": "/sessions", "Strategy Lab": "/backtests",
  "AI Memory": "/memory", "Risk Center": "/dashboard", "API & Integrations": "/readiness",
  "Budget Center": "/costs", "Settings": "/dashboard"
};
const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Row = Record<string, unknown>;
function isRow(value: unknown): value is Row { return !!value && typeof value === "object" && !Array.isArray(value); }
const fieldLabels: Record<string, string> = {
  as_of: "Évalué le", active: "Sessions actives", primary: "Session principale", broker_hours_verified: "Horaires du courtier vérifiés",
  total_usd: "Total dépensé (USD)", today_usd: "Dépensé aujourd'hui (USD)", daily_limit_usd: "Plafond quotidien (USD)",
  experiment_limit_usd: "Plafond de l'expérience (USD)", calls: "Appels aux modèles", new_model_calls_blocked: "Nouveaux appels IA bloqués",
  kill_switch: "Arrêt des nouvelles entrées actif", broker: "Courtier", pending_order_intents: "Ordres à vérifier à la main",
  live_trading: "Trading réel autorisé", mode: "Mode", ready_for_local_review: "Prêt pour la revue locale",
  ready_for_14_day_demo: "Prêt pour la démo de 14 jours", execution_mode: "Mode d'exécution",
  mt5_demo_account_configured: "Compte MT5 démo renseigné",
  openai_key_present: "Clé OpenAI présente", newsapi_key_present: "Clé NewsAPI présente",
  tradingeconomics_key_present: "Clé Trading Economics présente", verified: "Connexions vérifiées"
};
function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Oui" : "Non";
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString("fr-FR", { maximumFractionDigits: 3 }) : "—";
  if (Array.isArray(value)) return value.map(show).join(", ") || "—";
  return JSON.stringify(value);
}
const formatters: Record<string, (value: unknown) => string> = {
  as_of: when,
  broker: value => fr("values", value),
  mode: value => fr("values", value),
  execution_mode: value => fr("values", value)
};
function tiles(row: Row, keys: string[]) {
  return <div className="detail-grid">{keys.map(key => {
    const label = (fieldLabels[key] ?? key.replaceAll("_", " ")).toUpperCase();
    return <div className="detail" key={key}><span>{label}</span><strong>{(formatters[key] ?? show)(row[key])}</strong></div>;
  })}</div>;
}
function Empty({ children }: { children: string }) { return <div className="empty-small">{children}</div>; }
function Item({ title, children, tag }: { title: string; children?: React.ReactNode; tag?: string }) {
  return <div className="item"><strong>{title}</strong>{children}{tag && <em>{tag}</em>}</div>;
}
export default function ModuleView({ page }: { page: string }) {
  const [value, setValue] = useState<unknown>(null);
  const [studies, setStudies] = useState<unknown[]>([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(false); setValue(null); setStudies([]);
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
  const rows = (items: unknown[], limit = 30) => items.slice(0, limit).map(entry => (isRow(entry) ? entry : {}));
  return <section className="card page-card" aria-busy={loading}>
    {loading && <p className="loading">Chargement des données locales…</p>}
    {error && <div className="alert">API locale indisponible. Aucun état de marché ne peut être affiché.</div>}
    {!loading && !error && <>
      {page === "Skills Library" && <div className="items">{rows(list, 40).map((r, i) => <Item key={i} title={`${String(i + 1).padStart(2, "0")} · ${show(r.name)}`} tag={`v${show(r.version)}`}><span>{role(r.owner)}</span></Item>)}</div>}
      {page === "AI Agents" && <div className="items">{list.length ? rows(list).map((r, i) => <Item key={i} title={role(r.agent)} tag={action(r.action)}><span>{rationale(r.rationale)}</span></Item>) : <Empty>Aucune analyse enregistrée</Empty>}</div>}
      {page === "Market Intelligence" && <div className="items">{list.length ? rows(list, 50).map((r, i) => <Item key={i} title={show(r.headline)}><span>{show(r.source)} · {when(r.published_at)} · {fr("status", r.status)} · gravité {fr("severity", r.severity)} · pertinence {fr("relevance", r.relevance, "non classée")}</span></Item>) : <Empty>Aucun événement reçu</Empty>}</div>}
      {page === "Trading Terminal" && <div className="items">{list.length ? rows(list).map((r, i) => <Item key={i} title={action(r.action)}><span>{show(r.symbol)} · {fr("status", r.status)}</span><span>{rationale(r.rationale)}</span></Item>) : <Empty>Aucun signal</Empty>}</div>}
      {page === "Strategy Lab" && <>
        <h3 className="subhead">Backtests locaux</h3>
        <div className="items">{list.length ? rows(list).map((r, i) => { const result = isRow(r.result) ? r.result : {}; const metrics = isRow(result.metrics) ? result.metrics : {}; return <Item key={i} title={show(r.dataset)} tag="RECHERCHE UNIQUEMENT"><span>{show(metrics.trades)} trades · résultat simulé {show(metrics.net_pnl)} USD</span></Item>; }) : <Empty>Aucun backtest enregistré</Empty>}</div>
        <h3 className="subhead">Études d'indices synthétiques</h3>
        <p className="hint">Statistiques descriptives hors ligne : elles ne prédisent rien, ne produisent aucun signal et ne sont reliées à aucun ordre.</p>
        <div className="items">{studies.length ? studies.map((entry, i) => { const r = isRow(entry) ? entry : {}; const rep = isRow(r.report) ? r.report : {}; const all = isRow(rep.all) ? rep.all : {}; const freq = typeof all.absolute_jump_frequency === "number" ? `${(all.absolute_jump_frequency * 100).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %` : "—"; return <Item key={i} title={`${show(r.symbol)} · ${fr("families", r.family)}`} tag={rep.statistically_sufficient ? "ÉCHANTILLON SUFFISANT" : "ÉCHANTILLON INSUFFISANT"}><span>{show(all.observations)} bougies · {show(all.absolute_jump_count)} sauts brusques ({freq}) : {show(all.up_jump_count)} à la hausse, {show(all.down_jump_count)} à la baisse</span></Item>; }) : <Empty>Aucune étude enregistrée (commande analyze-synthetic --save)</Empty>}</div>
      </>}
      {page === "AI Memory" && <div className="items">{list.length ? rows(list).map((r, i) => <Item key={i} title={show(r.cause)}><span>{show(r.recommendation)}</span></Item>) : <Empty>Aucune observation enregistrée</Empty>}</div>}
      {page === "Session Analytics" && isRow(value) && tiles(value, ["as_of", "active", "primary", "broker_hours_verified"])}
      {page === "Budget Center" && isRow(value) && tiles(value, ["total_usd", "today_usd", "daily_limit_usd", "experiment_limit_usd", "calls", "new_model_calls_blocked"])}
      {page === "Risk Center" && isRow(value) && tiles(value, ["kill_switch", "broker", "pending_order_intents", "live_trading", "mode"])}
      {page === "API & Integrations" && isRow(value) && <>
        {tiles(value, ["ready_for_local_review", "ready_for_14_day_demo", "execution_mode"])}
        <h3 className="subhead">Conditions encore à remplir ({Array.isArray(value.blocked_gates) ? value.blocked_gates.length : 0})</h3>
        <div className="items">{(Array.isArray(value.blocked_gates) ? value.blocked_gates : []).map((id, i) => { const g = gate(String(id)); return <Item key={i} title={g.label}><span>{g.help}</span></Item>; })}</div>
        <h3 className="subhead">Accès configurés</h3>
        <p className="hint">Une clé présente ne prouve pas que la connexion fonctionne.</p>
        {isRow(value.credentials) && tiles(value.credentials, ["mt5_demo_account_configured", "openai_key_present", "newsapi_key_present", "tradingeconomics_key_present", "verified"])}
      </>}
      {page === "Settings" && <SettingsPanel/>}
    </>}
  </section>;
}
