"use client";
import { useState } from "react";
export default function EmergencyStop() {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [message, setMessage] = useState("");
  async function activate() {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/risk/kill-switch`,
                              { method: "POST", headers: { "X-Operator-Key": key } });
      if (!res.ok) throw new Error(`Échec de la demande (${res.status})`);
      setMessage("Arrêt des nouvelles entrées enregistré."); setKey("");
    } catch (error) { setMessage(`${String(error)} · Vérifiez l’état du worker séparément.`); }
  }
  return <><button type="button" className="stop-button" onClick={() => setOpen(true)}>ARRÊT D’URGENCE</button>
    {open && <div className="modal-backdrop" role="presentation"><div className="stop-dialog" role="dialog" aria-modal="true" aria-labelledby="stop-title">
      <h2 id="stop-title">Arrêt des nouvelles entrées</h2>
      <p>Cette commande persiste l’arrêt dans l’API locale. La liaison au worker MT5 reste à valider avant le test démo.</p>
      <label>Clé opérateur<input type="password" value={key} autoComplete="off" onChange={e => setKey(e.target.value)}/></label>
      <div className="dialog-actions"><button type="button" onClick={() => {setOpen(false);setKey("");setMessage("");}}>Fermer</button><button type="button" disabled={!key} onClick={activate}>Activer l’arrêt</button></div>
      {message && <p role="status">{message}</p>}
    </div></div>}
  </>;
}
