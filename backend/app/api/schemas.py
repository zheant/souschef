"""Schémas Pydantic de l'API (requêtes/réponses)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator


class MemberOut(BaseModel):
    name: str
    appetite_coefficient: float


class HouseholdOut(BaseModel):
    id: str
    home_lat: float
    home_lng: float
    time_value_cents_per_hour: int
    meals_per_horizon: int
    demand_slack_epsilon: Decimal
    max_store_visits: int
    min_distinct_recipes: int
    max_share_per_recipe: float
    diet_flags: list[str]
    allergen_flags: list[str]
    taste_preferences: dict
    available_equipment: list[str]
    max_prep_time_per_meal_h: float
    appetence_u_min_dollars: float | None
    min_protein_g_per_serving: float | None
    max_distinct_recipes: int | None
    members: list[MemberOut]
    demand: dict  # D exact + bornes (D9)


class HouseholdUpdate(BaseModel):
    """Mise à jour partielle du profil ; members (si fourni) remplace la liste."""

    home_lat: float | None = None
    home_lng: float | None = None
    time_value_cents_per_hour: int | None = Field(default=None, ge=0)
    meals_per_horizon: int | None = Field(default=None, gt=0)
    demand_slack_epsilon: Decimal | None = Field(default=None, ge=0, lt=1)
    max_store_visits: int | None = Field(default=None, ge=1)
    min_distinct_recipes: int | None = Field(default=None, ge=1)
    max_share_per_recipe: float | None = Field(default=None, gt=0, le=1)
    diet_flags: list[str] | None = None
    allergen_flags: list[str] | None = None
    taste_preferences: dict | None = None
    available_equipment: list[str] | None = None
    max_prep_time_per_meal_h: float | None = Field(default=None, gt=0)
    #: U_min. `null` explicite retire le plancher — la route sérialise avec
    #: `exclude_unset`, donc l'omettre le laisse inchangé et l'envoyer à `null`
    #: l'efface. Deux gestes distincts, comme il faut ici : « aucun plancher »
    #: est une valeur, pas une absence de valeur.
    appetence_u_min_dollars: float | None = Field(default=None, ge=0)
    min_protein_g_per_serving: float | None = Field(default=None, ge=0)
    max_distinct_recipes: int | None = Field(default=None, ge=1)
    #: Plancher de dépense d'épicerie, en cents CAD. Même sémantique de
    #: `null` que U_min ci-dessus : omettre laisse inchangé, envoyer `null`
    #: efface. En cents parce que c'est de l'argent (INVARIANTS, CLAUDE.md) —
    #: l'écran affiche des dollars, la frontière n'invente pas de flottant.
    members: list[MemberOut] | None = None


class StapleLine(BaseModel):
    canonical_ingredient_id: str
    name: str


class StaplesUpdate(BaseModel):
    """Remplace l'ensemble complet des essentiels du ménage (pilote,
    docs/product-pilot.md) — pas un upsert ligne par ligne, une simple
    appartenance sans quantité ni priorité."""

    canonical_ingredient_ids: list[str]


class PlanRequest(BaseModel):
    """SolverConfig partielle — tout champ absent prend le défaut de
    développement (spec)."""

    config: dict = Field(default_factory=dict)
    on_date: date | None = None


class RecipeLineIn(BaseModel):
    """Une ligne de recette proposée depuis l'application.

    Les quantités voyagent en **texte**, pas en flottant : une quantité est une
    décimale exacte en base, et un `float` l'arrondirait sur le chemin — la même
    règle que l'argent (INVARIANTS, CLAUDE.md).
    """

    canonical_ingredient_id: str = Field(min_length=1)
    qty_fixed_per_batch_base_unit: str = "0"
    qty_marginal_per_serving_base_unit: str = "0"


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    original_servings: int = Field(ge=1)
    prep_time_fixed_h: str = "0"
    prep_time_marginal_h: str = "0"
    min_batch_servings: int = Field(ge=1)
    max_batch_servings: int = Field(ge=1)
    ingredients: list[RecipeLineIn] = Field(min_length=1)
    diet_flags: list[str] = Field(default_factory=list)
    allergen_flags: list[str] = Field(default_factory=list)
    required_equipment: list[str] = Field(default_factory=list)


class MenuLine(BaseModel):
    recipe_id: str
    name: str
    servings: int
    prep_time_h: str
    attributed_cost_cents_cad: str


class NeededIngredientOut(BaseModel):
    """Ingrédient requis par le menu du plan (pilote, docs/product-pilot.md)
    — écran de confirmation post-génération, tous les ingrédients sont
    montrés ; ``is_staple`` pré-décoche ceux que le ménage est supposé déjà
    avoir."""

    canonical_ingredient_id: str
    name: str
    is_staple: bool


class PlanOut(BaseModel):
    id: int
    status: Literal["proposed", "committed"]
    solver_status: str
    on_date: date
    menu: list[MenuLine]
    grocery_list_by_store: list[dict]
    needed_ingredients: list[NeededIngredientOut]
    stores_visited: list[str]
    diagnostic: dict


class ReoptimizeRequest(BaseModel):
    """Verrouillage/remplacement de recette (pilote, docs/product-pilot.md).
    ``locked_recipe_ids`` doivent appartenir au plan visé ; leurs portions
    sont fixées exactement, jamais changées silencieusement.
    ``excluded_recipe_ids`` sont écartées (et leurs variantes d'échelle
    sœurs, D16) de la réoptimisation."""

    config: dict = Field(default_factory=dict)
    locked_recipe_ids: list[str] = Field(default_factory=list)
    excluded_recipe_ids: list[str] = Field(default_factory=list)


class FinalizeRequest(BaseModel):
    """Confirmation post-génération (pilote, docs/product-pilot.md) — les
    ingrédients dans ``confirmed_available_ids`` sont ceux que l'usager a
    déclaré posséder déjà (le reste de ``needed_ingredients`` non coché) ;
    le menu reste verrouillé en entier, seule la logistique d'achat peut
    changer."""

    config: dict = Field(default_factory=dict)
    confirmed_available_ids: list[str] = Field(default_factory=list)


class MenuChangeOut(BaseModel):
    added: list[str]
    removed: list[str]
    cost_delta_cents: str


class ReoptimizeOut(BaseModel):
    plan: PlanOut
    #: None si le nouveau plan est infaisable — voir plan.diagnostic.
    changes: MenuChangeOut | None


class RecipeIngredientOut(BaseModel):
    """Détail recette (pilote, docs/product-pilot.md)."""

    canonical_ingredient_id: str
    name: str


class NewProductIn(BaseModel):
    """Spécification d'un nouveau produit à créer (D18) — saisie manuelle,
    aucune extraction automatique depuis ``raw_text``."""

    canonical_ingredient_id: str
    brand: str
    package_qty_in_base_unit: Decimal = Field(gt=0)
    package_unit: str
    tax_rate: Decimal = Field(ge=0, lt=1)


class MapRequest(BaseModel):
    """Confirmation d'une offre non résolue : attacher un produit existant
    (``product_id``) ou en créer un nouveau (``new_product``) — exactement
    l'un des deux. La clé de résolution est (magasin, texte brut), pas le
    texte brut seul (D18) : un même libellé désigne des produits différents
    d'une bannière à l'autre."""

    store_external_key: str
    raw_text: str
    confirmed_by: str
    product_id: int | None = None
    new_product: NewProductIn | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "MapRequest":
        if (self.product_id is None) == (self.new_product is None):
            raise ValueError(
                "Fournir exactement un de product_id ou new_product."
            )
        return self


class PriceCoverageOut(BaseModel):
    """Fenêtre couverte par les prix chargés — `null` si la base est vide."""

    earliest: date | None
    latest: date | None


class PriceRefreshOut(BaseModel):
    """État du rafraîchissement de prix — une collecte détachée, pas une requête.

    `log_tail` est la fin de la sortie du collecteur, pas un pourcentage :
    l'écran montre ce que la collecte dit d'elle-même plutôt qu'une progression
    fabriquée à côté.
    """

    state: str  # idle | running | succeeded | failed
    banner: str | None
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    #: `False` : les prix importés sont réels mais partiels — la collecte a été
    #: tronquée. Distinct de `state`, qui ne dit que si la base a été écrite.
    collection_complete: bool | None
    #: Ce que la base a reçu (produits, offres, prix), lu du rapport d'import.
    imported: dict | None
    #: Date de la collecte la plus récente sur disque — y compris lancée en
    #: ligne de commande. `started_at` ne connaît que les lancements passés par
    #: l'application, et répondrait « jamais » à qui utilise
    #: `run_catalogues.cmd`.
    last_capture_at: str | None
    log_tail: list[str]


class PriceRefreshStart(BaseModel):
    """Bannière à collecter. Seule Super C est collectable sans humain devant
    l'écran (Maxi exige une fenêtre de navigateur visible)."""

    banner: str = "superc"
