# Refactorizaciones aplicadas

## Referencias y alcance

Codigo original: 969cbdb93b2fc34bce2f2236d4a405d6e1d1261f, etiqueta estado-inicial.

Revision con las 25 pruebas previas: ba8875c55adafb8c4b4f6404d34f0c2757b2c736.

Se aplicaron tres tecnicas distintas. La revision final se registrara al crear el commit de cierre.

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

Las pruebas actuales no cubren todos los errores y operaciones CRUD posibles. Falta adjuntar el analisis final de SonarQube y completar las evidencias de ejecucion de la API.

No se implementaron los adicionales de idempotencia, cola y DLQ, ni el analisis VHS.
