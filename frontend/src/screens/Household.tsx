import { useState } from "react";
import { api, messageOf } from "../api";
import type { Household, Member } from "../types";
import { StaplesPanel } from "./Staples";

/** Écran 2 — Ménage : trois sous-sections (Essentiels/Membres/
 *  Préférences), fusion de ce qui était trois écrans séparés dans la
 *  navigation à 5 onglets. D est calculé EN DIRECT côté client au fil de
 *  la frappe, puis confirmé par le serveur à la sauvegarde.
 *
 *  Pilote (docs/product-pilot.md) : « les coefficients d'appétit ne sont pas
 *  exposés » — ρ_h se choisit par catégorie (petit/moyen/grand), pas par
 *  nombre libre. Le résumé en langage naturel ("4 personnes, 9 repas à
 *  prévoir...") reste visible quel que soit le sous-onglet actif — c'est un
 *  aperçu du ménage dans son ensemble, pas propre à Membres ou Préférences.
 *  κ, ε, K, R_min, α et l'adresse restent des champs numériques exacts,
 *  repliés sous « Paramètres avancés » — déplacés dans Préférences (décision
 *  explicite : ce sont des réglages du ménage, pas des outils de
 *  développement, même si ce sont des chiffres exacts plutôt que des
 *  préférences). */

type SubTab = "essentiels" | "membres" | "preferences";

const APPETITE_LEVELS = [
  { value: 0.6, label: "Petit appétit" },
  { value: 1.0, label: "Appétit moyen" },
  { value: 1.4, label: "Grand appétit" },
] as const;

function presetFor(rho: number) {
  return APPETITE_LEVELS.find((l) => Math.abs(l.value - rho) < 0.001);
}

function tempoLabel(h: number): string {
  if (h <= 1) return "rapide";
  if (h <= 2) return "modérée";
  return "longue";
}

function storeLabel(k: number): string {
  return k <= 1 ? "une épicerie privilégiée" : `jusqu'à ${k} épiceries`;
}

function varietyLabel(rMin: number): string {
  if (rMin <= 2) return "faible";
  if (rMin <= 4) return "moyenne";
  return "élevée";
}

export default function HouseholdScreen(props: {
  household: Household; onSaved: (h: Household) => void;
}) {
  const h = props.household;
  const [subTab, setSubTab] = useState<SubTab>("membres");
  const [form, setForm] = useState({
    meals_per_horizon: h.meals_per_horizon,
    time_value_cents_per_hour: h.time_value_cents_per_hour,
    demand_slack_epsilon: h.demand_slack_epsilon,
    max_store_visits: h.max_store_visits,
    min_distinct_recipes: h.min_distinct_recipes,
    max_share_per_recipe: h.max_share_per_recipe,
    max_prep_time_per_meal_h: h.max_prep_time_per_meal_h,
    home_lat: h.home_lat, home_lng: h.home_lng,
    diet_flags: h.diet_flags.join(", "),
    allergen_flags: h.allergen_flags.join(", "),
    liked: (h.taste_preferences.liked_tags ?? []).join(", "),
    disliked: (h.taste_preferences.disliked_tags ?? []).join(", "),
    // Chaîne, pas nombre : `set()` convertit tout champ numérique avec
    // `Number()`, et `Number("")` vaut 0 — un plancher de 0 $, pas « aucun
    // plancher ». Les deux doivent rester distinguables jusqu'à la
    // sérialisation.
    u_min: h.appetence_u_min_dollars == null ? "" : String(h.appetence_u_min_dollars),
  });
  const [members, setMembers] = useState<Member[]>(h.members);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rhoSum = members.reduce((s, m) => s + (Number(m.appetite_coefficient) || 0), 0);
  const D = form.meals_per_horizon * rhoSum;
  const low = Math.ceil(D);
  const high = Math.ceil(D * (1 + Number(form.demand_slack_epsilon)));

  const summary =
    `${members.length} personne${members.length > 1 ? "s" : ""}, ` +
    `${form.meals_per_horizon} repas à prévoir, ` +
    `cuisine ${tempoLabel(form.max_prep_time_per_meal_h)}, ` +
    `${storeLabel(form.max_store_visits)}, ` +
    `variété ${varietyLabel(form.min_distinct_recipes)}.`;

  const set = (k: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });

  const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  async function save() {
    setSaving(true); setError(null);
    try {
      const saved = await api.updateHousehold({
        meals_per_horizon: form.meals_per_horizon,
        time_value_cents_per_hour: form.time_value_cents_per_hour,
        demand_slack_epsilon: form.demand_slack_epsilon,
        max_store_visits: form.max_store_visits,
        min_distinct_recipes: form.min_distinct_recipes,
        max_share_per_recipe: form.max_share_per_recipe,
        max_prep_time_per_meal_h: form.max_prep_time_per_meal_h,
        home_lat: form.home_lat, home_lng: form.home_lng,
        diet_flags: csv(form.diet_flags),
        allergen_flags: csv(form.allergen_flags),
        taste_preferences: { liked_tags: csv(form.liked), disliked_tags: csv(form.disliked) },
        // `null` explicite retire le plancher : la route sérialise avec
        // `exclude_unset`, donc envoyer la clé à `null` l'efface réellement.
        appetence_u_min_dollars: form.u_min.trim() === "" ? null : Number(form.u_min),
        members,
      });
      props.onSaved(saved);
    } catch (e) { setError(messageOf(e)); } finally { setSaving(false); }
  }

  return (
    <section>
      <h2>Ménage <span className="sub">— la source de vérité des paramètres</span></h2>
      <p className="callout">{summary}</p>

      <div className="subnav">
        <button className={subTab === "essentiels" ? "active" : ""} onClick={() => setSubTab("essentiels")}>
          Essentiels
        </button>
        <button className={subTab === "membres" ? "active" : ""} onClick={() => setSubTab("membres")}>
          Membres
        </button>
        <button className={subTab === "preferences" ? "active" : ""} onClick={() => setSubTab("preferences")}>
          Préférences
        </button>
      </div>

      {subTab === "essentiels" && <StaplesPanel />}

      {subTab === "membres" && (
        <>
          <div className="card">
            <div className="table-scroll">
              <table className="ledger" aria-label="Membres du ménage">
                <thead><tr><th>Membre</th><th>Appétit</th><th /></tr></thead>
                <tbody>
                  {members.map((m, i) => {
                    const rho = Number(m.appetite_coefficient);
                    const preset = presetFor(rho);
                    return (
                      <tr key={i}>
                        <td data-label="Membre"><input aria-label="nom" value={m.name}
                          onChange={(e) => setMembers(members.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} /></td>
                        <td data-label="Appétit">
                          <select
                            aria-label="appétit"
                            value={preset ? preset.value : "other"}
                            onChange={(e) => {
                              if (e.target.value === "other") return;
                              setMembers(members.map((x, j) => j === i ? { ...x, appetite_coefficient: Number(e.target.value) } : x));
                            }}
                          >
                            {!preset && <option value="other">Autre ({rho.toFixed(2)})</option>}
                            {APPETITE_LEVELS.map((l) => (
                              <option key={l.value} value={l.value}>{l.label}</option>
                            ))}
                          </select>
                        </td>
                        <td><button className="action ghost" onClick={() => setMembers(members.filter((_, j) => j !== i))}>Retirer</button></td>
                      </tr>
                    );
                  })}
                  <tr className="total">
                    <td colSpan={2}>
                      <button className="action ghost" onClick={() => setMembers([...members, { name: "Nouveau", appetite_coefficient: 1.0 }])}>
                        Ajouter un membre
                      </button>
                    </td>
                    <td />
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <SaveBar saving={saving} error={error} onSave={save} />
        </>
      )}

      {subTab === "preferences" && (
        <>
          <div className="card">
            <div className="grid">
              <label className="field"><span>Repas sur l'horizon</span>
                <input type="number" min="1" value={form.meals_per_horizon} onChange={set("meals_per_horizon")} /></label>
              <label className="field"><span>Séance de cuisine max. (h)</span>
                <input type="number" min="0.25" step="0.25" value={form.max_prep_time_per_meal_h} onChange={set("max_prep_time_per_meal_h")} /></label>
              <label className="field"><span>Régimes (séparés par des virgules)</span>
                <input value={form.diet_flags} onChange={set("diet_flags")} placeholder="vegetarien" /></label>
              <label className="field"><span>Allergènes à exclure</span>
                <input value={form.allergen_flags} onChange={set("allergen_flags")} placeholder="arachide, lactose" /></label>
              <label className="field"><span>Cuisines aimées</span>
                <input value={form.liked} onChange={set("liked")} placeholder="tex-mex, asiatique" /></label>
              <label className="field"><span>Cuisines évitées</span>
                <input value={form.disliked} onChange={set("disliked")} /></label>
              <label className="field">
                <span>Plancher d'appétence ($) <em>(vide = aucun)</em></span>
                <input
                  type="text" inputMode="decimal" value={form.u_min}
                  onChange={(e) => setForm({ ...form, u_min: e.target.value })}
                  placeholder="ex. 65"
                />
              </label>
            </div>
            <p className="muted" style={{ marginTop: 4 }}>
              Sans plancher, le menu part vers les recettes les moins chères :
              l'appétence n'est qu'un crédit dans l'objectif, donc tout plat
              bon marché l'emporte. Un plancher inverse la question — minimiser
              le coût <em>sous</em> une appétence exigée. Plus il monte, plus le
              menu suit vos goûts et plus l'épicerie coûte.
            </p>

            <details style={{ marginTop: 16 }}>
              <summary className="muted" style={{ cursor: "pointer" }}>Paramètres avancés</summary>
              <p className="callout" style={{ marginTop: 12 }}>
                Demande de l'horizon : D = {form.meals_per_horizon} × {rhoSum.toFixed(2)} ={" "}
                <strong className="mono">{D.toFixed(2)} portions</strong> — le solveur produira entre{" "}
                <span className="mono">{low}</span> et <span className="mono">{high}</span> portions
                (ε = {form.demand_slack_epsilon}).
              </p>
              <div className="grid" style={{ marginTop: 12 }}>
                <label className="field"><span>Valeur du temps κ (cents/h)</span>
                  <input type="number" min="0" step="100" value={form.time_value_cents_per_hour} onChange={set("time_value_cents_per_hour")} /></label>
                <label className="field"><span>Marge de demande ε</span>
                  <input type="number" min="0" max="0.9" step="0.05" value={form.demand_slack_epsilon} onChange={set("demand_slack_epsilon")} /></label>
                <label className="field"><span>Arrêts maximum K</span>
                  <input type="number" min="1" value={form.max_store_visits} onChange={set("max_store_visits")} /></label>
                <label className="field"><span>Recettes distinctes min. R_min</span>
                  <input type="number" min="1" value={form.min_distinct_recipes} onChange={set("min_distinct_recipes")} /></label>
                <label className="field"><span>Part max. d'une recette α</span>
                  <input type="number" min="0.05" max="1" step="0.05" value={form.max_share_per_recipe} onChange={set("max_share_per_recipe")} /></label>
                <label className="field"><span>Domicile — latitude</span>
                  <input type="number" step="0.0001" value={form.home_lat} onChange={set("home_lat")} /></label>
                <label className="field"><span>Domicile — longitude</span>
                  <input type="number" step="0.0001" value={form.home_lng} onChange={set("home_lng")} /></label>
              </div>
            </details>
          </div>
          <SaveBar saving={saving} error={error} onSave={save} />
        </>
      )}
    </section>
  );
}

/** Barre d'action collante — visible sur Membres et Préférences puisque
 *  les deux partagent le même appel api.updateHousehold et le même état de
 *  formulaire ; Essentiels a son propre bouton Enregistrer (StaplesPanel),
 *  indépendant. */
function SaveBar(props: { saving: boolean; error: string | null; onSave: () => void }) {
  return (
    <div className="sticky-bar">
      {props.error && <span className="callout error">{props.error}</span>}
      <button className="action" onClick={props.onSave} disabled={props.saving}>
        {props.saving ? "Enregistrement…" : "Enregistrer le profil"}
      </button>
    </div>
  );
}
