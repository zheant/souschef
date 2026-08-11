// Phrase d'explication après une réoptimisation (pilote,
// docs/product-pilot.md : « Deux recettes ont été remplacées... et
// économiser 4,80 $ »). Utilisée par Result.tsx (verrouillage/
// remplacement, POST /api/plan/{id}/reoptimize).

import type { MenuChange } from "./types";

/** Ne nomme pas les recettes (l'appelant n'a pas toujours leurs noms sous
 *  la main ici) — compte + delta de coût suffisent. */
export function describeChanges(c: MenuChange): string {
  const n = Math.max(c.added.length, c.removed.length);
  const what =
    n === 0 ? "Le menu n'a pas changé" :
    n === 1 ? "Une recette a été remplacée" :
    `${n} recettes ont été remplacées`;
  const delta = Number(c.cost_delta_cents) / 100;
  const fmt = (v: number) => Math.abs(v).toLocaleString("fr-CA", { style: "currency", currency: "CAD" });
  if (delta < -0.005) return `${what}, pour économiser ${fmt(delta)}.`;
  if (delta > 0.005) return `${what} — ${fmt(delta)} de plus.`;
  return `${what}, sans changer le coût des achats.`;
}
