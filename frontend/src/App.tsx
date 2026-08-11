import { useEffect, useState } from "react";
import { api } from "./api";
import type { Household, Plan, SolverConfigInput, Store } from "./types";
import DiagnosticScreen from "./screens/Diagnostic";
import HouseholdScreen from "./screens/Household";
import PlanningScreen from "./screens/Planning";
import "./styles.css";

// Trois onglets (pilote, docs/product-pilot.md) — fusion de ce qui était
// cinq onglets séparés : Génération+Résultat -> Planification,
// Ménage+Garde-manger -> Ménage (sous-onglets internes), Diagnostic ->
// Paramètres (fonctions développeur, pour l'instant).
const TABS = ["Planification", "Ménage", "Paramètres"] as const;
type Tab = (typeof TABS)[number];

// Défaut de développement (spec) : tout à false, un magasin, appétence en
// objectif — on rallume un mécanisme à la fois depuis l'onglet Paramètres.
const DEV_DEFAULT: SolverConfigInput = {
  appetence_mode: "objective", solver_time_limit_s: 120, mip_gap: 0.005,
};

export default function App() {
  const [tab, setTab] = useState<Tab>("Planification");
  const [household, setHousehold] = useState<Household | null>(null);
  const [stores, setStores] = useState<Store[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [config, setConfig] = useState<SolverConfigInput>(DEV_DEFAULT);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.household(), api.stores()])
      .then(([h, s]) => { setHousehold(h); setStores(s); })
      .catch((e) => setError(String(e)));
  }, []);

  async function refreshPlan(planId: number) {
    setPlan(await api.getPlan(planId));
  }

  return (
    <div className="shell">
      <header className="masthead">
        <h1>Menu Optimizer</h1>
        <span className="week">v1 — circulaires de la semaine</span>
      </header>
      <nav className="tabs" aria-label="Écrans">
        {TABS.map((t) => (
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>

      {error && <p className="callout error" role="alert">{error} — l'API est-elle démarrée ?</p>}
      {!household && !error && <p className="muted"><span className="spin" aria-hidden />Chargement du profil…</p>}

      {household && tab === "Planification" && (
        <PlanningScreen
          config={config} plan={plan} household={household} stores={stores}
          onPlan={setPlan} onCommitted={refreshPlan}
        />
      )}
      {household && tab === "Ménage" && (
        <HouseholdScreen household={household} onSaved={setHousehold} />
      )}
      {household && tab === "Paramètres" && (
        <DiagnosticScreen config={config} setConfig={setConfig} plan={plan} />
      )}
    </div>
  );
}
