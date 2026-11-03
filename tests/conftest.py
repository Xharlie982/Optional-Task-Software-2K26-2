import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'test.sqlite3')) as session:
        yield session


@pytest.fixture
def make_payload(client):
    # Crea un cliente y un producto y devuelve un cuerpo de pedido valido.
    def build(category='premium', price_cents=2500, stock=5, quantity=2, shipping='standard'):
        customer = client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com', 'category': category})
        assert customer.status_code == 201
        product = client.post('/products', json={'name': 'Libro', 'price_cents': price_cents, 'stock': stock})
        assert product.status_code == 201
        return {
            'customer_id': customer.json()['id'],
            'address': 'Calle 10',
            'city': 'Lima',
            'postal_code': '15001',
            'shipping': shipping,
            'items': [{'product_id': product.json()['id'], 'quantity': quantity}],
        }

    return build
