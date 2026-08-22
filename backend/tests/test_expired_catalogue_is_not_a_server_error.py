"""Un catalogue de prix périmé est une condition métier, jamais un 500.

`problem_data.py` ne charge que les prix dont la fenêtre de validité contient
`on_date`. Passé la dernière semaine chargée, il n'en reste aucun, donc aucune
recette ne survit au préfiltrage et l'assertion 5 lève `EmptyProblemError`.
Cette exception n'était traduite sur aucune des trois routes qui résolvent :
elle remontait en `500 Internal Server Error`, et l'écran n'affichait qu'un
code — alors que la cause (les prix ne couvrent pas cette date) et le geste
correctif (rafraîchir les circulaires) sont tous deux connus au moment de
l'échec.

Le seed jouet couvre la semaine du 2026-08-10 ; toute date hors de cette
fenêtre exerce donc le cas sans rien avoir à truquer en base.
"""

from __future__ import annotations

from tests.db_fixtures import api_client, db_session, test_engine, toy_seeded  # noqa: F401


#: Hors de toute fenêtre de validité du seed jouet, sans être une date absurde.
UNCOVERED_DATE = "2027-03-15"

#: Date couverte, pour prouver que le test discrimine une vraie condition et
#: non un endpoint cassé en toutes circonstances.
COVERED_DATE = "2026-08-10"


def test_expired_catalogue_answers_422_and_names_its_cause(api_client):
    r = api_client.post("/api/plan", json={"config": {}, "on_date": UNCOVERED_DATE})

    assert r.status_code == 422, (
        f"Attendu 422 (condition métier), obtenu {r.status_code} : {r.text}"
    )
    detail = r.json()["detail"]
    assert UNCOVERED_DATE in detail, f"La date en cause n'est pas nommée : {detail}"
    assert "périmé" in detail, f"La cause n'est pas nommée : {detail}"
    assert "run_weekly_catalogues" in detail, (
        f"Le geste correctif n'est pas nommé : {detail}"
    )


def test_a_covered_date_still_resolves(api_client):
    """Le garde ne doit pas transformer un plan valide en erreur."""
    r = api_client.post("/api/plan", json={"config": {}, "on_date": COVERED_DATE})

    assert r.status_code == 200, r.text
    assert r.json()["solver_status"] == "Optimal"


def test_finalize_on_an_uncovered_date_is_not_a_server_error(api_client):
    """`finalize` résout aussi — c'est la route du bouton « Confirmer ».

    Le plan se crée à une date couverte, puis la finalisation est demandée
    telle quelle : elle relit `plan.on_date`, donc reste couverte. Ce test
    verrouille l'autre moitié — qu'une finalisation légitime ne se mette pas
    à répondre 422 maintenant que la route traduit `ValidationError`.
    """
    created = api_client.post("/api/plan", json={"config": {}, "on_date": COVERED_DATE})
    assert created.status_code == 200, created.text
    plan_id = created.json()["id"]

    r = api_client.post(
        f"/api/plan/{plan_id}/finalize",
        json={"config": {}, "confirmed_available_ids": []},
    )
    assert r.status_code == 200, r.text
    assert r.status_code != 500


def test_price_coverage_names_the_window_the_solver_accepts(api_client):
    """L'écran de génération borne son champ de date avec cette réponse.

    Sans elle, la seule façon de connaître la borne était de demander un plan
    hors couverture et de lire l'échec.
    """
    r = api_client.get("/api/price-coverage")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["earliest"] and body["latest"], body
    assert body["earliest"] <= COVERED_DATE <= body["latest"], (
        "La date couverte utilisée par les autres tests doit tomber dans la "
        f"fenêtre annoncée : {body}"
    )
    assert not (body["earliest"] <= UNCOVERED_DATE <= body["latest"]), (
        f"La date non couverte ne doit pas être annoncée comme couverte : {body}"
    )


def test_invalid_solver_config_reports_only_its_message(api_client):
    """Le refus d'un `SolverConfig` ne recrache pas le dump Pydantic.

    « constraint » sans plancher est l'erreur de configuration la plus
    probable — le mode se choisit dans un onglet et la valeur se saisit dans
    un autre champ. `str()` sur la `ValidationError` affichait le
    dictionnaire d'entrée complet et une URL de documentation, noyant la
    seule phrase utile.
    """
    r = api_client.post(
        "/api/plan",
        json={"config": {"appetence_mode": "constraint"}, "on_date": COVERED_DATE},
    )

    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "appetence_u_min_dollars" in detail, detail
    assert "input_value" not in detail, f"Le dump Pydantic fuit encore : {detail}"
    assert "errors.pydantic.dev" not in detail, f"URL de doc exposée : {detail}"
    assert detail.count("\n") == 0, f"Message multiligne : {detail!r}"
