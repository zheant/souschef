import { useState } from "react";
import { api } from "../api";
import type { Household, Member } from "../types";

/** Écran 1 — Ménage : membres et ρ_h, repas, κ, filtres durs, adresse,
 *  diversité. D est calculé EN DIRECT côté client au fil de la frappe, puis
 *  confirmé par le serveur à la sauvegarde. */
export default function HouseholdScreen(props: {
  household: Household; onSaved: (h: Household) => void;
}) {
  const h = props.household;
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
  });
  const [members, setMembers] = useState<Member[]>(h.members);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rhoSum = members.reduce((s, m) => s + (Number(m.appetite_coefficient) || 0), 0);
  const D = form.meals_per_horizon * rhoSum;
  const low = Math.ceil(D);
  const high = Math.ceil(D * (1 + Number(form.demand_slack_epsilon)));

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
        members,
      });
      props.onSaved(saved);
    } catch (e) { setError(String(e)); } finally { setSaving(false); }
  }

  return (
    <section>
      <h2>Ménage <span className="sub">— la source de vérité des paramètres</span></h2>

      <div className="card">
        <table className="ledger" aria-label="Membres du ménage">
          <thead><tr><th>Membre</th><th className="num">Coefficient d'appétit ρ</th><th /></tr></thead>
          <tbody>
            {members.map((m, i) => (
              <tr key={i}>
                <td><input aria-label="nom" value={m.name}
                  onChange={(e) => setMembers(members.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} /></td>
                <td className="num"><input type="number" step="0.1" min="0.1" value={m.appetite_coefficient}
                  onChange={(e) => setMembers(members.map((x, j) => j === i ? { ...x, appetite_coefficient: Number(e.target.value) } : x))} /></td>
                <td><button className="action ghost" onClick={() => setMembers(members.filter((_, j) => j !== i))}>Retirer</button></td>
              </tr>
            ))}
            <tr className="total">
              <td>Σρ = <span className="mono">{rhoSum.toFixed(2)}</span></td>
              <td className="num" colSpan={2}>
                <button className="action ghost" onClick={() => setMembers([...members, { name: "Nouveau", appetite_coefficient: 1.0 }])}>
                  Ajouter un membre
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p className="callout" style={{ marginTop: 12 }}>
          Demande de l'horizon : D = {form.meals_per_horizon} × {rhoSum.toFixed(2)} ={" "}
          <strong className="mono">{D.toFixed(2)} portions</strong> — le solveur produira entre{" "}
          <span className="mono">{low}</span> et <span className="mono">{high}</span> portions
          (ε = {form.demand_slack_epsilon}).
        </p>
      </div>

      <div className="card">
        <div className="grid">
          <label className="field"><span>Repas sur l'horizon</span>
            <input type="number" min="1" value={form.meals_per_horizon} onChange={set("meals_per_horizon")} /></label>
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
          <label className="field"><span>Séance de cuisine max. (h)</span>
            <input type="number" min="0.25" step="0.25" value={form.max_prep_time_per_meal_h} onChange={set("max_prep_time_per_meal_h")} /></label>
          <label className="field"><span>Domicile — latitude</span>
            <input type="number" step="0.0001" value={form.home_lat} onChange={set("home_lat")} /></label>
          <label className="field"><span>Domicile — longitude</span>
            <input type="number" step="0.0001" value={form.home_lng} onChange={set("home_lng")} /></label>
          <label className="field"><span>Régimes (séparés par des virgules)</span>
            <input value={form.diet_flags} onChange={set("diet_flags")} placeholder="vegetarien" /></label>
          <label className="field"><span>Allergènes à exclure</span>
            <input value={form.allergen_flags} onChange={set("allergen_flags")} placeholder="arachide, lactose" /></label>
          <label className="field"><span>Cuisines aimées</span>
            <input value={form.liked} onChange={set("liked")} placeholder="tex-mex, asiatique" /></label>
          <label className="field"><span>Cuisines évitées</span>
            <input value={form.disliked} onChange={set("disliked")} /></label>
        </div>
        <div className="row" style={{ marginTop: 16 }}>
          <button className="action" onClick={save} disabled={saving}>
            {saving ? "Enregistrement…" : "Enregistrer le profil"}
          </button>
          {error && <span className="callout error">{error}</span>}
        </div>
      </div>
    </section>
  );
}
