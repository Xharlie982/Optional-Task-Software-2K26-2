import pytest

ORDER_URLS = ('/orders', '/orders/quote')


def product_url(payload):
    return '/products/' + str(payload['items'][0]['product_id'])


@pytest.mark.parametrize('url', ORDER_URLS)
def test_unknown_customer_is_rejected(client, make_payload, url):
    response = client.post(url, json=dict(make_payload(), customer_id=999))
    assert response.status_code == 404
    assert response.json() == {'detail': 'Cliente no encontrado'}
    assert client.get('/orders').json() == []


@pytest.mark.parametrize('url', ORDER_URLS)
def test_unknown_product_is_rejected_without_a_partial_order(client, make_payload, url):
    payload = make_payload()
    payload['items'].append({'product_id': 999, 'quantity': 1})
    response = client.post(url, json=payload)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Producto 999 no encontrado'}
    assert client.get('/orders').json() == []


@pytest.mark.parametrize('method,suffix', [
    ('get', ''),
    ('delete', ''),
    ('post', '/confirm'),
    ('post', '/cancel'),
    ('get', '/notifications'),
])
def test_missing_order_returns_404(client, method, suffix):
    response = getattr(client, method)('/orders/999' + suffix)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Pedido no encontrado'}


def test_updating_a_missing_order_returns_404(client, make_payload):
    response = client.put('/orders/999', json=make_payload())
    assert response.status_code == 404
    assert response.json() == {'detail': 'Pedido no encontrado'}


def test_failed_update_keeps_the_original_order(client, make_payload):
    payload = make_payload()
    original = client.post('/orders', json=payload).json()
    url = '/orders/' + str(original['id'])
    assert client.put(url, json=dict(payload, customer_id=999)).status_code == 404
    unknown_product = dict(payload, items=[{'product_id': 999, 'quantity': 1}])
    assert client.put(url, json=unknown_product).status_code == 404
    assert client.get(url).json() == original


def test_pending_order_can_be_deleted_and_frees_its_references(client, make_payload):
    payload = make_payload()
    order = client.post('/orders', json=payload).json()
    url = '/orders/' + str(order['id'])
    deleted = client.delete(url)
    assert deleted.status_code == 204
    assert deleted.content == b''
    assert client.get(url).status_code == 404
    assert client.get('/orders').json() == []
    assert client.get(product_url(payload)).json()['stock'] == 5
    assert client.delete(product_url(payload)).status_code == 204
    assert client.delete('/customers/' + str(payload['customer_id'])).status_code == 204


def test_orders_and_quotes_do_not_check_or_reserve_stock(client, make_payload):
    payload = make_payload(stock=1, quantity=3)
    assert client.post('/orders/quote', json=payload).status_code == 200
    created = client.post('/orders', json=payload)
    assert created.status_code == 201
    assert client.get(product_url(payload)).json()['stock'] == 1
    url = '/orders/' + str(created.json()['id'])
    confirmation = client.post(url + '/confirm')
    assert confirmation.status_code == 409
    assert confirmation.json() == {'detail': 'Stock insuficiente para producto ' + str(payload['items'][0]['product_id'])}
    assert client.get(product_url(payload)).json()['stock'] == 1
    assert client.get(url).json()['status'] == 'pending'


def test_confirmation_can_use_all_the_stock(client, make_payload):
    payload = make_payload(stock=2, quantity=2)
    order = client.post('/orders', json=payload).json()
    assert client.post('/orders/' + str(order['id']) + '/confirm').status_code == 200
    assert client.get(product_url(payload)).json()['stock'] == 0


def test_confirmation_registers_the_notification_for_the_customer(client, make_payload, deliver_notifications):
    payload = make_payload()
    order = client.post('/orders', json=payload).json()
    url = '/orders/' + str(order['id'])
    message = 'Pedido ' + str(order['id']) + ' confirmado. Total: 5500 centavos.'
    confirmation = client.post(url + '/confirm')
    assert confirmation.json() == {'id': order['id'], 'status': 'confirmed', 'message': message}
    assert client.get(url + '/notifications').json() == []
    assert deliver_notifications() == ['delivered']
    notifications = client.get(url + '/notifications').json()
    assert [(row['order_id'], row['recipient'], row['message']) for row in notifications] == [
        (order['id'], 'ana@example.com', message),
    ]


def test_list_is_a_summary_and_detail_includes_the_lines(client, make_payload):
    payload = make_payload()
    first = client.post('/orders', json=payload).json()
    second = client.post('/orders', json=payload).json()
    listing = client.get('/orders').json()
    assert [row['id'] for row in listing] == [first['id'], second['id']]
    assert all('items' not in row for row in listing)
    assert client.get('/orders/' + str(first['id'])).json()['items'] == first['items']


def test_quote_and_order_add_all_the_lines(client, make_payload):
    payload = make_payload()
    second = client.post('/products', json={'name': 'Agenda', 'price_cents': 1000, 'stock': 10}).json()
    payload['items'].append({'product_id': second['id'], 'quantity': 3})
    expected = {'subtotal_cents': 8000, 'discount_cents': 800, 'shipping_cents': 1000, 'total_cents': 8200}
    assert client.post('/orders/quote', json=payload).json() == expected
    order = client.post('/orders', json=payload).json()
    assert {key: order[key] for key in expected} == expected
    assert order['items'] == [
        {'product_id': payload['items'][0]['product_id'], 'quantity': 2, 'unit_price_cents': 2500},
        {'product_id': second['id'], 'quantity': 3, 'unit_price_cents': 1000},
    ]


def test_shipping_defaults_to_standard(client, make_payload):
    payload = make_payload(category='regular', price_cents=1000, quantity=1)
    del payload['shipping']
    quote = client.post('/orders/quote', json=payload)
    assert quote.status_code == 200
    assert quote.json() == {'subtotal_cents': 1000, 'discount_cents': 0, 'shipping_cents': 1000, 'total_cents': 2000}


@pytest.mark.parametrize('change', [
    {'customer_id': 0},
    {'customer_id': '1'},
    {'address': ''},
    {'address': 'x' * 201},
    {'city': ''},
    {'postal_code': ''},
    {'shipping': 'drone'},
    {'items': []},
    {'coupon': 'DESCUENTO'},
    {'items': [{'product_id': 1, 'quantity': 0}]},
    {'items': [{'product_id': 1, 'quantity': 10_001}]},
    {'items': [{'product_id': 1, 'quantity': '2'}]},
    {'items': [{'product_id': 0, 'quantity': 1}]},
    {'items': [{'product_id': number, 'quantity': 1} for number in range(1, 102)]},
])
@pytest.mark.parametrize('url', ORDER_URLS)
def test_invalid_order_is_rejected_without_side_effects(client, make_payload, url, change):
    response = client.post(url, json=dict(make_payload(), **change))
    assert response.status_code == 422
    assert client.get('/orders').json() == []
