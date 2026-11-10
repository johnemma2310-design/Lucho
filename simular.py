"""Simulador de consola: prueba a Lucho sin WhatsApp (sí necesita la base de datos y la clave de la IA: Gemini o Claude).

Uso:  python simular.py [telefono]

Comandos dentro del simulador:
  /pdf ruta/al/horario.pdf     envía un PDF
  /foto ruta/a/la/foto.jpg     envía una imagen
  /boton btn_guardar           toca un botón (btn_acepto, btn_guardar, btn_cancelar, btn_reemplazar, btn_agregar)
  /hora 2026-10-08 07:50       finge que es esa fecha y hora (para probar avisos)
  /revisar                     ejecuta el programador de avisos en la hora actual o fingida
  /salir
Cualquier otro texto se envía como mensaje normal.
"""
import mimetypes
import sys
from datetime import datetime

from app import bot, programador
from app.tiempo import ahora, zona
from app.canales import usar_canal


class CanalConsola:
    def enviar_texto(self, telefono, texto):
        print(f"\n🤖 Lucho → {telefono}:\n{texto}\n")

    def enviar_botones(self, telefono, texto, botones):
        print(f"\n🤖 Lucho → {telefono}:\n{texto}")
        print("   " + "  ".join(f"[{titulo} = /boton {bid}]" for bid, titulo in botones) + "\n")

    def enviar_plantilla(self, telefono, parametro):
        print(f"\n📨 (plantilla) Lucho → {telefono}:\n{parametro}\n")

    def descargar_media(self, media_id):
        raise NotImplementedError


def main():
    telefono = sys.argv[1] if len(sys.argv) > 1 else "573000000000"
    usar_canal(CanalConsola())
    momento_fijo = None
    print(f"Simulador de Lucho. Escribes como el número {telefono}. /salir para terminar.\n")
    while True:
        try:
            linea = input("👤 Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not linea:
            continue
        momento = momento_fijo or ahora()
        if linea == "/salir":
            break
        if linea.startswith("/hora "):
            momento_fijo = datetime.strptime(linea[6:].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=zona())
            print(f"   (ahora es {momento_fijo})")
        elif linea == "/revisar":
            print("   Enviados:", programador.revisar(momento))
        elif linea.startswith("/boton "):
            bot.procesar_mensaje(telefono, "boton", linea[7:].strip(), momento=momento)
        elif linea.startswith(("/pdf ", "/foto ")):
            ruta = linea.split(" ", 1)[1].strip()
            mime = mimetypes.guess_type(ruta)[0] or "application/octet-stream"
            with open(ruta, "rb") as f:
                contenido = f.read()
            tipo = "documento" if linea.startswith("/pdf") else "imagen"
            bot.procesar_mensaje(telefono, tipo, None, contenido, mime, momento=momento)
        else:
            bot.procesar_mensaje(telefono, "texto", linea, momento=momento)


if __name__ == "__main__":
    main()
