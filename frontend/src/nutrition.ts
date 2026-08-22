import { useEffect, useState } from "react";
import { api } from "./api";
import type { MenuLine, RecipeNutrition } from "./types";

/** Valeur nutritive des plats d'un menu, lue une fois pour tous les affichages.
 *
 *  Trois endroits en ont besoin — le résumé de la semaine, les puces des cartes
 *  de recette, et le détail d'une recette ouverte. Les laisser interroger la
 *  route chacun de leur côté, c'est trois fois la même requête et, tôt ou tard,
 *  trois chiffres qui divergent parce que l'un a été demandé à un autre nombre
 *  de portions.
 *
 *  Le nombre de portions est celui du plan, jamais le rendement publié : une
 *  recette mise à l'échelle par le solveur n'a pas la même valeur par portion,
 *  et certaines refusent d'être mises à l'échelle du tout (le refus est alors
 *  ce qu'on affiche). */
export function useMenuNutrition(
  menu: MenuLine[],
): { facts: Record<string, RecipeNutrition | null>; loading: boolean } {
  const [facts, setFacts] = useState<Record<string, RecipeNutrition | null>>({});
  const [loading, setLoading] = useState(menu.length > 0);
  // La clé de dépendance est la liste des couples (recette, portions) : c'est
  // exactement ce qui change la réponse. Dépendre du tableau lui-même
  // relancerait la requête à chaque rendu, l'identité de l'objet changeant.
  const key = menu.map((line) => `${line.recipe_id}:${line.servings}`).join("|");

  useEffect(() => {
    if (!menu.length) {
      setFacts({});
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    Promise.all(
      menu.map((line) =>
        api.recipeNutrition(line.recipe_id, line.servings)
          .then((row) => [line.recipe_id, row] as const)
          .catch(() => [line.recipe_id, null] as const),
      ),
    ).then((rows) => {
      if (!live) return;
      setFacts(Object.fromEntries(rows));
      setLoading(false);
    });
    return () => { live = false; };
  }, [key]);

  return { facts, loading };
}

/** Un nombre par portion, arrondi comme l'écran l'affiche, ou `null`.
 *
 *  `null` couvre les deux cas où il n'y a rien à montrer : la recette n'a pas
 *  été chiffrée, ou le module a refusé de la chiffrer. Les distinguer ici
 *  n'apporterait rien — l'appelant affiche « — » dans les deux cas, et le
 *  détail de la recette porte la raison. */
export function perServing(
  facts: RecipeNutrition | null | undefined,
  field: "kcal_per_serving" | "protein_g_per_serving",
): number | null {
  if (!facts || facts.status !== "complete") return null;
  const value = facts[field];
  return value == null ? null : Number(value);
}

/** Les protéines s'écrivent avec une décimale, l'énergie sans.
 *
 *  Arrondir les protéines à l'entier affichait « 0 g » pour une recette qui en
 *  porte 0,4 : sur le nombre que l'usager surveille, l'arrondi efface la
 *  différence entre peu et rien. Le bloc détaillé affiche déjà une décimale —
 *  les vues compactes le font donc aussi, plutôt que de donner deux chiffres
 *  différents pour le même fait. */
export const proteinLabel = (grams: number): string =>
  `${grams.toLocaleString("fr-CA", {
    minimumFractionDigits: 1, maximumFractionDigits: 1,
  })} g`;

export const kcalLabel = (kcal: number): string =>
  `${Math.round(kcal).toLocaleString("fr-CA")} kcal`;
