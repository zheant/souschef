import { useEffect, useMemo, useState } from "react";
import { api, cents } from "../api";
import { describeChanges } from "../changes";
import type {
  Household, Plan, RecipeIngredientLine, RecipeQuote, SolverConfigInput, Store,
} from "../types";

/** Écran 3 — Résultat (piste « circulaire du quartier », disposition « P »,
 *  docs/product-pilot.md) : deux onglets internes — Cette semaine (coût à
 *  l'épicerie, temps de cuisine, menu) et Épicerie (listes par magasin). Le
 *  détail de l'optimisation en 5 termes (5_essentiel au mode développeur,
 *  cf. l'onglet Diagnostic) reste disponible mais replié derrière la barre
 *  — l'usager courant n'a besoin que de ce qu'il dépense à l'épicerie et du
 *  temps que ça lui prend.
 *
 *  Pas de section garde-manger (pilote, docs/product-pilot.md — retiré au
 *  profit des essentiels) : la correction de ce que l'usager possède déjà
 *  se fait AVANT ce plan, à la confirmation post-génération
 *  (`Planning.tsx`), jamais ici.
 *
 *  Angle mort assumé : les photos de plat sont des dégradés de couleur
 *  dérivés de l'id de la recette, pas de vraies photos — l'app n'a aucune
 *  source d'images aujourd'hui (chantier séparé). */

function haversineKm(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const r = (x: number) => (x * Math.PI) / 180;
  const h =
    Math.sin(r(bLat - aLat) / 2) ** 2 +
    Math.cos(r(aLat)) * Math.cos(r(bLat)) * Math.sin(r(bLng - aLng) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

const PHOTO_CLASSES = ["rp-photo-a", "rp-photo-b", "rp-photo-c", "rp-photo-d", "rp-photo-e", "rp-photo-f"];
function photoClassFor(recipeId: string): string {
  let h = 0;
  for (let i = 0; i < recipeId.length; i++) h = (h * 31 + recipeId.charCodeAt(i)) >>> 0;
  return PHOTO_CLASSES[h % PHOTO_CLASSES.length];
}

const DISH_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={1.6} strokeLinecap="round">
    <circle cx="12" cy="14" r="7" />
    <path d="M9 4v4M12 3v5M15 4v4" />
  </svg>
);

const CLOCK_ICON = (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <path d="M12 6v6l4 2" />
  </svg>
);

const PORTIONS_ICON = (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
  </svg>
);

const CHECK_ICON = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 6L9 17l-5-5" />
  </svg>
);

const SWAP_ICON = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 1l4 4-4 4M3 11V9a4 4 0 014-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 01-4 4H3" />
  </svg>
);

type TermKey = "achats" | "deplacements" | "temps" | "recuperation" | "gaspillage" | "appetence";
const TERM_LABELS: [TermKey, string, boolean, number][] = [
  // clé, libellé, crédit?, opacité du segment (même dégradé que le prototype)
  ["achats", "Achats", false, 1],
  ["deplacements", "Déplacements", false, 0.7],
  ["temps", "Temps", false, 0.45],
  ["recuperation", "Récupération", true, 0.6],
  ["gaspillage", "Gaspillage", false, 0.85],
  ["appetence", "Appétence", true, 1],
];

export default function ResultScreen(props: {
  plan: Plan | null; household: Household; stores: Store[]; config: SolverConfigInput;
  onCommitted: (planId: number) => void;
}) {
  const { plan, household, stores } = props;
  const [tab, setTab] = useState<"semaine" | "epicerie">("semaine");
  const [barDetailed, setBarDetailed] = useState(false);

  const [reoptimizing, setReoptimizing] = useState(false);
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const [reoptimizeMsg, setReoptimizeMsg] = useState<string | null>(null);
  const [reoptimizeError, setReoptimizeError] = useState<string | null>(null);

  const [openRecipeId, setOpenRecipeId] = useState<string | null>(null);
  const [ingredients, setIngredients] = useState<RecipeIngredientLine[] | null>(null);
  const [ingredientsError, setIngredientsError] = useState<string | null>(null);
  const [recipeQuotes, setRecipeQuotes] = useState<Record<string, RecipeQuote>>({});
  const [quotesError, setQuotesError] = useState<string | null>(null);
  const [quotesLoading, setQuotesLoading] = useState(false);

  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [accepted, setAccepted] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);

  // Nouveau plan chargé (génération, remplacement) : rien de local ne
  // survit à un plan différent — même motif que les tranches précédentes.
  useEffect(() => {
    setChecked({});
    setAccepted(plan?.status === "committed");
    setBarDetailed(false);
    setOpenRecipeId(null);
  }, [plan?.id]);

  useEffect(() => {
    let cancelled = false;
    if (!plan) {
      setRecipeQuotes({});
      setQuotesLoading(false);
      return;
    }
    setQuotesError(null);
    setQuotesLoading(true);
    // Un devis par recette, et chacun encaisse son propre échec. Un `Promise.all`
    // nu était tout ou rien : une recette que le module refuse de rechiffrer
    // pour un autre nombre de portions (422) — le cas courant, `servings` étant
    // le x_r du solveur — effaçait le prix de tout le menu.
    Promise.all(
      plan.menu.map((line) =>
        api
          .recipeQuote(
            line.recipe_id,
            line.servings,
            plan.on_date,
            plan.stores_visited,
          )
          .catch((error: unknown) => {
            console.warn(`Devis indisponible pour ${line.recipe_id}`, error);
            return null;
          }),
      ),
    )
      .then((quotes) => {
        if (cancelled) return;
        const found = quotes.filter((q): q is RecipeQuote => q != null);
        setRecipeQuotes(Object.fromEntries(found.map((q) => [q.recipe_id, q])));
        setQuotesLoading(false);
        setQuotesError(
          found.length || !plan.menu.length
            ? null
            : "Prix des recettes indisponibles pour ce plan.",
        );
      })
      .catch((error) => {
        if (cancelled) return;
        setQuotesLoading(false);
        setQuotesError(String(error));
      });
    return () => { cancelled = true; };
  }, [plan]);

  const itinerary = useMemo(() => {
    if (!plan) return [];
    const byKey = new Map(stores.map((s) => [s.external_key, s]));
    return plan.stores_visited
      .map((k) => byKey.get(k))
      .filter((s): s is Store => Boolean(s))
      .map((s) => ({ ...s, km: haversineKm(household.home_lat, household.home_lng, s.lat, s.lng) }))
      .sort((a, b) => a.km - b.km);
  }, [plan, stores, household]);

  if (!plan) {
    return (
      <section className="result-v2">
        <h2 style={{ marginTop: 0 }}>Résultat</h2>
        <p className="muted">Aucun plan pour l'instant — passez par l'onglet Génération.</p>
      </section>
    );
  }

  const currentPlan = plan;
  const groceryTotalCents = currentPlan.grocery_list_by_store
    .reduce((s, g) => s + Number(g.subtotal_cents_cad), 0);
  const totalTimeH = currentPlan.menu.reduce((s, m) => s + Number(m.prep_time_h), 0);

  const t = currentPlan.diagnostic.objective_terms_cents;
  const termAbsSum = t
    ? TERM_LABELS.reduce((s, [k]) => s + Math.abs(Number(t[k])), 0) || 1
    : 1;

  async function callReoptimize(
    lockedRecipeIds: string[], excludedRecipeIds: string[], configOverride?: SolverConfigInput
  ) {
    setReoptimizing(true); setReoptimizeError(null); setReoptimizeMsg(null);
    try {
      const r = await api.reoptimizePlan(
        currentPlan.id, configOverride ?? props.config, lockedRecipeIds, excludedRecipeIds
      );
      if (r.changes) {
        setReoptimizeMsg(describeChanges(r.changes));
      } else {
        setReoptimizeError(
          `Réoptimisation infaisable : ${r.plan.diagnostic.infeasibility_note ?? "voir le diagnostic"}.`
        );
      }
      props.onCommitted(r.plan.id);
    } catch (e) {
      setReoptimizeError(String(e));
    } finally {
      setReoptimizing(false); setReplacingId(null);
    }
  }

  async function replace(recipeId: string) {
    setReplacingId(recipeId);
    const others = currentPlan.menu.map((m) => m.recipe_id).filter((id) => id !== recipeId);
    await callReoptimize(others, [recipeId]);
  }

  async function openDetail(recipeId: string) {
    setOpenRecipeId(recipeId);
    setIngredients(null);
    setIngredientsError(null);
    try {
      setIngredients(await api.recipeIngredients(recipeId));
    } catch (e) {
      setIngredientsError(String(e));
    }
  }

  function toggleChecked(key: string) {
    if (!accepted) return;
    setChecked((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function accept() {
    setCommitting(true); setCommitError(null);
    try {
      await api.commitPlan(currentPlan.id);
      setAccepted(true);
      props.onCommitted(currentPlan.id);
    } catch (e) {
      setCommitError(String(e));
    } finally {
      setCommitting(false);
    }
  }

  const totalItems = currentPlan.grocery_list_by_store
    .reduce((s, g) => s + g.lines.length, 0);
  const checkedCount = Object.values(checked).filter(Boolean).length;

  const openRecipe = openRecipeId
    ? currentPlan.menu.find((m) => m.recipe_id === openRecipeId)
    : undefined;

  return (
    <section className="result-v2">
      <div className="rp-segmented">
        <button className={tab === "semaine" ? "active" : ""} onClick={() => setTab("semaine")}>
          Cette semaine
        </button>
        <button className={tab === "epicerie" ? "active" : ""} onClick={() => setTab("epicerie")}>
          Épicerie
        </button>
      </div>

      {tab === "semaine" && (
        <>
          <div className={`rp-cost-card${barDetailed ? " rp-cost-card--detail" : ""}`}>
            <div className="rp-hero-label">Coût à l'épicerie</div>
            <div className="rp-hero-amount">
              {cents(groceryTotalCents)} <span className="rp-time">· {totalTimeH.toFixed(2)} h de cuisine</span>
            </div>
            <div className="rp-bar-slot" onClick={() => setBarDetailed((v) => !v)} role="button" tabIndex={0}>
              {!barDetailed && (
                <>
                  <div className="rp-splitbar">
                    <span style={{ width: "100%", background: "rgba(255,255,255,0.95)" }} />
                  </div>
                  <div className="rp-legend">
                    <span><span className="rp-sw" style={{ background: "rgba(255,255,255,0.95)" }} />Acheté</span>
                  </div>
                  <div className="rp-bar-hint">Détail de l'optimisation ›</div>
                </>
              )}
              {barDetailed && t && (
                <>
                  <div className="rp-bigbar">
                    {TERM_LABELS.map(([key, , credit, opacity]) => (
                      <span key={key} style={{
                        width: `${(Math.abs(Number(t[key])) / termAbsSum) * 100}%`,
                        background: credit ? "var(--rp-fresh)" : "var(--rp-deal)",
                        opacity,
                      }} />
                    ))}
                  </div>
                  <div className="rp-legend">
                    {TERM_LABELS.map(([key, label, credit, opacity]) => (
                      <span key={key}>
                        <span className="rp-sw" style={{
                          background: credit ? "var(--rp-fresh)" : "var(--rp-deal)", opacity,
                        }} />
                        {label}
                      </span>
                    ))}
                  </div>
                  <div className="rp-bar-hint">‹ Vue simple</div>
                </>
              )}
            </div>
          </div>

          <div style={{ height: 8 }} />

          {accepted && (
            <p className="rp-accept-note">
              Menu verrouillé — plan déjà accepté.
            </p>
          )}

          {currentPlan.menu.map((m) => (
            <div className="rp-recipe-row" key={m.recipe_id}>
              <div className="rp-recipe-card" onClick={() => openDetail(m.recipe_id)}>
                <div className={`rp-photo ${photoClassFor(m.recipe_id)}`}>{DISH_ICON}</div>
                <div className="rp-recipe-actions">
                  <button
                    aria-label="Garder" title="Garder"
                    disabled={reoptimizing || accepted}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {CHECK_ICON}
                  </button>
                  <button
                    className="rp-replace" aria-label="Remplacer" title="Remplacer"
                    disabled={reoptimizing || accepted}
                    onClick={(e) => { e.stopPropagation(); replace(m.recipe_id); }}
                  >
                    {replacingId === m.recipe_id ? "…" : SWAP_ICON}
                  </button>
                </div>
                <div className="rp-recipe-body">
                  <div className="rp-recipe-name">{m.name}</div>
                  <div className="rp-recipe-meta">
                    <span className="rp-chip">{CLOCK_ICON} {Number(m.prep_time_h).toFixed(2)} h</span>
                    <span className="rp-chip">{PORTIONS_ICON} {m.servings} portions</span>
                    <span className="rp-recipe-price">{cents(m.attributed_cost_cents_cad)}</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </>
      )}

      {tab === "epicerie" && (
        <>
          <div className="rp-section-label">Épicerie</div>
          {itinerary.length > 1 && (
            <p className="muted" style={{ margin: "0 16px 10px" }}>
              Itinéraire suggéré :{" "}
              {itinerary.map((s, i) => `${i + 1}. ${s.banner} (${s.km.toFixed(1)} km)`).join(" → ")}
            </p>
          )}
          {!accepted && (
            <p className="rp-accept-note">Les articles se cochent une fois le plan accepté.</p>
          )}
          {currentPlan.grocery_list_by_store.map((g) => {
            const store = stores.find((s) => s.external_key === g.store_external_key);
            return (
              <div className="rp-store" key={g.store_external_key}>
                <div className="rp-store-head">
                  <span className="rp-store-name">{store?.banner ?? g.store_external_key}</span>
                  <span className="rp-store-sub">{cents(g.subtotal_cents_cad)}</span>
                </div>
                {g.lines.map((l) => {
                  const key = `${g.store_external_key}:${l.product_external_key}`;
                  return (
                    <div className="rp-item" key={key}>
                      <input
                        type="checkbox"
                        checked={Boolean(checked[key])}
                        disabled={!accepted}
                        onChange={() => toggleChecked(key)}
                      />
                      <div className="rp-item-text">
                        <div className="rp-item-name">
                          {l.ingredient_name} — {l.units} × {l.package_unit}
                          {l.is_promo && <span className="rp-promo-badge">Rabais</span>}
                        </div>
                        <div className="rp-item-brand">{l.brand}</div>
                      </div>
                      <div className="rp-item-price">{cents(l.unit_price_cents_cad)}</div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </>
      )}

      {reoptimizeMsg && <p className="callout" style={{ margin: "10px 16px" }}>{reoptimizeMsg}</p>}
      {reoptimizeError && <p className="callout error" style={{ margin: "10px 16px" }}>{reoptimizeError}</p>}

      <div className="rp-cta-bar">
        <span className="rp-cta-count">
          {accepted ? `${checkedCount}/${totalItems} cochés` : `${totalItems} article${totalItems > 1 ? "s" : ""}`}
        </span>
        <button onClick={accept} disabled={committing || accepted}>
          {accepted ? "Accepté" : committing ? "…" : "Accepter"}
        </button>
      </div>
      {commitError && <p className="callout error" style={{ margin: "10px 16px" }}>{commitError}</p>}

      {openRecipeId && (
        <div className="rp-detail">
          <div className="rp-detail-header">
            <button className="rp-back-btn" onClick={() => setOpenRecipeId(null)}>‹ Retour</button>
          </div>
          <div className={`rp-detail-photo ${photoClassFor(openRecipeId)}`}>{DISH_ICON}</div>
          <div className="rp-detail-body">
            <div className="rp-detail-name">{openRecipe?.name ?? openRecipeId}</div>
            {openRecipe && (
              <div className="rp-detail-meta">
                {openRecipe.servings} portions · {Number(openRecipe.prep_time_h).toFixed(2)} h de cuisine ·{" "}
                {quotePriceLabel(recipeQuotes[openRecipe.recipe_id], quotesLoading)}
              </div>
            )}
            <div className="rp-detail-sec">Ingrédients</div>
            {ingredientsError && <p className="callout error">{ingredientsError}</p>}
            {!ingredientsError && !ingredients && <p className="muted">Chargement…</p>}
            {ingredients && (
              <ul className="rp-detail-ing">
                {ingredients.map((i) => <li key={i.canonical_ingredient_id}>{i.name}</li>)}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
