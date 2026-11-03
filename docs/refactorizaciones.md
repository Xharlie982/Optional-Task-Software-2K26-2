# Refactorizaciones aplicadas

## Referencias y alcance

Codigo original: 969cbdb93b2fc34bce2f2236d4a405d6e1d1261f, etiqueta estado-inicial.

Revision con las 25 pruebas previas: ba8875c55adafb8c4b4f6404d34f0c2757b2c736.

Se aplicaron tres tecnicas distintas. Revision del codigo refactorizado analizada en SonarQube: 1d8bdf27852f07ce293945d84e4bcac881221585.

## 1. Extract Method

Problema: save y quote repetian descuentos, envios y calculo del total.

Ubicacion inicial: app/orders.py, lineas 52-64 y 103-116.

Antes, bloque de save:

```python
if customer["category"] == "premium":
    discount = subtotal * 10 // 100
elif customer["category"] == "business":
    discount = subtotal * 15 // 100
else:
    discount = 0
if shipping == "pickup":
    delivery = 0
elif shipping == "standard":
    delivery = 0 if subtotal >= 10_000 else 1_000
else:
    delivery = 2_500
total = subtotal - discount + delivery
```

Primero se extrajo el bloque al metodo estatico OrderService._calculate_totals, utilizado desde save y quote. En la tercera tecnica ese metodo se traslado a PricingCalculator.calculate.

Despues, llamada compartida en la implementacion final:

```python
discount, delivery, total = PricingCalculator.calculate(customer["category"], subtotal, data.shipping)
```

Mejora: las reglas comerciales se mantienen en un solo lugar. Registro de validacion de la primera etapa: ../logs/refactor_01_pruebas.log.

## 2. Preserve Whole Object

Problema: las rutas desarmaban OrderInput para transmitir seis atributos por posicion, ademas del identificador opcional.

Antes:

```python
def save(self, customer_id, address, city, postal_code, shipping, items, order_id=None):
```

Despues:

```python
def save(self, data: OrderInput, order_id=None):
```

Las rutas create_order y update_order ahora pasan data completo. order_id permanece separado. No cambio el cuerpo HTTP ni la validacion de entrada.

Mejora: reduce argumentos posicionales y evita repetir el desglose del objeto. Mantiene el acoplamiento con OrderInput, aceptado para este laboratorio. Registro: ../logs/refactor_02_pruebas.log.

## 3. Extract Class

Problema: OrderService reunia calculos comerciales y coordinacion de persistencia y estados.

Antes: el calculo estaba dentro de OrderService, originalmente duplicado en save y quote, y luego centralizado en _calculate_totals.

Despues, archivo app/pricing.py:

```python
class PricingCalculator:
    @staticmethod
    def calculate(category, subtotal, shipping):
        if category == "premium":
            discount = subtotal * 10 // 100
        elif category == "business":
            discount = subtotal * 15 // 100
        else:
            discount = 0
        if shipping == "pickup":
            delivery = 0
        elif shipping == "standard":
            delivery = 0 if subtotal >= 10_000 else 1_000
        else:
            delivery = 2_500
        total = subtotal - discount + delivery
        return discount, delivery, total
```

OrderService importa PricingCalculator y lo utiliza desde save y quote. El calculador no depende de FastAPI ni SQLite y no guarda estado.

Mejora: separa las reglas aritmeticas de la persistencia. Registro: ../logs/refactor_03_pruebas.log.

## Validacion

Las mismas 25 pruebas pasaron antes de refactorizar y despues de cada etapa, sin cambiar sus expectativas.

| Etapa | Pruebas aprobadas | Cobertura de lineas |
| --- | --- | --- |
| Antes | 25 | 89.77 por ciento |
| Extract Method | 25 | 89.60 por ciento |
| Preserve Whole Object | 25 | 89.60 por ciento |
| Extract Class | 25 | 89.67 por ciento |

PricingCalculator alcanzo 100 por ciento de cobertura. Las variaciones globales reflejan cambios en el numero de instrucciones medidas; permanecen 31 instrucciones sin cubrir.

Las pruebas comprueban descuentos, truncamiento, umbral de envio gratuito, conservacion de precios, recalculo al editar, estados finales, stock insuficiente con rollback y persistencia tras reiniciar, entre otros casos.

## Limites pendientes

Long Method y Large Class se redujeron parcialmente: save y OrderService aun coordinan varias responsabilidades. No se afirma que todos los smells hayan desaparecido.

Las pruebas actuales no cubren todos los errores y operaciones CRUD posibles. El analisis final de SonarQube y el recorrido de la API se completaron; los resultados y evidencias se detallan a continuacion.

No se implementaron los adicionales de idempotencia, cola y DLQ, ni el analisis VHS.


## Resultados de SonarQube

Servidor: SonarQube Community Build 26.10.0.133078. Scanner: SonarScanner CLI 8.1.0.6389. Perfil de Python: Sonar way core, utilizado en ambos analisis.

| Metrica global | Antes | Despues |
| --- | --- | --- |
| Revision del codigo | ba8875c | 1d8bdf2 |
| Cobertura mostrada | 89.8 por ciento | 89.7 por ciento |
| Lineas a cubrir | 303 | 300 |
| Hallazgos abiertos de seguridad | 0 | 0 |
| Hallazgos abiertos de fiabilidad | 0 | 0 |
| Hallazgos abiertos de mantenibilidad | 0 | 0 |
| Duplicacion detectada | 0.0 por ciento | 0.0 por ciento |

Se consulto Overall Code. La cobertura exacta de pytest paso de 89.77 a 89.67 por ciento: una disminucion de 0.10 puntos porcentuales. Se mantienen 31 lineas sin cubrir; cambio el denominador al refactorizar.

Los cero hallazgos y la duplicacion automatica de 0.0 por ciento no invalidan los cuatro smells documentados manualmente: las metricas automaticas dependen de las reglas y criterios del analizador. No se afirma una reduccion de hallazgos automaticos, pues ambos analisis reportan cero. La ejecucion exitosa del scanner no demuestra por si sola el estado del Quality Gate.

Evidencias:

- [SonarQube antes](../evidencias/sonarqube_antes_refactorizacion.png).
- [SonarQube despues](../evidencias/sonarqube_despues_refactorizacion.png).
- [Log antes](../logs/sonar_antes_refactorizacion.log).
- [Log despues](../logs/sonar_despues_refactorizacion.log).

## Recorrido de la API en funcionamiento

Se ejecuto la API con LAB_DB_PATH=data/evidencia_api.sqlite3. Los identificadores devueltos para cliente, producto y pedido fueron 1.

| Operacion | Resultado observado |
| --- | --- |
| Crear cliente premium | HTTP 201 |
| Crear producto de 2500 centavos y stock 5 | HTTP 201 |
| Cotizar dos unidades con envio standard | HTTP 200; subtotal 5000, descuento 500, envio 1000, total 5500 |
| Crear pedido | HTTP 201; pending; total 5500 |
| Confirmar | HTTP 200; confirmed |
| Consultar producto | HTTP 200; stock 3 |
| Consultar notificaciones | HTTP 200; una notificacion |
| Repetir confirmacion | HTTP 409 |
| Consultar efectos despues del conflicto | Stock 3 y una notificacion |

Las respuestas se conservaron en logs/api_01_cliente.log hasta logs/api_09_verificacion_final.log. La [captura final](../evidencias/api_verificacion_final.png) muestra la consulta del registro de verificacion. Este recorrido prueba la proteccion contra confirmar dos veces; no implementa el adicional de idempotencia de creacion.
