from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.orders import OrderInput, OrderService
from main import create_app

KEY = {'Idempotency-Key': 'pedido-ana-001'}


def orders_of(client):
    return client.get('/orders').json()


def test_same_key_and_content_returns_the_original_result(client, make_payload):
    payload = make_payload()
    first = client.post('/orders', json=payload, headers=KEY)
    assert first.status_code == 201
    assert 'Idempotent-Replayed' not in first.headers
    second = client.post('/orders', json=payload, headers=KEY)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert second.headers['Idempotent-Replayed'] == 'true'
    assert [row['id'] for row in orders_of(client)] == [first.json()['id']]


def test_content_is_compared_after_validation(client, make_payload):
    payload = make_payload()
    first = client.post('/orders', json=payload, headers=KEY)
    padded = dict(payload, address='  ' + payload['address'] + '  ')
    second = client.post('/orders', json=padded, headers=KEY)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert len(orders_of(client)) == 1


@pytest.mark.parametrize('change', [
    {'address': 'Otra direccion 200'},
    {'shipping': 'express'},
    {'items': [{'product_id': 1, 'quantity': 3}]},
])
def test_same_key_with_different_content_is_a_conflict(client, make_payload, change):
    payload = make_payload()
    first = client.post('/orders', json=payload, headers=KEY)
    assert first.status_code == 201
    conflict = client.post('/orders', json=dict(payload, **change), headers=KEY)
    assert conflict.status_code == 409
    assert conflict.json() == {'detail': 'La clave de idempotencia ya se uso con un contenido distinto'}
    assert len(orders_of(client)) == 1
    assert client.get('/orders/' + str(first.json()['id'])).json() == first.json()
    assert client.post('/orders', json=payload, headers=KEY).json() == first.json()


def test_different_keys_and_requests_without_key_create_separate_orders(client, make_payload):
    payload = make_payload()
    first = client.post('/orders', json=payload, headers={'Idempotency-Key': 'clave-a'})
    second = client.post('/orders', json=payload, headers={'Idempotency-Key': 'clave-b'})
    third = client.post('/orders', json=payload)
    fourth = client.post('/orders', json=payload)
    assert [response.status_code for response in (first, second, third, fourth)] == [201] * 4
    assert len(orders_of(client)) == 4


def test_concurrent_requests_with_the_same_key_create_one_order(client, make_payload):
    payload = make_payload()
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post('/orders', json=payload, headers=KEY), range(8)))
    assert [response.status_code for response in responses] == [201] * 8
    assert len({response.json()['id'] for response in responses}) == 1
    assert sum(response.headers.get('Idempotent-Replayed') == 'true' for response in responses) == 7
    assert len(orders_of(client)) == 1


def test_key_survives_a_restart(tmp_path):
    path = tmp_path / 'idempotency.sqlite3'
    with TestClient(create_app(path)) as client:
        customer = client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com'}).json()
        product = client.post('/products', json={'name': 'Libro', 'price_cents': 2500, 'stock': 5}).json()
        payload = {'customer_id': customer['id'], 'address': 'Calle 10', 'city': 'Lima', 'postal_code': '15001',
                   'shipping': 'standard', 'items': [{'product_id': product['id'], 'quantity': 2}]}
        first = client.post('/orders', json=payload, headers=KEY)
        assert first.status_code == 201
    with TestClient(create_app(path)) as client:
        replay = client.post('/orders', json=payload, headers=KEY)
        assert replay.status_code == 201
        assert replay.json() == first.json()
        assert replay.headers['Idempotent-Replayed'] == 'true'
        conflict = client.post('/orders', json=dict(payload, city='Cusco'), headers=KEY)
        assert conflict.status_code == 409
        assert len(client.get('/orders').json()) == 1


def test_failed_attempt_does_not_consume_the_key(client):
    payload = {'customer_id': 1, 'address': 'Calle 10', 'city': 'Lima', 'postal_code': '15001',
               'shipping': 'standard', 'items': [{'product_id': 1, 'quantity': 2}]}
    failed = client.post('/orders', json=payload, headers=KEY)
    assert failed.status_code == 404
    assert orders_of(client) == []
    assert client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com', 'category': 'premium'}).status_code == 201
    assert client.post('/products', json={'name': 'Libro', 'price_cents': 2500, 'stock': 5}).status_code == 201
    retry = client.post('/orders', json=payload, headers=KEY)
    assert retry.status_code == 201
    assert retry.json()['total_cents'] == 5500
    assert 'Idempotent-Replayed' not in retry.headers
    assert len(orders_of(client)) == 1


def test_invalid_request_does_not_consume_the_key(client, make_payload):
    payload = make_payload()
    assert client.post('/orders', json=dict(payload, items=[]), headers=KEY).status_code == 422
    assert orders_of(client) == []
    assert client.post('/orders', json=payload, headers=KEY).status_code == 201


def test_failure_after_writing_the_order_leaves_nothing_behind(client, make_payload, monkeypatch):
    payload = make_payload()
    original = OrderService._write_order

    def write_then_fail(connection, data, order_id=None):
        original(connection, data, order_id)
        raise RuntimeError('fallo simulado despues de escribir el pedido')

    monkeypatch.setattr(OrderService, '_write_order', staticmethod(write_then_fail))
    service = OrderService(client.app.state.database)
    with pytest.raises(RuntimeError):
        service.create(OrderInput(**payload), 'clave-con-fallo')
    assert orders_of(client) == []
    monkeypatch.undo()
    retry = client.post('/orders', json=payload, headers={'Idempotency-Key': 'clave-con-fallo'})
    assert retry.status_code == 201
    assert 'Idempotent-Replayed' not in retry.headers
    assert len(orders_of(client)) == 1


@pytest.mark.parametrize('key', ['', 'con espacio', 'x' * 256])
def test_invalid_key_is_rejected(client, make_payload, key):
    response = client.post('/orders', json=make_payload(), headers={'Idempotency-Key': key})
    assert response.status_code == 422
    assert orders_of(client) == []


@pytest.mark.parametrize('key', ['x', 'x' * 255, 'a-B_c.1:2/3=+'])
def test_valid_keys_are_accepted(client, make_payload, key):
    response = client.post('/orders', json=make_payload(), headers={'Idempotency-Key': key})
    assert response.status_code == 201


def test_replay_returns_the_original_snapshot_even_if_the_order_changed(client, make_payload):
    payload = make_payload()
    first = client.post('/orders', json=payload, headers=KEY).json()
    url = '/orders/' + str(first['id'])
    assert client.put(url, json=dict(payload, address='Direccion nueva 5')).status_code == 200
    replay = client.post('/orders', json=payload, headers=KEY)
    assert replay.status_code == 201
    assert replay.json() == first
    assert client.get(url).json()['address'] == 'Direccion nueva 5'
    assert client.post(url + '/confirm').status_code == 200
    assert client.post('/orders', json=payload, headers=KEY).json() == first
    assert len(orders_of(client)) == 1


def test_deleting_the_order_releases_the_key(client, make_payload):
    payload = make_payload()
    first = client.post('/orders', json=payload, headers=KEY).json()
    assert client.delete('/orders/' + str(first['id'])).status_code == 204
    again = client.post('/orders', json=payload, headers=KEY)
    assert again.status_code == 201
    assert 'Idempotent-Replayed' not in again.headers
    assert len(orders_of(client)) == 1
