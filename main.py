import cv2
import numpy as np
import mediapipe as mp
import os
import random
from datetime import datetime
import requests
import qrcode
import threading
import webbrowser
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTERFACES_DIR = os.path.join(BASE_DIR, "interfaces")
CAPTURAS_DIR = os.path.join(BASE_DIR, "capturas")

MENU_IMG_PATH = os.path.join(INTERFACES_DIR, "MENU.png")
LIBRE_IMG_PATH = os.path.join(INTERFACES_DIR, "MODO LIBRE.png")
MANUAL_IMG_PATH = os.path.join(INTERFACES_DIR, "MANUAL DE INSTRUCCIONES.png")
MEMORIA_IMG_PATH = os.path.join(INTERFACES_DIR, "MODO MEMORIA.png")
FIGURA_IMG_PATH = os.path.join(INTERFACES_DIR, "FIGURA.png")
MANUAL_VISTO_PATH = os.path.join(BASE_DIR, "manual_visto.txt")

WINDOW_NAME = "Air Draw"
CAM_X = 106
CAM_Y = 180
CAM_W = 1743
CAM_H = 810

# Icono de ayuda (esquina superior derecha) -> click abre el manual
HELP_ICON_X = 1726
HELP_ICON_Y = 21
HELP_ICON_W = 172
HELP_ICON_H = 139

# Recuadro donde va la figura a memorizar, dentro de FIGURA.png
FIG_X = 516
FIG_Y = 277
FIG_W = 888
FIG_H = 674

TIEMPO_FIGURA_SEGUNDOS = 3


DRAW_THICKNESS = 10
POINTER_RADIUS = 18

COLORES = [
    (0, 0, 255),       # Rojo
    (0, 255, 0),       # Verde
    (255, 0, 0),       # Azul
    (0, 255, 255),     # Amarillo
    (203, 192, 255),   # Rosado
    (0, 165, 255),     # Naranja
    (255, 0, 255),     # Morado
    (255, 255, 0)      # Celeste
]

NOMBRES_COLORES = [
    "ROJO", "VERDE", "AZUL", "AMARILLO",
    "ROSADO", "NARANJA", "MORADO", "CELESTE"
]

color_actual = 0
DRAW_COLOR = COLORES[color_actual]

TOOLBAR_X = CAM_W - 170   # esquina superior derecha del recuadro
TOOLBAR_Y = 20
SWATCH = 70
GAP = 10

BOTONES = []

# 8 colores en grilla de 2 columnas x 4 filas
for i in range(len(COLORES)):
    col = i % 2
    fila = i // 2
    BOTONES.append({
        "tipo": "color",
        "valor": i,
        "rect": (
            TOOLBAR_X + col * (SWATCH + GAP),
            TOOLBAR_Y + fila * (SWATCH + GAP),
            SWATCH, SWATCH
        )
    })

_y_tras_colores = TOOLBAR_Y + 4 * (SWATCH + GAP)
_ancho_boton = 2 * SWATCH + GAP

BOTONES.append({
    "tipo": "borrador",
    "rect": (TOOLBAR_X, _y_tras_colores + GAP, _ancho_boton, 60)
})
BOTONES.append({
    "tipo": "vaciar",
    "rect": (TOOLBAR_X, _y_tras_colores + GAP + 70, _ancho_boton, 60)
})
BOTONES.append({
    "tipo": "guardar",
    "rect": (TOOLBAR_X, _y_tras_colores + GAP + 140, _ancho_boton, 60)
})


TOOLBAR_RECT = (
    TOOLBAR_X - GAP,
    TOOLBAR_Y - GAP,
    _ancho_boton + GAP * 2,
    (_y_tras_colores + GAP + 140 + 60) - TOOLBAR_Y + GAP * 2
)


def _rect_a_global(rect):
    """Convierte un rect en coordenadas LOCALES del recuadro de
    camara a coordenadas GLOBALES de toda la pantalla (sumando
    el offset CAM_X, CAM_Y donde se pega la camara)."""
    x, y, w, h = rect
    return (x + CAM_X, y + CAM_Y, w, h)



for _boton in BOTONES:
    _boton["rect_global"] = _rect_a_global(_boton["rect"])

TOOLBAR_RECT_GLOBAL = _rect_a_global(TOOLBAR_RECT)

UMBRAL_COLOR = 10     # cuadros para seleccionar un color (rapido)
UMBRAL_ACCION = 20    # cuadros para borrador/vaciar/guardar (mas lento)

boton_hover_actual = -1
boton_hover_frames = 0


STATE_MENU = "menu"
STATE_LIBRE = "libre"
STATE_MEMORIA_FIGURA = "memoria_figura"   # se muestra la figura a memorizar
STATE_MEMORIA_DIBUJO = "memoria_dibujo"   # camara, para dibujarla de memoria


mostrando_manual = False

# popup de analisis (solo en Modo Memoria, al presionar Enter)
mostrando_analisis = False
analisis_porcentaje = 0


manual_visto = os.path.exists(MANUAL_VISTO_PATH)


def cargar_imagen(path):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"No se encontro la imagen: {path}")
    return img


menu_img = cargar_imagen(MENU_IMG_PATH)
libre_img_base = cargar_imagen(LIBRE_IMG_PATH)
manual_img = cargar_imagen(MANUAL_IMG_PATH)
memoria_img_base = cargar_imagen(MEMORIA_IMG_PATH)
figura_img_base = cargar_imagen(FIGURA_IMG_PATH)

ALTO, ANCHO = libre_img_base.shape[:2]

canvas = np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)

# figura actual a memorizar (se elige al entrar a Modo Memoria)
figura_actual_nombre = None
figura_actual_img = None
figura_hasta = 0  # tick de reloj hasta el cual se muestra la figura



mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    max_num_hands=1,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)

prev_point = None
ultimo_gesto = 0
borrador_activo = False


cursor_global = None
hover_frames = 0
HOVER_FRAMES_PARA_ABRIR = 18  # cuadros sosteniendo el dedo sobre el icono

# mensaje temporal (ej: "Dibujo guardado") con su tiempo de expiracion
mensaje_temporal = ""
mensaje_hasta = 0
mostrando_guardado = False
mostrando_qr = False
qr_imagen = None
qr_url = ""
ultima_foto = None
lienzo_guardado = None
foto_guardada = None
qr_mensaje = ""


def distancia(p1, p2):
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def redimensionar_a_pantalla(img):
    if img.shape[:2] != (ALTO, ANCHO):
        return cv2.resize(img, (ANCHO, ALTO))
    return img


def contar_dedos(lm):
    dedos = 0
    if lm[8].y < lm[6].y:
        dedos += 1   # indice
    if lm[12].y < lm[10].y:
        dedos += 1   # medio
    if lm[16].y < lm[14].y:
        dedos += 1   # anular
    if lm[20].y < lm[18].y:
        dedos += 1   # menique
    return dedos


def cambiar_color():
    global color_actual, DRAW_COLOR
    color_actual += 1
    if color_actual >= len(COLORES):
        color_actual = 0
    DRAW_COLOR = COLORES[color_actual]


def mostrar_informacion(frame):
    cv2.rectangle(frame, (20, 20), (400, 110), (0, 0, 0), -1)

    cv2.rectangle(frame, (35, 35), (85, 85), DRAW_COLOR, -1)
    cv2.putText(
        frame, "COLOR: " + NOMBRES_COLORES[color_actual],
        (100, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
        (255, 255, 255), 2, cv2.LINE_AA
    )

    if borrador_activo:
        cv2.putText(
            frame, "BORRADOR ACTIVADO",
            (100, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (255, 255, 255), 2, cv2.LINE_AA
        )


def guardar_dibujo():
    global mensaje_temporal, mensaje_hasta
    global mostrando_guardado, lienzo_guardado, foto_guardada

    os.makedirs(CAPTURAS_DIR, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    nombre_lienzo = "lienzo_" + marca + ".png"
    ruta_lienzo = os.path.join(CAPTURAS_DIR, nombre_lienzo)
    lienzo_guardado = canvas.copy()
    cv2.imwrite(ruta_lienzo, lienzo_guardado)

    if ultima_foto is not None:
        nombre_foto = "foto_" + marca + ".jpg"
        ruta_foto = os.path.join(CAPTURAS_DIR, nombre_foto)
        foto_guardada = ultima_foto.copy()
        cv2.imwrite(ruta_foto, foto_guardada)
    else:
        foto_guardada = None

    mensaje_temporal = "Guardado: lienzo y foto"
    mensaje_hasta = cv2.getTickCount() + int(2.5 * cv2.getTickFrequency())
    mostrando_guardado = True
    return ruta_lienzo


def subir_imagen_y_generar_qr(imagen, tipo):
    global qr_imagen, qr_url, qr_mensaje, mostrando_qr

    if imagen is None:
        qr_mensaje = "No hay imagen disponible"
        mostrando_qr = True
        return

    os.makedirs(CAPTURAS_DIR, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    extension = ".jpg" if tipo == "foto" else ".png"
    nombre = tipo + "_qr_" + marca + extension
    ruta = os.path.join(CAPTURAS_DIR, nombre)

    if tipo == "foto":
        cv2.imwrite(ruta, imagen, [cv2.IMWRITE_JPEG_QUALITY, 95])
        mime = "image/jpeg"
    else:
        cv2.imwrite(ruta, imagen)
        mime = "image/png"

    try:
        with open(ruta, "rb") as archivo:
            respuesta = requests.post(
                "https://tempfile.org/api/upload/local",
                files={"files": (nombre, archivo, mime)},
                data={"expiryHours": "24"},
                timeout=60
            )

        if respuesta.status_code != 200:
            raise Exception(f"Error HTTP {respuesta.status_code}")

        datos = respuesta.json()

        if not datos.get("success"):
            raise Exception(datos.get("error", "No se pudo subir la imagen"))

        archivos = datos.get("files", [])
        if not archivos:
            raise Exception("TempFile no devolvio el archivo subido")

        archivo_temp = archivos[0]
        file_id = archivo_temp.get("id", "")
        pagina_url = archivo_temp.get("url", "")

        if file_id:
            url_publica = f"https://tempfile.org/{file_id}/download"
        elif pagina_url:
            url_publica = pagina_url
        else:
            raise Exception("No se recibio un enlace de descarga")

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=12,
            border=4
        )
        qr.add_data(url_publica)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_imagen = cv2.cvtColor(np.array(qr_img), cv2.COLOR_RGB2BGR)
        qr_url = url_publica
        qr_mensaje = "Escanea el QR para descargar la imagen"
        mostrando_qr = True

    except requests.exceptions.RequestException as e:
        qr_mensaje = "Error de conexion con TempFile"
        qr_url = ""
        qr_imagen = None
        mostrando_qr = True
        print("Error TempFile:", e)
    except Exception as e:
        qr_mensaje = "Error al subir: " + str(e)
        qr_url = ""
        qr_imagen = None
        mostrando_qr = True
        print("Error TempFile:", e)

def dibujar_popup_guardado(frame_base):
    overlay = frame_base.copy()
    oscuro = np.zeros_like(overlay)
    cv2.addWeighted(oscuro, 0.65, overlay, 0.35, 0, overlay)

    popup_w = 850
    popup_h = 500
    x0 = (ANCHO - popup_w) // 2
    y0 = (ALTO - popup_h) // 2

    cv2.rectangle(overlay, (x0, y0), (x0 + popup_w, y0 + popup_h), (255, 255, 255), -1)
    cv2.rectangle(overlay, (x0, y0), (x0 + popup_w, y0 + popup_h), (0, 0, 0), 4)

    cv2.putText(overlay, "DIBUJO GUARDADO", (x0 + 185, y0 + 75),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(overlay, "QUE QUIERES COMPARTIR?", (x0 + 190, y0 + 135),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)

    bx1, by = x0 + 100, y0 + 190
    bx2 = x0 + 470
    bw, bh = 270, 120

    cv2.rectangle(overlay, (bx1, by), (bx1 + bw, by + bh), (40, 40, 40), -1)
    cv2.rectangle(overlay, (bx2, by), (bx2 + bw, by + bh), (40, 40, 40), -1)

    cv2.putText(overlay, "LIENZO", (bx1 + 65, by + 72),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(overlay, "FOTO", (bx2 + 90, by + 72),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3, cv2.LINE_AA)

    cv2.putText(overlay, "L = Lienzo    F = Foto    ESC = Cerrar",
                (x0 + 150, y0 + 390), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 0), 2, cv2.LINE_AA)

    return overlay


def dibujar_popup_qr(frame_base):
    overlay = frame_base.copy()
    oscuro = np.zeros_like(overlay)
    cv2.addWeighted(oscuro, 0.70, overlay, 0.30, 0, overlay)

    popup_w = 900
    popup_h = 850
    x0 = (ANCHO - popup_w) // 2
    y0 = (ALTO - popup_h) // 2

    cv2.rectangle(overlay, (x0, y0), (x0 + popup_w, y0 + popup_h), (255, 255, 255), -1)
    cv2.rectangle(overlay, (x0, y0), (x0 + popup_w, y0 + popup_h), (0, 0, 0), 4)

    cv2.putText(overlay, "ESCANEA EL QR", (x0 + 270, y0 + 65),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3, cv2.LINE_AA)

    if qr_imagen is not None:
        max_qr = 650
        qr = cv2.resize(qr_imagen, (max_qr, max_qr), interpolation=cv2.INTER_NEAREST)
        qx = x0 + (popup_w - max_qr) // 2
        qy = y0 + 95
        overlay[qy:qy + max_qr, qx:qx + max_qr] = qr

    cv2.putText(overlay, qr_mensaje, (x0 + 205, y0 + 785),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(overlay, "ESC = cerrar", (x0 + 365, y0 + 820),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2, cv2.LINE_AA)

    return overlay


def calcular_similitud():
    """Compara la silueta de lo dibujado (canvas) contra la
    silueta de la figura original, y devuelve un porcentaje de
    parecido (0-100). Se dilatan ambas mascaras un poco para
    tolerar que el trazo a mano no caiga pixel-perfecto sobre
    la linea original."""
    kernel = np.ones((25, 25), np.uint8)

    gris_dibujo = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    _, mask_dibujo = cv2.threshold(gris_dibujo, 10, 255, cv2.THRESH_BINARY)
    mask_dibujo = cv2.dilate(mask_dibujo, kernel)

    figura_redim = cv2.resize(figura_actual_img, (CAM_W, CAM_H))
    gris_figura = cv2.cvtColor(figura_redim, cv2.COLOR_BGR2GRAY)
    _, mask_figura = cv2.threshold(gris_figura, 10, 255, cv2.THRESH_BINARY)
    mask_figura = cv2.dilate(mask_figura, kernel)

    interseccion = cv2.countNonZero(cv2.bitwise_and(mask_dibujo, mask_figura))
    union = cv2.countNonZero(cv2.bitwise_or(mask_dibujo, mask_figura))

    if union == 0:
        return 0
    return int((interseccion / union) * 100)


def dibujar_popup_analisis(frame_base, porcentaje):
    """Ventana emergente con el resultado del analisis."""
    overlay = frame_base.copy()

    fondo_oscuro = np.zeros_like(overlay)
    cv2.addWeighted(fondo_oscuro, 0.6, overlay, 0.4, 0, overlay)

    popup_w = int(ANCHO * 0.45)
    popup_h = int(ALTO * 0.38)
    x0 = (ANCHO - popup_w) // 2
    y0 = (ALTO - popup_h) // 2

    cv2.rectangle(overlay, (x0, y0), (x0 + popup_w, y0 + popup_h), (255, 255, 255), -1)
    cv2.rectangle(overlay, (x0, y0), (x0 + popup_w, y0 + popup_h), (0, 0, 0), 4)

    cv2.putText(
        overlay, "Parecido:", (x0 + 40, y0 + 90),
        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 3, cv2.LINE_AA
    )
    cv2.putText(
        overlay, f"{porcentaje}%", (x0 + 40, y0 + 190),
        cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 150, 0), 5, cv2.LINE_AA
    )

    cv2.putText(
        overlay, "R = volver al menu", (x0 + 40, y0 + popup_h - 90),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA
    )
    cv2.putText(
        overlay, "ESPACIO = seguir dibujando", (x0 + 40, y0 + popup_h - 40),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA
    )

    return overlay


def punto_en_rect(punto, rect):
    x, y = punto
    rx, ry, rw, rh = rect
    return rx <= x <= rx + rw and ry <= y <= ry + rh



def _fig_circulo(img, w, h):
    cv2.circle(img, (w // 2, h // 2), min(w, h) // 3, (255, 255, 255), 10, cv2.LINE_AA)


def _fig_cuadrado(img, w, h):
    m = min(w, h) // 3
    cv2.rectangle(img, (w // 2 - m, h // 2 - m), (w // 2 + m, h // 2 + m), (255, 255, 255), 10, cv2.LINE_AA)


def _fig_triangulo(img, w, h):
    m = min(w, h) // 3
    pts = np.array([[w // 2, h // 2 - m], [w // 2 - m, h // 2 + m], [w // 2 + m, h // 2 + m]], np.int32)
    cv2.polylines(img, [pts], True, (255, 255, 255), 10, cv2.LINE_AA)


def _fig_estrella(img, w, h):
    cx, cy = w // 2, h // 2
    r_ext = min(w, h) // 3
    r_int = r_ext // 2
    pts = []
    for i in range(10):
        ang = -90 + i * 36
        r = r_ext if i % 2 == 0 else r_int
        x = int(cx + r * np.cos(np.radians(ang)))
        y = int(cy + r * np.sin(np.radians(ang)))
        pts.append([x, y])
    cv2.polylines(img, [np.array(pts, np.int32)], True, (255, 255, 255), 10, cv2.LINE_AA)


def _fig_corazon(img, w, h):
    cx, cy = w // 2, h // 2
    escala = min(w, h) / 300
    pts = []
    for t in range(0, 360, 5):
        rad = np.radians(t)
        x = 16 * np.sin(rad) ** 3
        y = -(13 * np.cos(rad) - 5 * np.cos(2 * rad) - 2 * np.cos(3 * rad) - np.cos(4 * rad))
        pts.append([int(cx + x * 10 * escala), int(cy + y * 10 * escala)])
    cv2.polylines(img, [np.array(pts, np.int32)], True, (255, 255, 255), 10, cv2.LINE_AA)


def _fig_casa(img, w, h):
    cx, cy = w // 2, h // 2
    m = min(w, h) // 4
    cv2.rectangle(img, (cx - m, cy), (cx + m, cy + m), (255, 255, 255), 10, cv2.LINE_AA)
    pts = np.array([[cx - m - 20, cy], [cx, cy - m], [cx + m + 20, cy]], np.int32)
    cv2.polylines(img, [pts], True, (255, 255, 255), 10, cv2.LINE_AA)
    cv2.rectangle(img, (cx - 30, cy + m // 2), (cx + 30, cy + m), (255, 255, 255), 8, cv2.LINE_AA)


def _fig_sol(img, w, h):
    cx, cy = w // 2, h // 2
    r = min(w, h) // 5
    cv2.circle(img, (cx, cy), r, (255, 255, 255), 10, cv2.LINE_AA)
    for i in range(8):
        ang = np.radians(i * 45)
        x1 = int(cx + (r + 20) * np.cos(ang))
        y1 = int(cy + (r + 20) * np.sin(ang))
        x2 = int(cx + (r + 60) * np.cos(ang))
        y2 = int(cy + (r + 60) * np.sin(ang))
        cv2.line(img, (x1, y1), (x2, y2), (255, 255, 255), 8, cv2.LINE_AA)


def _fig_arbol(img, w, h):
    cx, cy = w // 2, h // 2
    cv2.rectangle(img, (cx - 15, cy + 40), (cx + 15, cy + 160), (255, 255, 255), -1)
    cv2.circle(img, (cx, cy - 40), 100, (255, 255, 255), 10, cv2.LINE_AA)


def _fig_pez(img, w, h):
    cx, cy = w // 2, h // 2
    cv2.ellipse(img, (cx, cy), (110, 60), 0, 0, 360, (255, 255, 255), 10, cv2.LINE_AA)
    pts = np.array([[cx + 100, cy], [cx + 170, cy - 55], [cx + 170, cy + 55]], np.int32)
    cv2.polylines(img, [pts], True, (255, 255, 255), 10, cv2.LINE_AA)


def _fig_carita(img, w, h):
    cx, cy = w // 2, h // 2
    r = min(w, h) // 3
    cv2.circle(img, (cx, cy), r, (255, 255, 255), 10, cv2.LINE_AA)
    cv2.circle(img, (cx - r // 3, cy - r // 4), 14, (255, 255, 255), -1)
    cv2.circle(img, (cx + r // 3, cy - r // 4), 14, (255, 255, 255), -1)
    cv2.ellipse(img, (cx, cy + r // 4), (r // 2, r // 3), 0, 0, 180, (255, 255, 255), 8, cv2.LINE_AA)


FIGURAS = {
    # geometricas
    "circulo": _fig_circulo,
    "cuadrado": _fig_cuadrado,
    "triangulo": _fig_triangulo,
    "estrella": _fig_estrella,
    "corazon": _fig_corazon,
    # trazo simple
    "casa": _fig_casa,
    "sol": _fig_sol,
    "arbol": _fig_arbol,
    "pez": _fig_pez,
    "carita": _fig_carita,
}


def elegir_figura_nueva():
    """Elige una figura al azar y la dibuja en un lienzo del
    tamano exacto del recuadro de FIGURA.png. Devuelve el
    nombre (por si se quiere mostrar/depurar) y la imagen."""
    nombre = random.choice(list(FIGURAS.keys()))
    lienzo = np.zeros((FIG_H, FIG_W, 3), dtype=np.uint8)
    FIGURAS[nombre](lienzo, FIG_W, FIG_H)
    return nombre, lienzo


def procesar_pantalla_figura():
    """Arma el frame de 'memoriza esta figura' y devuelve
    tambien si ya se cumplio el tiempo para pasar a dibujar."""
    salida = figura_img_base.copy()
    salida[FIG_Y:FIG_Y + FIG_H, FIG_X:FIG_X + FIG_W] = figura_actual_img
    tiempo_cumplido = cv2.getTickCount() >= figura_hasta
    return salida, tiempo_cumplido


def ejecutar_boton(boton):
    global color_actual, DRAW_COLOR, borrador_activo, prev_point

    if boton["tipo"] == "color":
        color_actual = boton["valor"]
        DRAW_COLOR = COLORES[color_actual]
        borrador_activo = False

    elif boton["tipo"] == "borrador":
        borrador_activo = not borrador_activo

    elif boton["tipo"] == "vaciar":
        canvas[:] = 0
        prev_point = None

    elif boton["tipo"] == "guardar":
        guardar_dibujo()


def manejar_hover_botones(cursor):
    """Revisa si el CURSOR (el mismo que llega hasta el icono de
    ayuda) esta sobre algun boton de la barra y, si se sostiene
    el tiempo suficiente, ejecuta la accion."""
    global boton_hover_actual, boton_hover_frames

    encontrado = -1
    for idx, boton in enumerate(BOTONES):
        if punto_en_rect(cursor, boton["rect_global"]):
            encontrado = idx
            break

    if encontrado == -1:
        boton_hover_actual = -1
        boton_hover_frames = 0
        return

    if encontrado != boton_hover_actual:
        boton_hover_actual = encontrado
        boton_hover_frames = 0

    boton_hover_frames += 1
    boton = BOTONES[encontrado]
    umbral = UMBRAL_COLOR if boton["tipo"] == "color" else UMBRAL_ACCION

    if boton_hover_frames == umbral:
        ejecutar_boton(boton)
        boton_hover_frames = -umbral  # enfriamiento


def dibujar_toolbar(frame):
    """Dibuja la barra de herramientas sobre el frame de camara
    (coordenadas locales del recuadro, 0..CAM_W, 0..CAM_H)."""

    fondo = frame.copy()
    cv2.rectangle(
        fondo,
        (TOOLBAR_RECT[0], TOOLBAR_RECT[1]),
        (TOOLBAR_RECT[0] + TOOLBAR_RECT[2], TOOLBAR_RECT[1] + TOOLBAR_RECT[3]),
        (0, 0, 0), -1
    )
    cv2.addWeighted(fondo, 0.6, frame, 0.4, 0, frame)

    for idx, boton in enumerate(BOTONES):
        x, y, w, h = boton["rect"]
        hover_activo = (idx == boton_hover_actual and boton_hover_frames > 0)

        if boton["tipo"] == "color":
            color = COLORES[boton["valor"]]
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, -1)
            if boton["valor"] == color_actual and not borrador_activo:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 255), 3)

        else:
            etiquetas = {"borrador": "BORRAR", "vaciar": "VACIAR", "guardar": "GUARDAR"}
            activo = boton["tipo"] == "borrador" and borrador_activo
            color_fondo = (60, 60, 60) if not activo else (0, 150, 0)
            cv2.rectangle(frame, (x, y), (x + w, y + h), color_fondo, -1)
            cv2.putText(
                frame, etiquetas[boton["tipo"]],
                (x + 8, y + h // 2 + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA
            )

        if hover_activo:
            umbral = UMBRAL_COLOR if boton["tipo"] == "color" else UMBRAL_ACCION
            progreso = min(1.0, boton_hover_frames / umbral)
            cv2.rectangle(
                frame, (x, y), (x + int(w * progreso), y + h),
                (0, 255, 0), 3
            )
        else:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 255), 1)


def procesar_camara(imagen_fondo, permitir_dibujo=True):
    """Lee la camara y arma la interfaz (Modo Libre o Modo
    Memoria, segun 'imagen_fondo' que se le pase).
    Si permitir_dibujo=False, la camara se sigue viendo pero
    no se registran nuevos trazos (se usa mientras el manual
    esta abierto encima, para no dibujar 'a ciegas')."""
    global prev_point, ultimo_gesto, borrador_activo
    global cursor_global, hover_frames, mostrando_manual
    global boton_hover_actual, boton_hover_frames
    global ultima_foto

    salida = imagen_fondo.copy()

    ok, frame = cap.read()
    if not ok:
        salida[CAM_Y:CAM_Y + CAM_H, CAM_X:CAM_X + CAM_W] = canvas
        return salida

    frame = cv2.flip(frame, 1)
    frame = cv2.resize(frame, (CAM_W, CAM_H))
    ultima_foto = frame.copy()

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    resultado = hands.process(frame_rgb)

    dibujando = False
    dedos_levantados = 0

    if resultado.multi_hand_landmarks:
        lm = resultado.multi_hand_landmarks[0].landmark
        dedos_levantados = contar_dedos(lm)
        indice = (int(lm[8].x * CAM_W), int(lm[8].y * CAM_H))

        
        cursor_global = (int(lm[8].x * ANCHO), int(lm[8].y * ALTO))

        if click_en_icono_ayuda(*cursor_global):
            hover_frames += 1
            if hover_frames == HOVER_FRAMES_PARA_ABRIR:
                mostrando_manual = not mostrando_manual
                hover_frames = -HOVER_FRAMES_PARA_ABRIR  # enfriamiento
        else:
            hover_frames = 0

        if not permitir_dibujo:
            # solo se ve la mano, no se dibuja ni se cambia nada
            prev_point = None
            ultimo_gesto = 0

        elif punto_en_rect(cursor_global, TOOLBAR_RECT_GLOBAL):
            
            manejar_hover_botones(cursor_global)
            prev_point = None
            ultimo_gesto = 0

        else:
            boton_hover_actual = -1
            boton_hover_frames = 0

            
            if dedos_levantados == 4:
                borrador_activo = True
                prev_point = None
                ultimo_gesto = 4

            elif dedos_levantados == 1:
                dibujando = True
                if borrador_activo:
                    if prev_point is not None:
                        cv2.line(
                            canvas, prev_point, indice,
                            (0, 0, 0), DRAW_THICKNESS * 2, cv2.LINE_AA
                        )
                else:
                    if prev_point is not None:
                        cv2.line(
                            canvas, prev_point, indice,
                            DRAW_COLOR, DRAW_THICKNESS, cv2.LINE_AA
                        )
                prev_point = indice
                ultimo_gesto = 1

            else:
                prev_point = None
                ultimo_gesto = 0

        if borrador_activo and dedos_levantados == 1 and permitir_dibujo:
            color_punto = (255, 255, 255)
        elif dibujando:
            color_punto = DRAW_COLOR
        else:
            color_punto = (255, 255, 255)

        cv2.circle(frame, indice, POINTER_RADIUS, color_punto, cv2.FILLED, cv2.LINE_AA)
    else:
        prev_point = None
        ultimo_gesto = 0
        cursor_global = None
        hover_frames = 0
        boton_hover_actual = -1
        boton_hover_frames = 0

    mascara = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    _, mascara = cv2.threshold(mascara, 10, 255, cv2.THRESH_BINARY)
    mascara_inv = cv2.bitwise_not(mascara)

    fondo = cv2.bitwise_and(frame, frame, mask=mascara_inv)
    trazos = cv2.bitwise_and(canvas, canvas, mask=mascara)
    frame_final = cv2.add(fondo, trazos)

    dibujar_toolbar(frame_final)
    mostrar_informacion(frame_final)

    if mensaje_temporal and cv2.getTickCount() < mensaje_hasta:
        cv2.putText(
            frame_final, mensaje_temporal,
            (100, CAM_H - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
            (0, 255, 0), 2, cv2.LINE_AA
        )

    salida[CAM_Y:CAM_Y + CAM_H, CAM_X:CAM_X + CAM_W] = frame_final

    
    if cursor_global is not None:
        cv2.circle(salida, cursor_global, 14, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(salida, cursor_global, 3, (255, 255, 255), cv2.FILLED, cv2.LINE_AA)

        if hover_frames > 0:
            centro = (
                HELP_ICON_X + HELP_ICON_W // 2,
                HELP_ICON_Y + HELP_ICON_H // 2
            )
            radio = max(HELP_ICON_W, HELP_ICON_H) // 2 + 12
            progreso = int(360 * hover_frames / HOVER_FRAMES_PARA_ABRIR)
            cv2.ellipse(
                salida, centro, (radio, radio), -90, 0, progreso,
                (0, 255, 0), 6, cv2.LINE_AA
            )

    return salida


def dibujar_popup_manual(frame_base):
    """Dibuja el manual como ventana emergente ENCIMA de lo que
    se esta mostrando, sin taparlo por completo ni perder nada
    de lo que hay debajo (camara/dibujo siguen intactos)."""
    overlay = frame_base.copy()

    fondo_oscuro = np.zeros_like(overlay)
    cv2.addWeighted(fondo_oscuro, 0.55, overlay, 0.45, 0, overlay)

    popup_w = int(ANCHO * 0.62)
    popup_h = int(ALTO * 0.72)
    x0 = (ANCHO - popup_w) // 2
    y0 = (ALTO - popup_h) // 2

    manual_resized = cv2.resize(manual_img, (popup_w, popup_h))

    borde = 8
    cv2.rectangle(
        overlay,
        (x0 - borde, y0 - borde),
        (x0 + popup_w + borde, y0 + popup_h + borde),
        (255, 255, 255), -1
    )
    overlay[y0:y0 + popup_h, x0:x0 + popup_w] = manual_resized

    cv2.putText(
        overlay, "Presiona M para cerrar",
        (x0, y0 + popup_h + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
        (255, 255, 255), 2, cv2.LINE_AA
    )

    return overlay


def click_en_icono_ayuda(x, y):
    return (
        HELP_ICON_X <= x <= HELP_ICON_X + HELP_ICON_W and
        HELP_ICON_Y <= y <= HELP_ICON_Y + HELP_ICON_H
    )


def manejar_click(event, x, y, flags, param):
    global mostrando_manual
    if event == cv2.EVENT_LBUTTONDOWN:
        # La ventana puede estar mostrada a un tamano distinto al de
        # la imagen real (1920x1080), asi que convertimos las
        # coordenadas del click a coordenadas reales de la imagen.
        rect = cv2.getWindowImageRect(WINDOW_NAME)
        _, _, win_w, win_h = rect
        if win_w > 0 and win_h > 0:
            x = int(x * ANCHO / win_w)
            y = int(y * ALTO / win_h)

        if click_en_icono_ayuda(x, y):
            mostrando_manual = not mostrando_manual



cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
cv2.resizeWindow(WINDOW_NAME, 1280, 720)
cv2.setMouseCallback(WINDOW_NAME, manejar_click)

estado = STATE_MENU



while True:

    if estado == STATE_MENU:
        frame_mostrar = redimensionar_a_pantalla(menu_img)

    elif estado == STATE_LIBRE:
        # si el manual esta abierto, la camara se sigue viendo
        # pero se desactiva el dibujo para no trazar "a ciegas"
        frame_mostrar = procesar_camara(libre_img_base, permitir_dibujo=not mostrando_manual)

    elif estado == STATE_MEMORIA_FIGURA:
        frame_mostrar, tiempo_cumplido = procesar_pantalla_figura()
        if tiempo_cumplido and not mostrando_manual:
            estado = STATE_MEMORIA_DIBUJO
            canvas[:] = 0
            prev_point = None

    elif estado == STATE_MEMORIA_DIBUJO:
        frame_mostrar = procesar_camara(
            memoria_img_base,
            permitir_dibujo=not mostrando_manual and not mostrando_analisis
        )

    if mostrando_guardado:
        frame_mostrar = dibujar_popup_guardado(frame_mostrar)

    if mostrando_qr:
        frame_mostrar = dibujar_popup_qr(frame_mostrar)

    if mostrando_manual:
        frame_mostrar = dibujar_popup_manual(frame_mostrar)

    if mostrando_analisis:
        frame_mostrar = dibujar_popup_analisis(frame_mostrar, analisis_porcentaje)

    cv2.imshow(WINDOW_NAME, frame_mostrar)
    key = cv2.waitKey(1) & 0xFF

    # si el usuario cerro la ventana con el boton X (en vez de
    # con una tecla), getWindowProperty devuelve < 1 -> salimos
    if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
        break

    if mostrando_qr:
        if key == 27:
            mostrando_qr = False
            qr_imagen = None
            qr_url = ""
        continue

    if mostrando_guardado:
        if key in (ord('l'), ord('L')):
            mostrando_guardado = False
            subir_imagen_y_generar_qr(lienzo_guardado, "lienzo")
        elif key in (ord('f'), ord('F')):
            mostrando_guardado = False
            subir_imagen_y_generar_qr(foto_guardada, "foto")
        elif key == 27:
            mostrando_guardado = False
        continue

    if key == ord('q') or key == 27:
        break

    elif mostrando_analisis:
        # mientras el popup de analisis esta abierto, solo estas
        # dos teclas hacen algo (el resto se ignora a proposito)
        if key in (ord('r'), ord('R')):
            mostrando_analisis = False
            estado = STATE_MENU
        elif key == 32:  # barra espaciadora
            mostrando_analisis = False

    elif key == ord('1'):
        estado = STATE_LIBRE

        if not manual_visto:
            mostrando_manual = True
            manual_visto = True
            with open(MANUAL_VISTO_PATH, "w") as _f:
                _f.write("visto")

    elif key == ord('2'):
        estado = STATE_MEMORIA_FIGURA
        figura_actual_nombre, figura_actual_img = elegir_figura_nueva()
        figura_hasta = cv2.getTickCount() + int(TIEMPO_FIGURA_SEGUNDOS * cv2.getTickFrequency())

    elif key in (13, 10):  # ENTER
        if estado == STATE_MEMORIA_DIBUJO and not mostrando_manual:
            analisis_porcentaje = calcular_similitud()
            mostrando_analisis = True

    elif key in (ord('m'), ord('M')):
        mostrando_manual = not mostrando_manual

    elif key in (ord('r'), ord('R')):
        if not mostrando_manual:
            estado = STATE_MENU

    elif key in (ord('s'), ord('S')):
        if estado in (STATE_LIBRE, STATE_MEMORIA_DIBUJO) and not mostrando_manual:
            guardar_dibujo()

    elif key in (ord('c'), ord('C')):
        if estado in (STATE_LIBRE, STATE_MEMORIA_DIBUJO) and not mostrando_manual:
            canvas[:] = 0
            prev_point = None

cap.release()
cv2.destroyAllWindows()