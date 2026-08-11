import { useState } from "react";
import { api } from "../api";
import type { Household, Plan, SolverConfigInput, Store } from "../types";
import ResultScreen from "./Result";

/** Écran 1 — Planification : orchestrateur mince entre la génération et le
 *  résultat. État initial : seulement le bouton Générer. Une fois un plan
 *  optimal obtenu, l'écran affiche directement le résultat (ses propres
 *  sous-onglets « Cette semaine »/« Épicerie », `Result.tsx`, inchangé).
 *
 *  La confirmation du garde-manger en deux temps (aucun/un peu/assez) qui
 *  vivait ici a été retirée (pilote, docs/product-pilot.md) : elle faisait
 *  double emploi avec « à acheter » dans la sous-catégorie garde-manger de
 *  la liste d'épicerie — un mécanisme réactif (corriger après coup)
 *  remplace le mécanisme proactif (déclarer avant), pas les deux à la
 *  fois. */
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

  const enabled = Object.entries(props.config)
    .filter(([k, v]) => k.startsWith("enable_") && v)
    .map(([k]) => k.replace("enable_", ""));

  async function generate() {
    setBusy(true); setError(null); setInfeasible(null);
    try {
      const plan = await api.createPlan(props.config);
      if (plan.solver_status !== "Optimal") { setInfeasible(plan); return; }
      props.onPlan(plan);
      setForceForm(false);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  if (props.plan && !forceForm) {
    return (
      <>
        <div className="row" style={{ margin: "18px 0 -8px" }}>
          <button className="action ghost" onClick={() => setForceForm(true)}>
            ‹ Générer un nouveau plan
          </button>
        </div>
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
