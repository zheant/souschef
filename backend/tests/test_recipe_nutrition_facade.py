"""La façade et la route rendent la valeur nutritive, ou refusent en le disant.

Contre PostgreSQL réel : la façade assemble quatre faits qui vivent à quatre
endroits (recettes, canon, pont FCÉN, teneurs fédérales) et le module pur est
déjà couvert ailleurs. Ce qui est exercé ici, c'est l'assemblage — et les deux
pannes de déploiement qui ont déjà coûté un 500 à la route des prix : un
fichier de règles absent, et une donnée de référence jamais importée.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import (
    CanonicalIngredientExternalRef,
    CnfNutrientAmount,
    CnfNutrientName,
)
from app.services import recipe_nutrition_facts

from tests.db_fixtures import api_client, db_session, test_engine, toy_seeded  # noqa: F401

SHA = "F5FAAD8977EE6BBDD9D69C8649077CACD87D8658AD200509A4047DB1E29EDCDD"
#: Riz blanc, grain long, étuvé, enrichi, cru — teneurs de l'archive 2026.
RICE_FOOD_CODE = "3708"
RICE = {"208": "374", "203": "7.51", "204": "1.03", "205": "80.89"}


def _publish_nutrients(session, food_code=RICE_FOOD_CODE, amounts=None):
    """Pose les quatre teneurs retenues, avec leurs unités publiées.

    Idempotente : le client HTTP de test valide sa session à chaque requête,
    donc des lignes d'un test précédent peuvent survivre à son `rollback`.
    """
    if session.query(CnfNutrientAmount).filter(
        CnfNutrientAmount.food_code == food_code
    ).count():
        return
    units = {
        "208": ("KCAL", "kilocalorie", "Energy (kilocalories)", "Énergie"),
        "203": ("PROT", "Gram", "Protein", "Protéines"),
        "204": ("FAT", "Gram", "Fat", "Lipides"),
        "205": ("CARB", "Gram", "Carbohydrate", "Glucides"),
    }
    for code, (symbol, unit, name_en, name_fr) in units.items():
        session.add(
            CnfNutrientName(
                source_version="2026", archive_sha256=SHA, nutrient_code=code,
                nutrient_symbol=symbol, nutrient_unit=unit,
                nutrient_name_en=name_en, nutrient_name_fr=name_fr,
                tagname=symbol, nutrient_decimals=2,
            )
        )
    for code, amount in (amounts or RICE).items():
        session.add(
            CnfNutrientAmount(
                source_version="2026", archive_sha256=SHA, food_code=food_code,
                nutrient_code=code, amount_per_100g=Decimal(amount),
                nutrient_source_code="4",
            )
        )
    session.flush()


def _attach(session, ingredient_id, food_code=RICE_FOOD_CODE):
    # Idempotente pour la même raison que `_publish_nutrients` : le client HTTP
    # de test valide sa session à chaque requête.
    if session.query(CanonicalIngredientExternalRef).filter(
        CanonicalIngredientExternalRef.external_id == food_code,
        CanonicalIngredientExternalRef.source_version == "2026",
    ).count():
        return
    session.add(
        CanonicalIngredientExternalRef(
            canonical_ingredient_id=ingredient_id, source="cnf",
            external_id=food_code, source_version="2026",
            notes="Rattachement de test.",
        )
    )
    session.flush()


def test_a_curated_ingredient_yields_a_real_per_serving_number(db_session):
    _publish_nutrients(db_session)
    _attach(db_session, "riz")

    facts = recipe_nutrition_facts.nutrition_facts(
        db_session, recipe_id="riz_nature"
    )
    assert len(facts) == 1
    quote = facts[0]
    # 80 g de riz par portion, à 374 kcal/100 g.
    assert quote.status == "complete"
    assert quote.kcal_per_serving == Decimal("299.2")
    assert quote.protein_g_per_serving == Decimal("6.0")
    assert quote.confidence == "exact"
    assert quote.lines[0].food_code == RICE_FOOD_CODE


def test_a_recipe_missing_one_ingredient_refuses_and_names_it(db_session):
    _publish_nutrients(db_session)
    _attach(db_session, "riz")

    (quote,) = recipe_nutrition_facts.nutrition_facts(
        db_session, recipe_id="dahl_toy"
    )
    assert quote.status == "incomplete"
    assert quote.kcal_per_serving is None
    assert [row[0] for row in quote.missing] == ["lentille"]


def test_an_uncurated_corpus_is_a_deployment_failure_not_a_silent_zero(
    db_session,
):
    """Aucune teneur chargée n'est pas « 0 kcal », c'est un import à rejouer."""
    # Explicite plutôt qu'implicite : un test précédent a pu valider des
    # teneurs par le client HTTP, et cette assertion porte sur leur absence.
    db_session.query(CnfNutrientAmount).delete()
    _attach(db_session, "riz")
    with pytest.raises(recipe_nutrition_facts.NutritionDataUnavailable) as error:
        recipe_nutrition_facts.nutrition_facts(db_session, recipe_id="riz_nature")
    assert "app.ingestion.cnf" in str(error.value)


def test_published_units_other_than_the_expected_ones_stop_the_calculation(
    db_session,
):
    """Le FCÉN ne convertit rien à l'import; la façade ne le suppose pas.

    Une édition publiant l'énergie en kilojoules donnerait des valeurs
    plausibles et fausses d'un facteur 4,184, sans rien changer d'autre.
    """
    _publish_nutrients(db_session)
    _attach(db_session, "riz")
    db_session.query(CnfNutrientName).filter(
        CnfNutrientName.nutrient_code == "208"
    ).update({"nutrient_unit": "kilojoule"})
    db_session.flush()

    with pytest.raises(recipe_nutrition_facts.NutritionDataUnavailable):
        recipe_nutrition_facts.nutrition_facts(db_session, recipe_id="riz_nature")


def test_a_missing_rules_file_is_a_named_deployment_failure(
    db_session, monkeypatch, tmp_path
):
    """Exactement la panne qui a valu un 500 à la route des devis (MENU_CONFIG_DIR)."""
    monkeypatch.setattr(
        recipe_nutrition_facts.settings, "config_dir", str(tmp_path)
    )
    with pytest.raises(recipe_nutrition_facts.NutritionRulesUnavailable) as error:
        recipe_nutrition_facts.nutrition_facts(db_session, recipe_id="riz_nature")
    assert "MENU_CONFIG_DIR" in str(error.value)


def test_an_invalid_rules_file_is_refused_rather_than_half_applied(
    db_session, monkeypatch, tmp_path
):
    (tmp_path / "nutrition-rules.json").write_text(
        '{"rule_version": "cassé", "negligible_contributions": '
        '[{"ingredient_id": "sel_table", "base_unit": "g"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        recipe_nutrition_facts.settings, "config_dir", str(tmp_path)
    )
    with pytest.raises(recipe_nutrition_facts.NutritionRulesUnavailable) as error:
        recipe_nutrition_facts.nutrition_facts(db_session, recipe_id="riz_nature")
    assert "kcal_per_100g" in str(error.value)


def test_an_unknown_recipe_is_a_lookup_error(db_session):
    with pytest.raises(LookupError):
        recipe_nutrition_facts.nutrition_facts(db_session, recipe_id="fantome")


def test_the_route_publishes_the_number_and_the_refusal(api_client, db_session):
    _publish_nutrients(db_session)
    _attach(db_session, "riz")

    response = api_client.get("/api/recipe-nutrition?recipe_id=riz_nature")
    assert response.status_code == 200
    body = response.json()[0]
    assert body["status"] == "complete"
    assert float(body["kcal_per_serving"]) == pytest.approx(299.2)
    assert body["missing"] == []
    assert body["rule_version"]

    refused = api_client.get("/api/recipe-nutrition?recipe_id=dahl_toy").json()[0]
    assert refused["status"] == "incomplete"
    assert refused["kcal_per_serving"] is None
    assert refused["missing"] == [
        {"canonical_ingredient_id": "lentille", "reason": "no_cnf_food"}
    ]


def test_the_route_rescales_to_the_requested_yield(api_client, db_session):
    """Le solveur passe son x_r en portions : la route doit suivre ce rendement.

    `riz_nature` ne porte que du marginal (80 g par portion), donc la valeur par
    portion ne bouge pas — c'est justement ce qu'il faut vérifier : rescaler ne
    doit pas la déformer. Une recette sans composante marginale, elle, est
    refusée par le module (couvert dans test_recipe_nutrition.py) et le refus
    est arbitré avant tout chargement de données de référence.
    """
    _publish_nutrients(db_session)
    _attach(db_session, "riz")

    for servings in (2, 5):
        body = api_client.get(
            f"/api/recipe-nutrition?recipe_id=riz_nature&servings={servings}"
        ).json()[0]
        assert body["servings"] == servings
        assert float(body["kcal_per_serving"]) == pytest.approx(299.2)


def test_the_route_reports_a_missing_rules_file_as_503(
    api_client, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        recipe_nutrition_facts.settings, "config_dir", str(tmp_path)
    )
    response = api_client.get("/api/recipe-nutrition?recipe_id=riz_nature")
    assert response.status_code == 503
    assert "MENU_CONFIG_DIR" in response.json()["detail"]
