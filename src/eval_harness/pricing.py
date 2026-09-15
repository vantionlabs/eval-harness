"""Turning token counts into money.

Prices come from `prices` in the config, in USD per million tokens. The harness
ships no price list: prices change, and a stale default would quietly report the
wrong cost. A model without a price is reported with its tokens and an unknown
cost, never a cost of zero.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from eval_harness.config import Price
from eval_harness.target import Usage


@dataclass(frozen=True)
class Cost:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0
    """None when any call had tokens but no price and no cost of its own."""
    unpriced_models: tuple[str, ...] = ()

    def __add__(self, other: "Cost") -> "Cost":
        both_known = self.cost_usd is not None and other.cost_usd is not None
        return Cost(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=(self.cost_usd or 0) + (other.cost_usd or 0) if both_known else None,
            unpriced_models=tuple(sorted({*self.unpriced_models, *other.unpriced_models})),
        )


def _price_for(model: str | None, prices: Mapping[str, Price]) -> Price | None:
    if model is None:
        return None
    if model in prices:
        return prices[model]
    # A judge reports `anthropic:claude-sonnet-5`; a config may key it without the provider.
    _, _, bare = model.partition(":")
    return prices.get(bare) if bare else None


def cost_of(usages: Iterable[Usage], prices: Mapping[str, Price]) -> Cost:
    total = Cost()
    for usage in usages:
        if usage.cost_usd is not None:
            amount: float | None = usage.cost_usd
            unpriced: tuple[str, ...] = ()
        elif (price := _price_for(usage.model, prices)) is not None:
            amount = (
                usage.input_tokens * price.input_per_mtok
                + usage.output_tokens * price.output_per_mtok
            ) / 1_000_000
            unpriced = ()
        elif usage.input_tokens == 0 and usage.output_tokens == 0:
            amount, unpriced = 0.0, ()
        else:
            amount, unpriced = None, (usage.model or "(unnamed model)",)
        total = total + Cost(usage.input_tokens, usage.output_tokens, amount, unpriced)
    return total
