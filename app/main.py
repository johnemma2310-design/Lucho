"""Servidor web de Lucho: recibe el webhook de WhatsApp y corre el programador de avisos.

Ejecutar:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from . import bot, db, programador
from .config import settings
from .canales import canal
from .whatsapp import firma_valida

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lucho")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    planificador = None
    if settings().activar_programador:
        planificador = BackgroundScheduler(timezone=settings().zona_horaria)
        planificador.add_job(programador.revisar, "interval", minutes=1, id="revisar",
                             max_instances=1, coalesce=True)
        planificador.start()
        log.info("Programador de avisos activo (cada minuto)")
    yield
    if planificador:
        planificador.shutdown(wait=False)


app = FastAPI(title="Lucho — asistente académico Luis Amigó", lifespan=ciclo_de_vida)


@app.get("/salud")
def salud():
    db.uno("SELECT 1 AS ok")
    return {"estado": "ok"}


@app.get("/webhook")
def verificar_webhook(request: Request):
    """Meta llama aquí una vez al configurar el webhook."""
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == settings().whatsapp_verify_token:
        return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/webhook")
async def recibir_webhook(request: Request, tareas: BackgroundTasks):
    cuerpo = await request.body()
    if not firma_valida(cuerpo, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Firma inválida")
    datos = await request.json()
    for mensaje in extraer_mensajes(datos):
        # Se responde 200 a Meta de inmediato y el mensaje se procesa en segundo plano
        tareas.add_task(run_in_threadpool, atender, mensaje)
    return {"recibido": True}


def extraer_mensajes(datos: dict) -> list[dict]:
    """Saca los mensajes entrantes del formato del webhook de WhatsApp (ignora estados de entrega)."""
    salida = []
    for entrada in datos.get("entry", []):
        for cambio in entrada.get("changes", []):
            valor = cambio.get("value", {})
            for m in valor.get("messages", []) or []:
                tipo = m.get("type")
                item = {"id": m.get("id"), "telefono": m.get("from"), "tipo": "otro", "texto": None,
                        "media_id": None, "mime": None}
                if tipo == "text":
                    item.update(tipo="texto", texto=m["text"]["body"])
                elif tipo == "interactive":
                    i = m.get("interactive", {})
                    respuesta = i.get("button_reply") or i.get("list_reply") or {}
                    item.update(tipo="boton", texto=respuesta.get("id"))
                elif tipo == "button":  # respuesta rápida de una plantilla
                    item.update(tipo="texto", texto=m.get("button", {}).get("text"))
                elif tipo == "image":
                    item.update(tipo="imagen", media_id=m["image"]["id"], mime=m["image"].get("mime_type"),
                                texto=m["image"].get("caption"))
                elif tipo == "document":
                    item.update(tipo="documento", media_id=m["document"]["id"], mime=m["document"].get("mime_type"),
                                texto=m["document"].get("caption"))
                salida.append(item)
    return salida


def atender(m: dict) -> None:
    # WhatsApp puede reenviar el mismo webhook: se procesa una sola vez
    nuevo = db.uno("INSERT INTO mensajes_procesados (wa_message_id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING 1 AS ok",
                   (m["id"],))
    if not nuevo:
        return
    try:
        contenido = None
        if m["media_id"]:
            contenido, mime = canal().descargar_media(m["media_id"])
            m["mime"] = m["mime"] or mime
        bot.procesar_mensaje(m["telefono"], m["tipo"], m["texto"], contenido, m["mime"])
    except Exception:
        log.exception("Error atendiendo el mensaje %s", m["id"])
        try:
            canal().enviar_texto(m["telefono"], "Uy, tuve un problema técnico 😓 Intenta de nuevo en un momento.")
        except Exception:
            pass
