import pytest
from fastapi.testclient import TestClient
from main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'states.sqlite3')) as session:
        yield session


@pytest.mark.parametrize('action,state,stock,notifications', [
    ('confirm', 'confirmed', 3, 1),
    ('cancel', 'cancelled', 5, 0),
])
def test_final_orders_reject_changes(client, deliver_notifications, action, state, stock, notifications):
    customer = client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com', 'category': 'premium'})
    assert customer.status_code == 201
    product = client.post('/products', json={'name': 'Libro', 'price_cents': 2500, 'stock': 5})
    assert product.status_code == 201
    product_url = '/products/' + str(product.json()['id'])
    payload = {'customer_id': customer.json()['id'], 'address': 'Calle 10', 'city': 'Lima', 'postal_code': '15001', 'shipping': 'standard', 'items': [{'product_id': product.json()['id'], 'quantity': 2}]}
    created = client.post('/orders', json=payload)
    assert created.status_code == 201
    url = '/orders/' + str(created.json()['id'])
    transition = client.post(url + '/' + action)
    assert transition.status_code == 200
    snapshot = client.get(url).json()
    assert snapshot['status'] == state
    deliver_notifications()
    initial_notifications = client.get(url + '/notifications').json()
    assert len(initial_notifications) == notifications
    assert client.put(url, json=dict(payload, address='Otra direccion')).status_code == 409
    assert client.delete(url).status_code == 409
    assert client.post(url + '/confirm').status_code == 409
    assert client.post(url + '/cancel').status_code == 409
    assert client.get(url).json() == snapshot
    assert client.get(product_url).json()['stock'] == stock
    assert client.get(url + '/notifications').json() == initial_notifications


def test_pending_order_recalculates_when_edited(client):
    customer_data = {'name': 'Ana', 'email': 'ana@example.com', 'category': 'regular'}
    customer = client.post('/customers', json=customer_data)
    assert customer.status_code == 201
    customer_id = customer.json()['id']
    product = client.post('/products', json={'name': 'Libro', 'price_cents': 2500, 'stock': 5})
    assert product.status_code == 201
    product_id = product.json()['id']
    payload = {'customer_id': customer_id, 'address': 'Calle 10', 'city': 'Lima', 'postal_code': '15001', 'shipping': 'standard', 'items': [{'product_id': product_id, 'quantity': 2}]}
    created = client.post('/orders', json=payload)
    assert created.status_code == 201
    original = created.json()
    assert original['total_cents'] == 6000
    url = '/orders/' + str(original['id'])
    product_url = '/products/' + str(product_id)
    assert client.put(product_url, json={'name': 'Libro', 'price_cents': 6000, 'stock': 5}).status_code == 200
    assert client.put('/customers/' + str(customer_id), json=dict(customer_data, category='business')).status_code == 200
    assert client.get(url).json() == original
    updated = client.put(url, json=dict(payload, address='Calle 20'))
    assert updated.status_code == 200
    order = updated.json()
    assert order['id'] == original['id']
    assert order['status'] == 'pending'
    assert order['customer_category'] == 'business'
    assert order['address'] == 'Calle 20'
    assert order['subtotal_cents'] == 12000
    assert order['discount_cents'] == 1800
    assert order['shipping_cents'] == 0
    assert order['total_cents'] == 10200
    assert order['items'] == [{'product_id': product_id, 'quantity': 2, 'unit_price_cents': 6000}]
    assert client.get(url).json() == order
    assert len(client.get('/orders').json()) == 1
    assert client.get(product_url).json()['stock'] == 5
    assert client.get(url + '/notifications').json() == []
