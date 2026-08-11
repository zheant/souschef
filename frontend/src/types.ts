// Types du contrat API — miroir de backend/app/api/schemas.py

export interface Member { name: string; appetite_coefficient: number }

export interface Household {
  id: string; home_lat: number; home_lng: number;
  time_value_cents_per_hour: number; meals_per_horizon: number;
  demand_slack_epsilon: number; max_store_visits: number;
  min_distinct_recipes: number; max_share_per_recipe: number;
  diet_flags: string[]; allergen_flags: string[];
  taste_preferences: { liked_tags?: string[]; disliked_tags?: string[] };
  available_equipment: string[]; max_prep_time_per_meal_h: number;
  members: Member[];
  demand: { D_exact: string; borne_basse: number; borne_haute: number };
}

// Périssables prioritaires ou obligatoires (pilote, docs/product-pilot.md) :
// "use_soon" (préférence, stockée, sans effet sur le solveur en v1) vs
// "must_use" (contrainte réelle).
export type PantryPriority = "normal" | "use_soon" | "must_use";

export interface PantryLine {
  canonical_ingredient_id: string; quantity_base_unit: string;
  priority: PantryPriority;
}

export interface SolverConfigInput {
  enable_multi_store?: boolean; enable_batch_fixed_cost?: boolean;
  enable_salvage?: boolean; enable_time_cost?: boolean;
  enable_pantry_stock?: boolean; enable_diversity?: boolean;
  appetence_mode?: "objective" | "constraint";
  appetence_u_min_dollars?: number | null;
  max_store_visits?: number | null; min_distinct_recipes?: number | null;
  max_share_per_recipe?: number | null; demand_slack_epsilon?: number | null;
  solver_time_limit_s?: number; mip_gap?: number;
}

export interface MenuLine {
  recipe_id: string; name: string; servings: number;
  prep_time_h: string; attributed_cost_cents_cad: string;
}

export interface GroceryLine {
  product_external_key: string; ingredient_name: string;
  brand: string; package_unit: string;
  units: number; unit_price_cents_cad: number; taxed_total_cents_cad: string;
  consumed_by: string[];
}

export interface GroceryGroup {
  store_external_key: string; lines: GroceryLine[]; subtotal_cents_cad: string;
}

export interface ObjectiveTermsCents {
  achats: string; deplacements: string; temps: string;
  recuperation: string; appetence: string; total: string;
}

export interface Diagnostic {
  solver_status: string; solve_time_s: number;
  mip_gap_requested: number; mip_gap_attained: number | null;
  objective_terms_cents: ObjectiveTermsCents | null;
  effective_params: Record<string, { valeur: string; provenance: string }>;
  flag_effects: Record<string, string[]>;
  saturated_constraints: Record<string, string[]>;
  prefilter_counts: Record<string, number>;
  surplus_by_ingredient: Record<string, { quantite_base_unit: string; valorisation_cents: string }>;
  pantry_consumed_by_ingredient: Record<string, { quantite_base_unit: string; valeur_cents: string }>;
  pantry_consumed_value_cents: string;
  distinct_recipes: number; max_share_of_demand: string | null;
  demand: Record<string, string>;
  assertions_passed: string[]; last_enabled_flag: string | null;
  infeasibility_note: string | null;
}

export interface Plan {
  id: number; status: "proposed" | "committed"; solver_status: string;
  on_date: string; menu: MenuLine[]; grocery_list_by_store: GroceryGroup[];
  stores_visited: string[]; diagnostic: Diagnostic;
}

// Verrouillage/remplacement/réoptimisation expliquée (pilote,
// docs/product-pilot.md).
export interface MenuChange {
  added: string[]; removed: string[]; cost_delta_cents: string;
}

export interface ReoptimizeResult {
  plan: Plan;
  changes: MenuChange | null;  // null si le nouveau plan est infaisable
}

// Confirmation du garde-manger en deux temps (pilote,
// docs/product-pilot.md) — liste priorisée pour un plan précis, pas un
// inventaire exhaustif.
export interface PantryPromptLine {
  canonical_ingredient_id: string;
  name: string;
  unit_kind: "mass" | "volume" | "count";
  base_unit: string;
  needed_quantity_base_unit: string;
  perishability: string;
  estimated_cost_cents: string;
}

export interface Store {
  external_key: string; banner: string; address: string;
  lat: number; lng: number; shopping_center_id: string | null;
}
