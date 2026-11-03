import pytest
from fastapi.testclient import TestClient
from main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'customers.sqlite3')) as session:
        yield session


def test_customer_crud(client):
    assert client.get('/customers').json() == []
    data = {'name': 'Ana', 'email': 'ana@example.com', 'category': 'regular'}
    created = client.post('/customers', json=data)
    assert created.status_code == 201
    customer = created.json()
    assert customer == dict(data, id=customer['id'])
    url = '/customers/' + str(customer['id'])
    fetched = client.get(url)
    assert fetched.status_code == 200
    assert fetched.json() == customer
    assert client.get('/customers').json() == [customer]
    updated_data = {'name': 'Ana Torres', 'email': 'ana.torres@example.com', 'category': 'business'}
    updated = client.put(url, json=updated_data)
    assert updated.status_code == 200
    assert updated.json() == dict(updated_data, id=customer['id'])
    assert client.get(url).json() == updated.json()
    deleted = client.delete(url)
    assert deleted.status_code == 204
    assert deleted.content == b''
    assert client.get(url).status_code == 404
    assert client.get('/customers').json() == []


def test_duplicate_email_is_rejected(client):
    data = {'name': 'Ana', 'email': 'ana@example.com', 'category': 'regular'}
    first = client.post('/customers', json=data)
    assert first.status_code == 201
    duplicate = client.post('/customers', json=dict(data, name='Otra persona'))
    assert duplicate.status_code == 409
    assert client.get('/customers').json() == [first.json()]


def test_category_defaults_to_regular(client):
    created = client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com'})
    assert created.status_code == 201
    assert created.json()['category'] == 'regular'


@pytest.mark.parametrize('method', ['get', 'put', 'delete'])
def test_missing_customer_returns_404(client, method):
    kwargs = {'json': {'name': 'Ana', 'email': 'ana@example.com', 'category': 'regular'}} if method == 'put' else {}
    response = getattr(client, method)('/customers/999', **kwargs)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Cliente no encontrado'}


def test_update_to_an_existing_email_is_rejected(client):
    first = client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com'}).json()
    second = client.post('/customers', json={'name': 'Luis', 'email': 'luis@example.com'}).json()
    response = client.put('/customers/' + str(second['id']), json={'name': 'Luis', 'email': 'ana@example.com'})
    assert response.status_code == 409
    assert response.json() == {'detail': 'El correo ya está registrado'}
    assert client.get('/customers').json() == [first, second]


def test_customer_can_keep_its_own_email_on_update(client):
    customer = client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com'}).json()
    changed = {'name': 'Ana Torres', 'email': 'ana@example.com', 'category': 'premium'}
    response = client.put('/customers/' + str(customer['id']), json=changed)
    assert response.status_code == 200
    assert response.json() == dict(changed, id=customer['id'])


def test_customer_with_orders_cannot_be_deleted(client, make_payload):
    payload = make_payload()
    url = '/customers/' + str(payload['customer_id'])
    assert client.post('/orders', json=payload).status_code == 201
    response = client.delete(url)
    assert response.status_code == 409
    assert response.json() == {'detail': 'El cliente tiene pedidos'}
    assert client.get(url).status_code == 200


@pytest.mark.parametrize('change', [
    {'name': ''},
    {'name': 'x' * 121},
    {'email': 'no-es-un-correo'},
    {'email': 'a' * 250 + '@example.com'},
    {'category': 'vip'},
    {'edad': 30},
])
def test_invalid_customer_is_rejected_without_side_effects(client, change):
    data = {'name': 'Ana', 'email': 'ana@example.com', 'category': 'regular'}
    assert client.post('/customers', json=dict(data, **change)).status_code == 422
    assert client.get('/customers').json() == []


def test_customers_survive_restart(tmp_path):
    path = tmp_path / 'persistent_customers.sqlite3'
    with TestClient(create_app(path)) as client:
        customer = client.post('/customers', json={'name': 'Ana', 'email': 'ana@example.com'}).json()
    with TestClient(create_app(path)) as client:
        assert client.get('/customers/' + str(customer['id'])).json() == customer
