"""Configuración de pruebas: usa una base de datos PostgreSQL de pruebas (TEST_DATABASE_URL)
y reemplaza WhatsApp y Gemini por versiones falsas, así las pruebas no cuestan ni envían nada."""
import os
from datetime import datetime

import pytest

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres@localhost:5432/lucho_test")
os.environ["ACTIVAR_PROGRAMADOR"] = "false"
os.environ["WHATSAPP_APP_SECRET"] = ""

from app import db  # noqa: E402
from app.tiempo import zona  # noqa: E402
from app.canales import usar_canal  # noqa: E402


class CanalFalso:
    ventana_24h = True  # se comporta como WhatsApp para probar la regla de plantillas

    def __init__(self):
        self.enviados = []  # (tipo, telefono, texto, extra)

    def enviar_texto(self, telefono, texto):
        self.enviados.append(("texto", telefono, texto, None))

    def enviar_botones(self, telefono, texto, botones):
        self.enviados.append(("botones", telefono, texto, [b[0] for b in botones]))

    def enviar_plantilla(self, telefono, parametro):
        self.enviados.append(("plantilla", telefono, parametro, None))

    def descargar_media(self, media_id):
        return b"%PDF-falso", "application/pdf"

    def ultimo(self):
        return self.enviados[-1]

    def textos(self):
        return "\n".join(e[2] for e in self.enviados)


@pytest.fixture(scope="session", autouse=True)
def cerrar_pool():
    yield
    db.pool().close()


@pytest.fixture(autouse=True)
def limpiar_bd():
    db.ejecutar("""TRUNCATE estudiantes, clases, borradores_horario, recordatorios, avisos, envios_log, mensajes,
                   mensajes_procesados, documentos_fragmentos RESTART IDENTITY CASCADE""")
    yield


@pytest.fixture
def canal():
    c = CanalFalso()
    usar_canal(c)
    return c


def momento(texto: str) -> datetime:
    return datetime.strptime(texto, "%Y-%m-%d %H:%M").replace(tzinfo=zona())


@pytest.fixture
def estudiante_activo():
    return db.uno(
        """INSERT INTO estudiantes (telefono, nombre, correo, programa, estado_registro, acepto_datos_at, ultimo_mensaje_at)
           VALUES ('573001112233', 'Ana Gómez', 'ana.gomez@amigo.edu.co', 'Ingeniería de Sistemas', 'activo', now(), now())
           RETURNING *""")


CLASES_EJEMPLO = [
    {"materia": "Cálculo Diferencial", "dia_semana": 1, "hora_inicio": "08:00", "hora_fin": "10:00", "salon": "305", "bloque": "2"},
    {"materia": "Cálculo Diferencial", "dia_semana": 3, "hora_inicio": "08:00", "hora_fin": "10:00", "salon": "305", "bloque": "2"},
    {"materia": "Bases de Datos", "dia_semana": 1, "hora_inicio": "10:00", "hora_fin": "12:00", "salon": "402", "bloque": "3"},
    {"materia": "Inglés III", "dia_semana": 2, "hora_inicio": "07:00", "hora_fin": "09:00", "salon": "", "bloque": "1"},
]
