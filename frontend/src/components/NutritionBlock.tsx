import type { RecipeNutrition } from "../types";

/** Valeur nutritive par portion, ou le refus du module, jamais un entre-deux.
 *
 *  Le module rend ses quatre nombres `null` ensemble dès qu'un ingrédient n'est
 *  pas résolu. L'écran ne comble donc rien : il nomme ce qui manque, comme la
 *  carte du menu nomme un prix indisponible plutôt que d'afficher 0,00 $.
 *
 *  La borne des apports déclarés négligeables s'affiche en « ± » : elle est
 *  petite (quelques kcal), mais un total qui la cache prétend une précision
 *  qu'il n'a pas. */
export function NutritionBlock({ facts }: { facts: RecipeNutrition }) {
  // Les quatre nombres sont `null` ensemble ou aucun ne l'est : le module
  // n'en publie jamais trois. Les exiger tous les quatre évite d'afficher un
  // « 0,0 g » là où la donnée est absente — la faute que l'écran doit refuser.
  const kcal = facts.kcal_per_serving;
  const protein = facts.protein_g_per_serving;
  const fat = facts.fat_g_per_serving;
  const carbohydrate = facts.carbohydrate_g_per_serving;
  if (
    facts.status !== "complete" ||
    kcal == null || protein == null || fat == null || carbohydrate == null
  ) {
    return (
      <div className="rp-nutrition-missing">
        <p>
          Valeur nutritive indisponible : {facts.missing.length}{" "}
          ingrédient{facts.missing.length > 1 ? "s" : ""} sans donnée
          nutritionnelle vérifiée. Un total partiel n'est pas un total.
        </p>
        <ul>
          {facts.missing.map((m) => (
            <li key={m.canonical_ingredient_id}>
              {m.canonical_ingredient_id}
              <span className="rp-nutrition-reason">{MISSING_LABELS[m.reason] ?? m.reason}</span>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  // Chaque nombre porte sa propre borne : une épice omise coûte des calories
  // *et* du gras. Afficher le « ± » sur l'énergie seule laissait croire les
  // trois autres exacts.
  const cells: [string, string | number | null, string | number | null, string][] = [
    ["Énergie", kcal, facts.kcal_error_bound_per_serving, "kcal"],
    ["Protéines", protein, facts.protein_g_error_bound_per_serving, "g"],
    ["Lipides", fat, facts.fat_g_error_bound_per_serving, "g"],
    ["Glucides", carbohydrate, facts.carbohydrate_g_error_bound_per_serving, "g"],
  ];
  const omitted = cells.some(([, , bound]) => Number(bound ?? 0) > 0);
  return (
    <>
      <div className="rp-nutrition">
        {cells.map(([label, value, bound, unit]) => (
          <div className="rp-nutrition-cell" key={label}>
            <div className="rp-nutrition-value">
              {grams(value ?? 0, unit === "kcal" ? "" : unit)}
              {unit === "kcal" ? " kcal" : ""}
            </div>
            {Number(bound ?? 0) > 0 && (
              <div className="rp-nutrition-bound">± {grams(bound ?? 0, "")}</div>
            )}
            <div className="rp-nutrition-label">{label}</div>
          </div>
        ))}
      </div>
      <p className="rp-nutrition-note">
        {omitted
          ? "Les « ± » bornent les apports déclarés négligeables (sel, bouillon, épices en petite quantité) : ils comptent pour zéro, et voici de combien."
          : "Aucun apport omis."}{" "}
        Règlement {facts.rule_version}.
      </p>
    </>
  );
}

/** Raisons de blocage, dites en français plutôt qu'en identifiants. */
const MISSING_LABELS: Record<string, string> = {
  no_cnf_food: "aucun aliment du FCÉN rattaché",
  ambiguous_cnf_food: "plusieurs aliments du FCÉN rattachés, aucun retenu",
  chosen_food_not_attached: "aliment retenu non rattaché à l'ingrédient",
  missing_nutrient_values: "aliment sans les quatre teneurs retenues",
  missing_density: "densité absente : le volume ne se ramène pas en grammes",
  missing_grams_per_unit: "masse par unité absente",
  over_negligible_ceiling: "quantité au-delà du plafond déclaré négligeable",
  negligible_unit_mismatch: "borne déclarée dans une autre unité",
  unknown_ingredient: "ingrédient absent du catalogue canonique",
};

const grams = (value: string | number, unit: string): string =>
  `${Number(value).toLocaleString("fr-CA", {
    minimumFractionDigits: 1, maximumFractionDigits: 1,
  })}${unit ? ` ${unit}` : ""}`;


export { MISSING_LABELS };
