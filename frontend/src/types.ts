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
  //: Plancher d'appétence du plan, en dollars. `null` : aucun plancher.
  appetence_u_min_dollars: number | null;
  min_protein_g_per_serving: number | null;
  max_distinct_recipes: number | null;
  members: Member[];
  demand: { D_exact: string; borne_basse: number; borne_haute: number };
}

// Essentiels (staples, pilote, docs/product-pilot.md) : simple appartenance
// ménage/ingrédient, sans quantité ni priorité — remplace le garde-manger.
export interface StapleLine {
  canonical_ingredient_id: string; name: string;
}

export interface SolverConfigInput {
  enable_multi_store?: boolean; enable_batch_fixed_cost?: boolean;
  enable_salvage?: boolean; enable_perishable_penalty?: boolean;
  enable_time_cost?: boolean;
  enable_staples?: boolean; enable_diversity?: boolean;
  //: `undefined` — le défaut — suit le plancher du profil.
  appetence_mode?: "objective" | "constraint";
  appetence_u_min_dollars?: number | null;
  min_protein_g_per_serving?: number | null;
  max_distinct_recipes?: number | null;
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
  // Rabais et économies (pilote, docs/product-pilot.md) — référence
  // honnête : prix régulier du même produit. savings_cents_cad est null
  // hors promo ou si le prix régulier n'est pas connu/supérieur.
  is_promo: boolean;
  regular_price_cents_cad: number | null;
  savings_cents_cad: string | null;
}

export interface GroceryGroup {
  store_external_key: string; lines: GroceryLine[]; subtotal_cents_cad: string;
  savings_cents_cad: string;
}

export interface ObjectiveTermsCents {
  achats: string; deplacements: string; temps: string;
  recuperation: string; gaspillage: string; appetence: string; total: string;
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
  distinct_recipes: number; max_share_of_demand: string | null;
  demand: Record<string, string>;
  assertions_passed: string[]; last_enabled_flag: string | null;
  infeasibility_note: string | null;
}

// Ingrédient requis par le menu du plan (pilote, docs/product-pilot.md) —
// écran de confirmation post-génération, tous les ingrédients sont montrés ;
// is_staple pré-décoche ceux que le ménage est supposé déjà avoir.
export interface NeededIngredientLine {
  canonical_ingredient_id: string; name: string; is_staple: boolean;
}

export interface Plan {
  id: number; status: "proposed" | "committed"; solver_status: string;
  on_date: string; menu: MenuLine[]; grocery_list_by_store: GroceryGroup[];
  needed_ingredients: NeededIngredientLine[];
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

export interface Store {
  external_key: string; banner: string; address: string;
  lat: number; lng: number; shopping_center_id: string | null;
}

// Détail recette (pilote, docs/product-pilot.md).
/** Une recette du catalogue, telle que `GET /api/recipes` la pagine. Le
 *  navigateur de recettes (écran Recettes) n'a besoin que de l'identité et du
 *  rendement publié : la valeur nutritive se demande recette par recette, à
 *  l'ouverture, pour ne pas calculer 121 recettes par page affichée. */
export interface RecipeSummary {
  id: string;
  name: string;
  original_servings: number;
  prep_time_fixed_h: string;
  prep_time_marginal_h: string;
  tags: Record<string, unknown>;
}

/** Une recette proposée depuis l'application.
 *
 *  Les quantités sont des **chaînes** : une quantité est une décimale exacte en
 *  base, et un `number` JavaScript l'arrondirait en chemin — même règle que
 *  l'argent, transporté en cents. */
/** Un ingrédient canonique tel que le formulaire le propose. L'unité de base
 *  voyage avec le nom : c'est elle qui dit en quoi la quantité se saisit. */
export interface IngredientOption {
  id: string;
  name: string;
  base_unit: string;
}

export interface RecipeDraft {
  name: string;
  original_servings: number;
  prep_time_fixed_h: string;
  prep_time_marginal_h: string;
  min_batch_servings: number;
  max_batch_servings: number;
  ingredients: {
    canonical_ingredient_id: string;
    qty_fixed_per_batch_base_unit: string;
    qty_marginal_per_serving_base_unit: string;
  }[];
}

export interface RecipePage {
  total: number; limit: number; offset: number; items: RecipeSummary[];
}

export interface RecipeIngredientLine {
  canonical_ingredient_id: string; name: string;
}

export type Confidence = "exact" | "audited_conversion" | "estimated" | "incomplete";

/** Valeur nutritive par portion, telle que le module la calcule.
 *
 *  Les quatre nombres sont `null` **ensemble** dès qu'une ligne d'ingrédient
 *  n'est pas résolue : le module ne présente jamais un total partiel comme un
 *  total. `missing` dit alors quoi curer, et `lines` porte la preuve
 *  ingrédient par ingrédient.
 *
 *  Les quatre `*_error_bound_per_serving` sont la somme des bornes des apports
 *  déclarés négligeables (sel, bouillon, épices en petite quantité) : l'écran
 *  les affiche en « ± », il ne les absorbe pas. Borner la seule énergie
 *  laissait publier « 0,0 g de lipides » comme un fait mesuré, alors qu'une
 *  épice omise emporte jusqu'à un gramme de gras. */
export interface RecipeNutrition {
  recipe_id: string; recipe_name: string; servings: number;
  status: "complete" | "incomplete";
  kcal_per_serving: string | number | null;
  protein_g_per_serving: string | number | null;
  fat_g_per_serving: string | number | null;
  carbohydrate_g_per_serving: string | number | null;
  kcal_error_bound_per_serving: string | number | null;
  protein_g_error_bound_per_serving: string | number | null;
  fat_g_error_bound_per_serving: string | number | null;
  carbohydrate_g_error_bound_per_serving: string | number | null;
  confidence: Confidence;
  rule_version: string;
  lines: RecipeNutritionLine[];
  missing: { canonical_ingredient_id: string; reason: string }[];
}

export interface RecipeNutritionLine {
  ingredient_id: string;
  qty_per_serving: string | number;
  base_unit: string;
  grams_per_serving: string | number | null;
  resolution: "computed" | "negligible" | "gap" | "no_quantity_required";
  reason: string | null;
  food_code: string | null;
  kcal: string | number | null;
  protein_g: string | number | null;
  fat_g: string | number | null;
  carbohydrate_g: string | number | null;
  kcal_error_bound: string | number;
  protein_g_error_bound: string | number;
  fat_g_error_bound: string | number;
  carbohydrate_g_error_bound: string | number;
  confidence: Confidence;
  detail: string | null;
}

export interface RecipeQuote {
  recipe_id: string; recipe_name: string; servings: number;
  status: "complete" | "incomplete";
  consumed_cost_cents: string | number | null;
  consumed_cost_per_serving_cents: string | number | null;
  best_unit_price_cents: string | number | null;
  autonomous_checkout_cents: string | number | null;
  regular_comparable_cents: string | number | null;
  promotional_savings_cents: string | number | null;
  // Deux nombres de fiabilité différente, donc deux niveaux : un produit vendu
  // au poids n'affecte que le décaissement.
  consumed_confidence: Confidence;
  checkout_confidence: Confidence;
  basket_scope: "single_store" | "multi_store";
  stores: string[];
  valid_from: string | null; valid_to: string | null;
  validity_reason: string | null;
  incomplete_ingredients: string[];
}

/** Fenêtre de dates réellement couverte par les prix chargés. */
export interface PriceCoverage {
  earliest: string | null;
  latest: string | null;
}

/** État d'une collecte de prix lancée depuis l'application.
 *
 *  `log_tail` est la fin de la sortie du collecteur — la progression réelle,
 *  pas un pourcentage fabriqué par l'écran. */
export interface PriceRefresh {
  state: "idle" | "running" | "succeeded" | "failed";
  banner: string | null;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  /** `false` : prix importés mais capture tronquée — partiels, pas faux. */
  collection_complete: boolean | null;
  /** Compteurs rendus par l'import : products_upserted, prices_upserted… */
  imported: Record<string, number> | null;
  /** Dernière collecte trouvée sur disque, ligne de commande comprise. */
  last_capture_at: string | null;
  log_tail: string[];
}
