// Client API typé — seule porte vers le back-end.

import type {
  Household, PantryLine, PantryPriority, Plan,
  RecipeIngredientLine, ReoptimizeResult, SolverConfigInput, Store,
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
  pantry: () => req<PantryLine[]>("/api/pantry"),
  updatePantry: (lines: { canonical_ingredient_id: string; quantity_base_unit: number }[]) =>
    req<PantryLine[]>("/api/pantry", { method: "PUT", body: JSON.stringify({ lines }) }),
  setPantryPriority: (canonicalIngredientId: string, priority: PantryPriority) =>
    req<PantryLine>(`/api/pantry/${canonicalIngredientId}/priority`, {
      method: "PUT", body: JSON.stringify({ priority }),
    }),
  createPlan: (config: SolverConfigInput) =>
    req<Plan>("/api/plan", { method: "POST", body: JSON.stringify({ config }) }),
  getPlan: (id: number) => req<Plan>(`/api/plan/${id}`),
  commitPlan: (id: number, buyInsteadIds: string[] = []) =>
    req<{ plan_id: number; status: string; pantry_after_commit: Record<string, string> }>(
      `/api/plan/${id}/commit`, {
        method: "POST", body: JSON.stringify({ buy_instead_ids: buyInsteadIds }),
      }),
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
  stores: () => req<Store[]>("/api/stores"),
  recipeIngredients: (recipeId: string) =>
    req<RecipeIngredientLine[]>(`/api/recipes/${recipeId}/ingredients`),
};

export const cents = (v: string | number): string =>
  (Number(v) / 100).toLocaleString("fr-CA", { style: "currency", currency: "CAD" });
