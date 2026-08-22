import { cents, hours } from "../api";
import { kcalLabel, perServing, proteinLabel, useMenuNutrition } from "../nutrition";
import type { Plan } from "../types";

/** Résumé de la semaine — cinq nombres, en haut de la page principale.
 *
 *  Les protéines passent devant les calories : c'est le nombre que ce ménage
 *  surveille, et un résumé qui l'enterre sous l'énergie ne résume pas ce qui
 *  l'intéresse.
 *
 *  Le coût et le temps de cuisine sont ceux que l'écran Résultat affiche déjà,
 *  calculés de la même façon (sous-total des listes d'épicerie ; somme des temps
 *  du menu) — deux endroits qui additionneraient différemment finiraient par se
 *  contredire.
 *
 *  Les moyennes sont pondérées **par portion**, pas par plat : quatre portions
 *  de riz et douze de chili ne pèsent pas pareil dans une semaine. Et elles ne
 *  se donnent jamais sans dire sur combien de plats elles portent — une recette
 *  dont la valeur est refusée est exclue du calcul, et le dire est la seule
 *  façon de ne pas présenter une moyenne partielle comme une moyenne. */
export function WeekSummary({ plan }: { plan: Plan }) {
  const { facts, loading } = useMenuNutrition(plan.menu);

  const groceryTotalCents = plan.grocery_list_by_store
    .reduce((sum, store) => sum + Number(store.subtotal_cents_cad), 0);
  const totalTimeH = plan.menu.reduce((sum, line) => sum + Number(line.prep_time_h), 0);
  const totalServings = plan.menu.reduce((sum, line) => sum + line.servings, 0);

  const counted = plan.menu.filter(
    (line) => perServing(facts[line.recipe_id], "protein_g_per_serving") != null,
  );
  const countedServings = counted.reduce((sum, line) => sum + line.servings, 0);
  const average = (field: "kcal_per_serving" | "protein_g_per_serving"): number | null =>
    countedServings
      ? counted.reduce(
          (sum, line) =>
            sum + (perServing(facts[line.recipe_id], field) ?? 0) * line.servings,
          0,
        ) / countedServings
      : null;
  const proteins = average("protein_g_per_serving");
  const kcal = average("kcal_per_serving");
  const show = (
    value: number | null, label: (v: number) => string,
  ): string => (loading ? "…" : value === null ? "—" : label(value));

  return (
    <div className="ws-card">
      <div className="ws-title">La semaine en bref</div>
      <div className="ws-grid">
        <div className="ws-cell ws-cell--lead">
          <div className="ws-value">{show(proteins, proteinLabel)}</div>
          <div className="ws-label">protéines par portion</div>
        </div>
        <div className="ws-cell">
          <div className="ws-value">{show(kcal, kcalLabel)}</div>
          <div className="ws-label">par portion</div>
        </div>
        <div className="ws-cell">
          <div className="ws-value">{cents(groceryTotalCents)}</div>
          <div className="ws-label">épicerie</div>
        </div>
        <div className="ws-cell">
          <div className="ws-value">{hours(totalTimeH)}</div>
          <div className="ws-label">de cuisine</div>
        </div>
        <div className="ws-cell">
          <div className="ws-value">{totalServings}</div>
          <div className="ws-label">
            portions · {plan.menu.length} plat{plan.menu.length > 1 ? "s" : ""}
          </div>
        </div>
      </div>
      {!loading && (
        <p className="ws-note">
          {proteins === null
            ? "Aucun plat du menu n'a de valeur nutritive calculable : les moyennes ne sont pas affichées plutôt que d'être approchées."
            : counted.length === plan.menu.length
              ? `Moyennes pondérées par portion, sur les ${plan.menu.length} plats du menu.`
              : `Moyennes pondérées par portion, sur ${counted.length} des ${plan.menu.length} plats — les autres n'ont pas de valeur nutritive calculable, et leur absence ne se compense pas.`}
        </p>
      )}
    </div>
  );
}
