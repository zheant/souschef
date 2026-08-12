import type { Plan, SolverConfigInput } from "../types";

/** Écran 3 — Paramètres : pour l'instant, uniquement les fonctions
 *  développeur (rapport complet + drapeaux du SolverConfig modifiables).
 *  Outil de travail : exhaustif avant d'être joli (spec). Un vrai écran de
 *  réglages utilisateur, distinct du mode développeur, reste un chantier
 *  séparé. */

const FLAGS: (keyof SolverConfigInput)[] = [
  "enable_multi_store", "enable_batch_fixed_cost", "enable_salvage",
  "enable_perishable_penalty", "enable_time_cost", "enable_staples",
  "enable_diversity",
];

export default function DiagnosticScreen(props: {
  config: SolverConfigInput;
  setConfig: (c: SolverConfigInput) => void;
  plan: Plan | null;
}) {
  const { config, setConfig, plan } = props;
  const d = plan?.diagnostic;

  const num = (k: keyof SolverConfigInput, label: string, step = 1) => (
    <label className="field" key={String(k)}>
      <span>{label} <em>(vide = profil)</em></span>
      <input
        type="number" step={step}
        value={config[k] == null ? "" : String(config[k])}
        onChange={(e) =>
          setConfig({ ...config, [k]: e.target.value === "" ? null : Number(e.target.value) })}
      />
    </label>
  );

  return (
    <section>
      <h2>Paramètres <span className="sub">— mode développeur : on rallume un mécanisme à la fois</span></h2>

      <div className="card">
        <div className="flags">
          {FLAGS.map((f) => (
            <label key={String(f)}>
              <input type="checkbox" checked={Boolean(config[f])}
                onChange={(e) => setConfig({ ...config, [f]: e.target.checked })} />
              <span className="mono">{String(f)}</span>
            </label>
          ))}
        </div>
        <div className="grid" style={{ marginTop: 16 }}>
          <label className="field"><span>Mode d'appétence</span>
            <select value={config.appetence_mode ?? "objective"}
              onChange={(e) => setConfig({ ...config, appetence_mode: e.target.value as "objective" | "constraint" })}>
              <option value="objective">objective (−Σu·x)</option>
              <option value="constraint">constraint (Σu·x ≥ U_min)</option>
            </select>
          </label>
          {config.appetence_mode === "constraint" &&
            num("appetence_u_min_dollars", "U_min ($)", 0.5)}
          {num("max_store_visits", "Surcharge K")}
          {num("min_distinct_recipes", "Surcharge R_min")}
          {num("max_share_per_recipe", "Surcharge α", 0.05)}
          {num("demand_slack_epsilon", "Surcharge ε", 0.05)}
          <label className="field"><span>Limite de temps solveur (s)</span>
            <input type="number" min="1" value={config.solver_time_limit_s ?? 60}
              onChange={(e) => setConfig({ ...config, solver_time_limit_s: Number(e.target.value) })} /></label>
          <label className="field"><span>Gap MIP</span>
            <input type="number" min="0" step="0.001" value={config.mip_gap ?? 0.001}
              onChange={(e) => setConfig({ ...config, mip_gap: Number(e.target.value) })} /></label>
        </div>
      </div>

      {!d && <p className="card muted">Générez un plan pour voir son rapport.</p>}
      {d && (
        <div className="card">
          <div className="table-scroll">
            <table className="ledger">
              <tbody>
                <tr><td>Statut / temps</td><td className="num">{d.solver_status} en {d.solve_time_s}s</td></tr>
                <tr><td>Gap MIP demandé / atteint</td>
                  <td className="num">{d.mip_gap_requested} / {d.mip_gap_attained ?? "non exposé par CBC"}</td></tr>
                <tr><td>Demande</td>
                  <td className="num">{Object.entries(d.demand).map(([k, v]) => `${k}=${v}`).join("  ")}</td></tr>
                <tr><td>Recettes distinctes / part max</td>
                  <td className="num">{d.distinct_recipes} / {d.max_share_of_demand ?? "—"}</td></tr>
                <tr><td>Préfiltrage</td>
                  <td className="num">{Object.entries(d.prefilter_counts).map(([k, v]) => `${k}:${v}`).join(" → ")}</td></tr>
                <tr><td>Paramètres effectifs</td>
                  <td className="num">
                    {Object.entries(d.effective_params)
                      .map(([k, v]) => `${k}=${v.valeur} (${v.provenance})`).join("  ·  ")}
                  </td></tr>
                <tr><td>Drapeaux altérant les besoins</td>
                  <td className="num">{(d.flag_effects.alterent_les_besoins_en_ingredients ?? []).join(", ") || "aucun"}</td></tr>
                <tr><td>Assertions passées</td>
                  <td className="num">{d.assertions_passed.length}/7</td></tr>
              </tbody>
            </table>
          </div>
          <h2>Rapport brut</h2>
          <pre className="raw">{JSON.stringify(d, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}
