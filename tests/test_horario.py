"""CU-02 a CU-08: carga de horario por archivo o texto, confirmación y consultas."""
from app import bot, db, horario, ia
from app.herramientas import Herramientas
from tests.conftest import CLASES_EJEMPLO, momento


def _extraccion(clases=None, evaluaciones=None, tipo="horario", confianza="alta"):
    return {"tipo_documento": tipo, "confianza": confianza, "clases": clases or [], "evaluaciones": evaluaciones or []}


def test_validacion_de_clases():
    validas, problemas = horario.validar_clases(CLASES_EJEMPLO + [
        {"materia": "Física", "dia_semana": 9, "hora_inicio": "08:00", "hora_fin": "10:00"},
        {"materia": "Química", "dia_semana": 2, "hora_inicio": "10:00", "hora_fin": "08:00"},
        CLASES_EJEMPLO[0],  # duplicada
    ])
    assert len(validas) == 4
    assert len(problemas) == 2
    assert validas[0]["materia"] == "Cálculo Diferencial" and validas[0]["dia_semana"] == 1
    assert next(c for c in validas if c["materia"] == "Inglés III")["salon"] is None  # no tenía salón


def test_cruces():
    clases, _ = horario.validar_clases(CLASES_EJEMPLO + [
        {"materia": "Ética", "dia_semana": 1, "hora_inicio": "09:00", "hora_fin": "11:00"}])
    pares = horario.cruces(clases)
    assert {(a["materia"], b["materia"]) for a, b in pares} == {("Cálculo Diferencial", "Ética"), ("Ética", "Bases de Datos")}


def test_cargar_pdf_confirmar_y_reemplazar(canal, estudiante_activo, monkeypatch):
    monkeypatch.setattr(ia, "extraer", lambda **kw: _extraccion(CLASES_EJEMPLO))
    tel = estudiante_activo["telefono"]
    bot.procesar_mensaje(tel, "documento", None, b"%PDF", "application/pdf", momento=momento("2026-10-07 10:00"))
    textos = canal.textos()
    assert "leyendo" in textos and "*Lunes*" in textos and "salón por confirmar" in textos
    assert canal.ultimo()[3] == ["btn_guardar", "btn_cancelar"]
    assert horario.contar_clases(estudiante_activo["id"]) == 0  # nada se guarda sin confirmar (RN-03)

    bot.procesar_mensaje(tel, "boton", "btn_guardar")
    assert horario.contar_clases(estudiante_activo["id"]) == 4
    assert "Guardé tu horario con 4 clases" in canal.ultimo()[2]

    # Segundo horario: pregunta si reemplazar o agregar
    monkeypatch.setattr(ia, "extraer", lambda **kw: _extraccion(CLASES_EJEMPLO[:1]))
    bot.procesar_mensaje(tel, "imagen", None, b"jpg", "image/jpeg")
    bot.procesar_mensaje(tel, "texto", "sí")
    assert canal.ultimo()[3] == ["btn_reemplazar", "btn_agregar", "btn_cancelar"]
    bot.procesar_mensaje(tel, "boton", "btn_reemplazar")
    assert horario.contar_clases(estudiante_activo["id"]) == 1


def test_varias_fotos_se_unen(canal, estudiante_activo, monkeypatch):
    tel = estudiante_activo["telefono"]
    monkeypatch.setattr(ia, "extraer", lambda **kw: _extraccion(CLASES_EJEMPLO[:2]))
    bot.procesar_mensaje(tel, "imagen", None, b"1", "image/png")
    monkeypatch.setattr(ia, "extraer", lambda **kw: _extraccion(CLASES_EJEMPLO[1:]))
    bot.procesar_mensaje(tel, "imagen", None, b"2", "image/png")
    assert len(horario.obtener_borrador(estudiante_activo["id"])["clases"]) == 4


def test_archivo_invalido_o_ilegible(canal, estudiante_activo, monkeypatch):
    tel = estudiante_activo["telefono"]
    bot.procesar_mensaje(tel, "documento", None, b"x", "application/zip")
    assert "no lo puedo leer" in canal.ultimo()[2]
    monkeypatch.setattr(ia, "extraer", lambda **kw: _extraccion(tipo="otro", confianza="baja"))
    bot.procesar_mensaje(tel, "imagen", None, b"x", "image/jpeg")
    assert "buena luz" in canal.ultimo()[2]


def test_cancelar_borrador(canal, estudiante_activo, monkeypatch):
    monkeypatch.setattr(ia, "extraer", lambda **kw: _extraccion(CLASES_EJEMPLO))
    tel = estudiante_activo["telefono"]
    bot.procesar_mensaje(tel, "imagen", None, b"x", "image/jpeg")
    bot.procesar_mensaje(tel, "boton", "btn_cancelar")
    assert horario.obtener_borrador(estudiante_activo["id"]) is None
    assert horario.contar_clases(estudiante_activo["id"]) == 0


def test_cargar_por_texto_via_ia(canal, estudiante_activo, monkeypatch):
    """CU-04: la IA llama cargar_horario_texto y el bot muestra el borrador con botones."""
    monkeypatch.setattr(ia, "extraer", lambda **kw: _extraccion(CLASES_EJEMPLO[:2]))

    def conversar_falso(sistema, historial, mensaje, declaraciones, ejecutar):
        ejecutar("cargar_horario_texto", {"texto": mensaje})
        return "Listo"
    monkeypatch.setattr(ia, "conversar", conversar_falso)
    bot.procesar_mensaje(estudiante_activo["telefono"], "texto", "lunes y miércoles cálculo de 8 a 10 en el 305 bloque 2")
    assert canal.ultimo()[3] == ["btn_guardar", "btn_cancelar"]
    assert "Cálculo Diferencial" in canal.enviados[-2][2]


def test_corregir_borrador_via_ia(canal, estudiante_activo, monkeypatch):
    """CU-05 flujo 3a."""
    monkeypatch.setattr(ia, "extraer", lambda **kw: _extraccion(CLASES_EJEMPLO))
    tel = estudiante_activo["telefono"]
    bot.procesar_mensaje(tel, "imagen", None, b"x", "image/jpeg")
    corregidas = [dict(c) for c in CLASES_EJEMPLO]
    corregidas[3]["salon"] = "210"
    monkeypatch.setattr(ia, "corregir", lambda borrador, instruccion, hoy: _extraccion(corregidas))

    def conversar_falso(sistema, historial, mensaje, declaraciones, ejecutar):
        assert "corregir_borrador" in [d["name"] for d in declaraciones]
        ejecutar("corregir_borrador", {"instruccion": mensaje})
        return ""
    monkeypatch.setattr(ia, "conversar", conversar_falso)
    bot.procesar_mensaje(tel, "texto", "inglés es en el 210")
    assert "salón 210" in canal.enviados[-2][2]


def _guardar_clases(est_id):
    clases, _ = horario.validar_clases(CLASES_EJEMPLO)
    horario.confirmar_horario(est_id, clases, reemplazar=True)


def test_clase_actual(estudiante_activo):
    eid = estudiante_activo["id"]
    assert horario.clase_actual(eid).startswith("SIN_HORARIO")
    _guardar_clases(eid)
    # Lunes 5 de octubre de 2026
    r = horario.clase_actual(eid, momento("2026-10-05 07:45"))
    assert "PRÓXIMA HOY" in r and "Cálculo" in r and "15 minutos" in r
    r = horario.clase_actual(eid, momento("2026-10-05 10:30"))
    assert "EN CURSO" in r and "Bases de Datos" in r and "salón 402" in r
    r = horario.clase_actual(eid, momento("2026-10-05 13:00"))
    assert "martes 6 de octubre" in r and "Inglés" in r
    # Lunes 12 de octubre es festivo: salta al martes 13
    r = horario.clase_actual(eid, momento("2026-10-12 07:00"))
    assert "Día de la Raza" in r and "martes 13 de octubre" in r


def test_horario_rango_y_materia(estudiante_activo):
    eid = estudiante_activo["id"]
    _guardar_clases(eid)
    h = Herramientas(estudiante_activo, momento("2026-10-04 20:00"))
    texto = h.ejecutar("consultar_horario", {"desde": "2026-10-05", "hasta": "2026-10-07"})
    assert "LUNES 5 DE OCTUBRE" in texto and "MIÉRCOLES 7 DE OCTUBRE" in texto
    assert "calculo" in horario.normalizar(h.ejecutar("buscar_materia", {"materia": "calculo"}))


def test_modificar_y_eliminar_clase(estudiante_activo):
    eid = estudiante_activo["id"]
    _guardar_clases(eid)
    h = Herramientas(estudiante_activo)
    r = h.ejecutar("modificar_clase", {"materia": "bases de datos", "nuevo_salon": "410"})
    assert "salón 410" in r
    r = h.ejecutar("modificar_clase", {"materia": "cálculo", "nuevo_dia_semana": 5})
    assert "error" in r  # se ve dos días, hay que precisar
    r = h.ejecutar("modificar_clase", {"materia": "cálculo", "dia_semana": 3, "nuevo_dia_semana": 5})
    assert "Viernes" in r
    assert "Eliminadas 1" in h.ejecutar("eliminar_clase", {"materia": "ingles"})
    assert horario.contar_clases(eid) == 3
    r = h.ejecutar("agregar_clase", {"materia": "Ética", "dia_semana": 1, "hora_inicio": "09:00", "hora_fin": "11:00"})
    assert "se cruza" in r


def test_preferencias(estudiante_activo):
    h = Herramientas(estudiante_activo)
    assert "error" in h.ejecutar("configurar_preferencias", {"minutos_aviso_clase": 300})
    r = h.ejecutar("configurar_preferencias", {"aviso_clase": True, "minutos_aviso_clase": 20, "hora_resumen": "05:30"})
    assert r["aviso_antes_de_clase"] == "20 minutos antes"
    assert "5:30 a. m." in r["resumen_diario"]


def test_info_universidad(estudiante_activo):
    db.ejecutar("INSERT INTO documentos_fragmentos (documento, contenido) VALUES (%s, %s)",
                ("Calendario académico 2026-2", "La fecha límite para cancelación de asignaturas es el 30 de octubre de 2026."))
    h = Herramientas(estudiante_activo)
    r = h.ejecutar("buscar_info_universidad", {"consulta": "cuándo puedo cancelar materias"})
    assert isinstance(r, list) and "30 de octubre" in r[0]["fragmento"]
    assert h.ejecutar("buscar_info_universidad", {"consulta": "parqueadero motos"}).startswith("SIN_INFORMACION")


def test_eliminar_cuenta(canal, estudiante_activo):
    h = Herramientas(estudiante_activo)
    h.ejecutar("solicitar_eliminar_cuenta", {})
    bot.procesar_mensaje(estudiante_activo["telefono"], "texto", "ELIMINAR")
    assert db.uno("SELECT count(*) AS n FROM estudiantes")["n"] == 0


def test_eliminar_cuenta_cancelada(canal, estudiante_activo):
    Herramientas(estudiante_activo).ejecutar("solicitar_eliminar_cuenta", {})
    bot.procesar_mensaje(estudiante_activo["telefono"], "texto", "mejor no")
    assert db.uno("SELECT estado_registro FROM estudiantes")["estado_registro"] == "activo"
