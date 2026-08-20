import { useState } from "react";
import { api, messageOf } from "../api";
import { describeChanges } from "../changes";
import type { Household, Plan, SolverConfigInput, Store } from "../types";
import ResultScreen from "./Result";

/** Écran 1 — Planification : orchestrateur entre la génération, la
 *  confirmation post-génération et le résultat. État initial : seulement
 *  le bouton Générer. Une fois un plan optimal obtenu, une liste de
 *  confirmation s'intercale (pilote, docs/product-pilot.md — remplace le
 *  garde-manger à quantité suivie) : tous les ingrédients requis par le
 *  menu, essentiels pré-décochés (supposés déjà présents), le reste
 *  pré-coché (à acheter de toute façon). L'usager corrige ce qui manque
 *  réellement, puis ``finalize_plan`` verrouille le menu et détermine la
 *  logistique d'achat finale. Une fois confirmé, l'écran affiche le
 *  résultat (ses propres sous-onglets « Cette semaine »/« Épicerie »,
 *  `Result.tsx`, inchangé). */
export default function PlanningScreen(props: {
  config: SolverConfigInput;
  plan: Plan | null;
  household: Household;
  stores: Store[];
  onPlan: (p: Plan) => void;
  onCommitted: (planId: number) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infeasible, setInfeasible] = useState<Plan | null>(null);
  // Génération et Résultat étaient deux onglets séparés — fusionnés ici,
  // il faut un moyen de revenir au formulaire même quand un plan existe
  // déjà (sinon Planification reste coincée sur le dernier résultat).
  const [forceForm, setForceForm] = useState(false);

  // Confirmation post-génération : plan généré mais pas encore finalisé,
  // en attente de correction de la liste d'ingrédients à acheter.
  const [pendingPlan, setPendingPlan] = useState<Plan | null>(null);
  const [toBuy, setToBuy] = useState<Record<string, boolean>>({});
  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);
  const [finalizeMsg, setFinalizeMsg] = useState<string | null>(null);

  const enabled = Object.entries(props.config)
    .filter(([k, v]) => k.startsWith("enable_") && v)
    .map(([k]) => k.replace("enable_", ""));

  async function generate() {
    setBusy(true); setError(null); setInfeasible(null); setFinalizeMsg(null);
    try {
      const plan = await api.createPlan(props.config);
      if (plan.solver_status !== "Optimal") { setInfeasible(plan); return; }
      setPendingPlan(plan);
      setToBuy(Object.fromEntries(
        plan.needed_ingredients.map((l) => [l.canonical_ingredient_id, !l.is_staple])
      ));
      setForceForm(false);
    } catch (e) { setError(messageOf(e)); } finally { setBusy(false); }
  }

  async function confirm() {
    if (!pendingPlan) return;
    setFinalizing(true); setFinalizeError(null);
    try {
      const confirmedAvailableIds = pendingPlan.needed_ingredients
        .filter((l) => !toBuy[l.canonical_ingredient_id])
        .map((l) => l.canonical_ingredient_id);
      const r = await api.finalizePlan(pendingPlan.id, props.config, confirmedAvailableIds);
      if (r.changes) setFinalizeMsg(describeChanges(r.changes));
      props.onPlan(r.plan);
      setPendingPlan(null);
    } catch (e) { setFinalizeError(messageOf(e)); } finally { setFinalizing(false); }
  }

  if (pendingPlan) {
    return (
      <section>
        <h2>Confirmer les ingrédients <span className="sub">— corrigez ce que vous avez déjà</span></h2>
        <div className="card">
          <p className="muted" style={{ margin: "0 0 14px" }}>
            Les essentiels sont pré-décochés (supposés déjà présents) ; le
            reste est pré-coché (à acheter de toute façon). Corrigez ce qui
            manque réellement, puis confirmez pour verrouiller le menu et
            obtenir la liste d'épicerie finale.
          </p>
          <div className="table-scroll">
            <table className="ledger">
              <thead><tr><th>À acheter</th><th>Ingrédient</th></tr></thead>
              <tbody>
                {pendingPlan.needed_ingredients.map((l) => (
                  <tr key={l.canonical_ingredient_id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={Boolean(toBuy[l.canonical_ingredient_id])}
                        onChange={() => setToBuy((prev) => ({
                          ...prev, [l.canonical_ingredient_id]: !prev[l.canonical_ingredient_id],
                        }))}
                      />
                    </td>
                    <td>
                      {l.name}
                      {l.is_staple && <span className="badge" style={{ marginLeft: 6 }}>Essentiel</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 14 }}>
            <button className="action" onClick={confirm} disabled={finalizing}>
              {finalizing ? <><span className="spin" aria-hidden />Confirmation…</> : "Confirmer"}
            </button>
            {finalizeError && <span className="callout error">{finalizeError}</span>}
          </div>
        </div>
      </section>
    );
  }

  if (props.plan && !forceForm) {
    return (
      <>
        <div className="row" style={{ margin: "18px 0 -8px" }}>
          <button className="action ghost" onClick={() => setForceForm(true)}>
            ‹ Générer un nouveau plan
          </button>
        </div>
        {finalizeMsg && <p className="callout" style={{ margin: "10px 0" }}>{finalizeMsg}</p>}
        <ResultScreen
          plan={props.plan} household={props.household} stores={props.stores}
          config={props.config} onCommitted={props.onCommitted}
        />
      </>
    );
  }

  return (
    <section>
      <h2>Planification <span className="sub">— une résolution, un plan persisté</span></h2>
      <div className="card">
        <p>
          Mécanismes actifs :{" "}
          {enabled.length
            ? enabled.map((f) => <span key={f} className="badge" style={{ marginRight: 6 }}>{f}</span>)
            : <span className="muted">aucun — configuration de développement (un magasin, appétence en objectif)</span>}
        </p>
        <p className="muted">Les drapeaux se règlent dans l'onglet Paramètres (mode développeur).</p>
        <button className="action" onClick={generate} disabled={busy}>
          {busy ? <><span className="spin" aria-hidden />Résolution en cours…</> : "Générer le plan de la semaine"}
        </button>
        {error && <p className="callout error" role="alert">{error}</p>}
        {infeasible && (
          <div className="callout error" role="alert" style={{ marginTop: 14 }}>
            <strong>Infaisable ({infeasible.solver_status}).</strong>{" "}
            {infeasible.diagnostic.infeasibility_note}
            <div className="muted" style={{ marginTop: 6 }}>
              Assertions passées : {infeasible.diagnostic.assertions_passed.join(", ") || "—"}.
              Dernier drapeau activé : <span className="mono">{infeasible.diagnostic.last_enabled_flag ?? "aucun"}</span>.
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
