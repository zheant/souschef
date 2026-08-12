import { useEffect, useState } from "react";
import { api } from "../api";

/** Sous-section « Essentiels » de l'écran Ménage (pilote,
 *  docs/product-pilot.md) — remplace le garde-manger à quantité suivie :
 *  une simple appartenance ménage/ingrédient, sans quantité ni priorité.
 *  Un essentiel n'est jamais gratuit : il est acheté comme n'importe quel
 *  ingrédient, seulement évalué au prix historique le plus bas dans
 *  l'objectif du solveur, ce qui biaise le choix de recettes sans jamais
 *  fausser le montant réellement affiché.
 *
 *  Sous-composant plutôt qu'écran de haut niveau — pas de <h2> propre, le
 *  sous-onglet parent (Household.tsx) fait déjà ce travail. La liste est
 *  remplacée comme un tout à chaque enregistrement (services/household.py::
 *  set_staples), pas un upsert ligne par ligne. */
export function StaplesPanel() {
  const [items, setItems] = useState<{ id: string; name: string }[]>([]);
  const [newId, setNewId] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const rows = await api.staples();
    setItems(rows.map((r) => ({ id: r.canonical_ingredient_id, name: r.name })));
  }
  useEffect(() => { refresh().catch((e) => setError(String(e))); }, []);

  async function save(ids: string[]) {
    setError(null); setStatus(null);
    try {
      await api.setStaples(ids);
      await refresh();
      setStatus("Essentiels enregistrés.");
      setNewId("");
    } catch (e) { setError(String(e)); }
  }

  return (
    <>
      <p className="muted" style={{ margin: "0 0 14px" }}>
        Ingrédients que ce ménage est supposé toujours avoir sous la main —
        évalués au prix le plus bas de la dernière année pour orienter le
        choix de recettes, achetés comme n'importe quel autre ingrédient
        sinon.
      </p>
      <div className="card">
        <div className="table-scroll">
          <table className="ledger">
            <thead>
              <tr><th>Ingrédient</th><th /></tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id}>
                  <td data-label="Ingrédient">{l.name}</td>
                  <td className="num">
                    <button className="action ghost"
                      onClick={() => save(items.filter((x) => x.id !== l.id).map((x) => x.id))}>
                      Retirer
                    </button>
                  </td>
                </tr>
              ))}
              <tr>
                <td data-label="Ingrédient">
                  <input placeholder="identifiant canonique (ex. riz_basmati)" value={newId}
                    onChange={(e) => setNewId(e.target.value)} />
                </td>
                <td className="num">
                  <button className="action"
                    disabled={!newId}
                    onClick={() => save([...items.map((x) => x.id), newId])}>
                    Ajouter
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          {status && <span className="badge">{status}</span>}
          {error && <span className="callout error">{error}</span>}
        </div>
      </div>
    </>
  );
}
