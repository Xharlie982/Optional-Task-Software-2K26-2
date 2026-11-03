import argparse
import os
import threading
import time
from collections import Counter

from app.database import Database
from app.notifications import NotificationQueue, PermanentDeliveryError, SimulatedChannel

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5.0
LEASE_SECONDS = 30.0
POLL_SECONDS = 1.0


class NotificationWorker:
    """Worker unico que procesa la cola de notificaciones, de a un mensaje por vez."""

    def __init__(self, database, channel, clock=time.time, max_attempts=MAX_ATTEMPTS,
                 retry_delay=RETRY_DELAY_SECONDS, lease_seconds=LEASE_SECONDS):
        self.queue = NotificationQueue(database, clock)
        self.channel = channel
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self.lease_seconds = lease_seconds

    def run_once(self):
        """Procesa un mensaje disponible. Devuelve delivered, duplicate, retry o dead; None si no hay ninguno."""
        message = self.queue.claim(self.max_attempts, self.lease_seconds)
        if message is None:
            return None
        if self.queue.is_delivered(message["dedupe_key"]):
            self.queue.acknowledge(message["id"])
            return "duplicate"
        try:
            self.channel.deliver(message["recipient"], message["message"], message["attempts"])
        except PermanentDeliveryError as error:
            return self.queue.record_failure(message, error, self.max_attempts, self.retry_delay, permanent=True)
        except Exception as error:  # cualquier otro fallo del canal se trata como transitorio
            return self.queue.record_failure(message, error, self.max_attempts, self.retry_delay)
        self.queue.complete(message)
        return "delivered"

    def run_pending(self):
        """Procesa todo lo disponible ahora y devuelve los resultados en orden."""
        results = []
        while (result := self.run_once()) is not None:
            results.append(result)
        return results

    def run_forever(self, stop, poll_seconds=POLL_SECONDS, report=None):
        while not stop.is_set():
            result = self.run_once()
            if result is None:
                stop.wait(poll_seconds)
            elif report is not None:
                report(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Worker de notificaciones de Tienda Lab")
    parser.add_argument("--once", action="store_true", help="procesa lo disponible y termina")
    parser.add_argument("--poll", type=float, default=POLL_SECONDS, help="segundos entre consultas a la cola")
    args = parser.parse_args(argv)
    database = Database(os.getenv("LAB_DB_PATH", "data/store.sqlite3"))
    database.initialize()
    worker = NotificationWorker(database, SimulatedChannel.from_text(os.getenv("LAB_NOTIFY_SIMULATION", "")))
    if args.once:
        results = worker.run_pending()
        print(f"Mensajes procesados: {len(results)} {dict(Counter(results))}")
        return 0
    print("Worker iniciado; Ctrl+C para detenerlo.", flush=True)
    try:
        worker.run_forever(threading.Event(), args.poll, report=lambda result: print(f"Resultado: {result}", flush=True))
    except KeyboardInterrupt:
        print("Worker detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
