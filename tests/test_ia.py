"""Pruebas del proveedor Claude y del selector de IA, con un cliente falso de Anthropic (no gasta créditos)."""
from types import SimpleNamespace

import anthropic
import pytest

try:  # las versiones nuevas del SDK de Anthropic usan httpx2
    import httpx2 as httpx
except ImportError:
    import httpx

from app import ia, ia_claude
from app.config import settings


def texto(t):
    return SimpleNamespace(type="text", text=t)


def herramienta(nombre, entrada, id_="toolu_1"):
    return SimpleNamespace(type="tool_use", name=nombre, input=entrada, id=id_)


class ClaudeFalso:
    """Imita client.messages.create: devuelve las respuestas en orden y guarda cada llamada."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.messages = self

    def create(self, **datos):
        # Se guarda una copia de los mensajes, porque conversar() sigue agregando a la misma lista
        self.llamadas.append({**datos, "messages": [dict(m) for m in datos.get("messages", [])]})
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(content=r)


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setattr(settings(), "ia_proveedor", "claude")
    monkeypatch.setattr(settings(), "claude_model", "claude-haiku-5-5")
    monkeypatch.setattr(settings(), "claude_model_respaldo", "claude-sonnet-5-5")
    monkeypatch.setattr(ia_claude, "ESPERAS", (0, 0))

    def usar(*respuestas):
        falso = ClaudeFalso(*respuestas)
        monkeypatch.setattr(ia_claude, "_cliente", falso)
        return falso
    return usar


def saturado():
    respuesta = httpx.Response(529, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return anthropic.APIStatusError("Overloaded", response=respuesta, body=None)


def test_selector_elige_el_proveedor(monkeypatch):
    monkeypatch.setattr(settings(), "ia_proveedor", "Claude ")
    assert ia.proveedor() is ia_claude
    monkeypatch.setattr(settings(), "ia_proveedor", "chatgpt")
    with pytest.raises(ValueError, match="gemini' o 'claude"):
        ia.proveedor()


def test_falta_clave_de_claude(monkeypatch):
    monkeypatch.setattr(settings(), "ia_proveedor", "claude")
    monkeypatch.setattr(settings(), "anthropic_api_key", "")
    assert ia.falta_clave() == "ANTHROPIC_API_KEY"
    monkeypatch.setattr(settings(), "anthropic_api_key", "sk-ant-prueba")
    assert ia.falta_clave() is None
    assert ia.descripcion() == f"claude ({settings().claude_model}, respaldo {settings().claude_model_respaldo})"


def test_extraer_pdf_obliga_a_usar_el_esquema(claude):
    datos = {"tipo_documento": "horario", "confianza": "alta", "evaluaciones": [],
             "clases": [{"materia": "Cálculo", "dia_semana": 1, "hora_inicio": "08:00", "hora_fin": "10:00"}]}
    falso = claude([herramienta(ia_claude.HERRAMIENTA_EXTRACCION, datos)])
    assert ia.extraer(contenido=b"%PDF-1.4", mime="application/pdf", hoy="2026-11-10") == datos

    llamada = falso.llamadas[0]
    assert llamada["model"] == "claude-haiku-5-5"
    assert llamada["tool_choice"] == {"type": "tool", "name": ia_claude.HERRAMIENTA_EXTRACCION}
    assert llamada["tools"][0]["input_schema"] is ia.ESQUEMA_EXTRACCION
    partes = llamada["messages"][0]["content"]
    assert partes[0]["type"] == "document" and partes[0]["source"]["media_type"] == "application/pdf"
    assert partes[-1] == {"type": "text", "text": "Fecha de hoy: 2026-11-10"}
    assert "temperature" not in llamada


def test_extraer_imagen_y_tipo_no_soportado(claude):
    falso = claude([herramienta(ia_claude.HERRAMIENTA_EXTRACCION, {"tipo_documento": "otro"})])
    ia.extraer(contenido=b"\xff\xd8", mime="image/jpeg")
    assert falso.llamadas[0]["messages"][0]["content"][0]["type"] == "image"
    with pytest.raises(ValueError, match="image/heic"):
        ia.extraer(contenido=b"...", mime="image/heic")


def test_conversar_ejecuta_herramientas_y_responde(claude):
    falso = claude(
        [texto("Déjame revisar."), herramienta("clase_actual", {}, "toolu_9")],
        [texto("Parce, a las 8:00 tienes Cálculo en el 305.")],
    )
    pedidas = []

    def ejecutar(nombre, args):
        pedidas.append((nombre, args))
        return {"materia": "Cálculo", "salon": "305"}

    historial = [{"rol": "user", "contenido": "hola"}, {"rol": "model", "contenido": "¡Quiubo!"}]
    declaraciones = [{"name": "clase_actual", "description": "Clase actual",
                      "parameters": {"type": "object", "properties": {}}}]
    respuesta = ia.conversar("Eres Lucho.", historial, "¿qué salón me toca?", declaraciones, ejecutar)

    assert respuesta == "Parce, a las 8:00 tienes Cálculo en el 305."
    assert pedidas == [("clase_actual", {})]
    primera, segunda = falso.llamadas
    assert primera["system"] == "Eres Lucho."
    assert [m["role"] for m in primera["messages"]] == ["user", "assistant", "user"]
    assert primera["tools"] == [{"name": "clase_actual", "description": "Clase actual",
                                 "input_schema": {"type": "object", "properties": {}}}]
    resultado = segunda["messages"][-1]["content"][0]
    assert resultado["type"] == "tool_result" and resultado["tool_use_id"] == "toolu_9"
    assert "305" in resultado["content"]


def test_error_en_herramienta_se_le_explica_a_claude(claude):
    falso = claude([herramienta("clase_actual", {})], [texto("Uy, no pude consultar.")])

    def ejecutar(nombre, args):
        raise RuntimeError("se cayó la base de datos")

    assert ia.conversar("s", [], "hola", [], ejecutar) == "Uy, no pude consultar."
    assert "se cayó la base de datos" in falso.llamadas[1]["messages"][-1]["content"][0]["content"]


def test_historial_se_une_y_empieza_por_el_estudiante():
    mensajes = ia_claude._mensajes(
        [{"rol": "model", "contenido": "suelto"}, {"rol": "user", "contenido": "a"},
         {"rol": "user", "contenido": "b"}, {"rol": "model", "contenido": "c"}], "d")
    assert mensajes == [{"role": "user", "content": "a\n\nb"}, {"role": "assistant", "content": "c"},
                        {"role": "user", "content": "d"}]


def test_saturado_reintenta_y_cambia_al_respaldo(claude):
    falso = claude(saturado(), saturado(), saturado(), [texto("Listo desde el respaldo")])
    assert ia.conversar("s", [], "hola", [], lambda n, a: None) == "Listo desde el respaldo"
    assert [ll["model"] for ll in falso.llamadas] == ["claude-haiku-5-5"] * 3 + ["claude-sonnet-5-5"]


def test_error_no_temporal_no_se_reintenta(claude):
    respuesta = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    falso = claude(anthropic.AuthenticationError("clave inválida", response=respuesta, body=None))
    with pytest.raises(anthropic.AuthenticationError):
        ia.conversar("s", [], "hola", [], lambda n, a: None)
    assert len(falso.llamadas) == 1
