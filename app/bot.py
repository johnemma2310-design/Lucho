"""Lógica central de Lucho: decide qué hacer con cada mensaje que llega."""
import logging
from datetime import datetime

from . import db, horario, ia, recordatorios, registro
from .herramientas import DECLARACIONES, Herramientas, instruccion_sistema
from .tiempo import ahora
from .canales import canal

log = logging.getLogger("lucho.bot")

MIME_PERMITIDOS = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
TAMANO_MAXIMO = 10 * 1024 * 1024  # 10 MB
MENSAJES_HISTORIAL = 10

CONFIRMAR = {"btn_guardar", "si", "sí", "guardar", "confirmar", "confirmo", "ok", "dale", "listo", "correcto", "esta bien", "está bien"}
CANCELAR = {"btn_cancelar", "cancelar", "no", "descartar", "borrar"}
REEMPLAZAR = {"btn_reemplazar", "reemplazar", "reemplazarlo"}
AGREGAR = {"btn_agregar", "agregar", "agregarlas", "sumar"}


def procesar_mensaje(telefono: str, tipo: str, texto: str | None = None, contenido: bytes | None = None,
                     mime: str | None = None, momento: datetime | None = None) -> None:
    """Punto de entrada. tipo: 'texto', 'boton', 'imagen', 'documento' u 'otro'.
    Para 'boton', texto es el id del botón. Para imagen/documento, contenido son los bytes y texto el pie de foto."""
    momento = momento or ahora()
    est = registro.obtener_o_crear(telefono)
    db.ejecutar("UPDATE estudiantes SET ultimo_mensaje_at = %s WHERE id = %s", (momento, est["id"]))
    est["ultimo_mensaje_at"] = momento

    if est["estado_registro"] == "confirmando_eliminacion":
        _confirmar_eliminacion(est, texto or "")
        return

    if est["estado_registro"] != "activo":
        if tipo in ("imagen", "documento"):
            canal().enviar_texto(telefono, "Primero terminemos tu registro y luego me mandas el horario 😉")
        registro.procesar(est, texto or "", momento)
        return

    if tipo in ("imagen", "documento"):
        _recibir_archivo(est, contenido, mime, texto, momento)
        return
    if tipo == "otro":
        canal().enviar_texto(telefono, "Por ahora solo entiendo texto, fotos y PDF 🙈 ¿Me lo escribes?")
        return

    texto = (texto or "").strip()
    if not texto:
        return
    borrador = horario.obtener_borrador(est["id"])
    if borrador and _responder_borrador(est, borrador, texto, momento):
        return
    _conversar(est, texto, borrador, momento)


# ---------- Archivos (CU-02, CU-03, CU-09 flujo 1a) ----------

def _recibir_archivo(est: dict, contenido: bytes | None, mime: str | None, pie: str | None, momento: datetime) -> None:
    tel = est["telefono"]
    mime = (mime or "").split(";")[0].strip().lower()
    if mime not in MIME_PERMITIDOS:
        canal().enviar_texto(tel, "Ese tipo de archivo no lo puedo leer. Envíame un *PDF* o una *foto* (JPG o PNG).")
        return
    if not contenido or len(contenido) > TAMANO_MAXIMO:
        canal().enviar_texto(tel, "El archivo pesa más de 10 MB. ¿Me mandas una versión más liviana o una foto?")
        return
    canal().enviar_texto(tel, "📖 Dame un momento, estoy leyendo tu archivo…")
    unir = horario.obtener_borrador(est["id"]) is not None
    procesar_extraccion(est, contenido=contenido, mime=mime, texto=pie, momento=momento, unir=unir)


def procesar_extraccion(est: dict, contenido: bytes | None = None, mime: str | None = None, texto: str | None = None,
                        momento: datetime | None = None, unir: bool = False, enviar: bool = True) -> dict:
    """Envía el contenido a la IA, valida lo que devuelve y deja un borrador para confirmar.
    Con enviar=True le muestra el resultado al estudiante. Los archivos no se guardan (RN-09)."""
    momento = momento or ahora()
    tel = est["telefono"]

    def fallo(mensaje: str) -> dict:
        if enviar:
            canal().enviar_texto(tel, mensaje)
        return {"ok": False, "error": mensaje}

    try:
        datos = ia.extraer(contenido=contenido, mime=mime, texto=texto, hoy=momento.date().isoformat())
    except Exception:
        log.exception("Error extrayendo con la IA")
        return fallo("Tuve un problema leyendo eso 😓 Inténtalo de nuevo en un momento.")
    return _borrador_desde_extraccion(est, datos, momento, unir, enviar, fallo)


def _borrador_desde_extraccion(est, datos, momento, unir, enviar, fallo) -> dict:
    tipo = datos.get("tipo_documento")
    if tipo == "otro" or (not datos.get("clases") and not datos.get("evaluaciones")):
        if datos.get("confianza") == "baja":
            return fallo("No logro leer bien la imagen 🧐 Prueba con una foto de frente, con buena luz y que se vea "
                         "el horario completo. También me puedes mandar el PDF.")
        return fallo("No encontré un horario ni fechas de evaluaciones ahí. ¿Me envías el PDF de tu horario de "
                     "matrícula, una foto o me lo escribes?")
    if tipo == "evaluaciones":
        validas, problemas = horario.validar_evaluaciones(datos.get("evaluaciones"), momento.date())
        if not validas:
            return fallo("Encontré fechas, pero todas ya pasaron o no las entendí. ¿Me las escribes?")
        borrador = {"tipo": "evaluaciones", "evaluaciones": validas, "problemas": problemas}
    else:
        validas, problemas = horario.validar_clases(datos.get("clases"))
        if not validas:
            return fallo("Vi algo parecido a un horario pero no pude sacar las clases 😕 ¿Me mandas una foto más "
                         "nítida o me lo escribes?")
        if datos.get("confianza") == "baja":
            problemas.append("La imagen no se veía muy clara; revisa bien antes de guardar.")
        borrador = {"tipo": "horario", "clases": validas, "problemas": problemas}
    borrador = horario.guardar_borrador(est["id"], borrador, unir=unir)
    if enviar:
        mostrar_borrador(est, borrador)
    return {"ok": True, "borrador": borrador}


def mostrar_borrador(est: dict, borrador: dict) -> None:
    tel = est["telefono"]
    canal().enviar_texto(tel, horario.resumen_borrador(borrador))
    extra = " Si tu horario tiene más fotos, envíalas y las uno." if borrador["tipo"] == "horario" else ""
    canal().enviar_botones(
        tel,
        f"¿Está bien así? Si algo falla, escríbeme la corrección (ej.: _el viernes es en el 210_).{extra}",
        [("btn_guardar", "✅ Guardar"), ("btn_cancelar", "❌ Cancelar")],
    )


# ---------- Confirmación del borrador (CU-05) ----------

def _responder_borrador(est: dict, borrador: dict, texto: str, momento: datetime) -> bool:
    """Devuelve True si el mensaje se usó para confirmar o cancelar el borrador."""
    t = texto.lower().strip().rstrip(".!")
    tel = est["telefono"]
    if t in CANCELAR:
        horario.descartar_borrador(est["id"])
        canal().enviar_texto(tel, "Listo, lo descarté. Cuando quieras me mandas el PDF, una foto o me lo escribes.")
        return True

    if borrador["tipo"] == "evaluaciones" and t in CONFIRMAR:
        creados = []
        for e in borrador["evaluaciones"]:
            r = recordatorios.crear(est["id"], e["titulo"], e["fecha"], e.get("hora"), e["tipo"], e.get("materia"),
                                    momento=momento)
            if "id" in r:
                creados.append(r)
        horario.descartar_borrador(est["id"])
        canal().enviar_texto(tel, f"✅ Guardé {len(creados)} recordatorio(s). Te aviso el día anterior a las 7:00 p. m. "
                                  "y el mismo día. Escribe *pendientes* para verlos.")
        return True

    if borrador["tipo"] == "horario":
        existentes = horario.contar_clases(est["id"])
        if t in CONFIRMAR and existentes:
            canal().enviar_botones(tel, f"Ya tenías {existentes} clases guardadas. ¿Reemplazo tu horario o agrego estas clases?",
                                   [("btn_reemplazar", "Reemplazar"), ("btn_agregar", "Agregar"),
                                    ("btn_cancelar", "Cancelar")])
            return True
        if t in CONFIRMAR or t in REEMPLAZAR or t in AGREGAR:
            n = horario.confirmar_horario(est["id"], borrador["clases"], reemplazar=t not in AGREGAR)
            canal().enviar_texto(tel, (
                f"✅ ¡Guardé tu horario con {n} clases!\n\n"
                "Ya me puedes preguntar cosas como:\n• _¿Qué salón me toca?_\n• _¿Qué tengo mañana?_\n"
                "• _El parcial de cálculo es el 20, recuérdamelo_\n\n"
                "Te mandaré un resumen cada mañana a las 6:00 a. m. Si quieres que te avise antes de cada clase, "
                "escribe _avísame 15 minutos antes de clase_."
            ))
            return True
    return False


# ---------- Conversación con IA ----------

def _conversar(est: dict, texto: str, borrador: dict | None, momento: datetime) -> None:
    tel = est["telefono"]
    herramientas = Herramientas(est, momento)
    declaraciones = list(DECLARACIONES)
    sistema = instruccion_sistema(est, momento)
    if borrador:
        declaraciones.append(DECLARACION_CORREGIR)
        sistema += ("\n\nHay un borrador de horario o fechas sin confirmar:\n" + horario.resumen_borrador(borrador) +
                    "\nSi el mensaje corrige ese borrador, usa corregir_borrador. Recuérdale que debe tocar Guardar.")
        herramientas._corregir_borrador = lambda instruccion: _corregir(est, borrador, instruccion, momento, herramientas)

    historial = [
        {"rol": f["rol"], "contenido": f["contenido"]}
        for f in reversed(db.varios(
            """SELECT rol, contenido FROM mensajes WHERE estudiante_id = %s AND creado_at > now() - interval '2 days'
               ORDER BY creado_at DESC LIMIT %s""", (est["id"], MENSAJES_HISTORIAL)))
    ]
    # La IA exige que la conversación empiece con el estudiante
    while historial and historial[0]["rol"] != "user":
        historial.pop(0)
    try:
        respuesta = ia.conversar(sistema, historial, texto, declaraciones, herramientas.ejecutar)
    except Exception:
        log.exception("Error conversando con la IA")
        canal().enviar_texto(tel, "Uy, se me enredaron los cables 🤖 Intenta de nuevo en un momento.")
        return

    with db.conexion() as conn:
        conn.execute("INSERT INTO mensajes (estudiante_id, rol, contenido) VALUES (%s, 'user', %s)", (est["id"], texto))
        if respuesta:
            conn.execute("INSERT INTO mensajes (estudiante_id, rol, contenido) VALUES (%s, 'model', %s)",
                         (est["id"], respuesta))

    if herramientas.borrador_creado:
        mostrar_borrador(est, horario.obtener_borrador(est["id"]))
    elif respuesta:
        canal().enviar_texto(tel, respuesta)


DECLARACION_CORREGIR = {
    "name": "corregir_borrador",
    "description": "Aplica al borrador pendiente la corrección que pide el estudiante (salón, hora, día, materia, quitar o agregar algo).",
    "parameters": {"type": "object", "properties": {"instruccion": {"type": "string"}}, "required": ["instruccion"]},
}


def _corregir(est, borrador, instruccion, momento, herramientas):
    try:
        datos = ia.corregir(borrador, instruccion, momento.date().isoformat())
    except Exception as e:
        return {"error": str(e)}
    resultado = _borrador_desde_extraccion(est, datos, momento, unir=False, enviar=False,
                                           fallo=lambda m: {"ok": False, "error": m})
    if resultado.get("ok"):
        herramientas.borrador_creado = True
        return "Borrador corregido. Lucho mostrará el nuevo resumen; no lo repitas."
    return resultado


# ---------- Eliminación de cuenta (CU-16) ----------

def _confirmar_eliminacion(est: dict, texto: str) -> None:
    if texto.strip() == "ELIMINAR":
        db.ejecutar("DELETE FROM estudiantes WHERE id = %s", (est["id"],))
        canal().enviar_texto(est["telefono"], "Listo. Borré tu cuenta, tu horario y tus recordatorios. "
                                              "¡Éxitos en todo! Si algún día vuelves, solo escríbeme. 👋")
    else:
        db.ejecutar("UPDATE estudiantes SET estado_registro = 'activo' WHERE id = %s", (est["id"],))
        canal().enviar_texto(est["telefono"], "Ok, no borré nada. Sigo aquí para ayudarte 🙂")
