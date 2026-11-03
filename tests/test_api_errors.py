import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.database import Database
from main import create_app


def test_unavailable_database_returns_503(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path / 'down.sqlite3')) as client:
        def unavailable(self):
            raise sqlite3.OperationalError('database is locked')

        monkeypatch.setattr(Database, 'connect', unavailable)
        for url in ('/products', '/customers', '/orders'):
            response = client.get(url)
            assert response.status_code == 503
            assert response.json() == {'detail': 'Base de datos no disponible; reintente más tarde'}


@pytest.mark.parametrize('url', ['/products/abc', '/customers/abc', '/orders/abc'])
def test_non_numeric_identifier_is_rejected(client, url):
    assert client.get(url).status_code == 422
