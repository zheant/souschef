"""Le script d'appariement propose, rejette, et se trompe de façon vérifiable.

Les cas de ce fichier ne sont pas inventés : ce sont les noms réels de
l'archive FCÉN 2026. Deux exigences les gouvernent — rejeter les faux positifs
que la ressemblance de chaînes acceptait (l'huile appariée à des frites, le
sirop d'érable à une crêpe), et trouver les appariements qu'elle manquait
(ketchup, parmesan, courgette, poireau), dont le nom fédéral ne ressemble pas
du tout au nom canonique pris en entier.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.cnf_match_proposal import (
    COMPOSITE_DISH,
    COOKED_OR_PREPARED_FORM,
    MatchFood,
    MatchTarget,
    propose_matches,
)


def food(code, name, group="Divers", kcal="100"):
    return MatchFood(
        food_code=code,
        name=name,
        group=group,
        kcal_per_100g=Decimal(kcal) if kcal is not None else None,
    )


def target(ingredient_id, name, family_name=None, blocked=0, attached=()):
    return MatchTarget(
        ingredient_id=ingredient_id,
        name=name,
        family_name=family_name,
        base_unit="g",
        blocked_recipes=blocked,
        attached_food_codes=tuple(attached),
    )


def one(targets, foods, **kwargs):
    return propose_matches(targets, foods, **kwargs)[0]


def codes(proposal):
    return [row.food_code for row in proposal.candidates]


def rejections(proposal):
    return {row.food_code: row.reason for row in proposal.rejected}


# --- Les faux positifs nommés dans le ticket -------------------------------

def test_oil_is_not_matched_to_frozen_fries():
    """« huile » apparaît au cinquième segment d'un nom de frites.

    C'est le faux positif type de la ressemblance de chaînes : le mot est là,
    l'aliment n'a rien à voir. Un ingrédient nommé au fond d'un nom composé
    décrit une préparation, pas l'ingrédient.
    """
    proposal = one(
        [target("huile_vegetale", "Huile végétale", "Huiles et matières grasses")],
        [
            food("451", "Huile végétale, canola (colza)", kcal="885"),
            food(
                "2436",
                "Pomme de terre, frite, congelée, préparée au restaurant avec "
                "de l'huile végétale",
                kcal="196",
            ),
        ],
    )
    assert codes(proposal) == ["451"]
    assert rejections(proposal)["2436"] in (COMPOSITE_DISH, COOKED_OR_PREPARED_FORM)


def test_maple_syrup_is_not_matched_to_a_pancake():
    proposal = one(
        [target("sirop_erable", "Sirop d'érable", "Sucres et sirops")],
        [
            food("4326", "Confiseries, sirop d'érable, en vrac", kcal="272"),
            food(
                "6782",
                "Crêpe, nature, faite maison avec beurre et sirop d'érable",
                kcal="210",
            ),
        ],
    )
    assert codes(proposal) == ["4326"]
    assert rejections(proposal)["6782"] == COMPOSITE_DISH


def test_canned_tomato_is_not_matched_to_juice():
    """Le jus partage le mot, pas la couverture : il perd sur « conserve »."""
    proposal = one(
        [target("tomate_conserve", "Tomate en conserve", "Tomates transformées")],
        [
            food("2265", "Tomate, jus, conserve", kcal="17"),
            food("2258", "Tomate, rouge, mûre, conserve, entière", kcal="16"),
        ],
    )
    assert codes(proposal)[0] == "2258"


def test_onion_is_not_matched_to_a_cooked_form():
    proposal = one(
        [target("oignon_jaune", "Oignon jaune", "Alliacées")],
        [
            food("2401", "Oignon, cru", kcal="40"),
            food("2404", "Oignon, bouilli, égoutté", kcal="44"),
            food("950", "Soupe, oignon, conserve, condensée", kcal="46"),
        ],
    )
    assert codes(proposal)[0] == "2401"
    assert rejections(proposal)["2404"] == COOKED_OR_PREPARED_FORM


# --- Les appariements que la ressemblance de chaînes manquait ---------------

def test_ketchup_is_found_under_a_federal_name_that_starts_elsewhere():
    """« Tomates, ketchup (catsup) » ne ressemble pas à « Ketchup ».

    Sur la chaîne entière, la similarité est faible; sur les jetons, le mot est
    là et il est le seul. C'est le cas qui justifie la recherche par jetons.
    """
    proposal = one(
        [target("ketchup", "Ketchup", "Sauces et condiments")],
        [
            food("2494", "Tomates, ketchup (catsup)", kcal="101"),
            food("2498", "Tomates, ketchup (catsup), faible en sodium", kcal="101"),
            food("5354", "Sauce, chili, piments forts, conserve", kcal="21"),
        ],
    )
    assert codes(proposal)[0] == "2494"
    # La sauce chili ne partage aucun jeton : elle n'est même pas candidate.
    assert "5354" not in codes(proposal)


def test_parmesan_is_found_and_the_frozen_dish_is_rejected():
    proposal = one(
        [target("parmesan", "Parmesan", "Fromages")],
        [
            food("40", "Fromage parmesan, pâte dure", kcal="392"),
            food(
                "7447",
                "Met surgelé, poulet parmesan (panné ou non panné) avec pâtes",
                kcal="106",
            ),
        ],
    )
    assert codes(proposal) == ["40"]
    assert rejections(proposal)["7447"] == COOKED_OR_PREPARED_FORM


def test_courgette_is_found_under_its_botanical_first_segment():
    proposal = one(
        [target("courgette", "Courgette", "Légumes")],
        [
            food("2225", "Courge d'été, courgette (zucchini), crue", kcal="17"),
            food(
                "2226",
                "Courge d'été, courgette (zucchini), bouillie, égouttée",
                kcal="15",
            ),
        ],
    )
    assert codes(proposal) == ["2225"]
    assert rejections(proposal)["2226"] == COOKED_OR_PREPARED_FORM


def test_leek_prefers_the_raw_form_over_a_dehydrated_soup():
    proposal = one(
        [target("poireau", "Poireau", "Alliacées")],
        [
            food("2396", "Poireaux (bulbe et portion inférieure), crus", kcal="61"),
            food("980", "Soupe, poireaux, déshydratée", kcal="377"),
        ],
    )
    assert codes(proposal) == ["2396"]


def test_a_bird_category_is_not_read_as_a_cooking_method():
    """« Poulet à griller » est une catégorie d'oiseau, pas du poulet grillé.

    Trouvé en exécutant sur l'archive réelle : comparer les marques de cuisson
    par préfixe rejetait les seules cuisses de poulet crues du fichier fédéral,
    et « cuisse » se lisait comme « cuit » par le même mécanisme.
    """
    proposal = one(
        [target("poulet_cuisse", "Cuisses de poulet", "Volaille")],
        [
            food("607", "Poulet à griller, cuisse, viande et peau, cru", kcal="211"),
            food("610", "Poulet à griller, cuisse, viande et peau, rôti", kcal="247"),
        ],
    )
    assert codes(proposal) == ["607"]
    assert rejections(proposal)["610"] == COOKED_OR_PREPARED_FORM


def test_freezing_is_a_purchase_state_not_a_preparation():
    """Le FCÉN écrit « frais ou congelé, cru » : c'est l'état d'achat.

    Trouvé en exécutant : traiter la congélation comme une cuisson rejetait
    l'œuf de poule et laissait l'œuf de cane en tête, à 186 kcal/100 g.
    """
    proposal = one(
        [target("oeuf", "Œuf de calibre gros", "Œufs")],
        [
            food("125", "Oeuf, poule, entier, frais ou congelé, cru", kcal="143"),
            food("88", "Oeuf, canard, entier, frais, cru", kcal="186"),
            food("83", "Oeuf, poule, déshydraté, entier", kcal="594"),
        ],
    )
    # L'œuf de poule est candidat, l'œuf déshydraté est rejeté. Lequel des
    # oiseaux passe devant l'autre, le module ne le sait pas : « Œuf de calibre
    # gros » ne nomme aucune espèce, et « canard » n'est pas plus bavard que
    # « poule ». C'est précisément ce que le manifeste laisse à un humain.
    assert "125" in codes(proposal)
    assert rejections(proposal)["83"] == COOKED_OR_PREPARED_FORM


def test_the_oe_ligature_does_not_hide_a_word():
    """« Œuf » et « Oeuf » sont le même mot; la décomposition Unicode l'ignore.

    Sans réduction de la ligature, « Œuf de calibre gros » ne partageait aucun
    jeton avec « Oeuf, poule, … » et s'appariait sur « gros » à « Porc, morceau
    de gros, gras de dos, cru » — 812 kcal/100 g.
    """
    proposal = one(
        [target("oeuf", "Œuf de calibre gros", "Œufs")],
        [
            food("125", "Oeuf, poule, entier, frais ou congelé, cru", kcal="143"),
            food("1757", "Porc, morceau de gros, gras de dos, cru", kcal="812"),
        ],
    )
    assert codes(proposal) == ["125"]


def test_a_preparation_that_contains_the_ingredient_is_not_the_ingredient():
    """« Biscuit, beurre, Petit Beurre » n'est pas du beurre.

    Trouvé en exécutant : le mot cherché est au deuxième segment, donc le rejet
    de plat composé ne le voit pas. Et juger les transformations en bloc
    désarmait la règle — le nom porte « beurre », que le canon nomme, ce qui
    faisait passer « biscuit » et « huile » gratuitement.
    """
    proposal = one(
        [target("beurre_non_precise", "Beurre non précisé", "Produits laitiers")],
        [
            food("118", "Beurre, salé", kcal="717"),
            food(
                "7833",
                "Biscuit, beurre, Petit Beurre, fait avec de l'huile végétale",
                kcal="447",
            ),
        ],
    )
    assert codes(proposal)[0] == "118"
    signals = proposal.candidates[1].signals
    assert any(signal.startswith("derived_form") for signal in signals)


def test_a_parenthesised_synonym_belongs_to_the_head_of_the_name():
    """Le FCÉN met le mot qui discrimine entre parenthèses, où qu'il tombe.

    Trouvé en exécutant : « Confiseries, sucre, brun (cassonade) » et « Pâtes
    (spaghetti, macaroni), enrichi, sec » étaient rejetés comme plats composés,
    le mot cherché tombant au troisième segment. La cassonade et les pâtes
    sèches génériques ressortaient donc sans aucun candidat.
    """
    sugar = one(
        [target("cassonade", "Cassonade", "Sucres et sirops")],
        [food("4317", "Confiseries, sucre, brun (cassonade)", kcal="380")],
    )
    assert codes(sugar) == ["4317"]
    assert "head_match" in sugar.candidates[0].signals

    pasta = one(
        [target("spaghetti", "Spaghetti", "Pâtes et nouilles")],
        [food("4515", "Pâtes (spaghetti, macaroni), enrichi, sec", kcal="371")],
    )
    assert codes(pasta) == ["4515"]


# --- Propriétés du manifeste ------------------------------------------------

def test_the_raw_state_is_preferred_because_the_project_assumes_raw_quantities():
    proposal = one(
        [target("carotte", "Carotte", "Légumes")],
        [
            food("2381", "Carotte, bouillie, égouttée", kcal="35"),
            food("2380", "Carotte, crue", kcal="41"),
        ],
    )
    assert codes(proposal) == ["2380"]
    assert "raw_form" in proposal.candidates[0].signals


def test_the_family_name_breaks_a_tie_the_ingredient_name_cannot():
    """Le nom de famille est une information que le canon porte déjà.

    « Parmesan » seul ne dit pas qu'on cherche un fromage; sa famille le dit.
    """
    proposal = one(
        [target("parmesan", "Parmesan", "Fromages")],
        [
            food("40", "Fromage parmesan, pâte dure", kcal="392"),
            food("6000", "Craquelin parmesan", kcal="450"),
        ],
    )
    assert codes(proposal)[0] == "40"
    assert "family_match" in proposal.candidates[0].signals


def test_the_number_of_candidates_is_capped_and_ordered_deterministically():
    foods = [food(str(2400 + i), f"Oignon, variété {i}", kcal="40") for i in range(9)]
    proposal = one([target("oignon_jaune", "Oignon jaune", "Alliacées")], foods, limit=5)
    assert len(proposal.candidates) == 5
    # À égalité de score, le code d'aliment tranche : deux exécutions rendent
    # le même manifeste, donc deux décisions citent la même proposition.
    assert codes(proposal) == sorted(codes(proposal), key=int)


def test_an_ingredient_without_any_shared_token_gets_no_candidate():
    proposal = one(
        [target("gomme_xanthane", "Gomme xanthane", "Additifs")],
        [food("2401", "Oignon, cru", kcal="40")],
    )
    assert proposal.candidates == ()
    assert proposal.rejected == ()


def test_proposals_are_ordered_by_the_recipes_they_would_unblock():
    proposals = propose_matches(
        [
            target("carotte", "Carotte", "Légumes", blocked=3),
            target("oignon_jaune", "Oignon jaune", "Alliacées", blocked=35),
        ],
        [food("2380", "Carotte, crue"), food("2401", "Oignon, cru")],
    )
    assert [row.ingredient_id for row in proposals] == ["oignon_jaune", "carotte"]


def test_an_ambiguous_ingredient_carries_its_existing_foods_into_the_manifest():
    """Choisir entre trois avocats demande de voir les trois, et leur écart."""
    proposal = one(
        [target("avocat", "Avocat", "Fruits", attached=("1511", "1512", "1513"))],
        [
            food("1511", "Avocat, cru, toutes variétés commerciales", kcal="160"),
            food("1512", "Avocat, cru, californie", kcal="167"),
            food("1513", "Avocat, cru, Floride", kcal="120"),
        ],
    )
    assert proposal.attached_food_codes == ("1511", "1512", "1513")
    assert set(codes(proposal)) == {"1511", "1512", "1513"}
    # Le générique gagne : il porte le moins de qualificatifs que le canon ne
    # nomme pas (« commerciales » est un mot vide, « californie » non).
    assert codes(proposal)[0] == "1511"


def test_short_words_and_stop_words_do_not_retrieve_anything():
    """« de », « avec », « tous » ne discriminent rien et ne doivent pas relier.

    Sans ce filtre, « Riz au lait » remontait pour tout ingrédient dont le nom
    contient « au », et le manifeste devenait illisible.
    """
    proposal = one(
        [target("lait_325", "Lait 3,25 %", "Produits laitiers")],
        [
            food(
                "113",
                "Lait, liquide, entier, homogénéisé, pasteurisé, 3.25% M.G.",
                kcal="59",
            ),
            food("3800", "Riz avec tous les grains, cuit dans de l'eau"),
        ],
    )
    assert codes(proposal) == ["113"]


def test_a_fat_grade_is_what_distinguishes_two_dairy_foods():
    """35 % et 5 % de matière grasse, c'est 4,6 fois l'énergie.

    Trouvé en revue : les nombres étaient jetés au découpage, donc « Crème
    35 % » ne pouvait pas préférer la crème à fouetter à la crème légère, et le
    classement retombait sur la brièveté du libellé. Les codes et les teneurs
    ci-dessous sont ceux de l'archive 2026.
    """
    cream = one(
        [target("creme_35", "Crème 35 %", "Produits laitiers")],
        [
            food("7589", "Crème, légere, 5% M.G.", kcal="72"),
            food("137", "Crème à fouetter, 32% M.G.", kcal="292"),
            food("138", "Crème à fouetter, 35% M.G.", kcal="328"),
        ],
    )
    assert codes(cream)[0] == "138"

    milk = one(
        [target("lait_325", "Lait 3,25 %", "Produits laitiers")],
        [
            food("114", "Lait, liquide, écrémé, 0.1% M.G.", kcal="33"),
            food("61", "Lait, partiellement écrémé, liquide, 2% M.G.", kcal="47"),
            food(
                "113",
                "Lait, liquide, entier, homogénéisé, pasteurisé, 3.25% M.G.",
                kcal="59",
            ),
        ],
    )
    assert codes(milk)[0] == "113"
