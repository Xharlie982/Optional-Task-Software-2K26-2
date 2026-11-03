# Adicional 1: idempotencia en POST /orders

Rama: `adicional-1-idempotencia`, a partir de la etiqueta `estado-final` de `main`. No modifica las evidencias ni los resultados de la entrega base.

## Contrato

`POST /orders` acepta el encabezado opcional `Idempotency-Key`. La clave la elige el cliente y debe tener de 1 a 255 caracteres ASCII visibles, sin espacios (`^[\x21-\x7E]{1,255}$`).

| Peticion | Resultado |
| --- | --- |
| Sin encabezado | Igual que antes: cada peticion crea un pedido |
| Clave nueva | Crea el pedido y guarda la clave. `201` |
| Misma clave y mismo contenido | `201` con el cuerpo original y el encabezado `Idempotent-Replayed: true`. No crea otro pedido |
| Misma clave y contenido distinto | `409` con `detail` "La clave de idempotencia ya se uso con un contenido distinto" |
| Clave invalida (vacia, con espacios o de mas de 255 caracteres) | `422` |
| Peticion que falla (404, 422, error interno) | No consume la clave: se puede reintentar con la misma |

El contenido se compara despues de validar el cuerpo: se calcula un SHA-256 de su forma canonica (campos ordenados, textos sin espacios sobrantes). Las lineas del pedido cuentan en orden, de modo que cambiar el orden de los productos es un contenido distinto.

## Alcance

- Solo `POST /orders`. `quote`, `PUT`, `confirm`, `cancel` y `delete` no leen la clave; repetir una confirmacion ya devuelve `409` por el estado del pedido.
- Las claves comparten un unico espacio de nombres. El laboratorio no tiene autenticacion, por lo que no hay clientes que separar.
- No hay caducidad de claves, como permite el enunciado.
- El resultado repetido es la copia del cuerpo original, aunque el pedido cambie despues (por `PUT` o `confirm`). Consultar el pedido con `GET /orders/{id}` devuelve su estado actual.
- Eliminar el pedido libera su clave (`ON DELETE CASCADE`): una clave identifica una creacion que sigue existiendo, y reutilizarla despues crea un pedido nuevo.
- Un solo proceso con SQLite. La garantia de concurrencia descansa en el bloqueo de escritura de SQLite, no en memoria del proceso.

## Diseno

Tabla nueva en `app/database.py`, creada con `CREATE TABLE IF NOT EXISTS`, de modo que las bases existentes se actualizan al iniciar:

| Columna | Descripcion |
| --- | --- |
| `idempotency_key` | Clave del cliente; llave primaria |
| `request_hash` | SHA-256 del contenido canonico |
| `order_id` | Pedido creado; llave foranea con `ON DELETE CASCADE` |
| `response` | Cuerpo JSON de la respuesta original |

`OrderService.create` hace todo dentro de una unica transaccion, la misma que ya abre `Database.connect()` con `BEGIN IMMEDIATE`:

1. Busca la clave. Si existe con el mismo `request_hash`, devuelve la respuesta guardada; si el hash difiere, responde `409`.
2. Si no existe, crea el pedido con `_write_order` (el cuerpo que antes vivia dentro de `save`, extraido sin cambios para compartir la transaccion).
3. Guarda la clave con el identificador y la respuesta.
4. `commit`: el pedido y la clave aparecen juntos o no aparecen.

Por que esto cumple los criterios:

- **Concurrencia:** `BEGIN IMMEDIATE` serializa a los escritores. La segunda peticion espera su turno, y cuando entra ve la clave ya confirmada y repite la respuesta. La llave primaria es una segunda barrera.
- **Errores:** cualquier excepcion, incluso despues de insertar el pedido, hace `rollback`. No quedan ni pedido parcial ni clave huerfana, de modo que ninguna clave queda bloqueada.
- **Reinicio:** la clave vive en SQLite, no en memoria.

## Criterios y pruebas

Todas en `tests/test_idempotency.py`:

| Criterio | Prueba |
| --- | --- |
| Misma clave y contenido: resultado original, sin otro pedido | `test_same_key_and_content_returns_the_original_result`, `test_content_is_compared_after_validation` |
| Misma clave con contenido distinto: conflicto | `test_same_key_with_different_content_is_a_conflict` |
| Concurrencia: un solo pedido | `test_concurrent_requests_with_the_same_key_create_one_order` |
| Se conserva tras reiniciar | `test_key_survives_a_restart` |
| Un error no bloquea la clave ni deja pedido parcial | `test_failed_attempt_does_not_consume_the_key`, `test_invalid_request_does_not_consume_the_key`, `test_failure_after_writing_the_order_leaves_nothing_behind` |
| Contrato de la clave | `test_invalid_key_is_rejected`, `test_valid_keys_are_accepted` |
| Alcance | `test_different_keys_and_requests_without_key_create_separate_orders`, `test_replay_returns_the_original_snapshot_even_if_the_order_changed`, `test_deleting_the_order_releases_the_key` |

## Limitaciones

- No hay caducidad ni limpieza de claves; la tabla crece con cada pedido creado con clave.
- El espacio de claves es global; con varios clientes reales convendria asociar la clave a un cliente autenticado.
- La concurrencia esta probada con hilos sobre un unico proceso. Con varios procesos sobre el mismo archivo SQLite el bloqueo de escritura tambien serializa, pero no se probo.
- La respuesta guardada puede quedar desactualizada respecto del pedido, por diseno.

## Como probarlo

En Swagger, `POST /orders` muestra el campo `Idempotency-Key`. Con curl:

```bash
curl -i -X POST http://127.0.0.1:8000/orders -H "Content-Type: application/json" -H "Idempotency-Key: pedido-ana-001" -d @pedido.json
```

Repetir la misma orden devuelve el mismo cuerpo con `Idempotent-Replayed: true`; cambiar un campo del cuerpo con la misma clave devuelve `409`. Pruebas:

```bash
uv run pytest tests/test_idempotency.py
```
