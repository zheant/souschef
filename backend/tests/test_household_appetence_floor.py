"""Le plancher d'appétence vit sur le profil, et agit sur le plan.

Le réglage était `appetence_mode`/`appetence_u_min_dollars` sur `SolverConfig`,
donc l'état d'un onglet développeur : il repartait au défaut à chaque
rafraîchissement de la page, ce qui le rendait inutilisable comme préférence.
Il rejoint `household_profile`, avec les autres paramètres surchargeables
(K, R_min, α, ε), résolu par `services/params.py`.

Ce que ces tests verrouillent, et qu'aucun test de `resolve_effective_params`
seul ne pourrait prouver : le plancher persisté traverse réellement l'API et
le solveur, sans qu'aucun mode ne soit réarmé dans la requête.
"""

from __future__ import annotations

from tests.db_fixtures import api_client, db_session, test_engine, toy_seeded  # noqa: F401


ON = "2026-08-10"


def _plan(api_client, config: dict | None = None) -> dict:
    r = api_client.post("/api/plan", json={"config": config or {}, "on_date": ON})
    assert r.status_code == 200, r.text
    return r.json()


def test_without_a_floor_appetence_stays_a_credit_in_the_objective(api_client):
    """Comportement d'avant ce chantier — le défaut ne change pas."""
    d = _plan(api_client)["diagnostic"]

    assert d["effective_params"]["appetence_mode"]["valeur"] == "objective"
    assert d["effective_params"]["appetence_u_min_dollars"]["valeur"] == "None"
    # En mode « objective », l'appétence est créditée dans l'objectif.
    assert d["objective_terms_cents"]["appetence"] != "0.00"


def test_a_floor_saved_on_the_profile_drives_the_plan(api_client):
    """Le geste réel de l'usager : enregistrer, puis générer sans rien d'autre."""
    saved = api_client.put("/api/household", json={"appetence_u_min_dollars": 3.0})
    assert saved.status_code == 200, saved.text
    assert saved.json()["appetence_u_min_dollars"] == 3.0

    d = _plan(api_client)["diagnostic"]

    params = d["effective_params"]
    assert params["appetence_mode"]["valeur"] == "constraint"
    assert params["appetence_mode"]["provenance"] == "dérivé"
    assert params["appetence_u_min_dollars"]["provenance"] == "profil", (
        "Le plancher doit venir du profil, pas d'une surcharge de requête : "
        f"{params['appetence_u_min_dollars']}"
    )
    # En mode « constraint », l'appétence n'est plus un terme de l'objectif —
    # c'est une contrainte. Le rapport doit le refléter, sinon la
    # décomposition annoncerait un crédit qui n'existe pas.
    assert d["objective_terms_cents"]["appetence"] == "0.00"


def test_the_floor_can_be_cleared(api_client):
    """« Aucun plancher » est une valeur, pas une absence de valeur.

    La route sérialise avec `exclude_unset` : omettre la clé laisse le
    plancher intact, l'envoyer à `null` l'efface. Sans ce test, seul le
    premier geste serait couvert.
    """
    api_client.put("/api/household", json={"appetence_u_min_dollars": 3.0})

    # Une mise à jour sans la clé ne doit pas effacer le plancher.
    other = api_client.put("/api/household", json={"meals_per_horizon": 14})
    assert other.status_code == 200, other.text
    assert other.json()["appetence_u_min_dollars"] == 3.0

    cleared = api_client.put("/api/household", json={"appetence_u_min_dollars": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["appetence_u_min_dollars"] is None

    d = _plan(api_client)["diagnostic"]
    assert d["effective_params"]["appetence_mode"]["valeur"] == "objective"


def test_a_request_can_still_override_the_saved_floor(api_client):
    """Le mode développeur garde la main sur la préférence persistée."""
    api_client.put("/api/household", json={"appetence_u_min_dollars": 3.0})

    d = _plan(api_client, {"appetence_mode": "objective"})["diagnostic"]
    params = d["effective_params"]
    assert params["appetence_mode"]["valeur"] == "objective"
    assert params["appetence_u_min_dollars"]["provenance"] == "solver_config"
