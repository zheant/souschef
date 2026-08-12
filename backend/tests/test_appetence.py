from datetime import date
from decimal import Decimal

import pytest

from app.services.appetence import (
    AppetenceCalibrationError, RuleBasedAppetenceScorer, season_of,
)
from tests.conftest import make_problem, make_profile, make_recipe


def scorer(liked=(), disliked=(), recent=(), on=date(2026, 8, 10), recipes=None):
    p = make_problem(
        profile=make_profile(liked=liked, disliked=disliked), on=on, recipes=recipes
    )
    return RuleBasedAppetenceScorer(p, recent_recipe_ids=recent)


def test_neutral_recipe_scores_base():
    assert scorer().score(make_recipe()) == Decimal("1.300")


def test_liked_tags_bonus_capped():
    r = make_recipe(tags={"cuisine": "tex-mex", "style": "grill", "x": "wok"})
    s = scorer(liked=("tex-mex", "grill", "wok"))
    assert s.score(r) == Decimal("2.300")  # +1,00 plafonné, pas +1,50


def test_disliked_and_season():
    r = make_recipe(tags={"cuisine": "espagnole", "saison": "ete"})
    s = scorer(disliked=("espagnole",))
    # 1,30 − 0,45 + 0,35 (août = été)
    assert s.score(r) == Decimal("1.200")
    assert season_of(date(2026, 8, 10)) == "ete"


def test_repetition_penalty_most_recent_only():
    r = make_recipe(rid="chili")
    s = scorer(recent=(("chili",), ("chili",)))
    assert s.score(r) == Decimal("0.950")  # −0,35 seulement, pas cumulée


def test_repetition_penalty_applies_across_dish_family_variants():
    """D16 : la pénalité de répétition inter-plans compare des
    dish_family_id, pas des recipe.id. Le plan précédent a cuisiné la
    variante régulière ("chili") ; la variante familiale n'a JAMAIS été
    cuisinée elle-même, mais son plat (même dish_family_id) l'a été — même
    malus que si c'était la recette identique."""
    base = make_recipe(rid="chili", dish_family_id="chili")
    familial = make_recipe(rid="chili_familial", dish_family_id="chili")
    s = scorer(recent=(("chili",),), recipes=[base, familial])
    assert s.score(familial) == Decimal("0.950")  # 1,30 − 0,35
    # Une recette d'une AUTRE famille, elle, n'est pas pénalisée.
    other = make_recipe(rid="dahl", dish_family_id="dahl")
    s2 = scorer(recent=(("chili",),), recipes=[base, familial, other])
    assert s2.score(other) == Decimal("1.300")
    # utility_segments() hérite de score() : pas de chemin résiduel où le
    # premier segment de la variante familiale redémarrerait à plein tarif
    # (1,300) malgré la répétition inter-plans de son plat.
    first_segment_u = s.utility_segments(familial)[0].marginal_u_per_serving
    assert first_segment_u == Decimal("0.950")


def test_bounds_hold_at_extremes():
    """Pire cas de calibration : tous les malus, aucun bonus → doit rester ≥ 0."""
    r = make_recipe(rid="worst", tags={"a": "x", "b": "y", "saison": "hiver"})
    s = scorer(disliked=("x", "y"), recent=(("worst",),))
    assert Decimal("0") <= s.score(r) <= Decimal("3")


def test_out_of_range_raises_not_clamped(monkeypatch):
    import app.services.appetence as ap
    monkeypatch.setattr(ap, "_BASE", Decimal("3.5"))
    with pytest.raises(AppetenceCalibrationError):
        scorer().score(make_recipe())


def test_concave_segments_decreasing_and_cover_m():
    r = make_recipe(m=9)
    segs = scorer().utility_segments(r)
    assert sum(s.max_portions for s in segs) == 9
    marginals = [s.marginal_u_per_serving for s in segs]
    assert marginals == sorted(marginals, reverse=True)
    assert len(set(marginals)) == len(marginals)  # strictement décroissants


def test_concave_segments_never_skip_the_65_percent_tier():
    """m=2 est le seul cas où la formule brute donne un palier à 65 % vide
    (second=0) alors qu'il reste une portion après le premier tiers — sans
    garde-fou, cette portion tombait au palier 35 % au lieu de 65 %,
    contredisant le docstring (« premier tiers plein tarif, deuxième
    65 %, reste 35 % »)."""
    r = make_recipe(m=2)
    segs = scorer().utility_segments(r)
    assert [(s.max_portions, s.marginal_u_per_serving) for s in segs] == [
        (1, Decimal("1.300")), (1, Decimal("0.845")),  # 1,300 * 0,65
    ]


def test_concave_segments_unchanged_for_m_other_than_two():
    """Le garde-fou du palier 65 % ne doit rien changer pour m ≠ 2 — vérifié
    sur un échantillon plutôt que supposé."""
    for m in (1, 3, 4, 5, 6, 8, 12):
        segs = scorer().utility_segments(make_recipe(m=m))
        assert sum(s.max_portions for s in segs) == m
