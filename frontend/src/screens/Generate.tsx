import { useState } from "react";
import { api } from "../api";
import { describeChanges } from "../changes";
import type { Plan, PantryPromptLine, SolverConfigInput } from "../types";

type Phase = "form" | "confirm-pantry" | "confirmed";
type PantryAnswer = "none" | "little" | "enough";

/** Écran 2 — Génération : bouton, état de résolution, gestion explicite du
 *  cas infaisable avec le message du diagnostic — puis, sur un plan
 *  optimal, confirmation du garde-manger en deux temps (pilote,
 *  docs/product-pilot.md) avant de passer à l'écran Résultat. Souschef ne
 *  demande pas un inventaire exhaustif : une liste courte, priorisée
 *  côté serveur, avec un choix « aucun / un peu / assez » — une quantité
 *  précise reste facultative. */
export default function GenerateScreen(props: {
  config: SolverConfigInput;
  onPlan: (p: Plan) => void;
  goToResult: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infeasible, setInfeasible] = useState<Plan | null>(null);

  const [phase, setPhase] = useState<Phase>("form");
  const [generatedPlan, setGeneratedPlan] = useState<Plan | null>(null);
  const [promptLines, setPromptLines] = useState<PantryPromptLine[]>([]);
  const [answers, setAnswers] = useState<Record<string, PantryAnswer>>({});
  const [exactQty, setExactQty] = useState<Record<string, string>>({});
  const [continuing, setContinuing] = useState(false);
  const [pantryError, setPantryError] = useState<string | null>(null);
  const [confirmMsg, setConfirmMsg] = useState<string | null>(null);
  const [finalPlan, setFinalPlan] = useState<Plan | null>(null);

  const enabled = Object.entries(props.config)
    .filter(([k, v]) => k.startsWith("enable_") && v)
    .map(([k]) => k.replace("enable_", ""));

  async function generate() {
    setBusy(true); setError(null); setInfeasible(null);
    try {
      const plan = await api.createPlan(props.config);
      if (plan.solver_status !== "Optimal") { setInfeasible(plan); return; }
      setGeneratedPlan(plan);
      try {
        const lines = await api.pantryPrompt(plan.id);
        setPromptLines(lines);
        setAnswers({});
        setExactQty({});
        setPhase("confirm-pantry");
      } catch {
        // La confirmation du garde-manger est un raffinement, pas un
        // blocage : si la liste priorisée échoue à charger, on continue
        // directement vers le résultat plutôt que de bloquer l'utilisateur.
        props.onPlan(plan);
        props.goToResult();
      }
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  function setAnswer(id: string, a: PantryAnswer) {
    setAnswers((prev) => ({ ...prev, [id]: a }));
  }

  async function confirmPantry() {
    if (!generatedPlan) return;
    setContinuing(true); setPantryError(null);
    try {
      const lines = promptLines
        .filter((l) => (answers[l.canonical_ingredient_id] ?? "none") !== "none")
        .map((l) => {
          const exact = exactQty[l.canonical_ingredient_id];
          const needed = Number(l.needed_quantity_base_unit);
          const qty = exact
            ? Number(exact)
            : answers[l.canonical_ingredient_id] === "enough" ? needed : needed / 2;
          return { canonical_ingredient_id: l.canonical_ingredient_id, quantity_base_unit: qty };
        });
      if (lines.length) await api.updatePantry(lines);

      const r = await api.reoptimizePlan(
        generatedPlan.id, { ...props.config, enable_pantry_stock: true }, [], []
      );
      setFinalPlan(r.plan);
      setConfirmMsg(
        r.changes
          ? describeChanges(r.changes)
          : `Réoptimisation infaisable avec le garde-manger déclaré : ${r.plan.diagnostic.infeasibility_note ?? "voir le diagnostic"}.`
      );
      setPhase("confirmed");
    } catch (e) {
      setPantryError(String(e));
    } finally {
      setContinuing(false);
    }
  }

  function skipPantry() {
    if (!generatedPlan) return;
    props.onPlan(generatedPlan);
    props.goToResult();
  }

  function seeResult() {
    props.onPlan(finalPlan ?? generatedPlan!);
    props.goToResult();
  }

  return (
    <section>
      <h2>Génération <span className="sub">— une résolution, un plan persisté</span></h2>

      {phase === "form" && (
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
      )}

      {phase === "confirm-pantry" && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Garde-manger</h2>
          <p className="muted">
            Avez-vous déjà certains de ces ingrédients ? Une quantité précise
            reste facultative — « un peu » ou « assez » suffit.
          </p>
          {promptLines.length === 0 ? (
            <p className="muted">Rien de particulier à confirmer pour ce menu.</p>
          ) : (
            <table className="ledger">
              <thead>
                <tr>
                  <th>Ingrédient</th><th className="num">Aucun</th>
                  <th className="num">Un peu</th><th className="num">Assez</th>
                  <th>Quantité exacte (optionnel)</th>
                </tr>
              </thead>
              <tbody>
                {promptLines.map((l) => (
                  <tr key={l.canonical_ingredient_id}>
                    <td>{l.name}</td>
                    {(["none", "little", "enough"] as const).map((opt) => (
                      <td className="num" key={opt}>
                        <input
                          type="radio"
                          name={`pantry-${l.canonical_ingredient_id}`}
                          checked={(answers[l.canonical_ingredient_id] ?? "none") === opt}
                          onChange={() => setAnswer(l.canonical_ingredient_id, opt)}
                        />
                      </td>
                    ))}
                    <td>
                      <input
                        type="number" min={0}
                        placeholder={l.base_unit}
                        value={exactQty[l.canonical_ingredient_id] ?? ""}
                        onChange={(e) =>
                          setExactQty((prev) => ({ ...prev, [l.canonical_ingredient_id]: e.target.value }))
                        }
                        style={{ width: 90 }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="row" style={{ marginTop: 10 }}>
            <button className="action" onClick={confirmPantry} disabled={continuing}>
              {continuing ? "Réoptimisation…" : "Continuer"}
            </button>
            <button className="action" onClick={skipPantry} disabled={continuing}>
              Passer — garder ce plan
            </button>
          </div>
          {pantryError && <p className="callout error">{pantryError}</p>}
        </div>
      )}

      {phase === "confirmed" && (
        <div className="card">
          <p className="callout">{confirmMsg}</p>
          <button className="action" onClick={seeResult}>Voir le résultat</button>
        </div>
      )}
    </section>
  );
}
