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
