# Informe de laboratorio: FEKA STORE

Laboratorio de pruebas, analisis estatico y refactorizacion de una API de pedidos e inventario (FastAPI y SQLite). Este documento es la entrada del informe: resume las revisiones, las versiones y los comandos para reproducir, y enlaza el detalle y las evidencias.

## Contenido del informe

| Tema | Documento |
| --- | --- |
| Cuatro code smells | [code_smells.md](code_smells.md) |
| Tres tecnicas de refactorizacion, validacion y resultados de SonarQube | [refactorizaciones.md](refactorizaciones.md) |
| Diagramas de clases inicial y final | [diagramas/](diagramas/): cada uno con fuente `.mmd` (Mermaid) y vista `.png` |
| Capturas y registros | [../evidencias/](../evidencias/) y [../logs/](../logs/) |

## Revisiones

| Etapa | Revision | Descripcion |
| --- | --- | --- |
| Inicial | `969cbdb` (etiqueta `estado-inicial`) | Codigo original, con 4 pruebas |
| Pruebas ampliadas | `e0d471e` | Cobertura de 82.84 por ciento y evidencia inicial |
| Antes de refactorizar | `ba8875c` | 25 pruebas, 89.77 por ciento; cuatro smells documentados |
| Refactorizada | `1d8bdf2` | Extract Method, Preserve Whole Object y Extract Class; 25 pruebas, 89.67 por ciento |
| Ultima con cambios de codigo | `70d49be` | Formato de `app/orders.py` (`ff80d4c`) y 133 pruebas, 99.67 por ciento; analizada de nuevo en SonarQube |
| Entrega | etiqueta `estado-final` | Incluye este informe y todas las evidencias |

## Versiones utilizadas

| Herramienta | Version |
| --- | --- |
| Python | CPython 3.13.5 (Windows 11, x86_64) |
| uv | 0.12.24 (5411378eb 2026-10-08) |
| FastAPI | 0.162.0 |
| pytest, pytest-cov, coverage | 9.1.1, 7.1.0, 7.17.0 |
| Docker Desktop | 4.97.0 |
| SonarQube | Community Build 26.10.0.133078; perfil de Python Sonar way core |
| SonarScanner CLI | 8.1.0.6389 (Java 21.0.12.1) |

Las dependencias exactas estan fijadas en `uv.lock`; el registro de instalacion es `../logs/instalacion.log`.

## Como reproducir

Requisitos: Git, uv, Docker con Compose y SonarScanner CLI. Todos los comandos se ejecutan desde la raiz del repositorio.

### Instalar y ejecutar la API

```bash
uv sync --locked
uv run main.py
```

Swagger queda en http://127.0.0.1:8000/docs. Para repetir el recorrido inicial del README sin tocar los datos locales, define antes `LAB_DB_PATH` con otra ruta, por ejemplo `data/evidencia_api.sqlite3` (en PowerShell: `$env:LAB_DB_PATH = "data/evidencia_api.sqlite3"`; en cmd: `set LAB_DB_PATH=data/evidencia_api.sqlite3`).

### Pruebas y cobertura

```bash
uv run pytest --cov --cov-report=term-missing --cov-report=xml --cov-report=html --cov-fail-under=80
```

Genera `coverage.xml` (lo importa SonarQube) y `htmlcov/index.html`. Resultado en la ultima revision: 133 pruebas aprobadas y 99.67 por ciento de cobertura de lineas.

### SonarQube

```bash
docker compose up -d
```

Espera a http://localhost:9000, crea el proyecto `tienda-lab` y genera un token de analisis. Con `coverage.xml` ya generado, en PowerShell:

```powershell
$env:SONAR_HOST_URL = "http://localhost:9000"
$secret = Read-Host "Token de SonarQube" -AsSecureString
$env:SONAR_TOKEN = [System.Net.NetworkCredential]::new("", $secret).Password
sonar-scanner
Remove-Item Env:SONAR_TOKEN
```

El token no se guarda en el repositorio. Para detener SonarQube conservando sus datos: `docker compose down`.

### Repetir las cifras de revisiones anteriores

Cada revision se puede probar en un directorio aparte, sin tocar el trabajo actual:

```powershell
git worktree add ..\feka-antes ba8875c
cd ..\feka-antes
uv sync --locked
uv run pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Sustituye `ba8875c` por `1d8bdf2` (refactorizada) o por `estado-inicial` (original). Con el codigo original el comando termina con error porque la cobertura de 67.33 por ciento no alcanza el umbral. Las 108 pruebas nuevas existen solo desde `70d49be`.

## Evolucion de pruebas y cobertura

| Revision | Pruebas | Cobertura de lineas | Registro |
| --- | --- | --- | --- |
| `969cbdb` | 4 | 67.33 por ciento (no alcanza 80) | [pruebas_iniciales_cobertura_67.log](../logs/pruebas_iniciales_cobertura_67.log) |
| `e0d471e` | no registrado | 82.84 por ciento | [sonar_inicial_cobertura_82_8.log](../logs/sonar_inicial_cobertura_82_8.log) |
| `ba8875c` | 25 | 89.77 por ciento | [pruebas_antes_refactorizacion.log](../logs/pruebas_antes_refactorizacion.log) |
| `1d8bdf2` | 25 | 89.67 por ciento | [refactor_03_pruebas.log](../logs/refactor_03_pruebas.log) |
| `70d49be` | 133 | 99.67 por ciento | [pruebas_finales_cobertura_99_67.log](../logs/pruebas_finales_cobertura_99_67.log) |

## Evidencias

| Evidencia | Que muestra |
| --- | --- |
| [api_verificacion_final.png](../evidencias/api_verificacion_final.png) y `logs/api_01` a `logs/api_09` | Recorrido inicial del README con las respuestas HTTP y la verificacion final |
| [sonarqube_inicial_cobertura_82_8.png](../evidencias/sonarqube_inicial_cobertura_82_8.png) | Resumen de SonarQube en la etapa inicial (82.84 por ciento) |
| [sonarqube_antes_refactorizacion.png](../evidencias/sonarqube_antes_refactorizacion.png) | Overall Code antes de refactorizar (`ba8875c`) |
| [sonarqube_despues_refactorizacion.png](../evidencias/sonarqube_despues_refactorizacion.png) | Overall Code despues de refactorizar (`1d8bdf2`) |
| [sonarqube_final_cobertura_99_7.png](../evidencias/sonarqube_final_cobertura_99_7.png) | Overall Code con la suite ampliada (`70d49be`) |
| `logs/sonar_*.log` | Salida del scanner de cada analisis, con la revision de git registrada |
| `logs/refactor_01_pruebas.log` a `logs/refactor_03_pruebas.log` | Las mismas 25 pruebas tras cada tecnica de refactorizacion |

## Limitaciones pendientes

- Cobertura: la linea 38 de `main.py` (`uvicorn.run` bajo `if __name__ == "__main__"`) no se ejecuta en las pruebas. No se excluyo del analisis.
- Long Method y Large Class se redujeron solo en parte: `OrderService.save` y `OrderService` siguen coordinando varias responsabilidades (detalle en `refactorizaciones.md`).
- Cero hallazgos y 0.0 por ciento de duplicacion automatica en SonarQube no invalidan los smells documentados a mano; dependen de las reglas del analizador.
- Las 108 pruebas nuevas no formaron parte de la comparacion antes y despues, que se hizo con las mismas 25 pruebas sin cambiar sus expectativas.
- No hay pruebas de concurrencia ni de carga. Cada operacion abre su propia conexion SQLite y las escrituras se serializan con `BEGIN IMMEDIATE`.
- SonarQube se ejecuto con su base de datos embebida, que el propio servidor advierte como pensada solo para evaluacion.
