import pytest

from app.pricing import PricingCalculator


@pytest.mark.parametrize('category,subtotal,discount', [
    ('regular', 10_000, 0),
    ('premium', 10_000, 1_000),
    ('business', 10_000, 1_500),
    ('premium', 9, 0),
    ('premium', 19, 1),
    ('premium', 1_999, 199),
    ('business', 7, 1),
    ('business', 101, 15),
])
def test_discount_is_truncated_to_whole_cents(category, subtotal, discount):
    assert PricingCalculator.calculate(category, subtotal, 'pickup')[0] == discount


@pytest.mark.parametrize('shipping,subtotal,delivery', [
    ('pickup', 1, 0),
    ('pickup', 50_000, 0),
    ('standard', 1, 1_000),
    ('standard', 9_999, 1_000),
    ('standard', 10_000, 0),
    ('standard', 10_001, 0),
    ('express', 1, 2_500),
    ('express', 10_000, 2_500),
    ('express', 1_000_000, 2_500),
])
def test_shipping_cost(shipping, subtotal, delivery):
    assert PricingCalculator.calculate('regular', subtotal, shipping)[1] == delivery


def test_free_shipping_threshold_uses_the_subtotal_before_the_discount():
    assert PricingCalculator.calculate('premium', 10_000, 'standard') == (1_000, 0, 9_000)
    assert PricingCalculator.calculate('premium', 9_999, 'standard') == (999, 1_000, 10_000)


@pytest.mark.parametrize('category,shipping,subtotal,expected', [
    ('premium', 'standard', 5_000, (500, 1_000, 5_500)),
    ('business', 'express', 2_000, (300, 2_500, 4_200)),
    ('regular', 'pickup', 2_500, (0, 0, 2_500)),
    ('business', 'standard', 12_000, (1_800, 0, 10_200)),
])
def test_total_is_subtotal_minus_discount_plus_shipping(category, shipping, subtotal, expected):
    assert PricingCalculator.calculate(category, subtotal, shipping) == expected
