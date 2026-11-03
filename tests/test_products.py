import pytest
from fastapi.testclient import TestClient

from main import create_app

VALID = {'name': 'Libro', 'price_cents': 2500, 'stock': 5}


def test_product_crud(client):
    assert client.get('/products').json() == []
    created = client.post('/products', json=VALID)
    assert created.status_code == 201
    product = created.json()
    assert product == dict(VALID, id=product['id'])
    url = '/products/' + str(product['id'])
    assert client.get(url).json() == product
    assert client.get('/products').json() == [product]
    changed = dict(VALID, name='Libro de algoritmos', price_cents=3000, stock=7)
    updated = client.put(url, json=changed)
    assert updated.status_code == 200
    assert updated.json() == dict(changed, id=product['id'])
    assert client.get(url).json() == updated.json()
    deleted = client.delete(url)
    assert deleted.status_code == 204
    assert deleted.content == b''
    assert client.get(url).status_code == 404
    assert client.get('/products').json() == []


def test_list_is_ordered_by_id_even_after_updates(client):
    created = [client.post('/products', json=dict(VALID, name='Producto ' + str(n))).json() for n in range(3)]
    assert client.put('/products/' + str(created[0]['id']), json=dict(VALID, name='Cambiado')).status_code == 200
    names = [row['name'] for row in client.get('/products').json()]
    assert names == ['Cambiado', 'Producto 1', 'Producto 2']


@pytest.mark.parametrize('method', ['get', 'put', 'delete'])
def test_missing_product_returns_404(client, method):
    kwargs = {'json': VALID} if method == 'put' else {}
    response = getattr(client, method)('/products/999', **kwargs)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Producto no encontrado'}


@pytest.mark.parametrize('change', [
    {'name': ''},
    {'name': '   '},
    {'name': 'x' * 121},
    {'price_cents': 0},
    {'price_cents': -1},
    {'price_cents': '2500'},
    {'price_cents': 2500.5},
    {'price_cents': 100_000_001},
    {'stock': -1},
    {'stock': 1.5},
    {'stock': 1_000_001},
    {'color': 'rojo'},
])
def test_invalid_product_is_rejected_without_side_effects(client, change):
    assert client.post('/products', json=dict(VALID, **change)).status_code == 422
    assert client.get('/products').json() == []


def test_invalid_update_keeps_the_product_unchanged(client):
    product = client.post('/products', json=VALID).json()
    url = '/products/' + str(product['id'])
    assert client.put(url, json=dict(VALID, price_cents=0)).status_code == 422
    assert client.get(url).json() == product


def test_boundary_values_are_accepted(client):
    edge = {'name': 'x' * 120, 'price_cents': 100_000_000, 'stock': 1_000_000}
    assert client.post('/products', json=edge).status_code == 201
    assert client.post('/products', json=dict(edge, price_cents=1, stock=0)).status_code == 201


def test_name_whitespace_is_stripped(client):
    created = client.post('/products', json=dict(VALID, name='  Libro  '))
    assert created.status_code == 201
    assert created.json()['name'] == 'Libro'


def test_product_in_an_order_cannot_be_deleted(client, make_payload):
    payload = make_payload()
    url = '/products/' + str(payload['items'][0]['product_id'])
    assert client.post('/orders', json=payload).status_code == 201
    response = client.delete(url)
    assert response.status_code == 409
    assert response.json() == {'detail': 'El producto pertenece a un pedido'}
    assert client.get(url).status_code == 200


def test_products_survive_restart(tmp_path):
    path = tmp_path / 'products.sqlite3'
    with TestClient(create_app(path)) as client:
        product = client.post('/products', json=VALID).json()
    with TestClient(create_app(path)) as client:
        assert client.get('/products/' + str(product['id'])).json() == product
