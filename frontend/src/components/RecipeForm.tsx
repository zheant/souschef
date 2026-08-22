import { useEffect, useState } from "react";
import { api, messageOf } from "../api";
import type { IngredientOption, RecipeDraft, RecipeSummary } from "../types";

/** Formulaire d'ajout d'une recette au catalogue.
 *
 *  Trois choix de conception, chacun pour une raison :
 *
 *  - **l'ingrédient se choisit, il ne se tape pas.** Une recette cite des
 *    ingrédients canoniques par identifiant, et personne ne tape
 *    `farine_tout_usage` de mémoire. La recherche appelle le catalogue, et
 *    l'unité de base s'affiche à côté du champ — c'est elle qui dit en quoi la
 *    quantité se saisit;
 *  - **deux quantités par ligne, pas une.** « Par lot » ne monte pas avec les
 *    portions, « par portion » si. C'est la distinction que le solveur emploie
 *    pour mettre une recette à l'échelle, et la masquer ferait saisir un chiffre
 *    dont personne ne connaîtrait le sens;
 *  - **les quantités restent du texte** jusqu'à l'API : une décimale exacte en
 *    base ne doit pas passer par un flottant.
 *
 *  Le refus vient du serveur, pas d'ici : quantités toutes nulles, ingrédient
 *  inconnu, bornes de lot incohérentes. Dupliquer ces règles dans l'écran, ce
 *  serait deux vérités à maintenir. */
export function RecipeForm(props: {
  onCreated: (recipe: RecipeSummary) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [servings, setServings] = useState("4");
  const [prepTime, setPrepTime] = useState("0.5");
  const [lines, setLines] = useState<
    { option: IngredientOption | null; fixed: string; marginal: string; query: string }[]
  >([{ option: null, fixed: "", marginal: "0", query: "" }]);
  const [options, setOptions] = useState<Record<number, IngredientOption[]>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const pending = lines
      .map((line, index) => ({ index, query: line.query }))
      .filter((row) => row.query.trim().length >= 2 && !lines[row.index].option);
    if (!pending.length) return;
    let live = true;
    const timer = window.setTimeout(() => {
      pending.forEach(({ index, query }) => {
        api.ingredients(query)
          .then((found) => live && setOptions((prev) => ({ ...prev, [index]: found })))
          .catch(() => undefined);
      });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [lines]);

  function setLine(index: number, patch: Partial<(typeof lines)[number]>) {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  }

  async function submit() {
    setError(null);
    const chosen = lines.filter((line) => line.option);
    if (!chosen.length) {
      setError("Choisir au moins un ingrédient.");
      return;
    }
    const draft: RecipeDraft = {
      name,
      original_servings: Math.max(1, Math.round(Number(servings) || 0)),
      prep_time_fixed_h: prepTime.trim() || "0",
      prep_time_marginal_h: "0",
      min_batch_servings: Math.max(1, Math.round(Number(servings) || 0)),
      max_batch_servings: Math.max(1, Math.round(Number(servings) || 0)),
      ingredients: chosen.map((line) => ({
        canonical_ingredient_id: line.option!.id,
        qty_fixed_per_batch_base_unit: line.fixed.trim() || "0",
        qty_marginal_per_serving_base_unit: line.marginal.trim() || "0",
      })),
    };
    setSaving(true);
    try {
      props.onCreated(await api.createRecipe(draft));
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h3>Nouvelle recette</h3>
      {error && <p className="callout error">{error}</p>}
      <label className="field">
        Nom
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="ex. Chili de lentilles" />
      </label>
      <div className="row" style={{ gap: 10 }}>
        <label className="field">
          Portions
          <input value={servings} inputMode="numeric" onChange={(e) => setServings(e.target.value)} />
        </label>
        <label className="field">
          Temps de cuisine (h)
          <input value={prepTime} inputMode="decimal" onChange={(e) => setPrepTime(e.target.value)} />
        </label>
      </div>

      <div className="rf-lines">
        {lines.map((line, index) => (
          <div className="rf-line" key={index}>
            {line.option ? (
              <button className="rf-chosen" onClick={() => setLine(index, { option: null, query: "" })}>
                {line.option.name} <span className="muted">({line.option.base_unit})</span> ✕
              </button>
            ) : (
              <>
                <input
                  value={line.query}
                  placeholder="chercher un ingrédient…"
                  onChange={(e) => setLine(index, { query: e.target.value })}
                />
                {(options[index] ?? []).length > 0 && (
                  <ul className="rf-options">
                    {(options[index] ?? []).slice(0, 6).map((option) => (
                      <li key={option.id}>
                        <button onClick={() => setLine(index, { option, query: option.name })}>
                          {option.name} <span className="muted">{option.base_unit}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
            <div className="row" style={{ gap: 8 }}>
              <label className="field">
                par lot {line.option ? `(${line.option.base_unit})` : ""}
                <input
                  value={line.fixed} inputMode="decimal"
                  onChange={(e) => setLine(index, { fixed: e.target.value })}
                />
              </label>
              <label className="field">
                par portion {line.option ? `(${line.option.base_unit})` : ""}
                <input
                  value={line.marginal} inputMode="decimal"
                  onChange={(e) => setLine(index, { marginal: e.target.value })}
                />
              </label>
            </div>
          </div>
        ))}
      </div>

      <div className="row" style={{ gap: 10, marginTop: 10 }}>
        <button
          className="action ghost"
          onClick={() => setLines([...lines, { option: null, fixed: "", marginal: "0", query: "" }])}
        >
          ＋ Ingrédient
        </button>
        <button className="action" onClick={submit} disabled={saving || !name.trim()}>
          {saving ? "…" : "Ajouter la recette"}
        </button>
        <button className="action ghost" onClick={props.onCancel}>Annuler</button>
      </div>
    </div>
  );
}
