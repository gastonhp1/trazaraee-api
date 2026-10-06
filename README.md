# TrazaRAEE API

Trazabilidad de residuos de aparatos eléctricos y electrónicos (RAEE) para cooperativas de reciclaje informático. Cada equipo recuperado lleva un QR que apunta a un ID opaco; detrás hay un historial verificable de dónde vino, qué se le hizo y adónde fue.

> **Estado: prototipo.** El flujo de trabajo (ingreso → prueba → desarme/borrado → venta, donación o scrap) está inferido de información pública sobre cooperativas de este tipo. **No fue validado en un galpón real.** Antes de tomar decisiones de diseño definitivas, hay que visitar una planta, mirar el flujo real y preguntar qué registros les exige hoy la autoridad ambiental. Repo hermano: `trazaraee-app` (PWA para usar en planta).

## Ideas centrales

- **Genealogía, no cadena lineal.** Un equipo se desarma y sus componentes nacen como activos nuevos con `source_asset` (de dónde salieron). Después pueden instalarse en otro equipo (`installed_in`). Se puede responder "este disco salió de la PC X del lote Y y hoy está en la PC Z".
- **Lotes + activos individuales.** Todo ingresa como lote (peso, generador). Solo lo que vale la pena (computadoras, notebooks, discos, RAM...) tiene QR propio. El scrap se registra por fracción de material con peso y destino.
- **Balance de masas** por lote: `ingresado = stock + reutilizado + fracciones (+ diferencia)`. Si la diferencia supera la tolerancia (2 % por defecto), el lote no cierra.
- **Borrado de datos obligatorio** antes de refuncionalizar, vender, donar o instalar cualquier equipo/componente con almacenamiento.
- **Eventos append-only con hash encadenado** por lote y por activo. Editar un evento viejo directo en la base rompe la verificación (`GET /assets/{id}/verify`).
- **Pensado para offline:** el cliente genera los IDs y un `client_id` por evento, así los reintentos de una cola offline son idempotentes.

## Decisiones de privacidad

| Dato | Dónde se ve |
|---|---|
| Serial del equipo | Solo estaciones autenticadas. Nunca en el QR ni en la vista pública. |
| Generador del lote (empresa/organismo) | Oculto en la vista pública salvo que se marque `generator_public`. |
| Destinatario de ventas/donaciones | Solo estaciones autenticadas. |
| Quién hizo cada paso | Se registra la **estación** (mesa, banco de pruebas), no la persona. Es deliberado: el sistema no debe servir para medir o controlar a trabajadores individuales. |
| Vista pública (`/public/a/{id}`) | Tipo, estado, origen (si es público), línea de tiempo (solo tipos de evento y fechas), si hay certificado de borrado y si la cadena verifica. |

## Correr en local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # editá ADMIN_KEY
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload
# Docs interactivas: http://localhost:8000/docs
```

Con Postgres:

```bash
ADMIN_KEY=una-clave-larga docker compose up --build
```

Tests:

```bash
pytest
```

## Primer uso

```bash
# 1. Crear una estación (la clave se muestra una sola vez)
curl -X POST localhost:8000/stations -H "X-Admin-Key: $ADMIN_KEY" \
     -H "Content-Type: application/json" -d '{"name":"Banco de pruebas"}'

# 2. Usar la clave devuelta en el resto de las llamadas
export K=tr_...
curl -X POST localhost:8000/lots -H "X-Station-Key: $K" -H "Content-Type: application/json" \
     -d '{"generator_name":"Empresa Ejemplo SA","weight_kg":120}'
```

## Estados de un activo

```
ingresado ─prueba→ funciona ─refuncionalizacion→ refuncionalizado ─┬→ vendido
              └──→ falla ─scrap→ scrap                    funciona ─┼→ donado
        funciona/falla ─desarme→ desarmado (nacen componentes)      └→ instalado (componente)
```

La definición ejecutable está en `app/rules.py`.

## Endpoints principales

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/stations` | Crea estación (requiere `X-Admin-Key`) |
| POST/GET | `/lots`, `/lots/{id}` | Alta y consulta de lotes |
| GET | `/lots/{id}/balance` | Balance de masas |
| POST/GET | `/lots/{id}/fractions` | Salidas de scrap por material |
| POST/GET | `/assets`, `/assets/{id}` | Alta y consulta de activos |
| POST | `/assets/{id}/events` | Prueba, borrado, refuncionalización, venta, donación, scrap, nota |
| POST | `/assets/{id}/disassemble` | Desarma y crea componentes |
| POST | `/assets/{id}/install` | Instala un componente en este equipo |
| GET | `/assets/{id}/genealogy` | Ancestros, componentes extraídos e instalados |
| GET | `/assets/{id}/verify` | Verifica la cadena de hashes |
| GET | `/public/a/{id}`, `/public/l/{id}` | Vista pública (sin auth) |
| GET | `/labels/{a\|l}/{id}.{svg\|png}` | QR para imprimir |

## Límites conocidos (honestos)

- **La cadena de hashes detecta manipulación, no la impide.** Quien tenga acceso total a la base puede recalcular toda la cadena. Si algún cliente exige inmutabilidad verificable por terceros, el paso siguiente es publicar periódicamente el hash raíz (`head` de `/verify`) en un medio externo, sin necesidad de smart contracts.
- Un solo certificado de borrado por activo (`wiped`); no modela discos múltiples dentro de una misma PC. Si hace falta, se modelan los discos como componentes.
- Sin migraciones: las tablas se crean al arrancar (`create_all`). Pasar a Alembic antes de tener datos reales.
- Autenticación por clave de estación, sin roles ni usuarios. Alcanza para un galpón; no para una plataforma multi-organización.
- Sin generación de manifiestos/declaraciones oficiales: depende de saber qué formato pide la autoridad ambiental.

## Licencia

Pendiente de definir. La intención es que sea software libre para que otras cooperativas puedan reutilizarlo.
