import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.notifications import NotificationQueue, PermanentDeliveryError, SimulatedChannel, TemporaryDeliveryError
from app.worker import LEASE_SECONDS, MAX_ATTEMPTS, POLL_SECONDS, RETRY_DELAY_SECONDS, NotificationWorker, main
from main import create_app

RECIPIENT = 'ana@example.com'


def confirmation_text(order_id):
    return 'Pedido ' + str(order_id) + ' confirmado. Total: 5500 centavos.'


class FakeClock:
    # Arranca adelantado y en segundos enteros: las sumas son exactas y los mensajes recien creados ya estan disponibles.
    def __init__(self):
        self.now = float(int(time.time()) + 60)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RecordingChannel:
    def __init__(self, error=None):
        self.error = error
        self.attempts = []

    def deliver(self, recipient, message, attempt):
        self.attempts.append(attempt)
        if self.error is not None:
            raise self.error


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def channel():
    return SimulatedChannel()


@pytest.fixture
def worker(client, channel, clock):
    return NotificationWorker(client.app.state.database, channel, clock=clock)


@pytest.fixture
def queue(client, clock):
    return NotificationQueue(client.app.state.database, clock)


def confirm(client, payload):
    order = client.post('/orders', json=payload).json()
    assert client.post('/orders/' + str(order['id']) + '/confirm').status_code == 200
    return order['id']


def queued(client):
    return client.get('/notifications/queue').json()


def dlq(client):
    return client.get('/notifications/dlq').json()


def delivered(client, order_id):
    return client.get('/orders/' + str(order_id) + '/notifications').json()


def enqueue_duplicate(client, order_id):
    with client.app.state.database.connect() as connection:
        NotificationQueue.enqueue(connection, order_id, RECIPIENT, confirmation_text(order_id),
                                  'pedido-confirmado-' + str(order_id), time.time())


def seed_confirmed_order(path):
    with TestClient(create_app(path)) as client:
        customer = client.post('/customers', json={'name': 'Ana', 'email': RECIPIENT, 'category': 'premium'}).json()
        product = client.post('/products', json={'name': 'Libro', 'price_cents': 2500, 'stock': 5}).json()
        payload = {'customer_id': customer['id'], 'address': 'Calle 10', 'city': 'Lima', 'postal_code': '15001',
                   'shipping': 'standard', 'items': [{'product_id': product['id'], 'quantity': 2}]}
        return confirm(client, payload)


def test_confirmation_leaves_a_pending_notification_until_the_worker_runs(client, make_payload, worker):
    order_id = confirm(client, make_payload())
    assert delivered(client, order_id) == []
    [message] = queued(client)
    assert (message['order_id'], message['recipient'], message['status'], message['attempts']) == (
        order_id, RECIPIENT, 'pending', 0)
    assert message['message'] == confirmation_text(order_id)
    assert worker.run_pending() == ['delivered']
    [notification] = delivered(client, order_id)
    assert (notification['recipient'], notification['message']) == (RECIPIENT, confirmation_text(order_id))
    assert queued(client) == []
    assert dlq(client) == []


def test_failed_confirmation_enqueues_nothing(client, make_payload):
    order = client.post('/orders', json=make_payload(stock=1, quantity=2)).json()
    assert client.post('/orders/' + str(order['id']) + '/confirm').status_code == 409
    assert queued(client) == []


def test_repeated_confirmation_enqueues_a_single_message(client, make_payload):
    order_id = confirm(client, make_payload())
    assert client.post('/orders/' + str(order_id) + '/confirm').status_code == 409
    assert len(queued(client)) == 1


def test_temporary_failure_is_retried_after_a_wait(client, make_payload, worker, channel, clock):
    channel.plan[RECIPIENT] = ('temporary', 2)
    order_id = confirm(client, make_payload())
    assert worker.run_once() == 'retry'
    [message] = queued(client)
    assert (message['status'], message['attempts']) == ('pending', 1)
    assert 'Fallo temporal simulado' in message['last_error']
    assert message['available_at'] == clock.now + RETRY_DELAY_SECONDS
    assert worker.run_once() is None
    clock.advance(RETRY_DELAY_SECONDS - 1)
    assert worker.run_once() is None
    clock.advance(1)
    assert worker.run_once() == 'retry'
    assert queued(client)[0]['available_at'] == clock.now + 2 * RETRY_DELAY_SECONDS
    clock.advance(2 * RETRY_DELAY_SECONDS)
    assert worker.run_once() == 'delivered'
    assert len(delivered(client, order_id)) == 1
    assert queued(client) == []
    assert dlq(client) == []


def test_exhausted_attempts_move_the_message_to_the_dlq(client, make_payload, worker, channel, clock):
    channel.plan[RECIPIENT] = ('temporary', 10)
    order_id = confirm(client, make_payload())
    assert worker.run_once() == 'retry'
    clock.advance(RETRY_DELAY_SECONDS)
    assert worker.run_once() == 'retry'
    clock.advance(2 * RETRY_DELAY_SECONDS)
    assert worker.run_once() == 'dead'
    assert queued(client) == []
    [entry] = dlq(client)
    assert (entry['order_id'], entry['recipient'], entry['message']) == (
        order_id, RECIPIENT, confirmation_text(order_id))
    assert entry['dedupe_key'] == 'pedido-confirmado-' + str(order_id)
    assert entry['attempts'] == MAX_ATTEMPTS
    assert 'intento 3' in entry['last_error']
    assert delivered(client, order_id) == []
    assert worker.run_pending() == []


def test_permanent_failure_goes_straight_to_the_dlq(client, make_payload, worker, channel):
    channel.plan[RECIPIENT] = ('permanent', 0)
    order_id = confirm(client, make_payload())
    assert worker.run_once() == 'dead'
    [entry] = dlq(client)
    assert (entry['order_id'], entry['attempts']) == (order_id, 1)
    assert 'permanente' in entry['last_error']
    assert queued(client) == []
    assert delivered(client, order_id) == []


def test_unexpected_channel_error_is_retried(client, make_payload, clock):
    channel = RecordingChannel(RuntimeError('caida del proveedor'))
    worker = NotificationWorker(client.app.state.database, channel, clock=clock)
    confirm(client, make_payload())
    assert worker.run_once() == 'retry'
    assert 'caida del proveedor' in queued(client)[0]['last_error']
    assert channel.attempts == [1]


def test_dlq_message_can_be_reprocessed_explicitly(client, make_payload, worker, channel):
    channel.plan[RECIPIENT] = ('permanent', 0)
    order_id = confirm(client, make_payload())
    assert worker.run_once() == 'dead'
    [entry] = dlq(client)
    channel.plan.clear()
    response = client.post('/notifications/dlq/' + str(entry['id']) + '/reprocess')
    assert response.status_code == 200
    body = response.json()
    assert (body['id'], body['status'], body['attempts']) == (entry['id'], 'pending', 0)
    assert dlq(client) == []
    assert worker.run_pending() == ['delivered']
    assert len(delivered(client, order_id)) == 1


def test_reprocessing_an_unknown_message_returns_404(client):
    response = client.post('/notifications/dlq/999/reprocess')
    assert response.status_code == 404
    assert response.json() == {'detail': 'Mensaje no encontrado en la DLQ'}


def test_message_ids_are_never_reused_so_reprocessing_cannot_collide(client, make_payload, worker, channel):
    payload = make_payload()
    channel.plan[RECIPIENT] = ('permanent', 0)
    confirm(client, payload)
    assert worker.run_once() == 'dead'
    [entry] = dlq(client)
    channel.plan.clear()
    confirm(client, payload)
    assert [message['id'] for message in queued(client)] == [entry['id'] + 1]
    assert client.post('/notifications/dlq/' + str(entry['id']) + '/reprocess').status_code == 200
    assert worker.run_pending() == ['delivered', 'delivered']


def test_pending_messages_survive_a_restart(tmp_path):
    path = tmp_path / 'queue.sqlite3'
    order_id = seed_confirmed_order(path)
    with TestClient(create_app(path)) as client:
        assert len(queued(client)) == 1
        worker = NotificationWorker(client.app.state.database, SimulatedChannel())
        assert worker.run_pending() == ['delivered']
        assert len(delivered(client, order_id)) == 1


def test_interrupted_message_is_recovered_after_the_lease_expires(client, make_payload, queue, clock):
    channel = RecordingChannel()
    worker = NotificationWorker(client.app.state.database, channel, clock=clock)
    order_id = confirm(client, make_payload())
    claimed = queue.claim(MAX_ATTEMPTS, LEASE_SECONDS)
    assert (claimed['status'], claimed['attempts']) == ('processing', 1)
    assert worker.run_once() is None
    clock.advance(LEASE_SECONDS - 1)
    assert worker.run_once() is None
    clock.advance(1)
    assert worker.run_once() == 'delivered'
    assert channel.attempts == [2]
    assert len(delivered(client, order_id)) == 1


def test_message_that_keeps_interrupting_the_worker_ends_in_the_dlq(client, make_payload, queue, worker, clock):
    order_id = confirm(client, make_payload())
    for _ in range(MAX_ATTEMPTS):
        assert queue.claim(MAX_ATTEMPTS, LEASE_SECONDS) is not None
        clock.advance(LEASE_SECONDS)
    assert worker.run_once() is None
    [entry] = dlq(client)
    assert (entry['order_id'], entry['attempts']) == (order_id, MAX_ATTEMPTS)
    assert 'Procesamiento interrumpido' in entry['last_error']
    assert queued(client) == []
    assert delivered(client, order_id) == []


def test_duplicate_messages_do_not_duplicate_the_notification(client, make_payload, worker):
    order_id = confirm(client, make_payload())
    enqueue_duplicate(client, order_id)
    assert len(queued(client)) == 2
    assert worker.run_pending() == ['delivered', 'duplicate']
    assert len(delivered(client, order_id)) == 1
    assert queued(client) == []
    enqueue_duplicate(client, order_id)
    assert worker.run_pending() == ['duplicate']
    assert len(delivered(client, order_id)) == 1


def test_completing_an_already_delivered_message_has_no_second_effect(client, make_payload, queue):
    order_id = confirm(client, make_payload())
    first = queue.claim(MAX_ATTEMPTS, LEASE_SECONDS)
    assert queue.complete(first) is True
    enqueue_duplicate(client, order_id)
    second = queue.claim(MAX_ATTEMPTS, LEASE_SECONDS)
    assert second['id'] != first['id']
    assert queue.complete(second) is False
    assert len(delivered(client, order_id)) == 1
    assert queued(client) == []


def test_simulation_plan_is_parsed_from_text():
    channel = SimulatedChannel.from_text(' ana@example.com=temporary:2, luis@example.com=permanent ,')
    assert channel.plan == {'ana@example.com': ('temporary', 2), 'luis@example.com': ('permanent', 0)}
    assert SimulatedChannel.from_text('').plan == {}
    assert SimulatedChannel.from_text(None).plan == {}


@pytest.mark.parametrize('text', [
    'ana@example.com',
    'ana@example.com=temporary',
    'ana@example.com=temporary:x',
    'ana@example.com=permanent:1',
    'ana@example.com=lento',
])
def test_invalid_simulation_rule_is_rejected(text):
    with pytest.raises(ValueError):
        SimulatedChannel.from_text(text)


def test_simulated_channel_is_deterministic():
    channel = SimulatedChannel({'a@x.com': ('temporary', 2), 'b@x.com': ('permanent', 0)})
    for attempt in (1, 2):
        with pytest.raises(TemporaryDeliveryError):
            channel.deliver('a@x.com', 'hola', attempt)
    channel.deliver('a@x.com', 'hola', 3)
    channel.deliver('otro@x.com', 'hola', 1)
    for attempt in (1, 5):
        with pytest.raises(PermanentDeliveryError):
            channel.deliver('b@x.com', 'hola', attempt)


def test_documented_defaults():
    assert (MAX_ATTEMPTS, RETRY_DELAY_SECONDS, LEASE_SECONDS, POLL_SECONDS) == (3, 5.0, 30.0, 1.0)


def test_run_forever_processes_messages_until_stopped(client, make_payload):
    worker = NotificationWorker(client.app.state.database, SimulatedChannel())
    stop = threading.Event()
    reported = []
    thread = threading.Thread(target=worker.run_forever, args=(stop, 0.01, reported.append))
    thread.start()
    try:
        order_id = confirm(client, make_payload())
        deadline = time.time() + 5
        while not delivered(client, order_id) and time.time() < deadline:
            time.sleep(0.02)
        assert len(delivered(client, order_id)) == 1
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert reported == ['delivered']


def test_main_once_processes_the_queue_and_exits(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'cli.sqlite3'
    order_id = seed_confirmed_order(path)
    monkeypatch.setenv('LAB_DB_PATH', str(path))
    monkeypatch.setenv('LAB_NOTIFY_SIMULATION', '')
    assert main(['--once']) == 0
    assert "'delivered': 1" in capsys.readouterr().out
    with TestClient(create_app(path)) as client:
        assert len(delivered(client, order_id)) == 1


def test_main_uses_the_failure_simulation_from_the_environment(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'cli_dlq.sqlite3'
    order_id = seed_confirmed_order(path)
    monkeypatch.setenv('LAB_DB_PATH', str(path))
    monkeypatch.setenv('LAB_NOTIFY_SIMULATION', RECIPIENT + '=permanent')
    assert main(['--once']) == 0
    assert "'dead': 1" in capsys.readouterr().out
    with TestClient(create_app(path)) as client:
        assert delivered(client, order_id) == []
        assert [entry['order_id'] for entry in dlq(client)] == [order_id]


def test_main_without_once_runs_until_interrupted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('LAB_DB_PATH', str(tmp_path / 'forever.sqlite3'))
    monkeypatch.setenv('LAB_NOTIFY_SIMULATION', '')

    def interrupted(self, stop, poll_seconds, report):
        assert poll_seconds == 0.5
        raise KeyboardInterrupt

    monkeypatch.setattr(NotificationWorker, 'run_forever', interrupted)
    assert main(['--poll', '0.5']) == 0
    assert 'Worker detenido' in capsys.readouterr().out
