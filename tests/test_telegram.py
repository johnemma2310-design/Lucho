"""Canal Telegram: lectura de actualizaciones, formato y envío (sin llamar a Telegram de verdad)."""
from app import canales, recordatorios
from app.telegram import CanalTelegram, ErrorTelegram, a_html, interpretar_update
from tests.conftest import momento


def _msg(**campos):
    base = {"message_id": 7, "chat": {"id": 555, "type": "private"}, "from": {"id": 555}}
    return {"update_id": 100, "message": {**base, **campos}}


def test_interpretar_texto_y_comandos():
    m = interpretar_update(_msg(text="¿qué salón me toca?"))
    assert m["destino"] == "tg:555" and m["tipo"] == "texto" and m["id"] == "tg:100"
    assert interpretar_update(_msg(text="/start"))["texto"] == "hola"
    assert interpretar_update(_msg(text="/pendientes@LuchoBot"))["texto"] == "¿Qué tengo pendiente?"


def test_interpretar_foto_documento_y_boton():
    foto = interpretar_update(_msg(photo=[{"file_id": "chica", "file_size": 10}, {"file_id": "grande", "file_size": 900}],
                                   caption="mi horario"))
    assert foto["tipo"] == "imagen" and foto["media_id"] == "grande" and foto["texto"] == "mi horario"
    pdf = interpretar_update(_msg(document={"file_id": "doc1", "mime_type": "application/pdf"}))
    assert pdf["tipo"] == "documento" and pdf["mime"] == "application/pdf"
    img_como_archivo = interpretar_update(_msg(document={"file_id": "doc2", "mime_type": "image/png"}))
    assert img_como_archivo["tipo"] == "imagen"
    boton = interpretar_update({"update_id": 101, "callback_query": {
        "id": "cb1", "data": "btn_guardar", "message": {"message_id": 9, "chat": {"id": 555, "type": "private"}}}})
    assert boton["tipo"] == "boton" and boton["texto"] == "btn_guardar" and boton["callback_id"] == "cb1"


def test_ignora_grupos_y_otros():
    grupo = {"update_id": 1, "message": {"message_id": 1, "chat": {"id": -5, "type": "group"}, "text": "hola"}}
    assert interpretar_update(grupo) is None
    assert interpretar_update({"update_id": 2, "edited_message": {}}) is None
    assert interpretar_update(_msg(sticker={"file_id": "x"}))["tipo"] == "otro"


def test_formato_html():
    assert a_html("Tienes *Cálculo* en el _305_") == "Tienes <b>Cálculo</b> en el <i>305</i>"
    assert a_html("correo john_lopez_es@amigo.edu.co") == "correo john_lopez_es@amigo.edu.co"
    assert a_html("2 < 3 & *ok*") == "2 &lt; 3 &amp; <b>ok</b>"


class _CanalGrabador(CanalTelegram):
    def __init__(self, fallar_html=False):
        super().__init__(token="prueba")
        self.llamadas, self.fallar_html = [], fallar_html

    def api(self, metodo, espera=20, **datos):
        if self.fallar_html and datos.get("parse_mode") == "HTML":
            raise ErrorTelegram(400, "can't parse entities")
        self.llamadas.append((metodo, datos))
        return {}


def test_envio_con_botones_y_respaldo_sin_formato():
    c = _CanalGrabador()
    c.enviar_botones("tg:555", "¿Guardo tu *horario*?", [("btn_guardar", "Guardar"), ("btn_cancelar", "Cancelar")])
    metodo, datos = c.llamadas[0]
    assert metodo == "sendMessage" and datos["chat_id"] == "555" and datos["parse_mode"] == "HTML"
    assert [b["callback_data"] for b in datos["reply_markup"]["inline_keyboard"][0]] == ["btn_guardar", "btn_cancelar"]
    c2 = _CanalGrabador(fallar_html=True)
    c2.enviar_texto("tg:555", "texto *raro")
    assert c2.llamadas[0][1]["text"] == "texto *raro" and "parse_mode" not in c2.llamadas[0][1]


def test_aviso_en_telegram_no_usa_plantilla(estudiante_activo):
    c = _CanalGrabador()
    canales.usar_canal(c)
    from app import db
    db.ejecutar("UPDATE estudiantes SET telefono = 'tg:555', ultimo_mensaje_at = %s WHERE id = %s",
                (momento("2026-10-10 10:00"), estudiante_activo["id"]))
    recordatorios.crear(estudiante_activo["id"], "Parcial", "2026-10-20", "08:00", "parcial",
                        momento=momento("2026-10-07 10:00"))
    from app import programador
    assert programador.revisar(momento("2026-10-19 19:00"))["recordatorios"] == 1
    assert c.llamadas[-1][0] == "sendMessage" and "Parcial" in c.llamadas[-1][1]["text"]
