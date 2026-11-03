from unittest.mock import MagicMock
import pytest
from app.orders import ItemInput, OrderInput, OrderService


@pytest.mark.parametrize('category,price,quantity,shipping,expected', [
    ('regular', 101, 1, 'pickup', (101, 0, 0, 101)),
    ('premium', 101, 1, 'pickup', (101, 10, 0, 91)),
    ('business', 101, 1, 'pickup', (101, 15, 0, 86)),
    ('regular', 9999, 1, 'standard', (9999, 0, 1000, 10999)),
    ('premium', 10000, 1, 'standard', (10000, 1000, 0, 9000)),
    ('business', 10001, 1, 'standard', (10001, 1500, 0, 8501)),
    ('regular', 2500, 2, 'express', (5000, 0, 2500, 7500)),
    ('premium', 2500, 2, 'standard', (5000, 500, 1000, 5500)),
    ('business', 5000, 2, 'standard', (10000, 1500, 0, 8500)),
])
def test_quote_business_rules(category, price, quantity, shipping, expected):
    database = MagicMock()
    connection = database.connect.return_value.__enter__.return_value
    connection.execute.return_value.fetchone.side_effect = [
        {'id': 1, 'category': category},
        {'id': 1, 'price_cents': price},
    ]
    data = OrderInput(customer_id=1, address='Calle 10', city='Lima', postal_code='15001', shipping=shipping, items=[ItemInput(product_id=1, quantity=quantity)])
    result = OrderService(database).quote(data)
    subtotal, discount, delivery, total = expected
    assert result == {
        'subtotal_cents': subtotal,
        'discount_cents': discount,
        'shipping_cents': delivery,
        'total_cents': total,
    }
