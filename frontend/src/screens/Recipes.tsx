import { useEffect, useState } from "react";
import { api, hours, messageOf } from "../api";
import { NutritionBlock } from "../components/NutritionBlock";
import type {
  RecipeIngredientLine, RecipeNutrition, RecipeSummary,
} from "../types";

/** Écran 4 — Recettes : le catalogue entier, et la valeur nutritive de chacune.
 *
 *  Pourquoi cet écran existe. La valeur nutritive ne vivait que dans le détail
 *  d'une recette **du menu de la semaine** : trois recettes sur 121, et
 *  seulement après avoir généré un plan. Une question aussi simple que « combien
 *  de calories dans cette recette ? » n'avait pas de réponse dans l'application
 *  pour les 118 autres.
 *
 *  Pourquoi la nutrition se demande à l'ouverture, et non pour la liste. La
 *  route `/api/recipe-nutrition` exige un `recipe_id` par choix : sans recette
 *  nommée, elle calculerait les 121 recettes en une requête non paginée
 *  (`api/routes.py`). Afficher les kcal dans la liste demanderait donc une route
 *  en lot — un chantier séparé. Ici, une recette ouverte, une requête.
 *
 *  Le bloc de valeur nutritive est le même composant que dans l'écran Résultat,
 *  pas une seconde copie : deux écrans qui affichent le même fait doivent le
 *  lire au même endroit. */

const PAGE = 20;

export default function RecipesScreen() {
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<RecipeSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const [open, setOpen] = useState<RecipeSummary | null>(null);
  const [nutrition, setNutrition] = useState<RecipeNutrition | null>(null);
  const [nutritionError, setNutritionError] = useState<string | null>(null);
  const [nutritionLoading, setNutritionLoading] = useState(false);
  const [ingredients, setIngredients] = useState<RecipeIngredientLine[] | null>(null);

  useEffect(() => {
    let live = true;
    setItems(null);
    setListError(null);
    api.recipes(query, PAGE, offset)
      .then((page) => {
        if (!live) return;
        setItems(page.items);
        setTotal(page.total);
      })
      .catch((e) => live && setListError(messageOf(e)));
    return () => { live = false; };
  }, [query, offset]);

  async function openRecipe(recipe: RecipeSummary) {
    setOpen(recipe);
    setNutrition(null);
    setNutritionError(null);
    setIngredients(null);
    setNutritionLoading(true);
    // Le rendement publié, pas un nombre inventé : demander une autre valeur
    // ferait refuser la recette dont toutes les quantités sont fixes par lot
    // (« ne peut être chiffrée que pour son rendement publié »).
    api.recipeNutrition(recipe.id, recipe.original_servings)
      .then((facts) => setNutrition(facts))
      .catch((e) => setNutritionError(messageOf(e)))
      .finally(() => setNutritionLoading(false));
    api.recipeIngredients(recipe.id)
      .then(setIngredients)
      .catch(() => setIngredients([]));
  }

  if (open) {
    return (
      <section className="screen">
        <div className="rp-detail">
          <div className="rp-detail-header">
            <button className="rp-back-btn" onClick={() => setOpen(null)}>‹ Retour</button>
          </div>
          <div className="rp-detail-body">
            <div className="rp-detail-name">{open.name}</div>
            <div className="rp-detail-meta">
              {open.original_servings} portions · {hours(open.prep_time_fixed_h)} de cuisine
            </div>
            <div className="rp-detail-sec">Valeur nutritive par portion</div>
            {nutritionError && <p className="callout error">{nutritionError}</p>}
            {!nutritionError && nutritionLoading && <p className="muted">Chargement…</p>}
            {!nutritionError && !nutritionLoading && !nutrition && (
              <p className="muted">Valeur nutritive indisponible pour cette recette.</p>
            )}
            {nutrition && <NutritionBlock facts={nutrition} />}

            <div className="rp-detail-sec">Ingrédients</div>
            {!ingredients && <p className="muted">Chargement…</p>}
            {ingredients && (
              <ul className="rp-detail-ing">
                {ingredients.map((i) => (
                  <li key={i.canonical_ingredient_id}>{i.name}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>
    );
  }

  const last = Math.max(0, Math.ceil(total / PAGE) - 1);
  const page = Math.floor(offset / PAGE);
  return (
    <section className="screen">
      <h2>Recettes <span className="muted">— {total} au catalogue</span></h2>
      <label className="field">
        Chercher une recette
        <input
          value={query}
          placeholder="tacos, lentilles, soupe…"
          onChange={(e) => { setQuery(e.target.value); setOffset(0); }}
        />
      </label>

      {listError && <p className="callout error">{listError}</p>}
      {!listError && !items && <p className="muted"><span className="spin" aria-hidden />Chargement…</p>}
      {items && items.length === 0 && (
        <p className="muted">Aucune recette ne porte ce nom.</p>
      )}

      <ul className="rc-list">
        {(items ?? []).map((recipe) => (
          <li key={recipe.id}>
            <button className="rc-row" onClick={() => openRecipe(recipe)}>
              <span className="rc-name">{recipe.name}</span>
              <span className="rc-meta">
                {recipe.original_servings} portions · {hours(recipe.prep_time_fixed_h)}
              </span>
            </button>
          </li>
        ))}
      </ul>

      {total > PAGE && (
        <div className="rc-pager">
          <button
            className="action ghost" disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
          >
            ‹ Précédentes
          </button>
          <span className="muted">page {page + 1} / {last + 1}</span>
          <button
            className="action ghost" disabled={page >= last}
            onClick={() => setOffset(offset + PAGE)}
          >
            Suivantes ›
          </button>
        </div>
      )}
    </section>
  );
}
