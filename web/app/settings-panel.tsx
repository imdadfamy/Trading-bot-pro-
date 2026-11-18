"use client";
import { useState } from "react";

type Settings = {
  mode: "observation";
  model_by_agent: Record<string, string>;
  daily_ai_limit_usd: number;
  experiment_ai_limit_usd: number;
  quote_max_age_seconds: number;
};
const agents = ["graph", "news", "quant", "risk", "director"];
const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function SettingsPanel() {
  const [key, setKey] = useState("");
  const [version, setVersion] = useState<number | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [message, setMessage] = useState("");
  async function load() {
    try {
      const res = await fetch(`${api}/settings`, { headers: { "X-Operator-Key": key }, cache: "no-store" });
      if (!res.ok) throw new Error(`Accès refusé ou API indisponible (${res.status})`);
      const result = await res.json();
      setVersion(result.version); setSettings(result.settings); setMessage("Paramètres chargés.");
    } catch (error) { setMessage(String(error)); }
  }
  async function save() {
    if (!settings || version === null) return;
    try {
      const res = await fetch(`${api}/settings`, {
        method: "PATCH", headers: { "X-Operator-Key": key, "X-Operator-Name": "web-local",
                                   "Content-Type": "application/json" },
        body: JSON.stringify({ settings, expected_version: version })
      });
      const result = await res.json();
      if (!res.ok) throw new Error(result.error ?? `Erreur ${res.status}`);
      setVersion(result.version); setMessage(`Version ${result.version} enregistrée. Le mode observation reste actif.`);
    } catch (error) { setMessage(String(error)); }
  }
  return <div className="settings-form">
    <p>Ces réglages sont enregistrés côté serveur avec leur version. Aucun fournisseur IA n’est appelé tant que ses API et sa recette ne sont pas configurées.</p>
    <label>Clé opérateur locale<input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder="Saisie temporaire" /></label>
    <button type="button" onClick={load} disabled={!key}>Charger les paramètres</button>
    {settings && <>
      <div className="detail-grid">{agents.map(agent => <label key={agent}>Modèle · {agent}<input value={settings.model_by_agent[agent] ?? ""} onChange={e => setSettings({ ...settings, model_by_agent: { ...settings.model_by_agent, [agent]: e.target.value } })} placeholder="Non configuré" /></label>)}</div>
      <div className="detail-grid">
        <label>Budget IA quotidien (USD)<input type="number" min="0" max="10000" step="0.01" value={settings.daily_ai_limit_usd} onChange={e => setSettings({ ...settings, daily_ai_limit_usd: Number(e.target.value) })}/></label>
        <label>Budget expérience (USD)<input type="number" min="0" max="10000" step="0.01" value={settings.experiment_ai_limit_usd} onChange={e => setSettings({ ...settings, experiment_ai_limit_usd: Number(e.target.value) })}/></label>
        <label>Fraîcheur cotation (secondes)<input type="number" min="0.1" max="60" step="0.1" value={settings.quote_max_age_seconds} onChange={e => setSettings({ ...settings, quote_max_age_seconds: Number(e.target.value) })}/></label>
      </div>
      <div className="settings-actions"><span>Version {version} · Mode observation</span><button type="button" onClick={save}>Enregistrer</button></div>
    </>}
    {message && <div className="form-message" role="status">{message}</div>}
  </div>;
}
