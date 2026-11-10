# Lucho 🤖📚

Asistente académico por Telegram (y WhatsApp a futuro) para estudiantes de la Universidad Católica Luis Amigó.
Te dice qué salón te toca, te muestra tu horario y te recuerda parciales y entregas.

**Stack:** Python 3.11+ · Telegram Bot API (MVP) / WhatsApp Cloud API · FastAPI · Claude o Gemini · PostgreSQL (Neon) · APScheduler

## Qué hace (primera versión)

| Caso de uso | Cómo se ve en WhatsApp |
| --- | --- |
| CU-01 Registro | Acepta la política de datos, verifica el correo `@amigo.edu.co` con un código de 6 dígitos |
| CU-02/03/04 Cargar horario | Envía el PDF, una foto o lo escribe; la IA lo lee |
| CU-05 Confirmar | Lucho muestra lo que entendió con botones *Guardar / Cancelar*; se corrige escribiendo |
| CU-06 Modificar | "cambiaron Bases de Datos al 410", "cancelé inglés" |
| CU-07/08 Consultas | "¿qué salón me toca?", "¿qué tengo mañana?", "¿cuándo veo cálculo?" |
| CU-09/10 Recordatorios | "el parcial de cálculo es el 20 a las 8", "¿qué tengo pendiente?", "ya entregué el taller" |
| CU-09 (1a) | Foto del programa del curso → guarda todas las fechas de parciales |
| CU-11/12 Avisos | Avisos de recordatorios, aviso antes de clase, resumen diario 6:00 a. m. y semanal |
| CU-13/15 Universidad | Responde con documentos oficiales cargados con `cargar_documento.py` |
| CU-14/16 | "avísame 20 minutos antes de clase", "borra mi cuenta" |

## Estructura

```
app/
  main.py          servidor web: webhook de WhatsApp + programador de avisos
  bot.py           decide qué hacer con cada mensaje
  registro.py      CU-01 registro y verificación
  horario.py       validación, borradores y consultas de horario
  recordatorios.py recordatorios y cálculo de avisos
  herramientas.py  funciones que la IA puede usar + instrucciones del bot
  ia.py            elige la IA (Claude o Gemini); ia_claude.py, ia_gemini.py y ia_comun.py la implementan
  programador.py   envíos automáticos cada minuto
  canales.py       elige el canal (Telegram o WhatsApp) y envía avisos
  telegram.py      Telegram Bot API
  whatsapp.py      WhatsApp Cloud API
  correo.py        envío del código de verificación
correr_telegram.py  corre a Lucho en Telegram (sin ngrok)
schema.sql         tablas de la base de datos
simular.py         probar el bot en la consola, sin WhatsApp
cargar_documento.py cargar documentos institucionales
tests/             40 pruebas automáticas
```

## Puesta en marcha

### 1. Instalar

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # y llenar los valores
```

### 2. Base de datos (Neon)

El proyecto **amigo-bot** ya está creado en su cuenta de Neon con todas las tablas.
Copien la cadena de conexión desde Neon → *amigo-bot* → **Connect** y pónganla en `DATABASE_URL`.
Si algún día necesitan otra base de datos, ejecuten `schema.sql` sobre ella.

### 3. Inteligencia artificial: Claude o Gemini

Lucho funciona con cualquiera de los dos. Se elige con `IA_PROVEEDOR` en el `.env`; el resto del código no cambia.

| | Claude (Anthropic) | Gemini (Google) |
| --- | --- | --- |
| `.env` | `IA_PROVEEDOR=claude` | `IA_PROVEEDOR=gemini` |
| Clave | `ANTHROPIC_API_KEY`, de [platform.claude.com](https://platform.claude.com) → *API Keys* (créditos en *Billing*) | `GEMINI_API_KEY`, de [Google AI Studio](https://aistudio.google.com/app/apikey) |
| Modelo | `CLAUDE_MODEL=claude-haiku-5-5` | `GEMINI_MODEL` (uno *Flash*) |
| Respaldo si se satura | `CLAUDE_MODEL_RESPALDO=claude-sonnet-5-5` | `GEMINI_MODEL_RESPALDO` |
| Código | `app/ia_claude.py` | `app/ia_gemini.py` |

`app/ia.py` elige el proveedor; `app/ia_comun.py` tiene lo que comparten (el esquema para leer horarios).
Al arrancar, `correr_telegram.py` muestra en el log qué IA está usando y avisa si falta la clave.

### 4. Probar sin WhatsApp

```bash
python simular.py
```

Escriban como si fueran un estudiante. El código de verificación sale en la consola si `SMTP_HOST` está vacío.
Comandos: `/pdf horario.pdf`, `/foto horario.jpg`, `/boton btn_guardar`, `/hora 2026-10-08 07:50`, `/revisar`.

### 5. Telegram (canal del MVP)

1. En Telegram, abre **@BotFather**, escribe `/newbot`, ponle nombre (Lucho) y un usuario que termine en `bot` (por ejemplo `LuchoAmigoBot`).
2. Copia el token que te da y ponlo en `.env` como `TELEGRAM_BOT_TOKEN=...`, con `CANAL=telegram`.
3. Opcional: con `/setcommands` en BotFather agrega `start`, `ayuda`, `horario` y `pendientes`.
4. Ejecuta:
   ```bash
   python correr_telegram.py
   ```
   No necesita ngrok: el programa consulta a Telegram (long polling) y corre el programador de avisos. Busca tu bot en Telegram y escríbele.

### 5b. WhatsApp Cloud API (cuando la universidad verifique la cuenta)

Pon `CANAL=whatsapp` y sigue estos pasos:

1. En [Meta for Developers](https://developers.facebook.com) creen una app de tipo **Business** y agreguen el producto **WhatsApp**.
2. En *WhatsApp → Configuración de la API* copien el **token** y el **Phone number ID** al `.env`, y agreguen sus números como destinatarios de prueba (el número de prueba solo escribe a hasta 5 números verificados).
3. Para que Meta llegue a su computador, ejecuten el servidor y expónganlo con [ngrok](https://ngrok.com):
   ```bash
   uvicorn app.main:app --port 8000
   ngrok http 8000
   ```
4. En *WhatsApp → Configuración → Webhook* pongan `https://SU-URL-DE-NGROK/webhook` y el mismo `WHATSAPP_VERIFY_TOKEN` del `.env`. Suscríbanse al campo **messages**.
5. Copien la **Clave secreta de la app** (*Configuración de la app → Básica*) en `WHATSAPP_APP_SECRET`.
6. El token temporal dura 24 horas. Para uno permanente, creen un *usuario del sistema* en Business Manager.

### 6. Plantilla para avisos

WhatsApp solo deja escribir libremente al estudiante si él escribió en las últimas 24 horas. Para recordatorios y resúmenes fuera de esa ventana, Lucho usa una plantilla. Créenla en *WhatsApp Manager → Plantillas de mensajes*:

- **Nombre:** `lucho_aviso` · **Categoría:** Utilidad · **Idioma:** Español (`es`)
- **Cuerpo:**
  ```
  Hola, soy Lucho 📚

  {{1}}

  Respóndeme si necesitas algo más.
  ```
- **Ejemplo de {{1}}:** `📝 Recordatorio: Parcial de Cálculo. Es mañana a las 8:00 a. m.`

Estos mensajes tienen costo según la tarifa de Meta para Colombia; inclúyanlo en el análisis de costos (RNF-08).

### 7. Correo de verificación

Para enviar el código de verdad, configuren SMTP. Con Gmail: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, su correo y una [contraseña de aplicación](https://myaccount.google.com/apppasswords).

### 8. Documentos de la universidad (opcional)

```bash
python cargar_documento.py "Calendario académico 2026-2" calendario.pdf
python cargar_documento.py "Directorio de dependencias" directorio.txt
```

Festivos y vacaciones van en la tabla `dias_no_habiles` (ya están los festivos que faltan de 2026).

## Despliegue

El programador de avisos corre dentro del servidor, así que necesitan un servicio **siempre encendido** (Railway, Fly.io, un VPS o Render de pago). Los planes gratuitos que "duermen" el servidor no enviarían los avisos a tiempo.

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Pruebas

Necesitan una base PostgreSQL vacía solo para pruebas (puede ser una rama de Neon o un Postgres local):

```bash
psql "$TEST_DATABASE_URL" -f schema.sql
TEST_DATABASE_URL=postgresql://... pytest
```

Las pruebas reemplazan WhatsApp, Gemini y Claude por versiones falsas, así que no gastan dinero ni envían mensajes.

## Decisiones de diseño para el documento

- **La IA no inventa datos (RN-04):** la IA (Claude o Gemini) solo interpreta el mensaje y elige una función; salones y horas salen de la base de datos.
- **Nada se guarda sin confirmar (RN-03):** lo que la IA lee de un PDF o foto queda como borrador hasta que el estudiante toca *Guardar*.
- **Archivos no se almacenan (RN-09):** el PDF o la foto se procesan en memoria; solo se guardan las clases extraídas.
- **Dentro de la política de WhatsApp (RN-06):** Lucho rechaza temas que no sean académicos o de la universidad.
- **Sin duplicados:** cada webhook y cada envío automático se registra para no procesarse ni enviarse dos veces.
