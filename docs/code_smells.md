# Code smells del codigo inicial

Revision original: 969cbdb93b2fc34bce2f2236d4a405d6e1d1261f (etiqueta estado-inicial).

## 1. Duplicate Code: calculo repetido de descuentos y envios

Categoria: Dispensables (elementos prescindibles).

Ubicacion: app/orders.py, clase OrderService. Metodo save, lineas 52-64; metodo quote, lineas 103-116. Las lineas corresponden a la revision original.

### Evidencia

Ambos metodos contienen estas mismas expresiones dentro de sus bloques de calculo:

    discount = subtotal * 10 // 100

    delivery = 0 if subtotal >= 10_000 else 1_000

Tambien repiten el descuento business del 15 por ciento, el envio pickup gratuito y el envio express de 2500 centavos.

### Problema de mantenimiento

Cambiar el descuento premium o el umbral de envio gratuito exige editar ambos metodos. Si solo se actualiza uno, la cotizacion y el pedido guardado pueden producir totales distintos para la misma entrada.

### Refactorizacion propuesta

Extract Method: extraer el calculo a una unica funcion o metodo compartido por save y quote, conservando los importes, el truncamiento y la aplicacion del umbral sobre el subtotal anterior al descuento.

Estado: identificado; pendiente de aplicar.


## 2. Long Method: multiples responsabilidades en save

Categoria: Bloaters (elementos de tamano o complejidad excesivos).

Ubicacion: app/orders.py, clase OrderService, metodo save, lineas 33-90 de la revision original.

### Evidencia

El mismo metodo concentra estas operaciones:

- Lineas 35-43: validar el pedido existente y buscar el cliente.
- Lineas 44-64: consultar productos y calcular lineas, descuentos, envio y total.
- Lineas 65-83: insertar o actualizar el pedido y guardar sus lineas.
- Lineas 85-90: consultar y construir la respuesta.

Fragmento del bloque de persistencia:

    connection.executemany(
        "INSERT INTO order_items(order_id, product_id, quantity, unit_price_cents) VALUES (?, ?, ?, ?)",
        [(order_id, *line) for line in lines],
    )

### Problema de mantenimiento

No se identifica solo por su longitud: save mezcla varias responsabilidades. Por ejemplo, cambiar la forma de construir la respuesta exige intervenir en el mismo metodo que controla la escritura transaccional. Esto aumenta el esfuerzo de revision y el riesgo de afectar operaciones ajenas al cambio.

### Refactorizacion propuesta

Extract Method: separar bloques con una responsabilidad clara, como calcular importes y construir el detalle del pedido. Los auxiliares de persistencia deben recibir la conexion existente para conservar una unica transaccion.

Esta tecnica tambien se propone para Duplicate Code; ambas aplicaciones cuentan como una sola tecnica distinta para la entrega.

Estado: identificado; pendiente de aplicar.


## 3. Long Parameter List: parametros separados en save

Categoria: Bloaters (elementos de tamano o complejidad excesivos).

Ubicacion: app/orders.py, clase OrderService, firma de save en la linea 33; llamadas desde create_order, lineas 195-197, y update_order, lineas 212-214 de la revision original.

### Evidencia

    def save(self, customer_id, address, city, postal_code, shipping, items, order_id=None):

El metodo recibe siete parametros ademas de self. Los seis primeros ya estan agrupados en OrderInput, pero las rutas extraen y transmiten cada atributo por separado.

### Problema de mantenimiento

La llamada posicional permite confundir address, city y postal_code, que son cadenas de texto. Agregar un dato obligatorio al pedido exigiria modificar la firma y las dos rutas que la invocan, aunque el dato ya forme parte de OrderInput.

### Refactorizacion propuesta

Preserve Whole Object: recibir el objeto OrderInput completo y mantener order_id como parametro opcional separado. La firma propuesta es:

    def save(self, data: OrderInput, order_id=None):

Las rutas enviarian el objeto validado que ya reciben. Se conservarian los cuerpos HTTP, las validaciones y las reglas de negocio. Esta decision mantiene el servicio acoplado al modelo de entrada existente; para el alcance del laboratorio evita introducir otro objeto con los mismos campos.

Estado: identificado; pendiente de aplicar.


## 4. Large Class: responsabilidades concentradas en OrderService

Categoria: Bloaters (elementos de tamano o complejidad excesivos).

Ubicacion: app/orders.py, clase OrderService, lineas 29-182 de la revision original.

### Evidencia

La clase agrupa responsabilidades con motivos de cambio diferentes:

- Calculo comercial: descuentos y envios en save y quote, lineas 52-64 y 103-116.
- Persistencia y consultas: save, get y list, lineas 33-132.
- Transiciones de estado y stock: confirm, cancel y delete, lineas 134-175.
- Construccion y registro de notificaciones: lineas 149-154; consulta mediante notifications, lineas 177-182.

Fragmento del calculo comercial incluido en la misma clase que ejecuta las escrituras SQL:

    total = subtotal - discount + delivery

### Problema de mantenimiento

El hallazgo se fundamenta en la concentracion de responsabilidades, no solo en el numero de lineas. Cambiar descuentos, modificar consultas SQL y ajustar mensajes de notificacion obliga a intervenir en la misma clase. Ademas, probar sus calculos actualmente requiere simular una conexion y respuestas SQL, aunque la aritmetica no necesita persistencia.

### Refactorizacion propuesta

Extract Class: trasladar las reglas de descuentos y envios a una clase PricingCalculator, independiente de HTTP y SQLite. OrderService conservaria la coordinacion de las operaciones y utilizaria ese calculador desde save y quote.

El alcance sera separar el calculo comercial; no se pretende eliminar todas las responsabilidades de OrderService ni introducir una arquitectura completa. Se conservaran las transacciones y los contratos HTTP.

Estado: identificado; pendiente de aplicar.
