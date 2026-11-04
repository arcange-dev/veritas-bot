"""Cost math. Decimal everywhere; a float here is a rounding bug in a bill."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from core.errors import SpendCapExceeded

MICRO = Decimal("0.000001")


def estimate_cost(input_tokens: int, output_tokens: int,
                  input_cost_per_1m: Decimal | str, output_cost_per_1m: Decimal | str) -> Decimal:
    """Cost in USD, quantised to 6 decimal places."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts cannot be negative")
    i = Decimal(str(input_cost_per_1m))
    o = Decimal(str(output_cost_per_1m))
    cost = (Decimal(input_tokens) * i + Decimal(output_tokens) * o) / Decimal(1_000_000)
    return cost.quantize(MICRO, rounding=ROUND_HALF_UP)


def check_caps(*, spent: Decimal, next_estimate: Decimal, run_cap: Decimal,
               org_cap: Decimal, monthly_spent: Decimal) -> None:
    """Raise before dispatch, never after the money is gone."""
    if spent + next_estimate > run_cap:
        raise SpendCapExceeded(
            f"This task would exceed its ${run_cap} cap. Raise the cap or split the task."
        )
    if monthly_spent + next_estimate > org_cap:
        raise SpendCapExceeded(
            f"Organization monthly cap of ${org_cap} would be exceeded."
        )


def estimate_tokens(text: str) -> int:
    """Rough pre-flight estimate only (~4 chars/token). Never billed from this."""
    return max(1, len(text) // 4)
