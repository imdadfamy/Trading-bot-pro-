"use client";
import { useEffect, useState } from "react";
import { Activity, BarChart3, BookOpen, BrainCircuit, ChartCandlestick, ChevronRight, CircleDollarSign, Database, FlaskConical, Gauge, Globe2, History, LayoutDashboard, LockKeyhole, Settings2, ShieldAlert, WifiOff } from "lucide-react";
import ModuleView from "./module-view";
import { action, fr, pageHelp, pageLabels, role } from "./labels";
import EmergencyStop from "./emergency-stop";

const pages = [
  ["Command Center", LayoutDashboard], ["AI Agents", BrainCircuit], ["Skills Library", BookOpen],
  ["Market Intelligence", Globe2], ["Trading Terminal", ChartCandlestick], ["Session Analytics", BarChart3],
  ["Strategy Lab", FlaskConical], ["AI Memory", History], ["Risk Center", ShieldAlert],
  ["API & Integrations", Database], ["Budget Center", CircleDollarSign], ["Settings", Settings2]
] as const;
type Dashboard = { mode: string; broker: string; kill_switch: boolean; symbol: string; agents: string[]; events: { seq: number; at: string; kind: string; payload: string }[] };
const roles = ["graph", "news", "quant", "risk", "director"] as const;
const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Latest = Record<string, string>;

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>;
}
export default function Home() {
  const [page, setPage] = useState("Command Center");
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState(false);
  const [latest, setLatest] = useState<Latest>({});
  const [clock, setClock] = useState("--:--");
  useEffect(() => {
    const tick = () => setClock(new Date().toISOString().slice(11, 16));
    tick(); const timer = setInterval(tick, 60000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    let mounted = true;
    let busy = false;
    const controller = new AbortController();
    const load = async () => {
      if (busy || !mounted) return;
      busy = true;
      try {
        const response = await fetch(`${base}/dashboard`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("API");
        const result = await response.json();
        const extra = async (path: string) => { try { const r = await fetch(base + path, { cache: "no-store", signal: controller.signal }); return r.ok ? await r.json() : []; } catch { return []; } };
        const [runs, signals] = await Promise.all([extra("/agents"), extra("/signals")]);
        const found: Latest = {};
        for (const run of Array.isArray(runs) ? runs : []) { if (run && typeof run.agent === "string" && !run.agent.includes(":") && !(run.agent in found)) found[run.agent] = String(run.action); }
        if (Array.isArray(signals) && signals[0]?.action) found.director = String(signals[0].action);
        if (mounted) { setData(result); setLatest(found); setError(false); }
      } catch { if (mounted) setError(true); }
      finally { busy = false; }
    };
    load(); const timer = setInterval(load, 15000);
    return () => { mounted = false; controller.abort(); clearInterval(timer); };
  }, []);
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Activity size={22}/></div><div><strong>TRADING<br/>INTELLIGENCE</strong><small>PRO · RESEARCH SYSTEM</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Navigation principale">{pages.map(([label, Icon]) => <button key={label} className={`nav-item ${page === label ? "selected" : ""}`} onClick={() => setPage(label)}><Icon size={18}/><span>{pageLabels[label]}</span>{page === label && <ChevronRight size={14} className="arrow"/>}</button>)}</nav>
      <div className="sidebar-bottom"><span className="dot red"/> ARRÊT DES ENTRÉES ACTIF <small>Compte réel désactivé · Aucun ordre en cours</small></div>
    </aside>
    <main>
      <header className="topbar"><div className="crumb">PLATEFORME <span>/</span> {pageLabels[page].toUpperCase()}</div><div className="top-right"><span className="pill gold">● MODE OBSERVATION</span><EmergencyStop/><span className="pill">UTC {clock}</span><span className="avatar">TIP</span></div></header>
      <div className="content"><div className="heading"><div><div className="eyebrow">RECHERCHE · OR / DOLLAR (XAUUSD)</div><h1>{pageLabels[page]}</h1><p>{pageHelp[page]}</p></div><span className="safety"><LockKeyhole size={16}/> Démo uniquement</span></div>
      {error && <div className="alert"><WifiOff size={18}/> API déconnectée. Les données en direct et l’exécution sont indisponibles.</div>}
      {page === "Command Center" ? <>
        <div className="metrics"><Card><div className="metric-label">CAPITAL DÉMO <span>↗</span></div><div className="metric">— <small>USD</small></div><div className="sub">Pas encore affiché ici</div></Card><Card><div className="metric-label">VALEUR DU COMPTE <span>◈</span></div><div className="metric">— <small>USD</small></div><div className="sub">Pas encore affiché ici</div></Card><Card><div className="metric-label">PROFIT NET <span>↗</span></div><div className="metric">— <small>USD</small></div><div className="sub">Aucune donnée disponible</div></Card><Card><div className="metric-label">BAISSE MAXIMALE <span>▥</span></div><div className="metric">— <small>%</small></div><div className="sub">Aucune expérience active</div></Card></div>
        <div className="grid"><Card className="chart"><div className="card-head"><div><span className="eyebrow">MARCHÉ</span><h2>XAUUSD <span className="dim">/ Or · Dollar US</span></h2></div><span className="pill">FLUX INDISPONIBLE</span></div><div className="empty-chart"><ChartCandlestick size={34}/><strong>En attente du flux courtier</strong><span>Les cotations apparaîtront ici après connexion du compte démo.</span></div><div className="chart-foot"><span>SPREAD —</span><span>COTATION —</span><span>SESSION —</span></div></Card>
        <Card className="agents"><div className="card-head"><div><span className="eyebrow">AGENTS</span><h2>Dernier avis de chaque rôle</h2></div><span className="pill">{Object.keys(latest).length} / 5 ONT RÉPONDU</span></div>{roles.map((id, i) => <div className="agent-row" key={id}><span className="agent-icon">{String(i+1).padStart(2,"0")}</span><span><strong>{role(id)}</strong><small>{fr("roleHelp", id)}</small></span><span className="status">{latest[id] ? action(latest[id]) : "AUCUN CYCLE"}</span></div>)}</Card></div>
        <div className="grid lower"><Card><div className="card-head"><div><span className="eyebrow">ACTIVITÉ</span><h2>Journal récent</h2></div><span className="pill">{data?.events.length ?? 0} ÉVÉNEMENTS</span></div>{data?.events.length ? data.events.slice(0,5).map(e => <div className="event" key={e.seq}><span className="dot gold-dot"/><span>{fr("events", e.kind)}</span><time>{e.at.slice(11,19)} UTC</time></div>) : <div className="empty-small">Aucun événement enregistré</div>}</Card><Card><div className="card-head"><div><span className="eyebrow">SÉCURITÉ</span><h2>Contrôle du risque</h2></div><ShieldAlert size={20} color="#d4b675"/></div><div className="risk-line"><span>Arrêt des nouvelles entrées</span><b className="negative">{data ? (data.kill_switch ? "ACTIF" : "INACTIF") : "—"}</b></div><div className="risk-line"><span>Connecteur MT5</span><b>NON CONNECTÉ</b></div><div className="risk-line"><span>Compte réel</span><b className="negative">INTERDIT</b></div><div className="risk-line"><span>Ordres autorisés</span><b>0</b></div></Card></div>
      </> : <ModuleView key={page} page={page}/>}
      <footer>TRADING INTELLIGENCE PRO <span>·</span> ENVIRONNEMENT DE RECHERCHE <span>·</span> AUCUN CONSEIL D’INVESTISSEMENT</footer></div>
    </main>
  </div>;
}
