// Client API typé — seule porte vers le back-end.

import type {
  Household, Plan,
  RecipeIngredientLine, ReoptimizeResult, SolverConfigInput, StapleLine, Store,
} from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status} — ${body}`);
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
  createPlan: (config: SolverConfigInput) =>
    req<Plan>("/api/plan", { method: "POST", body: JSON.stringify({ config }) }),
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
  recipeIngredients: (recipeId: string) =>
    req<RecipeIngredientLine[]>(`/api/recipes/${recipeId}/ingredients`),
};

export const cents = (v: string | number): string =>
  (Number(v) / 100).toLocaleString("fr-CA", { style: "currency", currency: "CAD" });
