"""Le solveur respecte la granularité publiée des produits au poids."""

from decimal import Decimal

from app.services.appetence import RuleBasedAppetenceScorer
from app.services.prefilter import prefilter_recipes
from app.services.problem_data import PriceData, ProductData
from app.solver import PulpMenuSolver, SolverConfig
from tests.conftest import make_problem, make_profile, make_recipe


def test_variable_weight_without_mass_increment_is_continuous():
    problem = make_problem(
        profile=make_profile(
            rho=("1",), meals=1, epsilon="0", r_min=1, alpha="1"
        ),
        recipes=[make_recipe(m=1, ingredients=(("riz", "0", "250"),))],
        products=[
            ProductData(
                id=1,
                external_key="riz-au-poids",
                canonical_ingredient_id="riz",
                package_qty_in_base_unit=Decimal("1000"),
                tax_rate=Decimal("0"),
                sale_mode="variable_weight",
                purchase_increment_in_base_unit=None,
            )
        ],
        prices=[
            PriceData(
                product_id=1,
                store_id=1,
                price_cents_cad=1000,
                is_promo=False,
                regular_price_cents_cad=1000,
            )
        ],
    )
    prefiltered = prefilter_recipes(
        problem.recipes, problem.profile, RuleBasedAppetenceScorer(problem)
    )

    result = PulpMenuSolver().solve(problem, prefiltered, SolverConfig())

    assert result.status == "Optimal"
    assert result.purchases[0].units == 0.25
    assert result.purchases[0].taxed_total_cents_cad == Decimal("250.00")


def test_variable_weight_with_increment_stays_integer():
    problem = make_problem(
        profile=make_profile(
            rho=("1",), meals=1, epsilon="0", r_min=1, alpha="1"
        ),
        recipes=[make_recipe(m=1, ingredients=(("riz", "0", "250"),))],
        products=[
            ProductData(
                id=1,
                external_key="riz-100g",
                canonical_ingredient_id="riz",
                package_qty_in_base_unit=Decimal("100"),
                tax_rate=Decimal("0"),
                sale_mode="variable_weight",
                purchase_increment_in_base_unit=Decimal("100"),
            )
        ],
        prices=[
            PriceData(
                product_id=1,
                store_id=1,
                price_cents_cad=100,
                is_promo=False,
                regular_price_cents_cad=100,
            )
        ],
    )
    prefiltered = prefilter_recipes(
        problem.recipes, problem.profile, RuleBasedAppetenceScorer(problem)
    )

    result = PulpMenuSolver().solve(problem, prefiltered, SolverConfig())

    assert result.status == "Optimal"
    assert result.purchases[0].units == 3
    assert result.purchases[0].taxed_total_cents_cad == Decimal("300.00")
