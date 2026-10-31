"""Corre a Lucho en Telegram.

Uso:  python correr_telegram.py

No necesita ngrok ni servidor web: el programa le pregunta a Telegram cada pocos segundos
si hay mensajes nuevos (long polling) y, en paralelo, corre el programador de avisos.
Requiere TELEGRAM_BOT_TOKEN y CANAL=telegram en el .env. Para detenerlo: Ctrl + C.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from apscheduler.schedulers.background import BackgroundScheduler

from app import bot, db, programador
from app.canales import canal
from app.config import settings
from app.telegram import ErrorTelegram, interpretar_update

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("lucho")


def atender(m: dict) -> None:
    """Procesa un mensaje una sola vez, aunque Telegram lo entregue repetido."""
    nuevo = db.uno("INSERT INTO mensajes_procesados (wa_message_id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING 1 AS ok",
                   (m["id"],))
    if not nuevo:
        return
    c = canal()
    try:
        if m["tipo"] == "boton":
            c.responder_boton(m["callback_id"])
            c.quitar_botones(m["destino"].removeprefix("tg:"), m["mensaje_id"])
        else:
            c.escribiendo(m["destino"])
        contenido = None
        if m["media_id"]:
            contenido, mime = c.descargar_media(m["media_id"])
            m["mime"] = m["mime"] or mime
        log.info("Mensaje de %s (%s): %s", m["destino"], m["tipo"], (m["texto"] or "")[:80])
        bot.procesar_mensaje(m["destino"], m["tipo"], m["texto"], contenido, m["mime"])
    except Exception:
        log.exception("Error atendiendo %s", m["id"])
        try:
            c.enviar_texto(m["destino"], "Uy, tuve un problema técnico 😓 Intenta de nuevo en un momento.")
        except Exception:
            pass


def main() -> None:
    if not settings().telegram_bot_token:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en el .env (te lo da @BotFather en Telegram).")
    c = canal()
    yo = c.api("getMe")
    c.api("deleteWebhook")  # el modo polling no funciona si hay un webhook configurado
    log.info("Lucho conectado a Telegram como @%s", yo["username"])

    planificador = BackgroundScheduler(timezone=settings().zona_horaria)
    planificador.add_job(programador.revisar, "interval", minutes=1, max_instances=1, coalesce=True)
    planificador.start()
    log.info("Programador de avisos activo (cada minuto). Ctrl + C para detener.")

    trabajadores = ThreadPoolExecutor(max_workers=4)
    offset = None
    try:
        while True:
            try:
                updates = c.api("getUpdates", espera=50, timeout=40, offset=offset,
                                allowed_updates=["message", "callback_query"])
            except ErrorTelegram as e:
                log.error("Telegram respondió con error: %s", e)
                time.sleep(5)
                continue
            except Exception as e:
                log.warning("Sin conexión con Telegram (%s); reintento en 5 s", e)
                time.sleep(5)
                continue
            for u in updates or []:
                offset = u["update_id"] + 1
                m = interpretar_update(u)
                if m:
                    trabajadores.submit(atender, m)
    except KeyboardInterrupt:
        log.info("Deteniendo a Lucho…")
    finally:
        planificador.shutdown(wait=False)
        trabajadores.shutdown(wait=True)
        db.pool().close()


if __name__ == "__main__":
    main()
