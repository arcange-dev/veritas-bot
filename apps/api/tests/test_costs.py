"""Money math must be exact. Floats are a defect here."""
from decimal import Decimal

import pytest

from billing.costs import check_caps, estimate_cost, estimate_tokens
from core.errors import SpendCapExceeded


def test_cost_is_exact_decimal():
    cost = estimate_cost(1_000_000, 0, "3.00", "15.00")
    assert cost == Decimal("3.000000")
    assert isinstance(cost, Decimal)


def test_cost_combines_input_and_output():
    assert estimate_cost(1_000_000, 1_000_000, "1.00", "2.00") == Decimal("3.000000")


def test_tiny_cost_keeps_six_places():
    assert estimate_cost(1, 0, "3.00", "15.00") == Decimal("0.000003")


def test_negative_tokens_rejected():
    with pytest.raises(ValueError):
        estimate_cost(-1, 0, "1", "1")


def test_run_cap_blocks_dispatch():
    with pytest.raises(SpendCapExceeded):
        check_caps(spent=Decimal("4.90"), next_estimate=Decimal("0.20"),
                   run_cap=Decimal("5.00"), org_cap=Decimal("50"),
                   monthly_spent=Decimal("0"))


def test_org_cap_blocks_dispatch():
    with pytest.raises(SpendCapExceeded):
        check_caps(spent=Decimal("0"), next_estimate=Decimal("1.00"),
                   run_cap=Decimal("5.00"), org_cap=Decimal("50"),
                   monthly_spent=Decimal("49.50"))


def test_within_caps_is_allowed():
    check_caps(spent=Decimal("1.00"), next_estimate=Decimal("0.50"),
               run_cap=Decimal("5.00"), org_cap=Decimal("50"),
               monthly_spent=Decimal("10"))


def test_token_estimate_is_positive():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd" * 100) == 100
