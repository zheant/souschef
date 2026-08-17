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
// Barre du bas à icônes seules (maquette « Agrumes frais ») plutôt que des
// onglets textuels en haut — nom accessible via aria-label, pas de libellé
// visible (même pari que la maquette : trois destinations, apprenables).
const CALENDAR_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="4" width="18" height="18" rx="4" /><path d="M3 10h18M9 4v16" />
  </svg>
);
const HOUSE_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" />
  </svg>
);
const GEAR_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 004.6 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 4.6a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
  </svg>
);
const TABS = [
  { key: "Planification", icon: CALENDAR_ICON },
  { key: "Ménage", icon: HOUSE_ICON },
  { key: "Paramètres", icon: GEAR_ICON },
] as const;
type Tab = (typeof TABS)[number]["key"];

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
      </header>

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

      <nav className="tabbar" aria-label="Écrans">
        {TABS.map((t) => (
          <button
            key={t.key} aria-label={t.key} title={t.key}
            className={t.key === tab ? "active" : ""}
            onClick={() => setTab(t.key)}
          >
            {t.icon}
          </button>
        ))}
      </nav>
    </div>
  );
}
