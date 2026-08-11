import { useEffect, useMemo, useState } from "react";
import { api, cents } from "../api";
import { describeChanges } from "../changes";
import type { Household, Plan, SolverConfigInput, Store } from "../types";

/** Écran 3 — Résultat : menu, liste d'épicerie groupée par magasin avec
 *  sous-totaux et itinéraire suggéré, et la décomposition du coût en cinq
 *  barres — la lecture la plus utile de tout le système (spec). La lecture
 *  D13 sépare décaissement et stock déjà payé. */

function haversineKm(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const r = (x: number) => (x * Math.PI) / 180;
  const h =
    Math.sin(r(bLat - aLat) / 2) ** 2 +
    Math.cos(r(aLat)) * Math.cos(r(bLat)) * Math.sin(r(bLng - aLng) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

const TERM_LABELS: [key: "achats" | "deplacements" | "temps" | "recuperation" | "appetence", label: string, credit: boolean][] = [
  ["achats", "Achats", false],
  ["deplacements", "Déplacements", false],
  ["temps", "Temps", false],
  ["recuperation", "Récupération", true],
  ["appetence", "Appétence", true],
];

export default function ResultScreen(props: {
  plan: Plan | null; household: Household; stores: Store[]; config: SolverConfigInput;
  onCommitted: (planId: number) => void;
}) {
  const { plan, household, stores } = props;
  const [committing, setCommitting] = useState(false);
  const [commitMsg, setCommitMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [lockedIds, setLockedIds] = useState<Set<string>>(new Set());
  const [reoptimizing, setReoptimizing] = useState(false);
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const [reoptimizeMsg, setReoptimizeMsg] = useState<string | null>(null);
  const [reoptimizeError, setReoptimizeError] = useState<string | null>(null);

  // Nouveau plan chargé (génération, commit, réoptimisation) : les verrous
  // ne s'appliquent qu'au plan qui les a vus posés.
  useEffect(() => { setLockedIds(new Set()); }, [plan?.id]);

  const itinerary = useMemo(() => {
    if (!plan) return [];
    const byKey = new Map(stores.map((s) => [s.external_key, s]));
    return plan.stores_visited
      .map((k) => byKey.get(k))
      .filter((s): s is Store => Boolean(s))
      .map((s) => ({ ...s, km: haversineKm(household.home_lat, household.home_lng, s.lat, s.lng) }))
      .sort((a, b) => a.km - b.km);
  }, [plan, stores, household]);

  if (!plan) {
    return (
      <section>
        <h2>Résultat</h2>
        <p className="card muted">Aucun plan pour l'instant — passez par l'onglet Génération.</p>
      </section>
    );
  }

  const t = plan.diagnostic.objective_terms_cents;
  const currentPlan = plan;  // non-nul ici : narrowing conservé dans commit()
  const maxAbs = t
    ? Math.max(...TERM_LABELS.map(([k]) => Math.abs(Number(t[k])))) || 1
    : 1;
  const disbursed = plan.grocery_list_by_store
    .reduce((s, g) => s + Number(g.subtotal_cents_cad), 0);
  const pantryValue = Number(plan.diagnostic.pantry_consumed_value_cents);

  async function commit() {
    setCommitting(true); setError(null);
    try {
      const r = await api.commitPlan(currentPlan.id);
      setCommitMsg(
        `Plan ${r.plan_id} commis : le stock consommé est décrémenté et les restes sont reportés au garde-manger (${Object.keys(r.pantry_after_commit).length} ingrédients mis à jour).`
      );
      props.onCommitted(currentPlan.id);
    } catch (e) { setError(String(e)); } finally { setCommitting(false); }
  }

  function toggleLock(recipeId: string) {
    setLockedIds((prev) => {
      const next = new Set(prev);
      if (next.has(recipeId)) next.delete(recipeId); else next.add(recipeId);
      return next;
    });
  }

  async function callReoptimize(lockedRecipeIds: string[], excludedRecipeIds: string[]) {
    setReoptimizing(true); setReoptimizeError(null); setReoptimizeMsg(null);
    try {
      const r = await api.reoptimizePlan(
        currentPlan.id, props.config, lockedRecipeIds, excludedRecipeIds
      );
      if (r.changes) {
        setReoptimizeMsg(describeChanges(r.changes));
      } else {
        setReoptimizeError(
          `Réoptimisation infaisable : ${r.plan.diagnostic.infeasibility_note ?? "voir le diagnostic"}.`
        );
      }
      props.onCommitted(r.plan.id);
    } catch (e) {
      setReoptimizeError(String(e));
    } finally {
      setReoptimizing(false); setReplacingId(null);
    }
  }

  async function replace(recipeId: string) {
    setReplacingId(recipeId);
    const others = currentPlan.menu.map((m) => m.recipe_id).filter((id) => id !== recipeId);
    await callReoptimize(others, [recipeId]);
  }

  async function reoptimizeLockedOnly() {
    await callReoptimize([...lockedIds], []);
  }

  return (
    <section>
      <h2>Résultat <span className="sub">— plan n°{plan.id} · {plan.status === "committed" ? "commis" : "proposé"}</span></h2>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Décomposition du coût</h2>
        {t && (
          <div className="decomp" role="img" aria-label="Décomposition du coût en cinq termes">
            {TERM_LABELS.map(([key, label, credit]) => {
              const v = Number(t[key]);
              const w = (Math.abs(v) / maxAbs) * 50;
              return (
                <div className="bar-row" key={key}>
                  <span className="bar-label">{label}</span>
                  <span className="bar-track">
                    <span className="bar-axis" aria-hidden />
                    <span
                      className={`bar-fill ${credit ? "credit" : "debit"}`}
                      style={{ width: `${w}%` }}
                    />
                  </span>
                  <span className="bar-amount">{credit ? "−" : ""}{cents(v)}</span>
                </div>
              );
            })}
            <div className="bar-row grand">
              <span className="bar-label"><strong>Coût net</strong></span>
              <span />
              <span className="bar-amount"><strong>{cents(t.total)}</strong></span>
            </div>
          </div>
        )}
        <p className="callout" style={{ marginTop: 14 }}>
          <strong>{cents(disbursed)} dépensés cette semaine</strong>
          {pantryValue > 0 && (
            <>, auxquels s'ajoutent <strong>{cents(pantryValue)}</strong> de
            garde-manger déjà payé et consommé par ce plan — un décaissement
            plus bas après un commit n'est pas une économie.</>
          )}
          {pantryValue === 0 && <> — aucun stock du garde-manger consommé.</>}
        </p>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Menu <span className="sub">— {plan.menu.reduce((s, m) => s + m.servings, 0)} portions</span></h2>
        <table className="ledger">
          <thead>
            <tr>
              <th>Recette</th><th className="num">Portions</th>
              <th className="num">Temps (h)</th><th className="num">Coût attribué</th>
              <th>Verrou</th><th></th>
            </tr>
          </thead>
          <tbody>
            {plan.menu.map((m) => (
              <tr key={m.recipe_id}>
                <td>{m.name}</td>
                <td className="num">{m.servings}</td>
                <td className="num">{Number(m.prep_time_h).toFixed(2)}</td>
                <td className="num">{cents(m.attributed_cost_cents_cad)}</td>
                <td>
                  <label>
                    <input
                      type="checkbox"
                      checked={lockedIds.has(m.recipe_id)}
                      disabled={reoptimizing}
                      onChange={() => toggleLock(m.recipe_id)}
                    />{" "}
                    Garder
                  </label>
                </td>
                <td>
                  <button
                    className="action"
                    onClick={() => replace(m.recipe_id)}
                    disabled={reoptimizing || lockedIds.has(m.recipe_id)}
                  >
                    {replacingId === m.recipe_id ? "Remplacement…" : "Remplacer"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 10 }}>
          <button
            className="action"
            onClick={reoptimizeLockedOnly}
            disabled={reoptimizing || lockedIds.size === 0}
          >
            {reoptimizing && !replacingId ? "Réoptimisation…" : "Réoptimiser le reste du menu"}
          </button>
          <span className="muted">
            Cochez « Garder » sur les recettes à conserver, puis réoptimisez le reste —
            ou remplacez une seule recette directement.
          </span>
        </div>
        {reoptimizeMsg && <p className="callout" style={{ marginTop: 10 }}>{reoptimizeMsg}</p>}
        {reoptimizeError && <p className="callout error">{reoptimizeError}</p>}
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Liste d'épicerie</h2>
        {itinerary.length > 1 && (
          <p className="muted">
            Itinéraire suggéré :{" "}
            {itinerary.map((s, i) => `${i + 1}. ${s.banner} (${s.km.toFixed(1)} km)`).join(" → ")}
          </p>
        )}
        {plan.grocery_list_by_store.map((g) => {
          const store = stores.find((s) => s.external_key === g.store_external_key);
          return (
            <div key={g.store_external_key} style={{ marginBottom: 18 }}>
              <h2>{store?.banner ?? g.store_external_key} <span className="sub">{store?.address}</span></h2>
              <table className="ledger">
                <thead>
                  <tr><th>Produit</th><th className="num">Qté</th><th className="num">Prix unit.</th><th className="num">Total taxé</th><th>Pour</th></tr>
                </thead>
                <tbody>
                  {g.lines.map((l) => (
                    <tr key={l.product_external_key}>
                      <td>{l.ingredient_name} <span className="muted">— {l.brand}, {l.package_unit}</span></td>
                      <td className="num">{l.units}</td>
                      <td className="num">{cents(l.unit_price_cents_cad)}</td>
                      <td className="num">{cents(l.taxed_total_cents_cad)}</td>
                      <td className="muted">{l.consumed_by.join(", ")}</td>
                    </tr>
                  ))}
                  <tr className="total">
                    <td>Sous-total {store?.banner ?? g.store_external_key}</td>
                    <td colSpan={2} />
                    <td className="num">{cents(g.subtotal_cents_cad)}</td>
                    <td />
                  </tr>
                </tbody>
              </table>
            </div>
          );
        })}
        <div className="row">
          <button
            className="action"
            onClick={commit}
            disabled={committing || plan.status === "committed"}
          >
            {plan.status === "committed" ? "Déjà commis" : committing ? "Commit…" : "Commettre ce plan"}
          </button>
          <span className="muted">
            Le commit décrémente le stock consommé et reporte les restes au garde-manger.
          </span>
        </div>
        {commitMsg && <p className="callout" style={{ marginTop: 10 }}>{commitMsg}</p>}
        {error && <p className="callout error">{error}</p>}
      </div>
    </section>
  );
}
