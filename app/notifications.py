import time

from fastapi import APIRouter, HTTPException, Request


class TemporaryDeliveryError(Exception):
    """Fallo transitorio: el mensaje se reintenta."""


class PermanentDeliveryError(Exception):
    """Fallo definitivo: el mensaje pasa directamente a la DLQ."""


class SimulatedChannel:
    """Canal local de notificaciones con fallos reproducibles por destinatario.

    El plan asigna a un destinatario ("temporary", n), que falla en sus primeros n intentos,
    o ("permanent", 0), que falla siempre. Los demas destinatarios reciben sin errores.
    El resultado depende solo del numero de intento guardado en la cola, no del azar ni del reloj.
    """

    def __init__(self, plan=None):
        self.plan = dict(plan or {})

    @classmethod
    def from_text(cls, text):
        # Formato: "ana@example.com=temporary:2,luis@example.com=permanent"
        plan = {}
        for entry in (part.strip() for part in (text or "").split(",")):
            if not entry:
                continue
            recipient, _, rule = entry.partition("=")
            kind, _, count = rule.partition(":")
            if kind == "temporary" and count.isdigit():
                plan[recipient.strip()] = ("temporary", int(count))
            elif kind == "permanent" and not count:
                plan[recipient.strip()] = ("permanent", 0)
            else:
                raise ValueError(f"Regla de simulacion invalida: {entry!r}")
        return cls(plan)

    def deliver(self, recipient, message, attempt):
        kind, count = self.plan.get(recipient, (None, 0))
        if kind == "permanent":
            raise PermanentDeliveryError("Fallo permanente simulado: destinatario rechazado")
        if kind == "temporary" and attempt <= count:
            raise TemporaryDeliveryError(f"Fallo temporal simulado en el intento {attempt} de {count} programados")


class NotificationQueue:
    """Cola de notificaciones y DLQ sobre SQLite. Cada operacion es una transaccion."""

    def __init__(self, database, clock=time.time):
        self.database = database
        self.clock = clock

    @staticmethod
    def enqueue(connection, order_id, recipient, message, dedupe_key, now):
        cursor = connection.execute(
            """INSERT INTO notification_queue(dedupe_key, order_id, recipient, message, available_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (dedupe_key, order_id, recipient, message, now, now),
        )
        return cursor.lastrowid

    def list_queue(self):
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM notification_queue ORDER BY id")]

    def list_dlq(self):
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM notification_dlq ORDER BY id")]

    def claim(self, max_attempts, lease_seconds):
        """Toma el siguiente mensaje disponible y lo deja en procesamiento. Cuenta como un intento.

        Tambien retoma los mensajes cuyo arrendamiento vencio porque el worker se interrumpio.
        Si uno de ellos ya agoto sus intentos, pasa a la DLQ en lugar de procesarse otra vez.
        """
        now = self.clock()
        with self.database.connect() as connection:
            while True:
                row = connection.execute(
                    """SELECT * FROM notification_queue
                       WHERE (status = 'pending' AND available_at <= ?)
                          OR (status = 'processing' AND locked_until <= ?)
                       ORDER BY available_at, id LIMIT 1""",
                    (now, now),
                ).fetchone()
                if row is None:
                    return None
                if row["status"] == "processing" and row["attempts"] >= max_attempts:
                    error = f"Procesamiento interrumpido: se agotaron los {max_attempts} intentos"
                    self._dead_letter(connection, row, error, now)
                    continue
                attempts = row["attempts"] + 1
                connection.execute(
                    "UPDATE notification_queue SET status = 'processing', attempts = ?, locked_until = ? WHERE id = ?",
                    (attempts, now + lease_seconds, row["id"]),
                )
                return dict(row, status="processing", attempts=attempts)

    def is_delivered(self, dedupe_key):
        with self.database.connect() as connection:
            row = connection.execute("SELECT 1 FROM delivered_messages WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            return row is not None

    def acknowledge(self, message_id):
        with self.database.connect() as connection:
            connection.execute("DELETE FROM notification_queue WHERE id = ?", (message_id,))

    def complete(self, message):
        """Registra la notificacion y confirma el mensaje en una sola transaccion.

        Devuelve False si la clave de deduplicacion ya estaba entregada: el efecto no se repite.
        """
        with self.database.connect() as connection:
            already = connection.execute(
                "SELECT 1 FROM delivered_messages WHERE dedupe_key = ?", (message["dedupe_key"],),
            ).fetchone()
            if already is None:
                cursor = connection.execute(
                    "INSERT INTO notifications(order_id, recipient, message) VALUES (?, ?, ?)",
                    (message["order_id"], message["recipient"], message["message"]),
                )
                connection.execute(
                    "INSERT INTO delivered_messages(dedupe_key, notification_id) VALUES (?, ?)",
                    (message["dedupe_key"], cursor.lastrowid),
                )
            connection.execute("DELETE FROM notification_queue WHERE id = ?", (message["id"],))
            return already is None

    def record_failure(self, message, error, max_attempts, retry_delay, permanent=False):
        """Programa un reintento con espera exponencial o, si no hay mas opciones, envia el mensaje a la DLQ."""
        now = self.clock()
        with self.database.connect() as connection:
            if permanent or message["attempts"] >= max_attempts:
                self._dead_letter(connection, message, str(error), now)
                return "dead"
            delay = retry_delay * 2 ** (message["attempts"] - 1)
            connection.execute(
                """UPDATE notification_queue
                   SET status = 'pending', locked_until = NULL, available_at = ?, last_error = ? WHERE id = ?""",
                (now + delay, str(error), message["id"]),
            )
            return "retry"

    def reprocess(self, message_id):
        """Devuelve un mensaje de la DLQ a la cola con un presupuesto de intentos nuevo."""
        now = self.clock()
        with self.database.connect() as connection:
            entry = connection.execute("SELECT * FROM notification_dlq WHERE id = ?", (message_id,)).fetchone()
            if entry is None:
                raise HTTPException(404, "Mensaje no encontrado en la DLQ")
            connection.execute(
                """INSERT INTO notification_queue(id, dedupe_key, order_id, recipient, message, last_error,
                                                  available_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry["id"], entry["dedupe_key"], entry["order_id"], entry["recipient"], entry["message"],
                 entry["last_error"], now, now),
            )
            connection.execute("DELETE FROM notification_dlq WHERE id = ?", (message_id,))
            return dict(connection.execute("SELECT * FROM notification_queue WHERE id = ?", (message_id,)).fetchone())

    @staticmethod
    def _dead_letter(connection, message, error, now):
        connection.execute(
            """INSERT INTO notification_dlq(id, dedupe_key, order_id, recipient, message, attempts, last_error, failed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (message["id"], message["dedupe_key"], message["order_id"], message["recipient"], message["message"],
             message["attempts"], error, now),
        )
        connection.execute("DELETE FROM notification_queue WHERE id = ?", (message["id"],))


router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/queue")
def list_queue(request: Request):
    return NotificationQueue(request.app.state.database).list_queue()


@router.get("/dlq")
def list_dlq(request: Request):
    return NotificationQueue(request.app.state.database).list_dlq()


@router.post("/dlq/{message_id}/reprocess")
def reprocess_message(message_id: int, request: Request):
    return NotificationQueue(request.app.state.database).reprocess(message_id)
