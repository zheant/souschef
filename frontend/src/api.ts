// Client API typé — seule porte vers le back-end.

import type {
  IngredientOption,
  RecipeDraft,
  RecipePage,
  RecipeSummary,
  Household, Plan, PriceCoverage, PriceRefresh,
  RecipeIngredientLine, RecipeNutrition, RecipeQuote, ReoptimizeResult,
  SolverConfigInput,
  StapleLine, Store,
} from "./types";

/** Message d'une exception, pour affichage.
 *
 *  `String(e)` sur un `Error` produit « Error: <message> » — le préfixe était
 *  affiché tel quel à l'usager sur les dix écrans qui rattrapent une erreur.
 *  Le message porte déjà tout ce qu'il y a à dire. */
export const messageOf = (e: unknown): string =>
  e instanceof Error ? e.message : String(e);

function errorMessage(status: number, body: string): string {
  try {
    const parsed = JSON.parse(body);
    const detail = parsed?.detail;
    if (typeof detail === "string" && detail) return detail;
    // 422 de validation Pydantic : une liste d'objets, pas une phrase.
    if (Array.isArray(detail) && detail.length) {
      const msgs = detail.map((d) => d?.msg).filter(Boolean);
      if (msgs.length) return msgs.join(" ; ");
    }
  } catch {
    // Corps non JSON (proxy, passerelle) : le texte brut est ce qu'on a.
  }
  return body ? `${status} — ${body}` : `Erreur ${status}`;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    const body = await r.text();
    // FastAPI enveloppe ses messages dans `{"detail": "..."}`. Recracher le
    // corps brut affichait l'enveloppe à l'écran (« 422 — {"detail":"Aucun
    // prix valide…"} ») : le message était déjà utile, sa présentation non.
    // Le code de statut ne reste devant que s'il n'y a pas de message à dire.
    throw new Error(errorMessage(r.status, body));
  }
  return r.json() as Promise<T>;
}

export const api = {
  household: () => req<Household>("/api/household"),
  updateHousehold: (patch: object) =>
    req<Household>("/api/household", { method: "PUT", body: JSON.stringify(patch) }),
  staples: () => req<StapleLine[]>("/api/staples"),
  setStaples: (canonicalIngredientIds: string[]) =>
    req<StapleLine[]>("/api/staples", {
      method: "PUT",
      body: JSON.stringify({ canonical_ingredient_ids: canonicalIngredientIds }),
    }),
  // `on_date` était accepté par la route depuis le début mais jamais envoyé :
  // le plan visait donc toujours aujourd'hui, sans recours quand les prix
  // chargés ne couvrent pas cette date.
  createPlan: (config: SolverConfigInput, onDate?: string) =>
    req<Plan>("/api/plan", {
      method: "POST",
      body: JSON.stringify(onDate ? { config, on_date: onDate } : { config }),
    }),
  priceCoverage: () => req<PriceCoverage>("/api/price-coverage"),
  priceRefresh: () => req<PriceRefresh>("/api/price-refresh"),
  startPriceRefresh: (banner = "superc") =>
    req<PriceRefresh>("/api/price-refresh", {
      method: "POST",
      body: JSON.stringify({ banner }),
    }),
  dismissPriceRefresh: () =>
    req<PriceRefresh>("/api/price-refresh", { method: "DELETE" }),
  getPlan: (id: number) => req<Plan>(`/api/plan/${id}`),
  commitPlan: (id: number) =>
    req<{ plan_id: number; status: string }>(
      `/api/plan/${id}/commit`, { method: "POST" }),
  reoptimizePlan: (
    id: number, config: SolverConfigInput,
    lockedRecipeIds: string[], excludedRecipeIds: string[],
  ) =>
    req<ReoptimizeResult>(`/api/plan/${id}/reoptimize`, {
      method: "POST",
      body: JSON.stringify({
        config,
        locked_recipe_ids: lockedRecipeIds,
        excluded_recipe_ids: excludedRecipeIds,
      }),
    }),
  finalizePlan: (
    id: number, config: SolverConfigInput, confirmedAvailableIds: string[],
  ) =>
    req<ReoptimizeResult>(`/api/plan/${id}/finalize`, {
      method: "POST",
      body: JSON.stringify({
        config, confirmed_available_ids: confirmedAvailableIds,
      }),
    }),
  stores: () => req<Store[]>("/api/stores"),
  recipes: (q: string, limit: number, offset: number) => {
    const query = new URLSearchParams({
      limit: String(limit), offset: String(offset),
    });
    // Une recherche vide n'est pas une recherche : envoyer `q=` filtrait sur
    // la chaîne vide côté route au lieu de tout rendre.
    if (q.trim()) query.set("q", q.trim());
    return req<RecipePage>(`/api/recipes?${query.toString()}`);
  },
  ingredients: (q: string, limit = 12) =>
    req<IngredientOption[]>(
      `/api/ingredients?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  createRecipe: (draft: RecipeDraft) =>
    req<RecipeSummary>("/api/recipes", {
      method: "POST",
      body: JSON.stringify(draft),
    }),
  // `dropPlans` est un consentement, pas un défaut : sans lui, l'API refuse
  // (409) de retirer une recette qu'un plan cite.
  deleteRecipe: (recipeId: string, dropPlans = false) =>
    req<void>(
      `/api/recipes/${recipeId}?drop_plans=${dropPlans ? "true" : "false"}`,
      { method: "DELETE" },
    ),
  recipeIngredients: (recipeId: string) =>
    req<RecipeIngredientLine[]>(`/api/recipes/${recipeId}/ingredients`),
  recipeQuote: (
    recipeId: string, servings: number, onDate: string, stores: string[],
  ): Promise<RecipeQuote | null> => {
    const query = new URLSearchParams({
      recipe_id: recipeId,
      servings: String(servings),
      on_date: onDate,
    });
    stores.forEach((store) => query.append("store", store));
    // `quotes[0]` sur une réponse vide rendait `undefined`, et l'appelant
    // lisait `.recipe_id` dessus : le TypeError partait dans le `.then` et
    // ressortait en bannière générique, masquant la vraie cause.
    return req<RecipeQuote[]>(`/api/recipe-quotes?${query.toString()}`).then(
      (quotes) => quotes[0] ?? null,
    );
  },
  // Même forme que `recipeQuote` : une liste côté route, un seul élément ici,
  // et `null` plutôt qu'un `undefined` que l'appelant déréférencerait.
  recipeNutrition: (
    recipeId: string, servings: number,
  ): Promise<RecipeNutrition | null> => {
    const query = new URLSearchParams({
      recipe_id: recipeId, servings: String(servings),
    });
    return req<RecipeNutrition[]>(
      `/api/recipe-nutrition?${query.toString()}`,
    ).then((rows) => rows[0] ?? null);
  },
};

export const cents = (v: string | number): string =>
  (Number(v) / 100).toLocaleString("fr-CA", { style: "currency", currency: "CAD" });

// Les heures se lisaient « 0.69 h » à côté d'un « 30,78 $ » : deux séparateurs
// décimaux dans la même ligne, parce que `toFixed` est insensible à la locale.
export const hours = (v: string | number): string =>
  `${Number(v).toLocaleString("fr-CA", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })} h`;
