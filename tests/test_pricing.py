import pytest
from fastapi.testclient import TestClient
from main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'pricing.sqlite3')) as session:
        yield session


@pytest.mark.parametrize('category,price,shipping,discount,delivery,total', [
    ('regular', 101, 'pickup', 0, 0, 101),
    ('premium', 101, 'pickup', 10, 0, 91),
    ('business', 101, 'express', 15, 2500, 2586),
    ('regular', 9999, 'standard', 0, 1000, 10999),
    ('premium', 9999, 'standard', 999, 1000, 10000),
    ('premium', 10000, 'standard', 1000, 0, 9000),
    ('regular', 10001, 'standard', 0, 0, 10001),
])
def test_quote_and_creation_preserve_pricing_rules(client, category, price, shipping, discount, delivery, total):
    customer = client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com', 'category': category})
    assert customer.status_code == 201
    product = client.post('/products', json={'name': 'Libro', 'price_cents': price, 'stock': 0})
    assert product.status_code == 201
    product_id = product.json()['id']
    payload = {'customer_id': customer.json()['id'], 'address': 'Calle 10', 'city': 'Lima', 'postal_code': '15001', 'shipping': shipping, 'items': [{'product_id': product_id, 'quantity': 1}]}
    expected = {'subtotal_cents': price, 'discount_cents': discount, 'shipping_cents': delivery, 'total_cents': total}
    quote = client.post('/orders/quote', json=payload)
    assert quote.status_code == 200
    assert quote.json() == expected
    assert client.get('/orders').json() == []
    created = client.post('/orders', json=payload)
    assert created.status_code == 201
    order = created.json()
    assert {key: order[key] for key in expected} == expected
    assert order['status'] == 'pending'
    assert client.get('/products/' + str(product_id)).json()['stock'] == 0
