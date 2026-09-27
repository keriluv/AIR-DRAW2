import cv2
import numpy as np
import mediapipe as mp
import os
from datetime import datetime



BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTERFACES_DIR = os.path.join(BASE_DIR, "interfaces")
CAPTURAS_DIR = os.path.join(BASE_DIR, "capturas")

MENU_IMG_PATH = os.path.join(INTERFACES_DIR, "MENU.png")
LIBRE_IMG_PATH = os.path.join(INTERFACES_DIR, "MODO LIBRE.png")
MANUAL_IMG_PATH = os.path.join(INTERFACES_DIR, "MANUAL DE INSTRUCCIONES.png")

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


# cada boton guarda tambien su posicion global, para poder usar
# el MISMO cursor (el que llega hasta el icono de ayuda) tanto
# afuera como adentro del recuadro de camara
for _boton in BOTONES:
    _boton["rect_global"] = _rect_a_global(_boton["rect"])

TOOLBAR_RECT_GLOBAL = _rect_a_global(TOOLBAR_RECT)

UMBRAL_COLOR = 10     # cuadros para seleccionar un color (rapido)
UMBRAL_ACCION = 20    # cuadros para borrador/vaciar/guardar (mas lento)

boton_hover_actual = -1
boton_hover_frames = 0

STATE_MENU = "menu"
STATE_LIBRE = "libre"

# el manual ya NO es un estado que reemplaza la pantalla,
# ahora es un popup que se dibuja ENCIMA del estado actual
mostrando_manual = False


def cargar_imagen(path):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"No se encontro la imagen: {path}")
    return img


menu_img = cargar_imagen(MENU_IMG_PATH)
libre_img_base = cargar_imagen(LIBRE_IMG_PATH)
manual_img = cargar_imagen(MANUAL_IMG_PATH)

ALTO, ANCHO = libre_img_base.shape[:2]

canvas = np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)


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

# cursor gestual: posicion del dedo indice mapeada a TODA la pantalla
# (no solo al recuadro de camara), para poder "tocar" el icono de ayuda
cursor_global = None
hover_frames = 0
HOVER_FRAMES_PARA_ABRIR = 18  # cuadros sosteniendo el dedo sobre el icono

# mensaje temporal (ej: "Dibujo guardado") con su tiempo de expiracion
mensaje_temporal = ""
mensaje_hasta = 0


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
    """Guarda el canvas (solo el dibujo, sin la camara) como PNG."""
    global mensaje_temporal, mensaje_hasta

    os.makedirs(CAPTURAS_DIR, exist_ok=True)
    nombre = "dibujo_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
    ruta = os.path.join(CAPTURAS_DIR, nombre)
    cv2.imwrite(ruta, canvas)

    mensaje_temporal = "Dibujo guardado: " + nombre
    mensaje_hasta = cv2.getTickCount() + int(2.5 * cv2.getTickFrequency())


def punto_en_rect(punto, rect):
    x, y = punto
    rx, ry, rw, rh = rect
    return rx <= x <= rx + rw and ry <= y <= ry + rh


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


def procesar_modo_libre(permitir_dibujo=True):
    """Lee la camara y arma la interfaz de modo libre.
    Si permitir_dibujo=False, la camara se sigue viendo pero
    no se registran nuevos trazos (se usa mientras el manual
    esta abierto encima, para no dibujar 'a ciegas')."""
    global prev_point, ultimo_gesto, borrador_activo
    global cursor_global, hover_frames, mostrando_manual
    global boton_hover_actual, boton_hover_frames

    salida = libre_img_base.copy()

    ok, frame = cap.read()
    if not ok:
        salida[CAM_Y:CAM_Y + CAM_H, CAM_X:CAM_X + CAM_W] = canvas
        return salida

    frame = cv2.flip(frame, 1)
    frame = cv2.resize(frame, (CAM_W, CAM_H))

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    resultado = hands.process(frame_rgb)

    dibujando = False
    dedos_levantados = 0

    if resultado.multi_hand_landmarks:
        lm = resultado.multi_hand_landmarks[0].landmark
        dedos_levantados = contar_dedos(lm)
        indice = (int(lm[8].x * CAM_W), int(lm[8].y * CAM_H))

        # cursor gestual: mismo dedo indice, pero mapeado a la
        # pantalla completa (1920x1080) para poder llegar al icono
        # de ayuda aunque este fuera del recuadro de la camara
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
            # el cursor (el MISMO que llega hasta el icono de ayuda)
            # esta sobre la barra: se maneja el hover de botones y
            # NO se dibuja en el lienzo
            manejar_hover_botones(cursor_global)
            prev_point = None
            ultimo_gesto = 0

        else:
            boton_hover_actual = -1
            boton_hover_frames = 0

            # el dedo/mano ahora es SOLO para dibujar (1 dedo) o
            # borrar (4 dedos) sobre el lienzo; seleccionar color,
            # abrir el manual, guardar o vaciar se hace con el
            # cursor sobre los botones/icono, no con gestos
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
        frame_mostrar = procesar_modo_libre(permitir_dibujo=not mostrando_manual)

    if mostrando_manual:
        frame_mostrar = dibujar_popup_manual(frame_mostrar)

    cv2.imshow(WINDOW_NAME, frame_mostrar)
    key = cv2.waitKey(1) & 0xFF

    if key == ord('q') or key == 27:
        break

    elif key == ord('1'):
        estado = STATE_LIBRE

    elif key in (ord('m'), ord('M')):
        mostrando_manual = not mostrando_manual

    elif key in (ord('r'), ord('R')):
        if not mostrando_manual:
            estado = STATE_MENU

    elif key in (ord('s'), ord('S')):
        if estado == STATE_LIBRE and not mostrando_manual:
            guardar_dibujo()

    elif key in (ord('c'), ord('C')):
        if not mostrando_manual:
            canvas[:] = 0
            prev_point = None

cap.release()
cv2.destroyAllWindows()