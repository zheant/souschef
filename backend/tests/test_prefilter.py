from app.services.appetence import RuleBasedAppetenceScorer
from app.services.prefilter import prefilter_recipes
from tests.conftest import make_problem, make_profile, make_recipe


def run(recipes, profile):
    p = make_problem(profile=profile, recipes=recipes)
    return prefilter_recipes(p.recipes, p.profile, RuleBasedAppetenceScorer(p))


def test_hard_filters_and_counts():
    recipes = [
        make_recipe(rid="ok"),
        make_recipe(rid="nut", allergens=("arachide",)),
        make_recipe(rid="carn"),  # non végé
        make_recipe(rid="vege", diets=("vegetarien",)),
        make_recipe(rid="four", equipment=("four_a_bois",)),
        make_recipe(rid="slow", tfix="4.0", beta=1),
    ]
    profile = make_profile(allergens=("arachide",), diets=("vegetarien",))
    res = run(recipes, profile)
    assert [r.id for r in res.surviving] == ["vege"]
    assert res.counts_by_stage == {
        "initial": 6, "allergenes": 5, "regime": 1, "equipement": 1,
        "temps_preparation": 1, "troncature": 1,
    }


def test_prep_time_is_a_session_constraint():
    """Critère corrigé au point de contrôle de l'étape 3 : τfix + β·τmarg.

    La recette "marathon" (τfix=0,9, τmarg=0,1, β=8 → séance de 1,7 h) est
    délibérément construite pour être RETENUE par l'ancien critère amorti
    (0,9/8 + 0,1 = 0,21 ≤ 1,5) et ÉCARTÉE par le nouveau (1,7 > 1,5)."""
    marathon = make_recipe(rid="marathon", tfix="0.9", tmarg="0.1", beta=8)
    ok = make_recipe(rid="ok", tfix="0.9", tmarg="0.1", beta=6)  # 1,5 ≤ 1,5
    res = run([marathon, ok], make_profile())
    assert [x.id for x in res.surviving] == ["ok"]
    assert res.counts_by_stage["temps_preparation"] == 1


def test_truncation_keeps_best_by_score():
    recipes = [make_recipe(rid=f"r{i:03d}") for i in range(10)]
    recipes.append(make_recipe(rid="star", tags={"cuisine": "tex-mex"}))
    p = make_problem(profile=make_profile(liked=("tex-mex",)), recipes=recipes)
    res = prefilter_recipes(
        p.recipes, p.profile, RuleBasedAppetenceScorer(p), truncation_keep=3
    )
    assert res.surviving[0].id == "star"
    assert len(res.surviving) == 3
    assert res.counts_by_stage["troncature"] == 3
