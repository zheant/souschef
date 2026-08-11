// Client API typé — seule porte vers le back-end.

import type {
  Household, PantryLine, PantryPromptLine, Plan, ReoptimizeResult,
  SolverConfigInput, Store,
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
  createPlan: (config: SolverConfigInput) =>
    req<Plan>("/api/plan", { method: "POST", body: JSON.stringify({ config }) }),
  getPlan: (id: number) => req<Plan>(`/api/plan/${id}`),
  commitPlan: (id: number) =>
    req<{ plan_id: number; status: string; pantry_after_commit: Record<string, string> }>(
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
  pantryPrompt: (planId: number) =>
    req<PantryPromptLine[]>(`/api/plan/${planId}/pantry_prompt`),
  stores: () => req<Store[]>("/api/stores"),
};

export const cents = (v: string | number): string =>
  (Number(v) / 100).toLocaleString("fr-CA", { style: "currency", currency: "CAD" });
