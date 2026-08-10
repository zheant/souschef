import { useEffect, useState } from "react";
import { api } from "../api";

/** Écran 4 — Garde-manger : stock courant (g_i), édition manuelle. */
export default function PantryScreen() {
  const [lines, setLines] = useState<{ id: string; qty: string }[]>([]);
  const [newId, setNewId] = useState("");
  const [newQty, setNewQty] = useState("0");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const rows = await api.pantry();
    setLines(rows.map((r) => ({ id: r.canonical_ingredient_id, qty: r.quantity_base_unit })));
  }
  useEffect(() => { refresh().catch((e) => setError(String(e))); }, []);

  async function save(extra?: { id: string; qty: string }) {
    setError(null); setStatus(null);
    const payload = [...lines, ...(extra ? [extra] : [])].map((l) => ({
      canonical_ingredient_id: l.id, quantity_base_unit: Number(l.qty),
    }));
    try {
      await api.updatePantry(payload);
      await refresh();
      setStatus("Garde-manger enregistré.");
      setNewId(""); setNewQty("0");
    } catch (e) { setError(String(e)); }
  }

  return (
    <section>
      <h2>Garde-manger <span className="sub">— reporté d'une exécution à l'autre par le commit</span></h2>
      <div className="card">
        <table className="ledger">
          <thead><tr><th>Ingrédient canonique</th><th className="num">Quantité (unité de base)</th></tr></thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={l.id}>
                <td className="mono">{l.id}</td>
                <td className="num">
                  <input type="number" min="0" step="1" value={l.qty}
                    onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, qty: e.target.value } : x))} />
                </td>
              </tr>
            ))}
            <tr>
              <td><input placeholder="identifiant canonique (ex. riz_basmati)" value={newId}
                onChange={(e) => setNewId(e.target.value)} /></td>
              <td className="num"><input type="number" min="0" value={newQty}
                onChange={(e) => setNewQty(e.target.value)} /></td>
            </tr>
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="action" onClick={() => save(newId ? { id: newId, qty: newQty } : undefined)}>
            Enregistrer
          </button>
          {status && <span className="badge">{status}</span>}
          {error && <span className="callout error">{error}</span>}
        </div>
      </div>
    </section>
  );
}
