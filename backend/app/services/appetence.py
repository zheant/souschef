"""Scoring d'appétence — par règles, pas par apprentissage (docs/spec.md).

u_r est en dollars-équivalents par portion, dans [0, 3]. Une valeur hors de
cet intervalle est une **erreur de calibration** détectée par assertion — le
score n'est jamais tronqué silencieusement.

Trois composantes, celles de la spec et rien d'autre :
1. correspondance des tags aux préférences déclarées
   (``household_profile.taste_preferences``) ;
2. pénalité de répétition récente (``recent_recipe_ids``, du plan le plus
   récent au plus ancien — branché sur l'historique des plans à l'étape 5,
   vide d'ici là) ;
3. bonus de saisonnalité (saison courante dérivée de la date du problème).

Répétition au niveau du PLAT (D16, docs/deviations.md) : ``recent_recipe_ids``
contient des ``recipe.id`` bruts (ce que les plans commis stockent), mais la
comparaison se fait sur ``dish_family_id`` — sinon cuisiner
``chili_familial`` une semaine après ``chili`` ne compte jamais comme une
répétition, alors que c'est le même plat. La table de correspondance
id→famille vient de ``problem.recipes`` (le catalogue courant) ; un id
historique absent du catalogue actuel retombe sur lui-même comme famille
(dégradation sûre vers l'ancien comportement, pas un crash). ``utility_segments``
hérite automatiquement de cette correction : il appelle ``score()`` pour
obtenir sa base, donc son premier segment ne « redémarre » jamais à plein
tarif pour une variante dont la famille vient d'être cuisinée.

Calibration (bornes par construction, vérifiées par ``test_appetence``) :
    base 1,30 ; +0,50/tag aimé (plafond +1,00) ; −0,45/tag évité
    (plancher −0,90) ; saison exacte +0,35, « toutes » +0,10 ;
    répétition −0,35 (dernier plan) ou −0,15 (avant-dernier).
    max = 1,30 + 1,00 + 0,35 = 2,65 ≤ 3 ; min = 1,30 − 0,90 − 0,35 = 0,05 ≥ 0.

L'interface ``AppetenceScorer`` isole ce calcul : un modèle appris le
remplacera plus tard sans toucher au préfiltrage ni au solveur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from .problem_data import ProblemData, RecipeData

U_MIN = Decimal("0")
U_MAX = Decimal("3")

_BASE = Decimal("1.30")
_LIKED_BONUS = Decimal("0.50")
_LIKED_CAP = Decimal("1.00")
_DISLIKED_MALUS = Decimal("0.45")
_DISLIKED_CAP = Decimal("0.90")
_SEASON_EXACT = Decimal("0.35")
_SEASON_ALL = Decimal("0.10")
_REPEAT_PENALTIES = (Decimal("0.35"), Decimal("0.15"))  # dernier, avant-dernier plan


class AppetenceCalibrationError(ValueError):
    """u_r hors de [0, 3] — erreur de calibration, jamais tronquée."""


@dataclass(frozen=True)
class UtilitySegment:
    """Segment d'utilité concave linéarisée par morceaux (consommé par le
    solveur à l'étape 4) : ``max_portions`` portions à ``marginal_u_per_serving``
    dollars-équivalents chacune."""

    max_portions: int
    marginal_u_per_serving: Decimal


class AppetenceScorer(Protocol):
    def score(self, recipe: RecipeData) -> Decimal:
        """u_r ∈ [0, 3] $/portion."""
        ...

    def utility_segments(self, recipe: RecipeData) -> list[UtilitySegment]:
        """Utilité concave par morceaux (segments décroissants) : la 8e portion
        de chili ne vaut pas la première."""
        ...


def season_of(d: date) -> str:
    return {12: "hiver", 1: "hiver", 2: "hiver", 3: "printemps", 4: "printemps",
            5: "printemps", 6: "ete", 7: "ete", 8: "ete", 9: "automne",
            10: "automne", 11: "automne"}[d.month]


class RuleBasedAppetenceScorer:
    """Implémentation v1 par règles. Déterministe : mêmes entrées, même u_r."""

    def __init__(
        self,
        problem: ProblemData,
        recent_recipe_ids: tuple[tuple[str, ...], ...] = (),
    ):
        prefs = problem.profile.taste_preferences or {}
        self._liked = set(prefs.get("liked_tags", []))
        self._disliked = set(prefs.get("disliked_tags", []))
        self._season = season_of(problem.on_date)
        #: Un tuple d'ids de recettes par plan passé, du plus récent au plus
        #: ancien ; branché sur l'historique des plans à l'étape 5.
        self._recent = recent_recipe_ids
        #: id de recette → dish_family_id, pour comparer la répétition au
        #: niveau du plat plutôt que de la recette (D16).
        self._family_of = {r.id: r.dish_family_id for r in problem.recipes}

    def score(self, recipe: RecipeData) -> Decimal:
        tag_values = {str(v) for v in recipe.tags.values()}

        u = _BASE
        u += min(_LIKED_BONUS * len(tag_values & self._liked), _LIKED_CAP)
        u -= min(_DISLIKED_MALUS * len(tag_values & self._disliked), _DISLIKED_CAP)

        saison = recipe.tags.get("saison")
        if saison == self._season:
            u += _SEASON_EXACT
        elif saison == "toutes":
            u += _SEASON_ALL

        target_family = recipe.dish_family_id
        for plan_ids, penalty in zip(self._recent, _REPEAT_PENALTIES):
            plan_families = {self._family_of.get(rid, rid) for rid in plan_ids}
            if target_family in plan_families:
                u -= penalty
                break  # la pénalité la plus récente seulement

        if not (U_MIN <= u <= U_MAX):
            raise AppetenceCalibrationError(
                f"u_r={u} hors [0, 3] pour la recette '{recipe.id}' : "
                "erreur de calibration du scorer."
            )
        return u.quantize(Decimal("0.001"))

    def utility_segments(self, recipe: RecipeData) -> list[UtilitySegment]:
        """Trois segments décroissants découpant [0, m_r] : plein tarif sur le
        premier tiers, 65 % sur le deuxième, 35 % sur le reste. Reste dans le
        MILP (coefficients constants par segment) et modélise la lassitude
        mieux que le seul plafond m_r."""
        u = self.score(recipe)
        m = recipe.max_batch_servings
        first = max(1, m // 3)
        second = max(0, (2 * m) // 3 - first)
        # Les paliers se remplissent dans l'ordre — jamais de portion au
        # palier 35 % tant que le palier 65 % est vide. Pour m=2, la
        # formule brute donne second=0 (4//3-1=0) alors qu'il reste une
        # portion après "first" : sans ce garde-fou, elle tombait dans
        # "rest" à 35 % au lieu de 65 %. Ne change rien pour m=1 (rien ne
        # reste après "first") ni pour m≥3 (second est déjà > 0).
        if second == 0 and m > first:
            second = 1
        rest = m - first - second
        segments = [UtilitySegment(first, u)]
        if second:
            segments.append(
                UtilitySegment(second, (u * Decimal("0.65")).quantize(Decimal("0.001")))
            )
        if rest:
            segments.append(
                UtilitySegment(rest, (u * Decimal("0.35")).quantize(Decimal("0.001")))
            )
        return segments
