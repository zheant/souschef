import { useEffect, useState } from "react";
import { api, messageOf } from "../api";
import { describeChanges } from "../changes";
import type { Household, Plan, PriceCoverage, SolverConfigInput, Store } from "../types";
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
/** Aujourd'hui en ISO local — `toISOString()` passe par UTC et décale d'un
 *  jour en soirée au Québec (UTC−4/−5). */
function isoToday(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const TODAY = isoToday();

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
  // Date du plan. Le solveur n'accepte que les prix dont la fenêtre de
  // validité la contient : hors couverture, aucune recette ne survit au
  // préfiltrage. Le défaut vise aujourd'hui, et retombe sur la dernière date
  // couverte quand les circulaires chargées sont plus anciennes — sinon le
  // seul recours était de découvrir la borne par un échec.
  const [coverage, setCoverage] = useState<PriceCoverage | null>(null);
  const [onDate, setOnDate] = useState<string>(TODAY);
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

  useEffect(() => {
    api.priceCoverage()
      .then((c) => {
        setCoverage(c);
        if (c.latest && TODAY > c.latest) setOnDate(c.latest);
        else if (c.earliest && TODAY < c.earliest) setOnDate(c.earliest);
      })
      .catch(() => setCoverage(null)); // information d'appoint : son absence
                                       // ne doit pas bloquer la génération.
  }, []);

  const outsideCoverage = Boolean(
    coverage?.earliest && coverage.latest &&
    (onDate < coverage.earliest || onDate > coverage.latest),
  );

  const enabled = Object.entries(props.config)
    .filter(([k, v]) => k.startsWith("enable_") && v)
    .map(([k]) => k.replace("enable_", ""));

  async function generate() {
    setBusy(true); setError(null); setInfeasible(null); setFinalizeMsg(null);
    try {
      const plan = await api.createPlan(props.config, onDate);
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
        <div className="row" style={{ gap: 10, alignItems: "baseline", margin: "0 0 14px" }}>
          <label htmlFor="on-date">Semaine du plan</label>
          <input
            id="on-date" type="date" value={onDate}
            min={coverage?.earliest ?? undefined}
            max={coverage?.latest ?? undefined}
            onChange={(e) => setOnDate(e.target.value)}
          />
          {coverage?.earliest && coverage.latest && (
            <span className="muted">
              prix chargés du {coverage.earliest} au {coverage.latest}
              {onDate !== TODAY && " — aujourd'hui n'est pas couvert"}
            </span>
          )}
        </div>
        {outsideCoverage && (
          <p className="callout" role="status" style={{ margin: "0 0 14px" }}>
            Aucun prix chargé ne couvre le {onDate} : la génération échouera.
            Choisir une date entre {coverage?.earliest} et {coverage?.latest},
            ou rafraîchir les circulaires.
          </p>
        )}
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
