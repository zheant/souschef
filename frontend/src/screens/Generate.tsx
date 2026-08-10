import { useState } from "react";
import { api } from "../api";
import type { Plan, SolverConfigInput } from "../types";

/** Écran 2 — Génération : bouton, état de résolution, gestion explicite du
 *  cas infaisable avec le message du diagnostic. */
export default function GenerateScreen(props: {
  config: SolverConfigInput;
  onPlan: (p: Plan) => void;
  goToResult: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infeasible, setInfeasible] = useState<Plan | null>(null);

  const enabled = Object.entries(props.config)
    .filter(([k, v]) => k.startsWith("enable_") && v)
    .map(([k]) => k.replace("enable_", ""));

  async function generate() {
    setBusy(true); setError(null); setInfeasible(null);
    try {
      const plan = await api.createPlan(props.config);
      if (plan.solver_status !== "Optimal") { setInfeasible(plan); return; }
      props.onPlan(plan);
      props.goToResult();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  return (
    <section>
      <h2>Génération <span className="sub">— une résolution, un plan persisté</span></h2>
      <div className="card">
        <p>
          Mécanismes actifs :{" "}
          {enabled.length
            ? enabled.map((f) => <span key={f} className="badge" style={{ marginRight: 6 }}>{f}</span>)
            : <span className="muted">aucun — configuration de développement (un magasin, appétence en objectif)</span>}
        </p>
        <p className="muted">Les drapeaux se règlent dans l'onglet Diagnostic (mode développeur).</p>
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
