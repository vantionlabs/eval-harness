from eval_harness.config import Price
from eval_harness.pricing import cost_of
from eval_harness.target import Usage

PRICES = {"claude-sonnet-5": Price(input_per_mtok=3.0, output_per_mtok=15.0)}


def test_prices_tokens_and_matches_a_judge_model_without_its_provider():
    cost = cost_of([Usage(1_000_000, 100_000, model="anthropic:claude-sonnet-5")], PRICES)

    assert cost.cost_usd == 3.0 + 1.5
    assert (cost.input_tokens, cost.output_tokens) == (1_000_000, 100_000)


def test_a_cost_the_application_reports_wins():
    assert cost_of([Usage(10, 10, model="claude-sonnet-5", cost_usd=0.25)], PRICES).cost_usd == 0.25


def test_unpriced_tokens_make_the_cost_unknown_rather_than_zero():
    cost = cost_of(
        [Usage(10, 10, model="claude-sonnet-5"), Usage(50, 5, model="mystery-model")], PRICES
    )

    assert cost.cost_usd is None
    assert cost.unpriced_models == ("mystery-model",)
    assert cost.input_tokens == 60
