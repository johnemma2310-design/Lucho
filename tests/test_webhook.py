"""Webhook de WhatsApp: verificación, firma y lectura de mensajes."""
import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app import main, whatsapp
from app.config import settings
from app.main import app, extraer_mensajes

cliente = TestClient(app)


def _webhook(mensajes):
    return {"object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"messaging_product": "whatsapp", "messages": mensajes}}]}]}


def test_verificacion():
    ok = cliente.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "lucho-verificacion",
                                         "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    assert cliente.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "malo"}).status_code == 403


def test_extraer_mensajes():
    datos = _webhook([
        {"id": "a", "from": "57300", "type": "text", "text": {"body": "hola"}},
        {"id": "b", "from": "57300", "type": "interactive", "interactive": {"type": "button_reply",
                                                                           "button_reply": {"id": "btn_guardar", "title": "Guardar"}}},
        {"id": "c", "from": "57300", "type": "document", "document": {"id": "m1", "mime_type": "application/pdf"}},
        {"id": "d", "from": "57300", "type": "image", "image": {"id": "m2", "mime_type": "image/jpeg", "caption": "mi horario"}},
        {"id": "e", "from": "57300", "type": "audio", "audio": {"id": "m3"}},
    ])
    m = extraer_mensajes(datos)
    assert [x["tipo"] for x in m] == ["texto", "boton", "documento", "imagen", "otro"]
    assert m[1]["texto"] == "btn_guardar" and m[3]["texto"] == "mi horario" and m[2]["media_id"] == "m1"
    assert extraer_mensajes({"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}) == []


def test_firma(monkeypatch):
    monkeypatch.setattr(settings(), "whatsapp_app_secret", "secreto")
    cuerpo = b'{"entry": []}'
    firma = "sha256=" + hmac.new(b"secreto", cuerpo, hashlib.sha256).hexdigest()
    assert whatsapp.firma_valida(cuerpo, firma)
    assert not whatsapp.firma_valida(cuerpo, "sha256=falsa")
    assert not whatsapp.firma_valida(cuerpo, None)
    r = cliente.post("/webhook", content=cuerpo, headers={"X-Hub-Signature-256": "sha256=falsa",
                                                           "Content-Type": "application/json"})
    assert r.status_code == 401


def test_mensaje_duplicado_se_procesa_una_vez(canal, monkeypatch):
    llamadas = []
    monkeypatch.setattr(main.bot, "procesar_mensaje", lambda *a, **k: llamadas.append(a))
    cuerpo = json.dumps(_webhook([{"id": "wamid.1", "from": "57300", "type": "text", "text": {"body": "hola"}}]))
    for _ in range(2):
        assert cliente.post("/webhook", content=cuerpo, headers={"Content-Type": "application/json"}).status_code == 200
    assert len(llamadas) == 1


def test_parametro_de_plantilla_sin_saltos():
    assert whatsapp._limpiar_parametro("Hola\n\n• uno\n•    dos") == "Hola · • uno · • dos"
