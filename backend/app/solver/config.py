"""Configuration du solveur (docs/spec.md).

Chaque drapeau doit produire un modèle **valide et résoluble seul**. Défaut de
développement : tout à ``False``, un seul magasin, ``appetence_mode =
"objective"``. On rallume un mécanisme à la fois.

Interactions documentées (sémantiques précisées, docs/deviations.md D11) :

- ``enable_batch_fixed_cost = False`` retire le mécanisme de lot complet :
  δ_r, τ^fixe_r, mais aussi â^fixe_ir (lié à δ_r dans la couverture) et la
  borne basse β_r (elle s'écrit β_r·δ_r). Si la diversité est active, un
  indicateur binaire δ_r subsiste avec le lien minimal x_r ≥ δ_r — sans lui,
  Σδ_r ≥ R_min se satisferait de recettes vides.
- ``enable_multi_store = False`` : un seul magasin imposé — celui du
  ``single_store_external_key`` s'il est fourni, sinon le plus proche du
  domicile (règle déterministe) ; z_s, y et tous les coûts de déplacement
  sont retirés.
- ``enable_time_cost = False`` : κ = 0 ; τ^fixe ne pèse dans l'objectif que si
  le coût du temps ET le coût fixe de lot sont actifs.
- ``appetence_mode`` : ``None`` (défaut) → suivre le plancher du profil ;
  "objective" → −Σ_k u_rk·x_rk dans l'objectif, en écartant ce plancher ;
  "constraint" → Σ_k u_rk·x_rk ≥ U_min (``appetence_u_min_dollars`` requis).
  Dans les deux cas l'utilité est concave par morceaux (segments du scorer).
- Avec ``enable_diversity = False``, un menu monotone est **attendu** — c'est
  la démonstration que la contrainte est nécessaire, vérifiée par test dans
  les deux configurations.
- ``enable_staples = False`` : un essentiel est évalué au prix courant comme
  n'importe quel ingrédient — aucun biais. Actif, seul l'objectif change
  (quel prix un essentiel voit) ; la couverture/le besoin ne bougent jamais,
  contrairement à l'ancien ``enable_pantry_stock`` qu'il remplace.
- ``enable_perishable_penalty = False`` (D19, docs/deviations.md) : sixième
  terme d'objectif, pénalise le surplus ``w_i`` d'un ingrédient périssable
  au lieu de simplement ne pas le créditer (ce que ``σ_i = 0`` fait déjà
  pour un ingrédient réellement périssable). Partage la variable ``w_i``
  avec ``enable_salvage`` (même définition, ``w_i ≤ approvisionnement −
  besoin``) mais reste testable seul — n'altère jamais la couverture/le
  besoin, seulement l'objectif.
- ``enable_variant_exclusion`` (D16, docs/deviations.md) fait EXCEPTION au
  défaut « tout à False » : il vaut ``True`` par défaut. Les variantes
  d'échelle du seed (format régulier / familial) sont deux segments d'une
  même courbe de coût non linéaire pour produire un seul plat, pas deux
  plats — les laisser cuisinables ensemble n'a aucun sens culinaire (payer
  τ_fixe deux fois pour le même plat) et ouvre un contournement structurel
  du plafond de part x_r ≤ α·D et du compte de diversité Σδ_r ≥ R_min
  (chaque variante reste sous le plafond individuellement, leur somme ne
  l'est pas). Ce n'est pas un mécanisme d'optimisation à activer un à un
  comme les autres — c'est une contrainte d'intégrité du modèle, active même
  en configuration de développement minimale.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SolverConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enable_multi_store: bool = False
    enable_batch_fixed_cost: bool = False
    enable_salvage: bool = False
    #: Sixième terme d'objectif (D19, docs/deviations.md) : pénalise le
    #: surplus d'un ingrédient périssable, symétrique de enable_salvage qui
    #: ne fait que le créditer. Partage w_i/_add_surplus avec enable_salvage
    #: (solver/model.py) mais reste indépendamment activable.
    enable_perishable_penalty: bool = False
    enable_time_cost: bool = False
    #: Essentiels (staples, pilote, docs/product-pilot.md) : biaise
    #: uniquement l'objectif (quel prix un essentiel voit), jamais la
    #: couverture — contrairement à l'ancien enable_pantry_stock, ce
    #: drapeau n'altère pas l'équation de besoin (FLAGS_ALTERING_NEEDS).
    enable_staples: bool = False
    enable_diversity: bool = False
    #: Exception au défaut « tout False » (voir docstring du module, D16) :
    #: exclusion mutuelle des variantes d'échelle du même plat, active par
    #: défaut.
    enable_variant_exclusion: bool = True

    #: Surcharge explicite du mode d'appétence. `None` — le défaut — signifie
    #: « suivre le profil » : le mode effectif se dérive alors du plancher
    #: persisté sur `household_profile` (`services/params.py`). Un défaut à
    #: "objective" rendait cette dérivation impossible : on ne pouvait pas
    #: distinguer « non surchargé » de « objective demandé explicitement »,
    #: donc la préférence du ménage était écartée dans le cas courant.
    appetence_mode: Literal["objective", "constraint"] | None = None
    #: U_min en dollars, requis si appetence_mode = "constraint".
    appetence_u_min_dollars: float | None = Field(default=None, ge=0)

    # Surcharges optionnelles du profil (résolues par resolve_effective_params,
    # l'unique point de préséance).
    max_store_visits: int | None = Field(default=None, ge=1)
    min_distinct_recipes: int | None = Field(default=None, ge=1)
    max_share_per_recipe: float | None = Field(default=None, gt=0, le=1)
    demand_slack_epsilon: float | None = Field(default=None, ge=0, lt=1)  # ε (D9)

    #: Magasin imposé quand enable_multi_store = False ; None → le plus proche.
    single_store_external_key: str | None = None

    #: recipe_id -> portions fixées exactement (x_r = valeur, δ_r = 1).
    #: Dict vide = comportement inchangé ; sa présence EST le drapeau, pas un
    #: enable_* séparé (évite un état ambigu drapeau=True/dict vide).
    #: Alimenté par services/planning.py::reoptimize_plan — jamais construit
    #: à la main par un appelant HTTP (verrouiller = figer la valeur du plan
    #: précédent, pas une valeur arbitraire).
    locked_recipe_servings: dict[str, int] = Field(default_factory=dict)

    #: Ingrédients confirmés disponibles pour CE plan précis, après la
    #: liste de confirmation post-génération (pilote,
    #: docs/product-pilot.md) — tuple vide = comportement inchangé, même
    #: motif que locked_recipe_servings. Alimenté par
    #: services/planning.py::finalize_plan, jamais construit à la main par
    #: un appelant HTTP. Contrairement à l'ancien pantry_stock, ceci n'est
    #: **jamais persisté** — un usage unique par résolution, dérivé de la
    #: confirmation de l'utilisateur pour ce plan-là seulement.
    confirmed_available_ids: tuple[str, ...] = ()

    solver_time_limit_s: int = Field(default=60, ge=1)
    mip_gap: float = Field(default=0.001, ge=0)

    @model_validator(mode="after")
    def _constraint_mode_needs_u_min(self) -> "SolverConfig":
        if self.appetence_mode == "constraint" and self.appetence_u_min_dollars is None:
            raise ValueError(
                "appetence_mode='constraint' exige appetence_u_min_dollars."
            )
        return self

    def enabled_flags(self) -> list[str]:
        """Drapeaux actifs, dans l'ordre de déclaration — le dernier élément
        est « le dernier drapeau activé » du rapport d'infaisabilité."""
        return [
            name
            for name in (
                "enable_multi_store", "enable_batch_fixed_cost", "enable_salvage",
                "enable_perishable_penalty", "enable_time_cost", "enable_staples",
                "enable_diversity", "enable_variant_exclusion",
            )
            if getattr(self, name)
        ]
