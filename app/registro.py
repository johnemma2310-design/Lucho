"""Registro y verificación del estudiante con su correo institucional (CU-01)."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta

from . import correo, db
from .config import settings
from .tiempo import ahora
from .canales import canal

MINUTOS_CODIGO = 10
MAX_INTENTOS = 3
MINUTOS_BLOQUEO = 30
PATRON_CORREO = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")

SI = {"si", "sí", "acepto", "aceptar", "ok", "dale", "listo", "de una", "btn_acepto"}
NO = {"no", "no acepto", "btn_no_acepto"}


def _hash(codigo: str) -> str:
    return hashlib.sha256(f"{settings().secreto_otp}:{codigo}".encode()).hexdigest()


def _limpio(texto: str) -> str:
    return texto.strip().lower().rstrip(".!")


def obtener_o_crear(telefono: str) -> dict:
    with db.conexion() as conn:
        conn.execute("INSERT INTO estudiantes (telefono) VALUES (%s) ON CONFLICT (telefono) DO NOTHING", (telefono,))
        return conn.execute("SELECT * FROM estudiantes WHERE telefono = %s", (telefono,)).fetchone()


def _estado(est_id: int, estado: str, **campos) -> None:
    sets = ", ".join(["estado_registro = %s"] + [f"{k} = %s" for k in campos])
    db.ejecutar(f"UPDATE estudiantes SET {sets} WHERE id = %s", (estado, *campos.values(), est_id))


def procesar(est: dict, texto: str, momento: datetime | None = None) -> None:
    """Avanza el registro según el estado actual del estudiante."""
    momento = momento or ahora()
    tel = est["telefono"]
    estado = est["estado_registro"]
    t = _limpio(texto or "")

    if estado == "nuevo":
        canal().enviar_texto(tel, (
            "¡Hola! 👋 Soy *Lucho*, el asistente académico de la Universidad Católica Luis Amigó.\n\n"
            "Te digo qué salón te toca, te muestro tu horario y te recuerdo parciales y entregas.\n\n"
            "Para empezar necesito guardar tu nombre, correo institucional, horario y recordatorios. "
            f"Los trato según la Ley 1581 de 2012 y la política de datos de la universidad: {settings().url_politica_datos}"
        ))
        canal().enviar_botones(tel, "¿Autorizas el tratamiento de tus datos?",
                               [("btn_acepto", "Sí, acepto"), ("btn_no_acepto", "No acepto")])
        _estado(est["id"], "esperando_aceptacion")
        return

    if estado == "esperando_aceptacion":
        if t in SI:
            _estado(est["id"], "esperando_correo", acepto_datos_at=momento)
            canal().enviar_texto(tel, f"¡Gracias! Escríbeme tu correo institucional (termina en @{settings().dominio_correo}).")
        elif t in NO:
            canal().enviar_texto(tel, "Entiendo. Sin tu autorización no puedo guardar datos, así que no puedo ayudarte. "
                                      "Si cambias de opinión, escribe *acepto*.")
        else:
            canal().enviar_botones(tel, "Antes de seguir necesito tu autorización para tratar tus datos.",
                                   [("btn_acepto", "Sí, acepto"), ("btn_no_acepto", "No acepto")])
        return

    if est.get("bloqueado_hasta") and est["bloqueado_hasta"] > momento:
        minutos = int((est["bloqueado_hasta"] - momento).total_seconds() // 60) + 1
        canal().enviar_texto(tel, f"Por seguridad, espera {minutos} minutos antes de intentar de nuevo.")
        return

    if estado == "esperando_correo":
        direccion = t.replace(" ", "")
        if not PATRON_CORREO.match(direccion):
            canal().enviar_texto(tel, "Eso no parece un correo. Escríbelo completo, por ejemplo nombre.apellido@"
                                      f"{settings().dominio_correo}")
            return
        if not direccion.endswith("@" + settings().dominio_correo):
            canal().enviar_texto(tel, f"Solo acepto correos institucionales (@{settings().dominio_correo}). "
                                      "Así sé que eres estudiante de la Luis Amigó.")
            return
        _enviar_codigo(est, direccion, momento)
        return

    if estado == "esperando_codigo":
        if t in {"reenviar", "reenviar codigo", "reenviar código"}:
            _enviar_codigo(est, est["correo_pendiente"], momento)
            return
        if t in {"cambiar correo", "otro correo"}:
            _estado(est["id"], "esperando_correo")
            canal().enviar_texto(tel, "Listo, escríbeme el correo correcto.")
            return
        codigo = re.sub(r"\D", "", t)
        if not est.get("otp_expira") or est["otp_expira"] < momento:
            canal().enviar_texto(tel, "Ese código ya venció. Escribe *reenviar* y te mando otro.")
            return
        if len(codigo) == 6 and secrets.compare_digest(_hash(codigo), est["otp_hash"] or ""):
            _verificado(est, momento)
            return
        intentos = est["otp_intentos"] + 1
        if intentos >= MAX_INTENTOS:
            _estado(est["id"], "esperando_correo", otp_intentos=0, otp_hash=None,
                    bloqueado_hasta=momento + timedelta(minutes=MINUTOS_BLOQUEO))
            canal().enviar_texto(tel, f"Código incorrecto 3 veces. Por seguridad, espera {MINUTOS_BLOQUEO} minutos y "
                                      "vuelve a escribirme tu correo.")
        else:
            _estado(est["id"], "esperando_codigo", otp_intentos=intentos)
            canal().enviar_texto(tel, f"Ese código no coincide. Te quedan {MAX_INTENTOS - intentos} intentos. "
                                      "(Escribe *reenviar* si no te llegó).")
        return

    if estado == "esperando_nombre":
        nombre = " ".join(w.capitalize() for w in (texto or "").strip().split())[:80]
        if len(nombre) < 2:
            canal().enviar_texto(tel, "¿Cómo te llamas?")
            return
        _estado(est["id"], "esperando_programa", nombre=nombre)
        canal().enviar_texto(tel, f"Mucho gusto, {nombre.split()[0]} 😊 ¿Qué programa estudias? (por ejemplo, Ingeniería de Sistemas)")
        return

    if estado == "esperando_programa":
        programa = (texto or "").strip()[:120]
        if len(programa) < 3:
            canal().enviar_texto(tel, "¿Qué programa estudias?")
            return
        _estado(est["id"], "activo", programa=programa)
        canal().enviar_texto(tel, (
            "¡Listo, ya quedaste registrado! 🎉\n\n"
            "Ahora cárgame tu horario de cualquiera de estas formas:\n"
            "📄 Envíame el *PDF* de tu horario de matrícula\n"
            "📸 Mándame una *foto* o captura de pantalla\n"
            "✍️ O *escríbelo*, por ejemplo: _lunes y miércoles Cálculo de 8 a 10 en el 305 del bloque 2_"
        ))


def _enviar_codigo(est: dict, direccion: str, momento: datetime) -> None:
    codigo = f"{secrets.randbelow(1_000_000):06d}"
    _estado(est["id"], "esperando_codigo", correo_pendiente=direccion, otp_hash=_hash(codigo),
            otp_expira=momento + timedelta(minutes=MINUTOS_CODIGO), otp_intentos=0)
    correo.enviar_codigo(direccion, codigo)
    canal().enviar_texto(est["telefono"], (
        f"Te envié un código de 6 dígitos a *{direccion}* 📧 Escríbemelo aquí (vence en {MINUTOS_CODIGO} minutos).\n"
        "Si no te llega, revisa el spam o escribe *reenviar*. Para corregir el correo escribe *cambiar correo*."
    ))


def _verificado(est: dict, momento: datetime) -> None:
    direccion = est["correo_pendiente"]
    tel = est["telefono"]
    with db.conexion() as conn:
        otra = conn.execute("SELECT * FROM estudiantes WHERE correo = %s AND id <> %s", (direccion, est["id"])).fetchone()
        if otra:
            # CU-01 flujo 6b: el correo ya tenía cuenta con otro número; se traslada a este número
            conn.execute("DELETE FROM estudiantes WHERE id = %s", (est["id"],))
            conn.execute("UPDATE estudiantes SET telefono = %s, estado_registro = 'activo', ultimo_mensaje_at = %s "
                         "WHERE id = %s", (tel, momento, otra["id"]))
        else:
            conn.execute(
                """UPDATE estudiantes SET correo = %s, correo_pendiente = NULL, otp_hash = NULL, otp_intentos = 0,
                   estado_registro = 'esperando_nombre' WHERE id = %s""", (direccion, est["id"]))
    if otra:
        canal().enviar_texto(tel, f"✅ Verificado. Ese correo ya tenía cuenta, así que la pasé a este número. "
                                  f"¡Hola de nuevo, {(otra['nombre'] or '').split(' ')[0]}! Tu horario y recordatorios siguen aquí.")
    else:
        canal().enviar_texto(tel, "✅ ¡Correo verificado! ¿Cuál es tu nombre?")
