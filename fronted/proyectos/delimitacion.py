"""
delimitacion.py
===============

Herramientas y visuales de la etapa Delimitación del módulo Proyectos.

Sesión D del módulo Proyectos.

Contiene:
  * HerramientaDibujoPolilinea — base state machine para dibujar
    muros y habitaciones con clics sucesivos. Snap ortogonal (Shift)
    respecto al último vértice.
  * HerramientaMuro — polilínea abierta (o cerrada explícitamente).
  * HerramientaHabitacion — polígono cerrado que al terminar pide
    un nombre en un diálogo modal.
  * MuroItem — QGraphicsObject que dibuja un muro sobre el canvas.
  * HabitacionItem — QGraphicsObject que dibuja una habitación
    (polígono + relleno translúcido + etiqueta con nombre y área).
  * VerticeEditableItem — círculo arrastrable que representa un
    vértice editable de un muro o habitación seleccionada.
  * DialogoNombreHabitacion — modal para asignar nombre + confirmar.
  * PreviewDibujoItem — visual efímero de la polilínea en curso.

Cada herramienta emite señales al terminar: el canvas / la página
Delimitación las escucha y persiste en el modelo `ProyectoAbierto`.

Convenciones:
  * Coordenadas de escena en pt del PDF nativo (72 DPI), como el
    resto del módulo.
  * Tamaños visuales (grosor de línea, radio de vértices, tamaño de
    texto) se ajustan al zoom del viewport para verse constantes
    en pantalla.
  * Snap ortogonal se activa mientras Shift está mantenido y se
    aplica al segmento entre el último vértice fijo y el cursor.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Optional

from PyQt6.QtCore import Qt, QPointF, QRectF, QObject, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QKeyEvent, QPainter,
    QPainterPath, QPainterPathStroker, QPen, QPolygonF, QTransform,
)
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGraphicsItem,
    QGraphicsObject,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStyleOptionGraphicsItem, QVBoxLayout, QWidget,
)

from datos_proyecto import (
    GROSOR_DEFAULT_POR_MATERIAL, Habitacion,
    JUSTIFICACION_MURO_LABELS, JustificacionMuro,
    MATERIAL_MURO_LABELS, Muro, Puerta, SentidoAperturaPuerta,
    TipoGeometriaMuro, TipoMaterialMuro, TipoUsoHabitacion,
    USO_HABITACION_LABELS, Ventana,
)
from escala_calibrador import EscalaCalibrada


# ---------------------------------------------------------------------------
# Paleta (self-contained)
# ---------------------------------------------------------------------------

COLOR_FONDO           = "#121212"
COLOR_SUPERFICIE      = "#1e1e1e"
COLOR_INPUT_BG        = "#2b2b2b"
COLOR_BORDE           = "#333"
COLOR_BORDE_FUERTE    = "#444"
COLOR_ACENTO          = "#0078d7"
COLOR_ACENTO_BRILL    = "#0094ff"
COLOR_TEXTO           = "#ffffff"
COLOR_TEXTO_SUAVE     = "#dddddd"
COLOR_TEXTO_MUTED     = "#aaaaaa"

# Colores propios de Delimitación (distintos de calibración/medición)
COLOR_MURO            = "#e0e0e0"   # gris claro (línea sobre plano oscuro)
COLOR_MURO_SEL        = "#ff9a3d"   # naranja al seleccionar
COLOR_MURO_HOVER_DEL  = "#ff4d4d"   # rojo al hover-para-borrar
COLOR_HAB_LINEA       = "#5aaefc"   # azul claro para contorno
COLOR_HAB_RELLENO     = "#5aaefc33" # relleno semi-transparente (RGBA)
COLOR_HAB_SEL         = "#ffb84d"
COLOR_HAB_HOVER_DEL   = "#ff4d4d"
COLOR_HAB_TEXTO       = "#ffffff"
COLOR_HAB_TEXTO_BG    = "#1a1a1acc"
COLOR_PREVIEW_LINEA   = "#0094ff"
COLOR_VERTICE         = "#ffb84d"
COLOR_VERTICE_HOVER   = "#ffffff"

# Grosores base (en pt PDF; se dividen por scale en el paint)
_GROSOR_MURO_PT       = 3.0
_GROSOR_HABITACION_PT = 2.5
_GROSOR_PREVIEW_PT    = 2.0
_RADIO_VERTICE_PT     = 6.0


# ---------------------------------------------------------------------------
# Helpers de dibujo
# ---------------------------------------------------------------------------

def _snap_ortogonal(punto_ref: QPointF, punto: QPointF) -> QPointF:
    """Ajusta `punto` para que el segmento desde `punto_ref` sea
    horizontal, vertical o a 45°. El más cercano gana."""
    dx = punto.x() - punto_ref.x()
    dy = punto.y() - punto_ref.y()
    if dx == 0.0 and dy == 0.0:
        return QPointF(punto)
    ang = math.atan2(dy, dx)
    paso = math.pi / 4.0
    snap = round(ang / paso) * paso
    largo = math.hypot(dx, dy)
    return QPointF(
        punto_ref.x() + largo * math.cos(snap),
        punto_ref.y() + largo * math.sin(snap),
    )


def _painter_scale(painter: QPainter) -> float:
    t = painter.worldTransform()
    s = math.hypot(t.m11(), t.m12())
    return max(s, 1e-6)


# ---------------------------------------------------------------------------
# Helpers de arco y círculo (Muro curvo, Habitación circular)
# ---------------------------------------------------------------------------

# Cantidad de vértices con los que se tesela una habitación circular.
# 48 da un círculo visualmente suave en pantalla y suficiente para
# cálculos de área NOM (error del polígono inscrito ≈ 0.3% vs. círculo
# exacto — muy por debajo del ±10% de tolerancia práctica NOM).
_N_VERTICES_CIRCULO_HAB = 48


def _centro_radio_circulo_3_puntos(
    p1: QPointF, p2: QPointF, p3: QPointF,
) -> Optional[tuple[QPointF, float]]:
    """Centro y radio del círculo único que pasa por 3 puntos.
    Devuelve None si los puntos son colineales (o casi)."""
    ax, ay = p1.x(), p1.y()
    bx, by = p2.x(), p2.y()
    cx, cy = p3.x(), p3.y()
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    centro = QPointF(ux, uy)
    radio = math.hypot(ax - ux, ay - uy)
    return centro, radio


def _angulo_arcTo(p: QPointF, centro: QPointF) -> float:
    """Ángulo (grados) para pasar a QPainterPath.arcTo.

    Convención de arcTo: 0° apunta a "las 3 en punto" (+X), y los
    ángulos positivos van en sentido antihorario en la pantalla
    (recuerda: en Qt, Y crece hacia abajo, así que hay que invertir
    la componente Y para que 90° apunte a "las 12 en punto")."""
    dx = p.x() - centro.x()
    dy = p.y() - centro.y()
    return math.degrees(math.atan2(-dy, dx))


def _arco_path_por_3_puntos(
    p1: QPointF, p2: QPointF, p3: QPointF,
) -> Optional[QPainterPath]:
    """Construye un QPainterPath con el arco que empieza en p1, pasa
    por p2 y termina en p3. None si los 3 puntos son colineales.

    IMPORTANTE: aproxima el arco con muchos segmentos rectos cortos
    (`lineTo`) en lugar de usar `arcTo`. El `QPainterPathStroker` que
    aplicamos después para darle grosor al muro no procesa
    correctamente las curvas Bezier internas que `arcTo` genera —
    resultado: el muro salía como polilínea de dos segmentos rectos
    en vez de curva suave. Con lineTo se ve idéntico al ojo (con
    N grande) y el stroker sí lo procesa bien.
    """
    resultado = _centro_radio_circulo_3_puntos(p1, p2, p3)
    if resultado is None:
        return None
    centro, radio = resultado

    a1 = _angulo_arcTo(p1, centro)
    a2 = _angulo_arcTo(p2, centro)
    a3 = _angulo_arcTo(p3, centro)

    # Barrido CCW de a1 → a3 en [0, 360); posición angular CCW de a2
    # respecto a a1 en el mismo sistema.
    d13_ccw = (a3 - a1) % 360.0
    d12_ccw = (a2 - a1) % 360.0
    if 0.0 < d12_ccw < d13_ccw:
        sweep_deg = d13_ccw            # CCW (positivo)
    else:
        sweep_deg = d13_ccw - 360.0    # CW (negativo)

    # Aproximar con segmentos rectos: ~0.5 por grado, mínimo 24. Antes
    # usábamos 2 por grado (180 para 90°) pero los micro-joins entre
    # segmentos creaban overlaps en el stroker y hacían que el hatch de
    # relleno se viera "denso" (Qt lo rellena con odd-even y las zonas
    # solapadas quedaban con doble patrón). Con menos segmentos + el
    # stroker con RoundJoin + `.simplified()` en el contorno, el arco
    # se ve suave y el hatch consistente con los muros rectos.
    n_segmentos = max(24, int(abs(sweep_deg) * 0.5))
    path = QPainterPath()
    path.moveTo(p1)
    for i in range(1, n_segmentos + 1):
        t = i / n_segmentos
        ang_deg = a1 + t * sweep_deg
        ang_rad = math.radians(ang_deg)
        # Coord en Y-down: x = cx + r*cos(a), y = cy - r*sin(a)
        px = centro.x() + radio * math.cos(ang_rad)
        py = centro.y() - radio * math.sin(ang_rad)
        path.lineTo(QPointF(px, py))
    return path


def _longitud_arco_3_puntos(
    p1: QPointF, p2: QPointF, p3: QPointF,
) -> float:
    """Longitud (en unidades de la escena, pt PDF) del arco por 3 puntos.
    Si los puntos son colineales, devuelve la distancia p1 → p3."""
    resultado = _centro_radio_circulo_3_puntos(p1, p2, p3)
    if resultado is None:
        return math.hypot(p3.x() - p1.x(), p3.y() - p1.y())
    centro, radio = resultado
    a1 = _angulo_arcTo(p1, centro)
    a2 = _angulo_arcTo(p2, centro)
    a3 = _angulo_arcTo(p3, centro)
    d13_ccw = (a3 - a1) % 360.0
    d12_ccw = (a2 - a1) % 360.0
    if 0.0 < d12_ccw < d13_ccw:
        sweep_deg = d13_ccw
    else:
        sweep_deg = 360.0 - d13_ccw
    return abs(math.radians(sweep_deg)) * radio


def _punto_medio_arco_3_puntos(
    p1: QPointF, p2: QPointF, p3: QPointF,
) -> Optional[QPointF]:
    """Punto medio geométrico del arco (mitad angular entre p1 y p3
    recorriendo por el mismo lado que p2). None si los 3 puntos son
    colineales.

    Nota: el vértice de control p2 NO es el punto medio del arco —
    puede estar en cualquier lugar del arco. Este helper devuelve el
    verdadero punto medio para exponerlo como snap-midpoint.
    """
    resultado = _centro_radio_circulo_3_puntos(p1, p2, p3)
    if resultado is None:
        # Colineal: punto medio del segmento p1 → p3
        return QPointF(
            (p1.x() + p3.x()) / 2.0, (p1.y() + p3.y()) / 2.0,
        )
    centro, radio = resultado
    a1 = _angulo_arcTo(p1, centro)
    a2 = _angulo_arcTo(p2, centro)
    a3 = _angulo_arcTo(p3, centro)
    d13_ccw = (a3 - a1) % 360.0
    d12_ccw = (a2 - a1) % 360.0
    if 0.0 < d12_ccw < d13_ccw:
        sweep_deg = d13_ccw           # CCW
    else:
        sweep_deg = d13_ccw - 360.0   # CW
    a_medio = a1 + sweep_deg / 2.0
    ang_rad = math.radians(a_medio)
    return QPointF(
        centro.x() + radio * math.cos(ang_rad),
        centro.y() - radio * math.sin(ang_rad),  # Y-down
    )


def _proyeccion_a_segmento(
    p: QPointF, a: QPointF, b: QPointF,
) -> tuple[QPointF, float]:
    """Punto más cercano en el segmento a→b al punto p, y su distancia
    al cuadrado. La proyección se clampa a los extremos si cae fuera."""
    dx = b.x() - a.x()
    dy = b.y() - a.y()
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        d2 = (p.x() - a.x()) ** 2 + (p.y() - a.y()) ** 2
        return QPointF(a), d2
    t = ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / len2
    t = max(0.0, min(1.0, t))
    q = QPointF(a.x() + t * dx, a.y() + t * dy)
    d2 = (p.x() - q.x()) ** 2 + (p.y() - q.y()) ** 2
    return q, d2


def _proyeccion_a_arco(
    p: QPointF, p1: QPointF, p2: QPointF, p3: QPointF,
) -> tuple[QPointF, float]:
    """Punto más cercano al cursor `p` sobre el arco definido por
    (p1, p2, p3), y su distancia al cuadrado. Si la proyección al
    círculo cae fuera del rango angular del arco, se devuelve el
    extremo más cercano.
    """
    resultado = _centro_radio_circulo_3_puntos(p1, p2, p3)
    if resultado is None:
        # Colineal: cae a proyección al segmento p1-p3
        return _proyeccion_a_segmento(p, p1, p3)
    centro, radio = resultado
    dx = p.x() - centro.x()
    dy = p.y() - centro.y()
    L = math.hypot(dx, dy) or 1.0
    # Proyección al círculo (por radial)
    q = QPointF(
        centro.x() + dx * radio / L,
        centro.y() + dy * radio / L,
    )
    # ¿Cae dentro del rango angular del arco?
    a_q = _angulo_arcTo(q, centro)
    a1 = _angulo_arcTo(p1, centro)
    a2 = _angulo_arcTo(p2, centro)
    a3 = _angulo_arcTo(p3, centro)
    d13_ccw = (a3 - a1) % 360.0
    d12_ccw = (a2 - a1) % 360.0
    if 0.0 < d12_ccw < d13_ccw:
        # CCW: q está dentro si (a_q - a1) mod 360 <= d13_ccw
        dq_ccw = (a_q - a1) % 360.0
        dentro = dq_ccw <= d13_ccw
    else:
        # CW: q está dentro si (a1 - a_q) mod 360 <= 360 - d13_ccw
        dq_cw = (a1 - a_q) % 360.0
        dentro = dq_cw <= (360.0 - d13_ccw)
    if dentro:
        d2 = (p.x() - q.x()) ** 2 + (p.y() - q.y()) ** 2
        return q, d2
    # Fuera del arco: el punto más cercano es uno de los extremos
    d2_1 = (p.x() - p1.x()) ** 2 + (p.y() - p1.y()) ** 2
    d2_3 = (p.x() - p3.x()) ** 2 + (p.y() - p3.y()) ** 2
    if d2_1 <= d2_3:
        return QPointF(p1), d2_1
    return QPointF(p3), d2_3


def _proyeccion_a_muro(
    p: QPointF, muro: "Muro",
) -> tuple[Optional[QPointF], float]:
    """Punto más cercano al cursor sobre el muro dado (lineal o arco).
    Devuelve (punto, distancia^2). Punto = None si el muro no tiene
    geometría útil."""
    if not muro.vertices:
        return None, float("inf")
    if muro.es_arco():
        return _proyeccion_a_arco(
            p, muro.vertices[0], muro.vertices[1], muro.vertices[2],
        )
    if len(muro.vertices) < 2:
        return None, float("inf")
    mejor_p: Optional[QPointF] = None
    mejor_d2 = float("inf")
    for i in range(len(muro.vertices) - 1):
        q, d2 = _proyeccion_a_segmento(
            p, muro.vertices[i], muro.vertices[i + 1],
        )
        if d2 < mejor_d2:
            mejor_d2 = d2
            mejor_p = q
    if muro.cerrado and len(muro.vertices) >= 3:
        q, d2 = _proyeccion_a_segmento(
            p, muro.vertices[-1], muro.vertices[0],
        )
        if d2 < mejor_d2:
            mejor_d2 = d2
            mejor_p = q
    return mejor_p, mejor_d2


def _rect_arco_3_puntos(
    p1: QPointF, p2: QPointF, p3: QPointF,
) -> QRectF:
    """Bbox aproximado (generoso) del arco. Para bounding boxes de
    items visuales: incluye los 3 puntos y, si el círculo es válido,
    también el centro extendido por el radio, para no cortar arcos que
    se abomban lejos de sus extremos."""
    xs = [p1.x(), p2.x(), p3.x()]
    ys = [p1.y(), p2.y(), p3.y()]
    resultado = _centro_radio_circulo_3_puntos(p1, p2, p3)
    if resultado is not None:
        centro, radio = resultado
        xs.extend([centro.x() - radio, centro.x() + radio])
        ys.extend([centro.y() - radio, centro.y() + radio])
    return QRectF(
        min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys),
    )


def _generar_poligono_circular(
    centro: QPointF, radio: float, n: int = _N_VERTICES_CIRCULO_HAB,
) -> list[QPointF]:
    """Genera N puntos equiespaciados en el círculo (centro, radio).
    Empieza en 0° (eje +X) y avanza en sentido antihorario."""
    if n < 3 or radio <= 0.0:
        return []
    puntos: list[QPointF] = []
    for i in range(n):
        ang = 2.0 * math.pi * i / n
        puntos.append(QPointF(
            centro.x() + radio * math.cos(ang),
            centro.y() + radio * math.sin(ang),
        ))
    return puntos


def _construir_path_muro(muro: Muro) -> QPainterPath:
    """Construye el QPainterPath del EJE del muro según su geometría.
    Se usa como base para calcular el polígono de contorno (con
    grosor) y para hit-testing."""
    path = QPainterPath()
    if not muro.vertices:
        return path
    if muro.es_arco():
        arco = _arco_path_por_3_puntos(
            muro.vertices[0], muro.vertices[1], muro.vertices[2],
        )
        if arco is not None:
            return arco
        # Fallback: 3 puntos colineales → línea recta p1 → p3
        path.moveTo(muro.vertices[0])
        path.lineTo(muro.vertices[2])
        return path
    # LINEAL
    path.moveTo(muro.vertices[0])
    for v in muro.vertices[1:]:
        path.lineTo(v)
    if muro.cerrado and len(muro.vertices) >= 3:
        path.lineTo(muro.vertices[0])
    return path


def _polilinea_offset(
    vertices: list[QPointF], offset_pt: float, cerrado: bool,
) -> list[QPointF]:
    """Desplaza una polilínea `offset_pt` hacia la NORMAL IZQUIERDA
    del sentido de recorrido (en sistema Y-down: `n = (-dy, dx)/L`
    de cada segmento). `offset_pt` negativo desplaza al otro lado.

    En cada vértice interior el punto desplazado va sobre la bisectriz
    a distancia `offset / cos(θ/2)` (INGLETE real): es justo donde se
    cruzan las dos líneas paralelas de los tramos adyacentes, así cada
    tramo desplazado queda paralelo al original. (Antes se usaba la
    normal promedio sin ese factor y en quiebres agudos las caras
    salían chuecas.) En los extremos de una polilínea abierta el
    desplazamiento es perpendicular al tramo.
    """
    n = len(vertices)
    if n < 2 or abs(offset_pt) < 1e-9:
        return [QPointF(p) for p in vertices]

    def _normal(a: QPointF, b: QPointF) -> Optional[tuple[float, float]]:
        dx, dy = b.x() - a.x(), b.y() - a.y()
        L = math.hypot(dx, dy)
        if L < 1e-9:
            return None
        return (-dy / L, dx / L)

    # Normal de cada tramo (None si el tramo tiene largo cero)
    normales: list[Optional[tuple[float, float]]] = [
        _normal(vertices[i], vertices[i + 1]) for i in range(n - 1)
    ]
    if cerrado and n >= 3:
        normales.append(_normal(vertices[-1], vertices[0]))

    def _antes(i: int) -> Optional[tuple[float, float]]:
        if i > 0:
            return normales[i - 1]
        return normales[-1] if cerrado and n >= 3 else None

    def _despues(i: int) -> Optional[tuple[float, float]]:
        if i < n - 1:
            return normales[i]
        return normales[-1] if cerrado and n >= 3 else None

    resultado: list[QPointF] = []
    for i in range(n):
        na, nd = _antes(i), _despues(i)
        if na is None and nd is None:
            nx, ny, factor = 0.0, 0.0, 0.0
        elif na is None or nd is None:
            nx, ny = na or nd
            factor = 1.0
        else:
            sx, sy = na[0] + nd[0], na[1] + nd[1]
            L = math.hypot(sx, sy)
            if L < 1e-9:
                # Vuelta en U: sin bisectriz útil, desplazar perpendicular
                nx, ny, factor = nd[0], nd[1], 1.0
            else:
                nx, ny = sx / L, sy / L
                cos_medio = nx * nd[0] + ny * nd[1]
                factor = min(1.0 / max(cos_medio, 1e-6), _MITER_MAX)
        resultado.append(QPointF(
            vertices[i].x() + nx * offset_pt * factor,
            vertices[i].y() + ny * offset_pt * factor,
        ))
    return resultado


# Largo máximo del inglete (en múltiplos del desplazamiento). En quiebres
# muy agudos el pico real se iría muy lejos; a partir de aquí se recorta.
_MITER_MAX = 4.0


def _arco_offset_3_puntos(
    p1: QPointF, p2: QPointF, p3: QPointF, offset_pt: float,
) -> Optional[tuple[QPointF, QPointF, QPointF]]:
    """Devuelve 3 nuevos puntos de control para un arco desplazado.
    Los 3 puntos originales se desplazan hacia el centro (o alejándose
    de él, según el signo), preservando la relación arco-normal.

    El signo de `offset_pt` sigue la misma convención que
    `_polilinea_offset`: positivo = normal izquierda.
    """
    if abs(offset_pt) < 1e-9:
        return QPointF(p1), QPointF(p2), QPointF(p3)
    resultado = _centro_radio_circulo_3_puntos(p1, p2, p3)
    if resultado is None:
        # Colineales: usar la normal común del segmento p1→p3
        dx = p3.x() - p1.x()
        dy = p3.y() - p1.y()
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        return (
            QPointF(p1.x() + nx * offset_pt, p1.y() + ny * offset_pt),
            QPointF(p2.x() + nx * offset_pt, p2.y() + ny * offset_pt),
            QPointF(p3.x() + nx * offset_pt, p3.y() + ny * offset_pt),
        )
    centro, radio = resultado

    # Determinar sentido del arco (CCW o CW) — mismo cálculo que
    # `_arco_path_por_3_puntos`
    a1 = _angulo_arcTo(p1, centro)
    a2 = _angulo_arcTo(p2, centro)
    a3 = _angulo_arcTo(p3, centro)
    d13_ccw = (a3 - a1) % 360.0
    d12_ccw = (a2 - a1) % 360.0
    signo_ccw = 1.0 if 0.0 < d12_ccw < d13_ccw else -1.0

    # Para offset "hacia la izquierda del sentido de recorrido":
    #   - Si CCW visto en Y-down (barrido positivo), la izquierda es
    #     hacia AFUERA del centro → radio aumenta.
    #   - Si CW, la izquierda es hacia ADENTRO → radio disminuye.
    # Nota: la convención Y-down + arcTo hace que "CCW en pantalla"
    # sea "sweep negativo" en atan2 estándar; aquí signo_ccw = -1
    # significa que el arco va CW en la geometría del arcTo.
    delta_radio = offset_pt * signo_ccw
    nuevo_radio = radio + delta_radio
    if nuevo_radio <= 0.0:
        return None  # el offset "colapsa" el arco

    # Cada punto original se recalcula: mismo ángulo desde el centro,
    # con el nuevo radio.
    def _mover(p: QPointF) -> QPointF:
        dx = p.x() - centro.x()
        dy = p.y() - centro.y()
        L = math.hypot(dx, dy) or 1.0
        return QPointF(
            centro.x() + dx * nuevo_radio / L,
            centro.y() + dy * nuevo_radio / L,
        )
    return _mover(p1), _mover(p2), _mover(p3)


def _construir_path_muro_desplazado(muro: Muro, offset_pt: float) -> QPainterPath:
    """Como `_construir_path_muro` pero aplica un offset al eje.
    `offset_pt` positivo = izquierda del sentido de recorrido.
    Con `offset_pt = 0`, equivalente a `_construir_path_muro`."""
    if abs(offset_pt) < 1e-9:
        return _construir_path_muro(muro)
    path = QPainterPath()
    if not muro.vertices:
        return path
    if muro.es_arco():
        nuevos = _arco_offset_3_puntos(
            muro.vertices[0], muro.vertices[1], muro.vertices[2],
            offset_pt,
        )
        if nuevos is not None:
            arco = _arco_path_por_3_puntos(*nuevos)
            if arco is not None:
                return arco
        # Fallback: segmento recto
        path.moveTo(muro.vertices[0])
        path.lineTo(muro.vertices[2])
        return path
    # LINEAL
    nuevos = _polilinea_offset(muro.vertices, offset_pt, muro.cerrado)
    path.moveTo(nuevos[0])
    for v in nuevos[1:]:
        path.lineTo(v)
    if muro.cerrado and len(nuevos) >= 3:
        path.lineTo(nuevos[0])
    return path


def _offset_por_justificacion(
    muro: Muro, grosor_pt: float,
) -> float:
    """Cuánto desplazar el eje del muro (en pt) antes de aplicarle
    el stroker según la justificación:

    * CENTRO    → 0.0
    * IZQUIERDA → grosor hacia la IZQUIERDA VISUAL del sentido de
                  recorrido. En Qt (Y-down) esto significa offset
                  NEGATIVO respecto a la normal matemática (-dy, dx),
                  porque en Y-down la rotación CCW matemática
                  se ve como CW en pantalla.
    * DERECHA   → simétrico (positivo).
    """
    j = muro.justificacion
    if j == JustificacionMuro.IZQUIERDA:
        return -grosor_pt / 2.0
    if j == JustificacionMuro.DERECHA:
        return grosor_pt / 2.0
    return 0.0


def esquinas_contorno_muro(
    muro: Muro, escala: Optional[EscalaCalibrada],
) -> list[QPointF]:
    """Devuelve las esquinas del polígono grueso del muro (los puntos
    donde se cortan las caras). Para un muro lineal simple de 2
    vértices son 4 esquinas. Para uno de N vértices, son 2N. Para un
    arco, son 4 (los extremos de las dos caras).

    Se usan como puntos snapables extra — al dibujar un muro pegado a
    la cara de otro, el operador puede enganchar exactamente en una
    esquina en vez del eje central.

    Si el muro no tiene grosor válido (por falta de calibración o
    cualquier otro motivo), devuelve una lista vacía.
    """
    grosor = muro.grosor_pt(escala)
    if grosor <= 0.0 or not muro.vertices:
        return []
    puntos: list[QPointF] = []
    if muro.es_arco() and len(muro.vertices) == 3:
        for signo in (+1.0, -1.0):
            offset = signo * grosor / 2.0
            nuevos = _arco_offset_3_puntos(
                muro.vertices[0], muro.vertices[1], muro.vertices[2],
                offset,
            )
            if nuevos is not None:
                puntos.append(QPointF(nuevos[0]))
                puntos.append(QPointF(nuevos[2]))
        return puntos
    if len(muro.vertices) < 2:
        return []
    for signo in (+1.0, -1.0):
        offset = signo * grosor / 2.0
        desplazados = _polilinea_offset(
            muro.vertices, offset, muro.cerrado,
        )
        puntos.extend(QPointF(p) for p in desplazados)
    return puntos


def _contorno_muro_con_grosor(muro: Muro, grosor_pt: float) -> QPainterPath:
    """Devuelve el polígono cerrado (contorno) del muro con el grosor
    dado, con el offset apropiado según la justificación:
      * CENTRO    → grosor centrado sobre la línea dibujada
      * IZQUIERDA → grosor completamente a la izquierda de la línea
      * DERECHA   → grosor completamente a la derecha de la línea

    Es lo que se pinta (con hatch por material) y también lo que se
    usa para hit-testing preciso."""
    if grosor_pt <= 0.0:
        return _construir_path_muro(muro)
    offset = _offset_por_justificacion(muro, grosor_pt)
    eje = _construir_path_muro_desplazado(muro, offset)
    if eje.isEmpty():
        return eje
    stroker = QPainterPathStroker()
    stroker.setWidth(grosor_pt)
    stroker.setCapStyle(Qt.PenCapStyle.FlatCap)
    if muro.es_arco():
        # Arco: el eje son muchos micro-segmentos; RoundJoin evita los
        # pequeños overshoots entre ellos que hacían ver el hatch denso.
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    else:
        # Muro recto con quiebres: esquinas en PICO (inglete), como en
        # un plano. El límite coincide con `_MITER_MAX` de
        # `_polilinea_offset` para que caras y contorno cuadren.
        stroker.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        stroker.setMiterLimit(_MITER_MAX)
    contorno = stroker.createStroke(eje)
    # `simplified()` fusiona subpaths y elimina auto-intersecciones,
    # garantizando que el fill quede uniforme aunque hayan quedado
    # micro-overlaps.
    return contorno.simplified()


# ---------------------------------------------------------------------------
# Auto-extend: prolongar extremos de un muro nuevo hasta topar con otro
# ---------------------------------------------------------------------------
#
# Cuando el operador termina un muro cerca de otro pero sin tocarlo, el
# extremo se prolonga en la dirección en que venía dibujando hasta la
# cara del muro con el que choca (estilo EXTEND de AutoCAD). Reglas:
#
#   * Sólo cierra huecos: si el extremo ya está dentro de otro muro, o
#     el operador lo enganchó a un vértice con snap, no se toca.
#   * Extiende lo necesario para que las DOS esquinas del extremo toquen
#     la cara (en uniones a 90° es exactamente la cara; en uniones en
#     ángulo una esquina queda un poco dentro del otro muro, así no
#     queda muesca).
#   * Muro lineal: sigue la recta del último segmento. Muro curvo: sigue
#     su propia circunferencia.
#   * Distancia máxima: `umbral_pt` (la página la calcula con el zoom y
#     la escala).

_EPS_EXT = 1e-6
# Seno mínimo del ángulo entre la dirección de avance y el borde que se
# toca (~17°). Evita "extender" a lo largo de un muro casi paralelo.
_MIN_SENO_CRUCE = 0.3
# Distancia mínima (pt) para considerar que hay hueco que cerrar.
_HUECO_MIN_PT = 0.05


def _segmentos_contorno_muro(
    muro: Muro, escala: Optional[EscalaCalibrada],
) -> tuple[list[tuple[QPointF, QPointF]], QPainterPath]:
    """Bordes del polígono grueso del muro (caras + topes) como lista
    de segmentos, junto con el path del contorno (para `contains`)."""
    contorno = _contorno_muro_con_grosor(muro, muro.grosor_pt(escala))
    segs: list[tuple[QPointF, QPointF]] = []
    for poly in contorno.toSubpathPolygons():
        n = poly.count()
        if n < 2:
            continue
        pts = [poly.at(i) for i in range(n)]
        for i in range(n - 1):
            segs.append((pts[i], pts[i + 1]))
        if (pts[0] - pts[-1]).manhattanLength() > 1e-9:
            segs.append((pts[-1], pts[0]))
    return segs, contorno


def _rect_aprox_muro(muro: Muro, margen: float) -> QRectF:
    """Bbox barato del muro (sin construir el contorno) inflado por
    `margen`. Sirve para descartar rápido los muros lejanos."""
    if muro.es_arco():
        r = _rect_arco_3_puntos(*muro.vertices)
    else:
        xs = [v.x() for v in muro.vertices]
        ys = [v.y() for v in muro.vertices]
        r = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return r.adjusted(-margen, -margen, margen, margen)


def _t_rayo_segmento(
    o: QPointF, dx: float, dy: float, a: QPointF, b: QPointF,
) -> Optional[float]:
    """Distancia t ≥ 0 a la que el rayo o + t·(dx, dy) (dirección
    unitaria) cruza el segmento a→b. None si no lo cruza o si el cruce
    es casi paralelo."""
    ex, ey = b.x() - a.x(), b.y() - a.y()
    largo = math.hypot(ex, ey)
    if largo < 1e-9:
        return None
    den = dx * ey - dy * ex
    if abs(den) / largo < _MIN_SENO_CRUCE:
        return None
    wx, wy = a.x() - o.x(), a.y() - o.y()
    t = (wx * ey - wy * ex) / den
    u = (wx * dy - wy * dx) / den
    if t < -_EPS_EXT or u < -1e-9 or u > 1.0 + 1e-9:
        return None
    return max(0.0, t)


def _delta_circulo_segmento(
    centro: QPointF, radio: float, ang0_deg: float, sentido: float,
    a: QPointF, b: QPointF,
) -> Optional[float]:
    """Ángulo (grados, > 0) que hay que recorrer sobre la circunferencia
    (centro, radio), partiendo de `ang0_deg` en el `sentido` dado (+1 =
    antihorario en pantalla), hasta cruzar el segmento a→b. None si no
    lo cruza o si el cruce es casi tangente."""
    ex, ey = b.x() - a.x(), b.y() - a.y()
    fx, fy = a.x() - centro.x(), a.y() - centro.y()
    qa = ex * ex + ey * ey
    if qa < 1e-12:
        return None
    qb = 2.0 * (fx * ex + fy * ey)
    qc = fx * fx + fy * fy - radio * radio
    disc = qb * qb - 4.0 * qa * qc
    if disc < 0.0:
        return None
    raiz = math.sqrt(disc)
    largo = math.sqrt(qa)
    mejor: Optional[float] = None
    for u in ((-qb - raiz) / (2.0 * qa), (-qb + raiz) / (2.0 * qa)):
        if u < -1e-9 or u > 1.0 + 1e-9:
            continue
        px, py = a.x() + u * ex, a.y() + u * ey
        phi = math.degrees(math.atan2(-(py - centro.y()), px - centro.x()))
        delta = ((phi - ang0_deg) * sentido) % 360.0
        if delta <= 1e-6:
            continue
        # Tangente del arco en ese punto, en el sentido de avance
        pr = math.radians(phi)
        tx, ty = sentido * -math.sin(pr), sentido * -math.cos(pr)
        if abs(tx * ey - ty * ex) / largo < _MIN_SENO_CRUCE:
            continue
        if mejor is None or delta < mejor:
            mejor = delta
    return mejor


def calcular_extensiones_muro(
    muro_nuevo: Muro,
    muros_existentes: list[Muro],
    escala: Optional[EscalaCalibrada],
    umbral_pt: float,
    puntos_fijos: Optional[list[QPointF]] = None,
) -> list[dict]:
    """Calcula (sin modificar nada) cuánto hay que prolongar cada
    extremo libre de `muro_nuevo` para cerrar el hueco con el muro más
    cercano en su dirección de avance.

    Devuelve una lista (0, 1 o 2 elementos) de dicts:
      {"extremo": "inicio" | "fin", "desde": QPointF, "hasta": QPointF,
       "dist_pt": float, "muro_id": str}

    `puntos_fijos`: puntos que el operador enganchó a propósito con el
    snap (vértices y esquinas de otros muros). Un extremo que cae en
    uno de ellos no se extiende.
    """
    verts = muro_nuevo.vertices
    if muro_nuevo.cerrado or len(verts) < 2 or umbral_pt <= 0.0:
        return []
    if muro_nuevo.es_arco() and len(verts) != 3:
        return []
    g = muro_nuevo.grosor_pt(escala)
    off = _offset_por_justificacion(muro_nuevo, g)
    fijos = puntos_fijos or []
    resultado: list[dict] = []
    for extremo in ("inicio", "fin"):
        punto = verts[0] if extremo == "inicio" else verts[-1]
        if any(
            math.hypot(punto.x() - f.x(), punto.y() - f.y()) < 0.5
            for f in fijos
        ):
            continue
        # Candidatos cercanos (filtro barato por bbox)
        candidatos = [
            m for m in muros_existentes
            if m.vertices and m.id != muro_nuevo.id
            and _rect_aprox_muro(
                m, m.grosor_pt(escala) + umbral_pt + g,
            ).contains(punto)
        ]
        if not candidatos:
            continue
        geo = [(m, *_segmentos_contorno_muro(m, escala)) for m in candidatos]
        if muro_nuevo.es_arco():
            info = _extension_extremo_arco(
                verts, extremo, g, off, geo, umbral_pt,
            )
        else:
            info = _extension_extremo_lineal(
                verts, extremo, g, off, geo, umbral_pt,
            )
        if info is not None:
            hasta, dist, muro_id = info
            resultado.append({
                "extremo": extremo, "desde": QPointF(punto),
                "hasta": hasta, "dist_pt": dist, "muro_id": muro_id,
            })
    return resultado


def _extension_extremo_lineal(verts, extremo, g, off, geo, umbral_pt):
    if extremo == "fin":
        punto, otro = verts[-1], verts[-2]
        sx, sy = punto.x() - otro.x(), punto.y() - otro.y()
    else:
        punto, otro = verts[0], verts[1]
        sx, sy = otro.x() - punto.x(), otro.y() - punto.y()
    largo = math.hypot(sx, sy)
    if largo < 1e-9:
        return None
    sx, sy = sx / largo, sy / largo           # sentido de recorrido
    nx, ny = -sy, sx                          # normal (misma que el offset)
    dx, dy = (sx, sy) if extremo == "fin" else (-sx, -sy)  # hacia afuera
    esquinas = [
        QPointF(punto.x() + nx * (off + s * g / 2.0),
                punto.y() + ny * (off + s * g / 2.0))
        for s in (+1.0, -1.0)
    ]
    mejor = None
    for m, segs, contorno in geo:
        # Cada esquina del tope avanza hasta la cara del otro muro; una
        # esquina que YA está dentro de él cuenta como 0. Así un muro que
        # llega en ángulo con una esquina metida y la otra al aire (el
        # snap lo dejó con el eje justo en la cara) se completa hasta
        # que ambas toquen.
        ts = []
        for e in esquinas:
            if contorno.contains(e):
                ts.append(0.0)
                continue
            hits = [
                t for a, b in segs
                if (t := _t_rayo_segmento(e, dx, dy, a, b)) is not None
            ]
            if not hits:
                break
            ts.append(min(hits))
        if len(ts) != 2:
            continue
        t = max(ts)
        if t <= _HUECO_MIN_PT:
            return None          # ya está unido a este muro
        if t <= umbral_pt and (mejor is None or t < mejor[0]):
            mejor = (t, m.id)
    if mejor is None:
        return None
    t, muro_id = mejor
    return QPointF(punto.x() + dx * t, punto.y() + dy * t), t, muro_id


def _extension_extremo_arco(verts, extremo, g, off, geo, umbral_pt):
    p1, p2, p3 = verts
    res = _centro_radio_circulo_3_puntos(p1, p2, p3)
    if res is None:
        return None
    centro, radio = res
    a1 = _angulo_arcTo(p1, centro)
    a2 = _angulo_arcTo(p2, centro)
    a3 = _angulo_arcTo(p3, centro)
    signo = 1.0 if 0.0 < (a2 - a1) % 360.0 < (a3 - a1) % 360.0 else -1.0
    if extremo == "fin":
        ang0, sentido = a3, signo
    else:
        ang0, sentido = a1, -signo
    # Radios de las dos caras (misma convención que _arco_offset_3_puntos)
    radios = [radio + (off + s * g / 2.0) * signo for s in (+1.0, -1.0)]
    if min(radios) <= 0.0:
        return None
    ar = math.radians(ang0)
    esquinas = [
        QPointF(centro.x() + r * math.cos(ar), centro.y() - r * math.sin(ar))
        for r in radios
    ]
    mejor = None
    for m, segs, contorno in geo:
        deltas = []
        for r, e in zip(radios, esquinas):
            if contorno.contains(e):
                deltas.append(0.0)
                continue
            hits = [
                d for a, b in segs
                if (d := _delta_circulo_segmento(centro, r, ang0, sentido, a, b))
                is not None
            ]
            if not hits:
                break
            deltas.append(min(hits))
        if len(deltas) != 2:
            continue
        delta = max(deltas)
        largo = math.radians(delta) * radio
        if largo <= _HUECO_MIN_PT:
            return None          # ya está unido a este muro
        if largo <= umbral_pt and (mejor is None or largo < mejor[0]):
            mejor = (largo, delta, m.id)
    if mejor is None:
        return None
    largo, delta, muro_id = mejor
    af = math.radians(ang0 + sentido * delta)
    hasta = QPointF(
        centro.x() + radio * math.cos(af), centro.y() - radio * math.sin(af),
    )
    return hasta, largo, muro_id


def proyeccion_a_caras_muro(
    p: QPointF, muro: Muro, escala: Optional[EscalaCalibrada],
    radio: float,
) -> tuple[Optional[QPointF], float]:
    """Punto más cercano a `p` sobre el CONTORNO del muro (sus caras y
    topes), y su distancia al cuadrado. Es lo que usa el snap "nearest"
    para que un muro o habitación nuevo quede pegado a la cara del muro
    existente, no metido hasta su centro. Si el muro está lejos (más
    que `radio` + grosor) devuelve (None, inf) sin construir el
    contorno."""
    if not muro.vertices:
        return None, float("inf")
    g = muro.grosor_pt(escala)
    if not _rect_aprox_muro(muro, g + radio).contains(p):
        return None, float("inf")
    segs, _contorno = _segmentos_contorno_muro(muro, escala)
    mejor: Optional[QPointF] = None
    mejor_d2 = float("inf")
    for a, b in segs:
        q, d2 = _proyeccion_a_segmento(p, a, b)
        if d2 < mejor_d2:
            mejor_d2 = d2
            mejor = q
    return mejor, mejor_d2


def aplicar_extensiones_muro(
    vertices: list[QPointF], extensiones: list[dict],
) -> list[QPointF]:
    """Devuelve una copia de `vertices` con los extremos movidos según
    `calcular_extensiones_muro`."""
    nuevos = [QPointF(v) for v in vertices]
    for ext in extensiones:
        if ext["extremo"] == "inicio":
            nuevos[0] = QPointF(ext["hasta"])
        else:
            nuevos[-1] = QPointF(ext["hasta"])
    return nuevos


# ---------------------------------------------------------------------------
# Muro divisorio: grosor = hueco entre dos divisiones
# ---------------------------------------------------------------------------
#
# Cuando ya existen las habitaciones (o muros) y el operador traza el muro
# que va ENTRE dos de ellas, no hace falta escribir el grosor: se mide el
# hueco libre perpendicular al trazo, de una división a la siguiente. El
# largo lo sigue resolviendo el auto-extend.

_FRACCIONES_MUESTRA_TOPE = (0.2, 0.35, 0.5, 0.65, 0.8)


def _intervalo_libre_en_normal(
    p: QPointF, n: QPointF, obstaculos: list[tuple[str, QPainterPath]],
    alcance: float, tol: float,
) -> Optional[tuple[float, float, str, str]]:
    """Sobre la recta p + t·n (|t| ≤ alcance), el tramo LIBRE (fuera de
    toda habitación/muro) que contiene a p — o el más cercano si p quedó
    apenas metido en una división (≤ tol). Devuelve (t1, t2, id1, id2)
    con t1 < t2 y los ids de las divisiones que lo limitan, o None si de
    algún lado no hay división dentro del alcance."""
    a = QPointF(p.x() - n.x() * alcance, p.y() - n.y() * alcance)
    cortes: list[tuple[float, str]] = []
    for oid, path in obstaculos:
        for poly in path.toSubpathPolygons():
            k = poly.count()
            for i in range(k):
                e0, e1 = poly.at(i), poly.at((i + 1) % k)
                ex, ey = e1.x() - e0.x(), e1.y() - e0.y()
                den = n.x() * ey - n.y() * ex
                if abs(den) < 1e-12:
                    continue
                wx, wy = e0.x() - a.x(), e0.y() - a.y()
                t = (wx * ey - wy * ex) / den          # sobre la recta
                u = (wx * n.y() - wy * n.x()) / den     # sobre la arista
                if -1e-9 <= u <= 1.0 + 1e-9 and 0.0 <= t <= 2.0 * alcance:
                    cortes.append((t - alcance, oid))
    if not cortes:
        return None
    cortes.sort()
    ts = [-alcance] + [c[0] for c in cortes] + [alcance]
    ids = [""] + [c[1] for c in cortes] + [""]

    def _ocupado(t: float) -> bool:
        q = QPointF(p.x() + n.x() * t, p.y() + n.y() * t)
        return any(path.contains(q) for _oid, path in obstaculos)

    libres = []
    for i in range(len(ts) - 1):
        t1, t2 = ts[i], ts[i + 1]
        if t2 - t1 < 1e-6 or _ocupado((t1 + t2) / 2.0):
            continue
        # Unir con el tramo libre anterior si se tocan (cruces duplicados)
        if libres and abs(libres[-1][1] - t1) < 1e-6:
            libres[-1] = (libres[-1][0], t2, libres[-1][2], ids[i + 1])
        else:
            libres.append((t1, t2, ids[i], ids[i + 1]))
    mejor = None
    for t1, t2, i1, i2 in libres:
        dist = 0.0 if t1 <= 0.0 <= t2 else min(abs(t1), abs(t2))
        if dist <= tol and (mejor is None or dist < mejor[0]):
            mejor = (dist, (t1, t2, i1, i2))
    if mejor is None:
        return None
    t1, t2, i1, i2 = mejor[1]
    if not i1 or not i2:
        return None                    # de un lado no hay división
    return t1, t2, i1, i2


def detectar_hueco_divisorio(
    vertices: list[QPointF], es_arco: bool,
    obstaculos: list[tuple[str, QPainterPath]],
    alcance_pt: float, tol_pt: float,
) -> Optional[dict]:
    """Mide el hueco entre las dos divisiones (habitaciones o muros) a
    los lados del trazo de un muro nuevo, en varios puntos a lo largo de
    él. Devuelve None si no hay división de los dos lados, o:

      * "t1", "t2" — dónde empieza y termina el hueco, medido sobre la
        normal del trazo (la misma que usan la justificación y
        `_polilinea_offset`); t1 < 0 < t2 si el trazo va por dentro.
      * "min", "max" — el ancho más chico y más grande medido.
      * "ids" — (división del lado −normal, división del lado +normal).
    """
    tmp = Muro(
        id="__tope__", vertices=[QPointF(v) for v in vertices],
        tipo_geometria=TipoGeometriaMuro.ARCO if es_arco else TipoGeometriaMuro.LINEAL,
    )
    largo = _longitud_total_eje_muro(tmp)
    if largo <= 1e-6:
        return None
    medidas = []
    for f in _FRACCIONES_MUESTRA_TOPE:
        info = _punto_y_normal_en_muro(tmp, largo * f)
        if info is None:
            continue
        p, _t, n = info
        r = _intervalo_libre_en_normal(p, n, obstaculos, alcance_pt, tol_pt)
        if r is not None:
            medidas.append(r)
    # Al menos la mitad de las muestras deben ver una división de cada lado
    if len(medidas) < max(1, (len(_FRACCIONES_MUESTRA_TOPE) + 1) // 2):
        return None

    def _mediana(xs: list[float]) -> float:
        xs = sorted(xs)
        k = len(xs)
        return xs[k // 2] if k % 2 else (xs[k // 2 - 1] + xs[k // 2]) / 2.0

    anchos = [m[1] - m[0] for m in medidas]
    ids1 = max(set(m[2] for m in medidas), key=[m[2] for m in medidas].count)
    ids2 = max(set(m[3] for m in medidas), key=[m[3] for m in medidas].count)
    return {
        "t1": _mediana([m[0] for m in medidas]),
        "t2": _mediana([m[1] for m in medidas]),
        "min": min(anchos), "max": max(anchos),
        "ids": (ids1, ids2),
    }


def desplazar_trazo_muro(
    vertices: list[QPointF], es_arco: bool, desplazamiento_pt: float,
) -> list[QPointF]:
    """El mismo trazo movido `desplazamiento_pt` sobre su normal (misma
    convención que la justificación). Para centrar un muro divisorio en
    el hueco."""
    if abs(desplazamiento_pt) < 1e-9:
        return [QPointF(v) for v in vertices]
    if es_arco and len(vertices) == 3:
        res = _arco_offset_3_puntos(*vertices, desplazamiento_pt)
        return list(res) if res is not None else [QPointF(v) for v in vertices]
    return [QPointF(p) for p in _polilinea_offset(
        [QPointF(v) for v in vertices], desplazamiento_pt, False,
    )]


# ---------------------------------------------------------------------------
# Esquinas en L entre muros separados
# ---------------------------------------------------------------------------
#
# Cuando dos muros terminan en el MISMO punto (snap a extremo) y doblan,
# sus topes rectos dejan una muesca en la esquina exterior. El "remiendo"
# es el polígono que la rellena hasta donde se cruzan sus caras
# exteriores (como el inglete de un muro con quiebre). Se pinta con el
# relleno del muro y su contorno lo traza `BordesMurosItem`.

def _marco_extremo_muro(
    muro: Muro, extremo: str, escala: Optional[EscalaCalibrada],
) -> Optional[tuple]:
    """(P, u, offsets, grosor) del extremo de un muro lineal: P = punto
    del eje, u = dirección unitaria hacia AFUERA del muro, offsets = las
    dos caras medidas sobre perp(u) = (−u.y, u.x)."""
    v = muro.vertices
    if extremo == "fin":
        a, p = v[-2], v[-1]
    else:
        a, p = v[1], v[0]
    largo = math.hypot(p.x() - a.x(), p.y() - a.y())
    if largo < 1e-9:
        return None
    u = QPointF((p.x() - a.x()) / largo, (p.y() - a.y()) / largo)
    g = muro.grosor_pt(escala)
    off = _offset_por_justificacion(muro, g)
    # La normal propia del muro es perp(sentido de recorrido); en el
    # "inicio" el recorrido va contra u, así que sus offsets se invierten.
    signo = 1.0 if extremo == "fin" else -1.0
    return p, u, [signo * (off + g / 2.0), signo * (off - g / 2.0)], g


def _remiendo_esquina_L(
    muro_a: Muro, ext_a: str, muro_b: Muro, ext_b: str,
    escala: Optional[EscalaCalibrada],
) -> Optional[QPolygonF]:
    """Polígono que completa la esquina exterior entre el extremo `ext_a`
    de `muro_a` y el extremo `ext_b` de `muro_b` (mismo punto). None si
    no hace falta (muros alineados, vuelta en U, o ya cierran)."""
    fa = _marco_extremo_muro(muro_a, ext_a, escala)
    fb = _marco_extremo_muro(muro_b, ext_b, escala)
    if fa is None or fb is None:
        return None
    p, d1, offs_a, ga = fa
    _pb, ub, offs_b_propios, gb = fb
    # Se ve como UN muro que llega por A y sigue por B: d2 = dirección
    # que se aleja de la esquina por B. Offsets de B medidos sobre perp(d2).
    d2 = QPointF(-ub.x(), -ub.y())
    offs_b = [-o for o in offs_b_propios]
    m1 = QPointF(-d1.y(), d1.x())
    m2 = QPointF(-d2.y(), d2.x())
    cruz = d1.x() * d2.y() - d1.y() * d2.x()
    if abs(cruz) < 0.05:
        return None                       # alineados o vuelta en U

    def _cruce(oa: float, ob: float) -> tuple[QPointF, float]:
        rx = m2.x() * ob - m1.x() * oa
        ry = m2.y() * ob - m1.y() * oa
        det = -cruz
        t = (-rx * d2.y() + d2.x() * ry) / det
        x = QPointF(p.x() + m1.x() * oa + d1.x() * t,
                    p.y() + m1.y() * oa + d1.y() * t)
        return x, t

    pares = [(max(offs_a), max(offs_b)), (min(offs_a), min(offs_b))]
    cruces = [(_cruce(oa, ob), oa, ob) for oa, ob in pares]
    (x_ext, t_ext), oa, ob = max(cruces, key=lambda c: c[0][1])
    if t_ext <= 1e-6:
        return None
    tope_a = QPointF(p.x() + m1.x() * oa, p.y() + m1.y() * oa)
    tope_b = QPointF(p.x() + m2.x() * ob, p.y() + m2.y() * ob)
    if math.hypot(x_ext.x() - p.x(), x_ext.y() - p.y()) > _MITER_MAX * max(ga, gb):
        # Ángulo muy cerrado: en vez de un pico larguísimo, bisel.
        return QPolygonF([tope_a, tope_b, QPointF(p)])
    return QPolygonF([tope_a, x_ext, tope_b, QPointF(p)])


def remiendos_esquinas_muros(
    muros: list[Muro], escala: Optional[EscalaCalibrada],
) -> dict[str, list[QPolygonF]]:
    """{muro_id: [polígonos]} con los remiendos de las esquinas en L
    (exactamente dos muros rectos que terminan en el mismo punto)."""
    grupos: dict[tuple[int, int], list[tuple[Muro, str]]] = {}
    for m in muros:
        if m.es_arco() or m.cerrado or len(m.vertices) < 2:
            continue
        for ext, p in (("inicio", m.vertices[0]), ("fin", m.vertices[-1])):
            clave = (round(p.x() * 20), round(p.y() * 20))   # 0.05 pt
            grupos.setdefault(clave, []).append((m, ext))
    res: dict[str, list[QPolygonF]] = {}
    for extremos in grupos.values():
        if len(extremos) != 2 or extremos[0][0] is extremos[1][0]:
            continue
        (ma, ea), (mb, eb) = extremos
        poly = _remiendo_esquina_L(ma, ea, mb, eb, escala)
        if poly is not None:
            res.setdefault(ma.id, []).append(poly)
    return res


# ---------------------------------------------------------------------------
# Hatch por material — patrón de relleno visual del muro
# ---------------------------------------------------------------------------

# Estilo de brush para cada material. Se aplica al polígono del muro.
HATCH_POR_MATERIAL: dict[TipoMaterialMuro, Qt.BrushStyle] = {
    TipoMaterialMuro.CONCRETO_ARMADO:   Qt.BrushStyle.SolidPattern,
    TipoMaterialMuro.BLOCK:             Qt.BrushStyle.DiagCrossPattern,
    TipoMaterialMuro.TABIQUE_LADRILLO:  Qt.BrushStyle.Dense6Pattern,
    TipoMaterialMuro.TABLAROCA:         Qt.BrushStyle.FDiagPattern,
    TipoMaterialMuro.DIVISORIO_LIGERO:  Qt.BrushStyle.Dense7Pattern,
    TipoMaterialMuro.MIXTO:             Qt.BrushStyle.BDiagPattern,
    TipoMaterialMuro.SIN_ESPECIFICAR:   Qt.BrushStyle.Dense7Pattern,
}

# Color del hatch (líneas/puntos del patrón). El fondo del polígono
# es el color base del muro (más claro), para que el hatch se vea.
COLOR_HATCH_POR_MATERIAL: dict[TipoMaterialMuro, str] = {
    TipoMaterialMuro.CONCRETO_ARMADO:   "#8a8a8a",
    TipoMaterialMuro.BLOCK:             "#c8c8c8",
    TipoMaterialMuro.TABIQUE_LADRILLO:  "#c8c8c8",
    TipoMaterialMuro.TABLAROCA:         "#d8d8d8",
    TipoMaterialMuro.DIVISORIO_LIGERO:  "#d0d0d0",
    TipoMaterialMuro.MIXTO:             "#b8b8b8",
    TipoMaterialMuro.SIN_ESPECIFICAR:   "#a8a8a8",
}


# ---------------------------------------------------------------------------
# Medición sobre el eje del muro (para posicionar puertas/ventanas)
# ---------------------------------------------------------------------------

def _longitud_total_eje_muro(muro: Muro) -> float:
    """Longitud total del eje del muro en pt PDF.
    LINEAL: suma de segmentos.
    ARCO: longitud del arco por 3 puntos.
    """
    if muro.es_arco():
        return _longitud_arco_3_puntos(
            muro.vertices[0], muro.vertices[1], muro.vertices[2],
        )
    total = 0.0
    for i in range(len(muro.vertices) - 1):
        dx = muro.vertices[i + 1].x() - muro.vertices[i].x()
        dy = muro.vertices[i + 1].y() - muro.vertices[i].y()
        total += math.hypot(dx, dy)
    if muro.cerrado and len(muro.vertices) >= 3:
        dx = muro.vertices[0].x() - muro.vertices[-1].x()
        dy = muro.vertices[0].y() - muro.vertices[-1].y()
        total += math.hypot(dx, dy)
    return total


def _punto_y_normal_en_muro(
    muro: Muro, d_desde_inicio_pt: float,
) -> Optional[tuple[QPointF, QPointF, QPointF]]:
    """Dado un muro y una distancia acumulada `d` sobre el eje desde
    el vértice inicial, devuelve `(punto, tangente_unitaria, normal_unitaria)`.

    La normal apunta a la izquierda del sentido de recorrido (mano
    derecha en Qt Y-down = izquierda visual). Devuelve None si `d`
    queda fuera del muro."""
    largo = _longitud_total_eje_muro(muro)
    if largo <= 0.0:
        return None
    d = max(0.0, min(d_desde_inicio_pt, largo))

    if muro.es_arco():
        return _punto_y_normal_en_arco(muro, d)

    # LINEAL: buscar el segmento donde cae d
    acc = 0.0
    segs = list(range(len(muro.vertices) - 1))
    if muro.cerrado and len(muro.vertices) >= 3:
        segs.append(-1)  # segmento de cierre
    for i in segs:
        a = muro.vertices[i]
        b = muro.vertices[(i + 1) % len(muro.vertices)] if i == -1 \
            else muro.vertices[i + 1]
        dx = b.x() - a.x()
        dy = b.y() - a.y()
        largo_seg = math.hypot(dx, dy)
        if largo_seg < 1e-9:
            continue
        if acc + largo_seg >= d:
            t = (d - acc) / largo_seg
            pt = QPointF(a.x() + t * dx, a.y() + t * dy)
            tx, ty = dx / largo_seg, dy / largo_seg
            nx, ny = -ty, tx
            return pt, QPointF(tx, ty), QPointF(nx, ny)
        acc += largo_seg
    # Si d == largo exacto, devolver punto final del último segmento
    ultimo = muro.vertices[-1]
    penultimo = muro.vertices[-2] if len(muro.vertices) >= 2 else ultimo
    dx = ultimo.x() - penultimo.x()
    dy = ultimo.y() - penultimo.y()
    ls = math.hypot(dx, dy) or 1.0
    tx, ty = dx / ls, dy / ls
    return ultimo, QPointF(tx, ty), QPointF(-ty, tx)


def _punto_y_normal_en_arco(
    muro: Muro, d_desde_inicio_pt: float,
) -> Optional[tuple[QPointF, QPointF, QPointF]]:
    """Versión para muro ARCO: parametriza sobre el arco por 3 puntos."""
    p1, p2, p3 = muro.vertices[0], muro.vertices[1], muro.vertices[2]
    resultado = _centro_radio_circulo_3_puntos(p1, p2, p3)
    if resultado is None:
        # Colineales: fallback recto p1 → p3
        dx = p3.x() - p1.x()
        dy = p3.y() - p1.y()
        largo = math.hypot(dx, dy) or 1.0
        t = d_desde_inicio_pt / largo
        pt = QPointF(p1.x() + t * dx, p1.y() + t * dy)
        tx, ty = dx / largo, dy / largo
        return pt, QPointF(tx, ty), QPointF(-ty, tx)

    centro, radio = resultado
    a1 = _angulo_arcTo(p1, centro)
    a2 = _angulo_arcTo(p2, centro)
    a3 = _angulo_arcTo(p3, centro)
    d13_ccw = (a3 - a1) % 360.0
    d12_ccw = (a2 - a1) % 360.0
    if 0.0 < d12_ccw < d13_ccw:
        sweep_deg = d13_ccw          # CCW
        signo = +1.0
    else:
        sweep_deg = 360.0 - d13_ccw  # CW
        signo = -1.0
    largo_total = abs(math.radians(sweep_deg)) * radio
    if largo_total <= 0.0:
        return None
    t = d_desde_inicio_pt / largo_total
    ang_deg = a1 + signo * t * sweep_deg
    ang_rad = math.radians(ang_deg)
    # x = cx + r*cos(a), y = cy - r*sin(a)  (invertido por Y-down)
    px = centro.x() + radio * math.cos(ang_rad)
    py = centro.y() - radio * math.sin(ang_rad)
    # Tangente: derivada del punto respecto a d (dirección en la que
    # CRECE d). Con P(a) = C + r·(cos a, −sin a):
    #   dP/da = r·(−sin a, −cos a), y a crece con d si signo = +1.
    # (Antes tenía un signo de más y la tangente apuntaba al revés,
    # lo que volteaba pivote y normal de puertas en muros curvos.)
    tx = signo * (-math.sin(ang_rad))
    ty = signo * (-math.cos(ang_rad))
    largo_tan = math.hypot(tx, ty) or 1.0
    tx /= largo_tan
    ty /= largo_tan
    return QPointF(px, py), QPointF(tx, ty), QPointF(-ty, tx)


def punto_cuerpo_muro(
    muro: Muro, d_desde_inicio_pt: float,
    escala: Optional[EscalaCalibrada],
) -> Optional[tuple[QPointF, QPointF, QPointF, float]]:
    """Como `_punto_y_normal_en_muro`, pero el punto devuelto está en
    el CENTRO DEL CUERPO del muro, no sobre la línea trazada.

    Cuando el muro tiene justificación IZQUIERDA o DERECHA, la línea
    que dibujó el operador es una de las caras y el cuerpo físico queda
    desplazado medio grosor hacia un lado. Puertas, ventanas y huecos
    deben centrarse en el cuerpo — si no, quedan medio fuera del muro.

    Devuelve `(centro_cuerpo, tangente, normal, grosor_pt)`, o None si
    la distancia cae fuera del muro.
    """
    info = _punto_y_normal_en_muro(muro, d_desde_inicio_pt)
    if info is None:
        return None
    pt, tang, normal = info
    grosor = muro.grosor_pt(escala)
    off = _offset_por_justificacion(muro, grosor)
    centro = QPointF(pt.x() + normal.x() * off, pt.y() + normal.y() * off)
    return centro, tang, normal, grosor


def angulo_barrido_puerta(
    pivote: QPointF, otro_extremo: QPointF, hoja_abierta: QPointF,
) -> tuple[float, float]:
    """Ángulos (grados, convención de `QPainter.drawArc`: 0° a las 3,
    positivo = antihorario en pantalla) para el arco de barrido de una
    puerta: parte de la hoja CERRADA (del pivote hacia el otro extremo
    del hueco) y termina en la hoja ABIERTA. Devuelve
    `(angulo_inicial, barrido)` con barrido = ±90°.

    Se calcula a partir de las direcciones reales en vez de suponer el
    signo, así funciona igual con cualquier pivote, lado o muro curvo.
    """
    a_ini = math.degrees(math.atan2(
        -(otro_extremo.y() - pivote.y()), otro_extremo.x() - pivote.x(),
    ))
    a_fin = math.degrees(math.atan2(
        -(hoja_abierta.y() - pivote.y()), hoja_abierta.x() - pivote.x(),
    ))
    barrido = (a_fin - a_ini + 540.0) % 360.0 - 180.0
    return a_ini, barrido


# ---------------------------------------------------------------------------
# Geometría de aberturas que SIGUE el trazo del muro
# ---------------------------------------------------------------------------
#
# Una abertura ocupa el intervalo [d_a, d_b] a lo largo del eje del muro.
# En lugar de un rectángulo recto (que en un zigzag se sale del muro o
# muerde el tramo vecino), su hueco y su símbolo siguen la polilínea:
#
#   * En los extremos de la abertura el corte es perpendicular a su tramo.
#   * En un quiebre INTERIOR a la abertura, dobla con inglete (la ventana
#     da la vuelta a la esquina).
#   * El extremo queda EXACTAMENTE donde se hizo clic. Si cae en la
#     "zona de esquina" de un quiebre (donde un corte perpendicular ya
#     cruzaría la diagonal de la esquina), el corte va en diagonal: de la
#     esquina interior al punto marcado — como en los planos de CAD. En
#     la punta de la esquina es el inglete completo. Ver
#     `corte_extremo_abertura` y `d_extremo_abertura`.
#   * En muros curvos se muestrea el arco, así la ventana sigue la curva.

_TOL_VERTICE = 1e-3
# Traslape mínimo (pt) de las celdas de tramo más allá de sus ingletes;
# ver `_celdas_tramos_muro`. Invisible a cualquier zoom práctico.
_EPS_CELDA = 0.02
# Margen extra del hueco más allá de las caras (pt): asegura que la resta
# del hueco no deje una línea de muro por antialias.
_MARGEN_HUECO_PT = 4.0


def _tramos_muro_lineal(muro: Muro) -> list[tuple[int, int, float, float]]:
    """(i, j, d_inicio, d_fin) de cada tramo de un muro lineal, incluido
    el de cierre si el muro es cerrado."""
    v = muro.vertices
    pares = [(i, i + 1) for i in range(len(v) - 1)]
    if muro.cerrado and len(v) >= 3:
        pares.append((len(v) - 1, 0))
    tramos = []
    acc = 0.0
    for i, j in pares:
        largo = math.hypot(v[j].x() - v[i].x(), v[j].y() - v[i].y())
        tramos.append((i, j, acc, acc + largo))
        acc += largo
    return tramos


def distancias_quiebres_muro(muro: Muro) -> list[float]:
    """Distancias a lo largo del eje donde hay un quiebre o un extremo
    del muro (0, cada vértice interior, largo total). En un muro curvo,
    sólo sus dos extremos."""
    largo = _longitud_total_eje_muro(muro)
    if muro.es_arco():
        return [0.0, largo]
    ds = [0.0]
    for _i, _j, _s, e in _tramos_muro_lineal(muro):
        ds.append(e)
    return ds


def _quiebres_interiores(muro: Muro) -> list[tuple[int, float]]:
    """(índice del vértice, distancia d) de cada quiebre INTERIOR de un
    muro lineal (no incluye sus dos extremos, salvo en muros cerrados
    donde todos los vértices son quiebres)."""
    if muro.es_arco():
        return []
    tramos = _tramos_muro_lineal(muro)
    res = [(j, e) for k, (_i, j, _s, e) in enumerate(tramos)
           if k < len(tramos) - 1]
    if muro.cerrado and tramos:
        # En un muro cerrado el vértice 0 también es esquina (d = 0 y
        # d = largo total son el mismo punto).
        res += [(0, 0.0), (0, tramos[-1][3])]
    return res


def _esquina_muro(
    muro: Muro, j: int, grosor: float, off: float, lado: int,
) -> Optional[dict]:
    """Esquina en el vértice interior `j` de un muro recto (abierto),
    vista desde el tramo del lado `lado` (+1: el tramo que SALE de j,
    −1: el que LLEGA a j). None si el muro no dobla ahí.

    Devuelve {"q", "V", "u", "c_in", "c_out", "l_in", "l_out"}:
      * u      — dirección unitaria desde el vértice hacia adentro del tramo.
      * c_in   — esquina interior (lado cóncavo) sobre la diagonal/inglete.
      * c_out  — esquina exterior (la punta).
      * l_in / l_out — coordenada de cada esquina a lo largo de u, medida
        desde el vértice (l_in > 0: queda dentro del tramo; l_out < 0:
        queda "más allá" del vértice)."""
    v = muro.vertices
    n = len(v)
    if muro.cerrado or j <= 0 or j >= n - 1:
        return None
    vert = v[j]
    otro = v[j + 1] if lado > 0 else v[j - 1]
    largo = math.hypot(otro.x() - vert.x(), otro.y() - vert.y())
    if largo < 1e-9:
        return None
    u = QPointF((otro.x() - vert.x()) / largo, (otro.y() - vert.y()) / largo)
    x = _polilinea_offset(v, off + grosor / 2.0, False)[j]
    y = _polilinea_offset(v, off - grosor / 2.0, False)[j]
    lx = (x.x() - vert.x()) * u.x() + (x.y() - vert.y()) * u.y()
    ly = (y.x() - vert.x()) * u.x() + (y.y() - vert.y()) * u.y()
    if abs(lx - ly) < 1e-6:
        return None                     # el muro sigue recto
    c_in, l_in, c_out, l_out = (x, lx, y, ly) if lx > ly else (y, ly, x, lx)
    q = _tramos_muro_lineal(muro)[j - 1][3]
    return {"q": q, "V": QPointF(vert), "u": u, "c_in": QPointF(c_in),
            "c_out": QPointF(c_out), "l_in": l_in, "l_out": l_out}


def _zona_esquina_extremo(
    muro: Muro, d: float, lado: int, grosor: float, off: float,
) -> Optional[dict]:
    """Si el extremo `d` de una abertura (con la abertura hacia `lado`:
    +1 = hacia d mayores, −1 = hacia d menores) cae en la ZONA DE ESQUINA
    de un quiebre — donde un corte perpendicular ya cruzaría la diagonal
    de la esquina —, devuelve la esquina (ver `_esquina_muro`) más:
      * "lam" — coordenada del extremo a lo largo de u (lado·(d − q)).
      * "F"   — punto de la cara exterior del tramo a esa coordenada.
    En esa zona el corte va de la esquina interior `c_in` a `F`: es una
    diagonal que gira según qué tan cerca de la esquina esté el punto
    (en la punta, `F = c_out`, es el inglete completo)."""
    if muro.es_arco() or muro.cerrado:
        return None
    mejor = None
    for j, _q in _quiebres_interiores(muro):
        e = _esquina_muro(muro, j, grosor, off, lado)
        if e is None:
            continue
        lam = lado * (d - e["q"])
        if e["l_out"] - 1e-6 <= lam < e["l_in"] - 1e-9:
            lam = max(lam, e["l_out"])
            if mejor is None or abs(lam) < abs(mejor["lam"]):
                u, c_out = e["u"], e["c_out"]
                mejor = dict(e, lam=lam, F=QPointF(
                    c_out.x() + u.x() * (lam - e["l_out"]),
                    c_out.y() + u.y() * (lam - e["l_out"]),
                ))
    return mejor


def d_extremo_abertura(
    muro: Muro, p: QPointF, lado: int, escala: Optional[EscalaCalibrada],
) -> float:
    """Distancia d (a lo largo del eje) del extremo de una abertura
    marcado con un clic en `p`, sabiendo hacia qué lado queda la abertura.

    Lejos de las esquinas es la proyección de `p` sobre el eje: el corte
    perpendicular pasa exactamente por donde se hizo clic. Cerca de una
    esquina se mide sobre el tramo donde va la abertura (aunque `p` quede
    "más allá" del vértice, hacia la punta), para que el corte diagonal
    pase por el punto marcado."""
    proy = proyectar_punto_sobre_muro(p, muro)
    d0 = proy[2] if proy is not None else 0.0
    if muro.es_arco() or muro.cerrado:
        return d0
    g = muro.grosor_pt(escala)
    off = _offset_por_justificacion(muro, g)
    mejor = None
    for j, _q in _quiebres_interiores(muro):
        e = _esquina_muro(muro, j, g, off, lado)
        if e is None:
            continue
        u, vert = e["u"], e["V"]
        dx, dy = p.x() - vert.x(), p.y() - vert.y()
        lam = dx * u.x() + dy * u.y()
        # Coordenada lateral: `p` debe caer en la franja de ESTE tramo
        # (entre sus dos caras, con un grosor de holgura).
        w = u.x() * dy - u.y() * dx
        w_in = u.x() * (e["c_in"].y() - vert.y()) - u.y() * (e["c_in"].x() - vert.x())
        w_out = u.x() * (e["c_out"].y() - vert.y()) - u.y() * (e["c_out"].x() - vert.x())
        if not (min(w_in, w_out) - g <= w <= max(w_in, w_out) + g):
            continue
        if e["l_out"] - g <= lam < e["l_in"]:
            lam = max(lam, e["l_out"])
            if mejor is None or abs(lam) < abs(mejor[0]):
                mejor = (lam, e["q"] + lado * lam)
    return mejor[1] if mejor is not None else d0


def corte_extremo_abertura(
    muro: Muro, d: float, lado: int, escala: Optional[EscalaCalibrada],
) -> Optional[tuple[QPointF, QPointF, str]]:
    """Línea donde se corta el muro en el extremo `d` de una abertura,
    de cara a cara. Devuelve `(p1, p2, tipo)` con tipo:
      * "esquina"  — la diagonal completa de la esquina (inglete).
      * "diagonal" — de la esquina interior al punto marcado en la otra
                     cara (el extremo cayó en la zona de esquina).
      * "extremo"  — el tope de un extremo libre del muro.
      * "recto"    — perpendicular al tramo.
    Es la misma línea que limita el hueco en `geometria_abertura`."""
    g = muro.grosor_pt(escala)
    off = _offset_por_justificacion(muro, g)
    z = _zona_esquina_extremo(muro, d, lado, g, off)
    if z is not None:
        tipo = "esquina" if z["lam"] <= z["l_out"] + 1e-6 else "diagonal"
        return QPointF(z["c_in"]), QPointF(z["F"]), tipo
    largo = _longitud_total_eje_muro(muro)
    info = punto_cuerpo_muro(muro, max(0.0, min(d, largo)), escala)
    if info is None:
        return None
    centro, _t, n, grosor = info
    en_extremo = not muro.cerrado and (d <= _TOL_VERTICE or d >= largo - _TOL_VERTICE)
    return (
        QPointF(centro.x() + n.x() * grosor / 2.0, centro.y() + n.y() * grosor / 2.0),
        QPointF(centro.x() - n.x() * grosor / 2.0, centro.y() - n.y() * grosor / 2.0),
        "extremo" if en_extremo else "recto",
    )


def puntos_enganche_abertura(
    muro: Muro, escala: Optional[EscalaCalibrada],
) -> list[tuple[QPointF, QPointF]]:
    """Puntos a los que se engancha el clic de una puerta/ventana cuando
    el Snap está encendido: (punto visible, punto que se usa).
      * Esquinas de cada quiebre (interior y punta) → ellas mismas.
      * Extremos libres del muro (eje y esquinas del tope) → el extremo
        del eje."""
    g = muro.grosor_pt(escala)
    off = _offset_por_justificacion(muro, g)
    res: list[tuple[QPointF, QPointF]] = []
    if not muro.es_arco() and not muro.cerrado:
        for j, _q in _quiebres_interiores(muro):
            e = _esquina_muro(muro, j, g, off, +1)
            if e is not None:
                res += [(e["c_in"], e["c_in"]), (e["c_out"], e["c_out"])]
    if not muro.cerrado:
        largo = _longitud_total_eje_muro(muro)
        for d in (0.0, largo):
            eje = _punto_y_normal_en_muro(muro, d)
            cuerpo = punto_cuerpo_muro(muro, d, escala)
            if eje is None or cuerpo is None:
                continue
            centro, _t, n, grosor = cuerpo
            for s in (0.0, +0.5, -0.5):
                res.append((QPointF(centro.x() + n.x() * grosor * s,
                                    centro.y() + n.y() * grosor * s),
                            QPointF(eje[0])))
    return res


def linea_corte_abertura(
    muro: Muro, d: float, escala: Optional[EscalaCalibrada], lado: int = -1,
) -> Optional[tuple[QPointF, QPointF, bool]]:
    """Compatibilidad: como `corte_extremo_abertura`, con el tercer valor
    = True si el corte va por una esquina o un extremo del muro."""
    c = corte_extremo_abertura(muro, d, lado, escala)
    if c is None:
        return None
    return c[0], c[1], c[2] in ("esquina", "extremo")


def _puntos_eje_tramo(muro: Muro, d_a: float, d_b: float) -> list[QPointF]:
    """Puntos del EJE del muro entre las distancias d_a < d_b: el punto
    en d_a, los vértices intermedios (muro lineal) o muestras del arco
    (muro curvo), y el punto en d_b."""
    largo = _longitud_total_eje_muro(muro)
    d_a = max(0.0, min(d_a, largo))
    d_b = max(0.0, min(d_b, largo))
    if d_b - d_a < 1e-6:
        return []

    def _pt(d: float) -> Optional[QPointF]:
        info = _punto_y_normal_en_muro(muro, d)
        return QPointF(info[0]) if info is not None else None

    if muro.es_arco():
        res = _centro_radio_circulo_3_puntos(*muro.vertices)
        radio = res[1] if res is not None else 1.0
        barrido = math.degrees((d_b - d_a) / max(radio, 1e-6))
        n = max(2, min(240, int(math.ceil(barrido / 3.0))))
        pts = [_pt(d_a + (d_b - d_a) * k / n) for k in range(n + 1)]
        return [p for p in pts if p is not None]

    pts: list[QPointF] = []
    inicio = _pt(d_a)
    if inicio is not None:
        pts.append(inicio)
    for _i, j, _s, e in _tramos_muro_lineal(muro):
        if d_a + _TOL_VERTICE < e < d_b - _TOL_VERTICE:
            pts.append(QPointF(muro.vertices[j]))
    fin = _pt(d_b)
    if fin is not None:
        pts.append(fin)
    return pts


def _celdas_tramos_muro(
    muro: Muro, off: float, alto: float, d_a: float, d_b: float,
) -> QPainterPath:
    """Unión de las "celdas" de los tramos que toca la abertura: la
    parte del cuerpo del muro que le pertenece a cada tramo, limitada
    por las bisectrices (ingletes) en sus quiebres."""
    v = muro.vertices
    borde1 = _polilinea_offset(v, off + alto / 2.0, muro.cerrado)
    borde2 = _polilinea_offset(v, off - alto / 2.0, muro.cerrado)
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for i, j, s, e in _tramos_muro_lineal(muro):
        if s < d_b - _TOL_VERTICE and e > d_a + _TOL_VERTICE:
            # Cada celda se alarga un pelo (_EPS_CELDA) más allá de sus
            # ingletes: si el borde del hueco cayera EXACTO sobre la
            # diagonal de la esquina, pasaría justo por las esquinas del
            # contorno del muro y la resta de Qt (que falla con bordes y
            # vértices coincidentes) se comía el resto del muro.
            largo = math.hypot(v[j].x() - v[i].x(), v[j].y() - v[i].y()) or 1.0
            ux = (v[j].x() - v[i].x()) / largo * _EPS_CELDA
            uy = (v[j].y() - v[i].y()) / largo * _EPS_CELDA
            path.addPolygon(QPolygonF([
                QPointF(borde1[i].x() - ux, borde1[i].y() - uy),
                QPointF(borde1[j].x() + ux, borde1[j].y() + uy),
                QPointF(borde2[j].x() + ux, borde2[j].y() + uy),
                QPointF(borde2[i].x() - ux, borde2[i].y() - uy),
            ]))
            path.closeSubpath()
    return path.simplified()


def _semiplano_corte(z: dict, largo: float) -> QPainterPath:
    """Semiplano (como polígono grande) del lado de la abertura respecto
    a su corte diagonal c_in → F. El corte se corre 2·_EPS_CELDA hacia
    afuera de la abertura para que no pase exacto por la esquina
    interior del contorno (Qt falla con vértices coincidentes)."""
    u = z["u"]
    ex, ey = -u.x() * 2.0 * _EPS_CELDA, -u.y() * 2.0 * _EPS_CELDA
    a = QPointF(z["c_in"].x() + ex, z["c_in"].y() + ey)
    b = QPointF(z["F"].x() + ex, z["F"].y() + ey)
    wx, wy = b.x() - a.x(), b.y() - a.y()
    n = math.hypot(wx, wy) or 1.0
    wx, wy = wx / n * largo, wy / n * largo
    a = QPointF(a.x() - wx, a.y() - wy)
    b = QPointF(b.x() + wx, b.y() + wy)
    path = QPainterPath()
    path.addPolygon(QPolygonF([
        a, b,
        QPointF(b.x() + u.x() * largo, b.y() + u.y() * largo),
        QPointF(a.x() + u.x() * largo, a.y() + u.y() * largo),
    ]))
    path.closeSubpath()
    return path


def geometria_abertura(
    muro: Muro, d_centro: float, ancho: float,
    escala: Optional[EscalaCalibrada],
) -> Optional[dict]:
    """Geometría de una abertura (puerta o ventana) que sigue el trazo
    del muro. Devuelve None si no cabe en el muro. Claves:

      * "eje"    — puntos del eje del muro a lo largo de la abertura
                   (prolongados en línea recta en un extremo de esquina;
                   el hueco los recorta).
      * "grosor" — grosor del muro (pt).
      * "offset" — desplazamiento del cuerpo por la justificación (pt).
      * "hueco"  — QPainterPath del hueco a restar del muro (llega un
                   poco más allá de las caras para que el corte sea limpio).

    Los extremos se cortan como dice `corte_extremo_abertura`:
    perpendicular, en diagonal hacia la esquina interior si caen en la
    zona de una esquina, o por el inglete completo en la punta."""
    d_a, d_b = d_centro - ancho / 2.0, d_centro + ancho / 2.0
    g = muro.grosor_pt(escala)
    off = _offset_por_justificacion(muro, g)
    alto = g + 2.0 * _MARGEN_HUECO_PT
    if muro.es_arco():
        eje = _puntos_eje_tramo(muro, d_a, d_b)
        if len(eje) < 2:
            return None
        borde1 = _polilinea_offset(eje, off + alto / 2.0, False)
        borde2 = _polilinea_offset(eje, off - alto / 2.0, False)
        hueco = QPainterPath()
        hueco.addPolygon(QPolygonF(borde1 + list(reversed(borde2))))
        hueco.closeSubpath()
        return {"eje": eje, "grosor": g, "offset": off, "hueco": hueco}

    za = _zona_esquina_extremo(muro, d_a, +1, g, off)
    zb = _zona_esquina_extremo(muro, d_b, -1, g, off)
    # En la zona de esquina el eje de la abertura llega a lo mucho al
    # vértice; de ahí sigue en línea recta (el corte diagonal lo limita).
    d_a_eje = za["q"] if za is not None and d_a < za["q"] else d_a
    d_b_eje = zb["q"] if zb is not None and d_b > zb["q"] else d_b
    eje = _puntos_eje_tramo(muro, d_a_eje, d_b_eje)
    if len(eje) < 2:
        return None
    largo_muro = _longitud_total_eje_muro(muro)
    largo_ext = alto * _MITER_MAX
    eje = list(eje)

    def _prolongar(p: QPointF, previo: QPointF) -> QPointF:
        dx, dy = p.x() - previo.x(), p.y() - previo.y()
        n = math.hypot(dx, dy) or 1.0
        return QPointF(p.x() + dx / n * largo_ext, p.y() + dy / n * largo_ext)

    # En la zona de esquina y en los extremos libres, el hueco sigue de
    # largo: así se come el tope completo / llega a la diagonal sin que
    # su borde coincida con el del contorno.
    if za is not None or (not muro.cerrado and d_a_eje <= _TOL_VERTICE):
        eje.insert(0, _prolongar(eje[0], eje[1]))
    if zb is not None or (not muro.cerrado and d_b_eje >= largo_muro - _TOL_VERTICE):
        eje.append(_prolongar(eje[-1], eje[-2]))
    borde1 = _polilinea_offset(eje, off + alto / 2.0, False)
    borde2 = _polilinea_offset(eje, off - alto / 2.0, False)
    hueco = QPainterPath()
    hueco.addPolygon(QPolygonF(borde1 + list(reversed(borde2))))
    hueco.closeSubpath()
    # La celda sólo debe recortar en las BISECTRICES de los quiebres.
    # Se construye 3 veces más ancha que el hueco para que sus bordes
    # laterales nunca coincidan con los del hueco: el recorte de Qt no
    # es fiable con bordes exactamente superpuestos.
    hueco = hueco.intersected(
        _celdas_tramos_muro(muro, off, alto * 3.0, d_a_eje, d_b_eje),
    )
    largo_semi = ancho + 10.0 * alto + largo_ext
    for z in (za, zb):
        if z is not None and z["lam"] > z["l_out"] + 1e-6:
            hueco = hueco.intersected(_semiplano_corte(z, largo_semi))
    if hueco.isEmpty():
        return None
    return {"eje": eje, "grosor": g, "offset": off, "hueco": hueco}


def dibujar_simbolo_ventana(
    painter: QPainter, geo: dict, escala_painter: float,
    color_caras: QColor, color_cristal: QColor,
) -> None:
    """Símbolo de ventana en planta, recortado al hueco: las dos CARAS
    del muro siguen a lo largo del vano y el CRISTAL va al centro. Lo
    usan la ventana colocada y su preview, así se ven idénticas."""
    eje, grosor, off = geo["eje"], geo["grosor"], geo["offset"]
    grosor_ln = max(1.4 / escala_painter, 0.3)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setClipPath(geo["hueco"], Qt.ClipOperation.IntersectClip)

    def _linea(desplazamiento: float) -> None:
        pts = _polilinea_offset(eje, off + desplazamiento, False)
        painter.drawPolyline(QPolygonF(pts))

    pen_caras = QPen(color_caras)
    pen_caras.setWidthF(grosor_ln * 0.9)
    pen_caras.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen_caras.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen_caras)
    _linea(+grosor / 2.0)
    _linea(-grosor / 2.0)

    pen_cristal = QPen(color_cristal)
    pen_cristal.setWidthF(grosor_ln * 1.5)
    pen_cristal.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen_cristal.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen_cristal)
    if grosor >= 6.0:
        # Muro con cuerpo suficiente: cristal doble (vidrio + marco)
        _linea(+grosor / 8.0)
        _linea(-grosor / 8.0)
    else:
        _linea(0.0)
    painter.restore()


# ---------------------------------------------------------------------------
# DialogoNombreHabitacion
# ---------------------------------------------------------------------------

class DialogoNombreHabitacion(QDialog):
    """Modal minimal para asignar nombre a una habitación recién
    dibujada. Foco directo en el input, Enter acepta."""

    def __init__(
        self,
        area_m2: Optional[float],
        parent: Optional[QWidget] = None,
        valor_sugerido: str = "",
        tipo_sugerido: TipoUsoHabitacion = TipoUsoHabitacion.OTRO,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nombrar habitación")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedSize(440, 280)
        self.setStyleSheet(self._stylesheet())

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(8)

        titulo = QLabel("Configurar habitación")
        titulo.setObjectName("tituloDialogo")
        v.addWidget(titulo)

        if area_m2 is not None:
            desc_txt = (
                f"Área calculada: <b>{area_m2:.2f} m²</b>. "
                "Elige el <b>tipo de uso</b> (para agrupación NOM y "
                "cálculo de carga) y un <b>nombre descriptivo</b>."
            )
        else:
            desc_txt = (
                "Sin escala calibrada aún. El área se calculará "
                "cuando calibres el plano. Elige el <b>tipo de uso</b> y "
                "un <b>nombre descriptivo</b>."
            )
        desc = QLabel(desc_txt)
        desc.setObjectName("descripcionDialogo")
        desc.setWordWrap(True)
        v.addWidget(desc)

        # Tipo de uso
        lbl_tipo = QLabel("Tipo de uso")
        lbl_tipo.setObjectName("etiquetaCampo")
        v.addWidget(lbl_tipo)

        self._combo_tipo = QComboBox()
        for t, label in USO_HABITACION_LABELS.items():
            self._combo_tipo.addItem(label, t)
        # Preseleccionar el tipo sugerido
        idx = self._combo_tipo.findData(tipo_sugerido)
        if idx >= 0:
            self._combo_tipo.setCurrentIndex(idx)
        # Al cambiar de tipo, pre-llenar el nombre si estaba vacío o
        # coincidía con el label del tipo anterior.
        self._combo_tipo.currentIndexChanged.connect(
            self._on_tipo_cambiado
        )
        v.addWidget(self._combo_tipo)

        # Nombre
        lbl_nombre = QLabel("Nombre (para el plano)")
        lbl_nombre.setObjectName("etiquetaCampo")
        v.addWidget(lbl_nombre)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Ej. Sala principal, Baño 1, Recámara padres…"
        )
        # Sugerencia inicial: el label del tipo elegido, si no hay valor.
        if valor_sugerido:
            self._input.setText(valor_sugerido)
        else:
            self._input.setText(USO_HABITACION_LABELS.get(tipo_sugerido, ""))
        v.addWidget(self._input)

        v.addStretch(1)

        botones = QHBoxLayout()
        botones.setSpacing(8)
        botones.addStretch(1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("secundario")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_cancel.clicked.connect(self.reject)
        botones.addWidget(btn_cancel)

        btn_ok = QPushButton("Aplicar")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        botones.addWidget(btn_ok)

        v.addLayout(botones)

        self._input.setFocus()
        self._input.selectAll()

    def nombre(self) -> str:
        return self._input.text().strip()

    def tipo_uso(self) -> TipoUsoHabitacion:
        return self._combo_tipo.currentData() or TipoUsoHabitacion.OTRO

    def _on_tipo_cambiado(self, _idx: int) -> None:
        # Sugerencia de nombre: si el usuario aún no personalizó el
        # nombre (está vacío o coincide con algún label del enum),
        # ponemos el label del nuevo tipo.
        actual = self._input.text().strip()
        etiquetas = set(USO_HABITACION_LABELS.values())
        if not actual or actual in etiquetas:
            nuevo_tipo = self._combo_tipo.currentData()
            if nuevo_tipo is not None:
                self._input.setText(USO_HABITACION_LABELS.get(nuevo_tipo, ""))

    def _stylesheet(self) -> str:
        return _dialogo_delim_stylesheet()


def _dialogo_delim_stylesheet() -> str:
    """QSS compartido entre DialogoNombreHabitacion y DialogoMaterialMuro
    (mismo look de diálogos modales de Delimitación)."""
    return f"""
        QDialog {{ background-color: {COLOR_FONDO}; color: {COLOR_TEXTO_SUAVE}; }}
        QLabel {{ color: {COLOR_TEXTO_SUAVE}; font-size: 12px; }}
        QLabel#tituloDialogo {{
            color: {COLOR_TEXTO}; font-size: 14px; font-weight: bold;
            padding-bottom: 4px;
        }}
        QLabel#descripcionDialogo {{
            color: {COLOR_TEXTO_MUTED}; font-size: 12px;
        }}
        QLabel#etiquetaCampo {{
            color: {COLOR_TEXTO_MUTED};
            font-size: 11px;
            padding-top: 4px;
        }}
        QLabel#equivDialogo {{
            color: {COLOR_TEXTO_MUTED};
            background-color: {COLOR_INPUT_BG};
            border: 1px solid {COLOR_BORDE};
            border-radius: 4px;
            padding: 6px 10px;
            font-size: 11px;
        }}
        QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
            background-color: {COLOR_INPUT_BG}; color: {COLOR_TEXTO};
            border: 1px solid {COLOR_BORDE_FUERTE};
            border-radius: 4px; padding: 7px 10px;
            font-size: 13px;
            selection-background-color: {COLOR_ACENTO};
        }}
        QLineEdit:focus, QComboBox:focus,
        QDoubleSpinBox:focus, QSpinBox:focus {{
            border-color: {COLOR_ACENTO};
        }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled {{
            color: {COLOR_TEXTO_MUTED}; border-color: {COLOR_BORDE};
        }}
        QCheckBox {{
            color: {COLOR_TEXTO}; font-size: 13px; spacing: 8px;
            padding-top: 6px;
        }}
        QCheckBox:disabled {{ color: {COLOR_TEXTO_MUTED}; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px; border-radius: 3px;
            border: 1px solid {COLOR_BORDE_FUERTE};
            background-color: {COLOR_INPUT_BG};
        }}
        QCheckBox::indicator:checked {{
            background-color: {COLOR_ACENTO}; border-color: {COLOR_ACENTO};
        }}
        QLabel#topeDialogo {{
            color: {COLOR_TEXTO_MUTED}; font-size: 11px; padding-left: 24px;
        }}
        QDoubleSpinBox::up-button, QSpinBox::up-button,
        QDoubleSpinBox::down-button, QSpinBox::down-button {{
            background-color: {COLOR_BORDE_FUERTE};
            border: none; width: 16px;
        }}
        QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
        QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {{
            background-color: {COLOR_ACENTO};
        }}
        QComboBox QAbstractItemView {{
            background-color: {COLOR_SUPERFICIE};
            color: {COLOR_TEXTO_SUAVE};
            border: 1px solid {COLOR_BORDE_FUERTE};
            selection-background-color: {COLOR_ACENTO};
            selection-color: {COLOR_TEXTO};
            padding: 2px;
            outline: none;
        }}
        QPushButton {{
            background-color: {COLOR_ACENTO}; color: {COLOR_TEXTO};
            border: none; padding: 8px 20px; border-radius: 4px;
            font-size: 12px; min-width: 100px; outline: none;
        }}
        QPushButton:hover {{ background-color: {COLOR_ACENTO_BRILL}; }}
        QPushButton#secundario {{
            background-color: {COLOR_INPUT_BG}; color: {COLOR_TEXTO_SUAVE};
        }}
        QPushButton#secundario:hover {{
            background-color: {COLOR_BORDE_FUERTE}; color: {COLOR_TEXTO};
        }}
    """


# ---------------------------------------------------------------------------
# DialogoMaterialMuro — combo de material al terminar cada muro
# ---------------------------------------------------------------------------

class DialogoMaterialMuro(QDialog):
    """Modal compacto que aparece al terminar un muro. Pide dos cosas:
    el MATERIAL (combo) y el GROSOR en cm (spinbox). El grosor
    autocompleta con el default del material elegido, pero el usuario
    puede sobreescribirlo (muros gruesos de fachada, muros divisorios
    muy delgados, etc.).

    Recuerda el último material y grosor entre muros consecutivos."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        material_sugerido: TipoMaterialMuro = TipoMaterialMuro.SIN_ESPECIFICAR,
        grosor_sugerido_cm: float = 0.0,
        justificacion_sugerida: JustificacionMuro = JustificacionMuro.CENTRO,
        longitud_m: Optional[float] = None,
        escala: Optional[EscalaCalibrada] = None,
        tope: Optional[dict] = None,
        usar_tope: bool = False,
    ) -> None:
        # Escala del plano actual (para el display de equivalencia en pt)
        self._escala = escala
        # Muro divisorio: hueco detectado entre las dos divisiones a los
        # lados del trazo ({"grosor_cm", "justificacion", "descripcion",
        # "centrado"}) o None si no hay división de los dos lados.
        self._tope = tope
        super().__init__(parent)
        self.setWindowTitle("Material del muro")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedSize(480, 560)
        self.setStyleSheet(_dialogo_delim_stylesheet())

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(8)

        titulo = QLabel("Material, grosor y cara del muro")
        titulo.setObjectName("tituloDialogo")
        v.addWidget(titulo)

        if longitud_m is not None:
            desc_txt = (
                f"Longitud del muro: <b>{longitud_m:.2f} m</b>. "
                "El material define el hatch y qué canalizaciones son "
                "válidas. El grosor lo usa el motor para canalización "
                "oculta. La <b>cara</b> decide hacia qué lado del "
                "trazo va el grosor."
            )
        else:
            desc_txt = (
                "El material define cómo se renderiza el muro (hatch) "
                "y qué canalizaciones son válidas. El grosor lo usa "
                "el motor. La <b>cara</b> decide hacia qué lado del "
                "trazo va el grosor."
            )
        desc = QLabel(desc_txt)
        desc.setObjectName("descripcionDialogo")
        desc.setWordWrap(True)
        v.addWidget(desc)

        # Material
        lbl_cmp = QLabel("Material")
        lbl_cmp.setObjectName("etiquetaCampo")
        v.addWidget(lbl_cmp)

        self._combo = QComboBox()
        for m, label in MATERIAL_MURO_LABELS.items():
            self._combo.addItem(label, m)
        idx = self._combo.findData(material_sugerido)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        # Al cambiar de material, autocompletar grosor si el usuario
        # no lo había personalizado.
        self._combo.currentIndexChanged.connect(self._on_material_cambiado)
        v.addWidget(self._combo)

        # Grosor (cm)
        lbl_gr = QLabel("Grosor (cm)")
        lbl_gr.setObjectName("etiquetaCampo")
        v.addWidget(lbl_gr)

        self._spin_grosor = QDoubleSpinBox()
        self._spin_grosor.setRange(
            2.0, max(60.0, float(tope["grosor_cm"]) + 1.0) if tope else 60.0,
        )
        self._spin_grosor.setDecimals(1)
        self._spin_grosor.setSingleStep(1.0)
        self._spin_grosor.setSuffix(" cm")
        # Valor inicial: sugerido, o default del material
        grosor_inicial = grosor_sugerido_cm
        if grosor_inicial <= 0.0:
            grosor_inicial = GROSOR_DEFAULT_POR_MATERIAL.get(
                material_sugerido, 12.0,
            )
        self._spin_grosor.setValue(grosor_inicial)
        # Marca si el usuario tocó manualmente el grosor (para no
        # sobreescribirlo al cambiar de material)
        self._grosor_personalizado = False
        self._spin_grosor.valueChanged.connect(self._on_grosor_cambiado)
        v.addWidget(self._spin_grosor)

        # Label de diagnóstico: equivalencia en pt PDF con la escala
        # actual — permite comparar contra el ancho del muro real
        # medido con la herramienta "Medir".
        self._lbl_equiv = QLabel("")
        self._lbl_equiv.setObjectName("equivDialogo")
        self._lbl_equiv.setWordWrap(True)
        v.addWidget(self._lbl_equiv)
        self._actualizar_equivalencia(grosor_inicial)

        # Muro divisorio: en vez de escribir el grosor, que llene el
        # hueco hasta la siguiente división (habitación o muro).
        self._chk_tope = QCheckBox("Topar con la siguiente división")
        self._lbl_tope = QLabel("")
        self._lbl_tope.setObjectName("topeDialogo")
        self._lbl_tope.setWordWrap(True)
        if tope is not None:
            extra = (
                " Se centra en el hueco." if tope.get("centrado") else
                " Crece desde tu trazo hacia la otra división."
            )
            self._lbl_tope.setText(
                f"Hueco detectado: <b>{tope['grosor_cm']:.1f} cm</b> "
                f"({tope.get('descripcion', '')}).{extra}"
            )
        else:
            self._chk_tope.setEnabled(False)
            self._lbl_tope.setText(
                "No hay otra habitación o muro del otro lado del trazo "
                "(a menos de 1 m): escribe el grosor."
            )
        self._chk_tope.toggled.connect(self._on_tope)
        v.addWidget(self._chk_tope)
        v.addWidget(self._lbl_tope)

        # Cara / Justificación
        lbl_j = QLabel("Cara del muro (hacia dónde va el grosor)")
        lbl_j.setObjectName("etiquetaCampo")
        v.addWidget(lbl_j)

        self._combo_just = QComboBox()
        for j, label in JUSTIFICACION_MURO_LABELS.items():
            self._combo_just.addItem(label, j)
        idx = self._combo_just.findData(justificacion_sugerida)
        if idx >= 0:
            self._combo_just.setCurrentIndex(idx)
        v.addWidget(self._combo_just)

        if tope is not None and usar_tope:
            self._chk_tope.setChecked(True)

        v.addStretch(1)

        botones = QHBoxLayout()
        botones.setSpacing(8)
        botones.addStretch(1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("secundario")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_cancel.clicked.connect(self.reject)
        botones.addWidget(btn_cancel)

        btn_ok = QPushButton("Aplicar")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        botones.addWidget(btn_ok)

        v.addLayout(botones)

        self._combo.setFocus()

    def _on_tope(self, activo: bool) -> None:
        """Topar: el grosor y la cara salen del hueco detectado (se
        bloquean); al desmarcar, el operador vuelve a escribirlos."""
        self._spin_grosor.setEnabled(not activo)
        self._combo_just.setEnabled(not activo)
        if not activo or self._tope is None:
            return
        self._spin_grosor.blockSignals(True)
        self._spin_grosor.setValue(float(self._tope["grosor_cm"]))
        self._spin_grosor.blockSignals(False)
        self._actualizar_equivalencia(float(self._tope["grosor_cm"]))
        idx = self._combo_just.findData(self._tope["justificacion"])
        if idx >= 0:
            self._combo_just.setCurrentIndex(idx)

    def usar_tope(self) -> bool:
        """True si el operador eligió topar con la siguiente división."""
        return self._tope is not None and self._chk_tope.isChecked()

    def _on_material_cambiado(self, _idx: int) -> None:
        # Si el usuario no ha tocado el spin, autocompletar con el
        # default del material seleccionado.
        if self._grosor_personalizado or self.usar_tope():
            return
        mat = self._combo.currentData()
        if mat is None:
            return
        default_cm = GROSOR_DEFAULT_POR_MATERIAL.get(mat, 12.0)
        # Bloquear la señal para no marcar como "personalizado"
        self._spin_grosor.blockSignals(True)
        self._spin_grosor.setValue(default_cm)
        self._spin_grosor.blockSignals(False)

    def _on_grosor_cambiado(self, val: float) -> None:
        self._grosor_personalizado = True
        self._actualizar_equivalencia(val)

    def _actualizar_equivalencia(self, cm: float) -> None:
        """Muestra el equivalente en pt PDF del grosor con la escala
        actual del plano. Sirve para verificar contra la herramienta
        de medición."""
        if self._escala is None or self._escala.m_por_pt <= 0.0:
            self._lbl_equiv.setText(
                "<i>Plano sin calibrar — el grosor se muestra con un "
                "ancho visual fijo (4 pt) hasta que calibres. Al "
                "calibrar, el muro se redibuja al ancho real.</i>"
            )
            return
        m = cm / 100.0
        pt = m / self._escala.m_por_pt
        m_por_pt = self._escala.m_por_pt
        self._lbl_equiv.setText(
            f"Equivalente con la escala actual: "
            f"<b>{pt:.2f} pt PDF</b> "
            f"(1 pt = {m_por_pt:.4f} m).<br>"
            f"Con la herramienta <b>Medir</b>, el ancho del muro real "
            f"del plano debería darte <b>{cm:.1f} cm</b> — si te da "
            f"otra cifra, la calibración necesita ajuste."
        )

    def material(self) -> TipoMaterialMuro:
        return self._combo.currentData() or TipoMaterialMuro.SIN_ESPECIFICAR

    def grosor_cm(self) -> float:
        return float(self._spin_grosor.value())

    def justificacion(self) -> JustificacionMuro:
        return self._combo_just.currentData() or JustificacionMuro.CENTRO


# ---------------------------------------------------------------------------
# PreviewDibujoItem — visual efímero mientras se dibuja
# ---------------------------------------------------------------------------

class ModoPreview(Enum):
    """Cómo debe interpretar el preview los vértices + cursor:

    * POLILINEA — el modo por default: cada segmento es una recta.
      El cursor extiende la polilínea (segmento provisional dashed).
    * ARCO — 3-clic: 1 = inicio, 2 = paso, 3 = fin. Con 0/1 vértices,
      preview lineal; con 2 vértices + cursor, arco provisional
      pasando por (v1, v2, cursor).
    * CIRCULO — 2-clic: 1 = centro, 2 = borde. Con 1 vértice + cursor,
      dibuja el círculo completo centrado en v1 con radio = dist a
      cursor. Sin cursor, muestra solo el vértice del centro.
    """
    POLILINEA = 0
    ARCO      = 1
    CIRCULO   = 2


class PreviewDibujoItem(QGraphicsObject):
    """Item efímero que se dibuja mientras el usuario está armando
    un muro o habitación. Muestra los vértices fijos + segmento/arco/
    círculo provisional al cursor según el modo."""

    def __init__(self, cerrado_provisional: bool = False) -> None:
        super().__init__()
        self._vertices: list[QPointF] = []
        self._cursor: Optional[QPointF] = None
        self._cerrado_prov = cerrado_provisional
        self._modo: ModoPreview = ModoPreview.POLILINEA
        self._rect_bbox: QRectF = QRectF()
        # Indicador de snap al primer vértice: cuando no es None, se
        # dibuja un círculo naranja alrededor de esa posición para
        # avisar al usuario "clic aquí para cerrar en ese punto exacto".
        self._indicador_snap: Optional[QPointF] = None
        # Indicador de snap a extremo/vértice de muro/habitación existente:
        # cuadrado cian que dice "clic aquí engancha con ese punto exacto".
        self._indicador_snap_extremo: Optional[QPointF] = None
        # Tipo del indicador: "endpoint" (cuadrado) o "midpoint" (rombo).
        self._indicador_snap_extremo_tipo: str = "endpoint"
        # Indicador de snap "cerca de muro" (proyección del cursor al
        # muro más cercano). Se dibuja como X cian — significa "clic
        # aquí engancha con ese muro, en este punto exacto de su recorrido".
        self._indicador_snap_nearest: Optional[QPointF] = None
        # Preview del arco de PUERTA durante el 3° clic (elección de
        # orientación). Dict con centro_hueco, tangente, normal, ancho,
        # punto_a, punto_b, pivote_en_inicio, sentido — o None.
        self._puerta_preview: Optional[dict] = None
        # Auto-extend: pares (desde, hasta) de los extremos del muro en
        # curso que se van a prolongar para cerrar el hueco con otro
        # muro. Se dibujan como línea punteada cian + tope.
        self._extensiones: list[tuple[QPointF, QPointF]] = []
        # Contorno del hueco de la puerta/ventana que se está colocando
        # (sigue el trazo del muro). None ⇒ nada.
        self._hueco_preview: Optional[QPainterPath] = None
        # Aberturas: línea de corte bajo el cursor (de cara a cara del
        # muro, en diagonal si cae en una esquina): (p1, p2, en_quiebre).
        self._corte_hover: Optional[tuple] = None
        # Aberturas: "fantasma" de la puerta/ventana en curso, idéntico
        # al resultado final. Dict con "tipo" ("ventana"|"puerta"),
        # "geo" (ver `geometria_abertura`), "contorno" (cuerpo del muro)
        # y "cortes" [(p1, p2, en_quiebre), ...] de los extremos fijos.
        self._abertura_prev: Optional[dict] = None
        # Habitación con curvas: {i: paso} de los tramos ya hechos en
        # arco, y el punto de paso del arco en curso (o None).
        self._arcos_trazo: dict[int, QPointF] = {}
        self._paso_trazo: Optional[QPointF] = None
        self.setZValue(9000)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def set_vertices(self, vertices: list[QPointF]) -> None:
        self.prepareGeometryChange()
        self._vertices = [QPointF(p) for p in vertices]
        self._recomputar_bbox()
        self.update()

    def set_cursor(self, punto: Optional[QPointF]) -> None:
        self.prepareGeometryChange()
        self._cursor = QPointF(punto) if punto is not None else None
        self._recomputar_bbox()
        self.update()

    def set_modo(self, modo: ModoPreview) -> None:
        """Cambia cómo interpretar los vértices + cursor. La UI llama
        esto al activar cada herramienta."""
        if modo == self._modo:
            return
        self.prepareGeometryChange()
        self._modo = modo
        self._recomputar_bbox()
        self.update()

    def set_indicador_snap(self, punto: Optional[QPointF]) -> None:
        """Activa/desactiva el indicador visual de snap. Se pasa la
        posición del primer vértice cuando el cursor entra en el
        radio de snap, o None para apagar."""
        if punto is None and self._indicador_snap is None:
            return
        if punto is not None and self._indicador_snap is not None:
            if (
                abs(punto.x() - self._indicador_snap.x()) < 0.001
                and abs(punto.y() - self._indicador_snap.y()) < 0.001
            ):
                return
        self.prepareGeometryChange()
        self._indicador_snap = QPointF(punto) if punto is not None else None
        self._recomputar_bbox()
        self.update()

    def set_indicador_snap_extremo(
        self, punto: Optional[QPointF], tipo: str = "endpoint",
    ) -> None:
        """Activa/desactiva el indicador visual de snap a punto exacto
        de un muro/habitación EXISTENTE. `tipo` distingue endpoint
        (cuadrado cian) de midpoint (rombo cian). Se pasa la posición
        del punto capturado cuando el cursor entra en su radio de snap,
        o None para apagar."""
        cambio_pos = True
        if punto is None and self._indicador_snap_extremo is None:
            cambio_pos = False
        elif punto is not None and self._indicador_snap_extremo is not None:
            if (
                abs(punto.x() - self._indicador_snap_extremo.x()) < 0.001
                and abs(punto.y() - self._indicador_snap_extremo.y()) < 0.001
            ):
                cambio_pos = False
        cambio_tipo = tipo != self._indicador_snap_extremo_tipo
        if not cambio_pos and not cambio_tipo:
            return
        self.prepareGeometryChange()
        self._indicador_snap_extremo = (
            QPointF(punto) if punto is not None else None
        )
        self._indicador_snap_extremo_tipo = tipo
        self._recomputar_bbox()
        self.update()

    def set_indicador_snap_nearest(
        self, punto: Optional[QPointF],
    ) -> None:
        """Activa/desactiva el indicador visual de snap a punto genérico
        sobre un muro (proyección del cursor). Se dibuja como X cian."""
        if punto is None and self._indicador_snap_nearest is None:
            return
        if punto is not None and self._indicador_snap_nearest is not None:
            if (
                abs(punto.x() - self._indicador_snap_nearest.x()) < 0.001
                and abs(punto.y() - self._indicador_snap_nearest.y()) < 0.001
            ):
                return
        self.prepareGeometryChange()
        self._indicador_snap_nearest = (
            QPointF(punto) if punto is not None else None
        )
        self._recomputar_bbox()
        self.update()

    def set_puerta_preview(self, datos: Optional[dict]) -> None:
        """Datos para dibujar el arco de barrido de la puerta durante
        la elección de orientación (3° clic). None ⇒ apagar."""
        if datos is None and self._puerta_preview is None:
            return
        self.prepareGeometryChange()
        self._puerta_preview = dict(datos) if datos is not None else None
        self._recomputar_bbox()
        self.update()

    def set_extensiones_preview(
        self, pares: list[tuple[QPointF, QPointF]],
    ) -> None:
        """Muestra hasta dónde se prolongará cada extremo del muro en
        curso (auto-extend). Lista vacía ⇒ nada."""
        if not pares and not self._extensiones:
            return
        self.prepareGeometryChange()
        self._extensiones = [(QPointF(a), QPointF(b)) for a, b in pares]
        self._recomputar_bbox()
        self.update()

    def set_hueco_preview(self, hueco: Optional[QPainterPath]) -> None:
        """Contorno del hueco de la abertura en curso (preview)."""
        if hueco is None and self._hueco_preview is None:
            return
        self.prepareGeometryChange()
        self._hueco_preview = QPainterPath(hueco) if hueco is not None else None
        self._recomputar_bbox()
        self.update()

    def set_trazo_arcos(
        self, arcos: dict[int, QPointF], paso: Optional[QPointF],
    ) -> None:
        """Tramos en arco del trazo en curso (habitación) y el punto de
        paso pendiente."""
        self.prepareGeometryChange()
        self._arcos_trazo = {i: QPointF(p) for i, p in (arcos or {}).items()}
        self._paso_trazo = QPointF(paso) if paso is not None else None
        self._recomputar_bbox()
        self.update()

    def set_corte_hover(self, corte: Optional[tuple]) -> None:
        """Marcador de abertura bajo el cursor: la línea exacta donde
        quedaría el corte si se hace clic ahora. None ⇒ nada."""
        if corte is None and self._corte_hover is None:
            return
        self.prepareGeometryChange()
        self._corte_hover = (
            (QPointF(corte[0]), QPointF(corte[1]), bool(corte[2]))
            if corte is not None else None
        )
        self._recomputar_bbox()
        self.update()

    def set_abertura_preview(self, datos: Optional[dict]) -> None:
        """Fantasma de la abertura en curso (ver `_abertura_prev`)."""
        if datos is None and self._abertura_prev is None:
            return
        self.prepareGeometryChange()
        self._abertura_prev = dict(datos) if datos is not None else None
        self._recomputar_bbox()
        self.update()

    def limpiar(self) -> None:
        self.prepareGeometryChange()
        self._corte_hover = None
        self._abertura_prev = None
        self._arcos_trazo = {}
        self._paso_trazo = None
        self._vertices = []
        self._cursor = None
        self._indicador_snap = None
        self._indicador_snap_extremo = None
        self._indicador_snap_nearest = None
        self._puerta_preview = None
        self._extensiones = []
        self._hueco_preview = None
        self._rect_bbox = QRectF()
        self.update()

    def _recomputar_bbox(self) -> None:
        puntos = list(self._vertices)
        if self._cursor is not None:
            puntos.append(self._cursor)
        # Los indicadores de snap también expanden el bbox: aunque no
        # haya vértices ni cursor todavía, Qt debe pintar el cuadrado /
        # rombo / X cuando el usuario está aproximándose a un muro
        # ANTES del primer clic. Sin esto, boundingRect estaría vacío
        # y Qt no llamaría a paint.
        if self._indicador_snap is not None:
            puntos.append(self._indicador_snap)
        if self._indicador_snap_extremo is not None:
            puntos.append(self._indicador_snap_extremo)
        if self._indicador_snap_nearest is not None:
            puntos.append(self._indicador_snap_nearest)
        for a, b in self._extensiones:
            puntos.extend([a, b])
        if self._hueco_preview is not None and not self._hueco_preview.isEmpty():
            r = self._hueco_preview.boundingRect()
            puntos.extend([r.topLeft(), r.bottomRight()])
        if self._corte_hover is not None:
            puntos.extend([self._corte_hover[0], self._corte_hover[1]])
        # Curvas del trazo de habitación (pueden abombarse fuera de los
        # vértices).
        vs = self._vertices
        for i, paso in self._arcos_trazo.items():
            if i + 1 < len(vs):
                r = _rect_arco_3_puntos(vs[i], paso, vs[i + 1])
                puntos.extend([r.topLeft(), r.bottomRight()])
        if self._paso_trazo is not None and vs:
            puntos.append(self._paso_trazo)
            if self._cursor is not None:
                r = _rect_arco_3_puntos(vs[-1], self._paso_trazo, self._cursor)
                puntos.extend([r.topLeft(), r.bottomRight()])
        if self._abertura_prev is not None:
            geo = self._abertura_prev.get("geo")
            if geo is not None and not geo["hueco"].isEmpty():
                r = geo["hueco"].boundingRect()
                puntos.extend([r.topLeft(), r.bottomRight()])
            for c in self._abertura_prev.get("cortes", []):
                puntos.extend([c[0], c[1]])
        # Puerta preview: incluir el círculo del arco (centro + radio)
        if self._puerta_preview is not None:
            pp = self._puerta_preview
            centro = pp.get("punto_a") if pp.get("pivote_en_inicio") \
                else pp.get("punto_b")
            radio = float(pp.get("ancho_pt", 0.0))
            if centro is not None and radio > 0.0:
                puntos.extend([
                    QPointF(centro.x() - radio, centro.y() - radio),
                    QPointF(centro.x() + radio, centro.y() + radio),
                ])
        if not puntos:
            self._rect_bbox = QRectF()
            return
        xs = [p.x() for p in puntos]
        ys = [p.y() for p in puntos]

        # Para ARCO y CIRCULO, extender con el círculo completo si es
        # calculable, para no cortar el trazo cuando se abomba lejos.
        if (
            self._modo == ModoPreview.ARCO
            and len(self._vertices) == 2
            and self._cursor is not None
        ):
            rect_arco = _rect_arco_3_puntos(
                self._vertices[0], self._vertices[1], self._cursor,
            )
            xs.extend([rect_arco.left(), rect_arco.right()])
            ys.extend([rect_arco.top(), rect_arco.bottom()])
        elif (
            self._modo == ModoPreview.CIRCULO
            and len(self._vertices) == 1
            and self._cursor is not None
        ):
            centro = self._vertices[0]
            r = math.hypot(
                self._cursor.x() - centro.x(),
                self._cursor.y() - centro.y(),
            )
            xs.extend([centro.x() - r, centro.x() + r])
            ys.extend([centro.y() - r, centro.y() + r])

        margen = 50.0
        self._rect_bbox = QRectF(
            min(xs) - margen, min(ys) - margen,
            (max(xs) - min(xs)) + 2 * margen,
            (max(ys) - min(ys)) + 2 * margen,
        )

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._rect_bbox

    # ---------- paint dispatchers ----------

    def _pen_solido(self, grosor: float) -> QPen:
        pen = QPen(QColor(COLOR_PREVIEW_LINEA))
        pen.setWidthF(grosor)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _pen_dashed(self, grosor: float) -> QPen:
        pen = QPen(QColor(COLOR_PREVIEW_LINEA))
        pen.setWidthF(grosor)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([5.0, 3.0])
        return pen

    def paint(  # noqa: N802
        self, painter, option, widget=None,
    ) -> None:
        scale = _painter_scale(painter)
        grosor = max(_GROSOR_PREVIEW_PT / scale, 0.5)
        radio_v = _RADIO_VERTICE_PT / scale

        # Dibuja el trazo en curso (segmentos, arco, círculo) sólo si hay
        # vértices. Los indicadores de snap se dibujan siempre — así el
        # usuario ve el cuadrado / rombo / X ANTES del primer clic, que
        # es cuando más los necesita.
        if self._vertices:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._modo == ModoPreview.ARCO:
                self._paint_modo_arco(painter, grosor)
            elif self._modo == ModoPreview.CIRCULO:
                self._paint_modo_circulo(painter, grosor)
            else:
                self._paint_modo_polilinea(painter, grosor)

            # Círculos rellenos en cada vértice fijo
            painter.setPen(self._pen_solido(grosor))
            painter.setBrush(QBrush(QColor(COLOR_PREVIEW_LINEA)))
            for v in self._vertices:
                painter.drawEllipse(v, radio_v, radio_v)

        # Indicador de snap al primer vértice: círculo grande naranja
        # + relleno claro, para señalar visualmente "clic aquí cierra".
        if self._indicador_snap is not None:
            radio_snap = radio_v * 3.0
            pen_snap = QPen(QColor(COLOR_VERTICE))  # naranja cálido
            pen_snap.setWidthF(grosor * 1.5)
            painter.setPen(pen_snap)
            fill = QColor(COLOR_VERTICE)
            fill.setAlpha(70)
            painter.setBrush(QBrush(fill))
            painter.drawEllipse(
                self._indicador_snap, radio_snap, radio_snap
            )

        # Indicador de snap a extremo/vértice existente: cuadrado cian
        # (endpoint) o rombo cian (midpoint). Se distinguen para que el
        # usuario sepa a qué está enganchando.
        if self._indicador_snap_extremo is not None:
            lado = radio_v * 2.8
            pen_ext = QPen(QColor("#00e5ff"))  # cian brillante
            pen_ext.setWidthF(grosor * 1.4)
            painter.setPen(pen_ext)
            fill_ext = QColor("#00e5ff")
            fill_ext.setAlpha(60)
            painter.setBrush(QBrush(fill_ext))
            p = self._indicador_snap_extremo
            if self._indicador_snap_extremo_tipo == "midpoint":
                # Rombo (cuadrado rotado 45°): triángulo/rombo = midpoint
                rombo = QPolygonF([
                    QPointF(p.x(), p.y() - lado),
                    QPointF(p.x() + lado, p.y()),
                    QPointF(p.x(), p.y() + lado),
                    QPointF(p.x() - lado, p.y()),
                ])
                painter.drawPolygon(rombo)
            else:
                # Cuadrado alineado a ejes = endpoint
                painter.drawRect(QRectF(
                    p.x() - lado, p.y() - lado, 2.0 * lado, 2.0 * lado,
                ))

        # Preview del arco de PUERTA durante la elección de orientación
        # (3° clic). Se dibuja el arco de barrido en dashed cyan sobre
        # el hueco. La página empuja los datos por `set_puerta_preview`.
        # Contorno del hueco de la abertura en curso: relleno tenue y
        # borde punteado. Muestra exactamente la zona que se va a abrir
        # en el muro (incluidos los quiebres).
        if self._hueco_preview is not None and not self._hueco_preview.isEmpty():
            relleno = QColor(COLOR_PREVIEW_LINEA)
            relleno.setAlpha(45)
            pen_h = QPen(QColor(COLOR_PREVIEW_LINEA))
            pen_h.setWidthF(grosor * 0.8)
            pen_h.setStyle(Qt.PenStyle.CustomDashLine)
            pen_h.setDashPattern([4.0, 3.0])
            pen_h.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(pen_h)
            painter.setBrush(QBrush(relleno))
            painter.drawPath(self._hueco_preview)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._abertura_prev is not None:
            self._paint_abertura_prev(painter, scale, grosor)
        if self._corte_hover is not None:
            self._paint_corte(painter, self._corte_hover, grosor,
                              QColor("#00e5ff"), radio_v)

        if self._puerta_preview is not None:
            self._paint_puerta_preview(painter, grosor)

        # Auto-extend: tramo cian (sólido y más grueso que la línea del
        # trazo, para que se distinga) desde el extremo actual hasta
        # donde se prolongará, con un tope perpendicular en la llegada.
        if self._extensiones:
            color_ext = QColor("#00e5ff")
            pen_ext = QPen(color_ext)
            pen_ext.setWidthF(grosor * 2.2)
            pen_ext.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen_tope = QPen(color_ext)
            pen_tope.setWidthF(grosor * 1.8)
            pen_tope.setCapStyle(Qt.PenCapStyle.RoundCap)
            largo_tope = radio_v * 2.6
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for a, b in self._extensiones:
                painter.setPen(pen_ext)
                painter.drawLine(a, b)
                dx, dy = b.x() - a.x(), b.y() - a.y()
                d = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / d, dx / d
                painter.setPen(pen_tope)
                painter.drawLine(
                    QPointF(b.x() - nx * largo_tope, b.y() - ny * largo_tope),
                    QPointF(b.x() + nx * largo_tope, b.y() + ny * largo_tope),
                )

        # Indicador de snap "cerca de muro" (proyección): X cian. Ganchea
        # a cualquier punto del recorrido del muro. Prioridad menor que
        # endpoint/midpoint, por eso el símbolo es más ligero.
        if self._indicador_snap_nearest is not None:
            lado = radio_v * 2.4
            pen_n = QPen(QColor("#00e5ff"))
            pen_n.setWidthF(grosor * 1.4)
            pen_n.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_n)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            p = self._indicador_snap_nearest
            painter.drawLine(
                QPointF(p.x() - lado, p.y() - lado),
                QPointF(p.x() + lado, p.y() + lado),
            )
            painter.drawLine(
                QPointF(p.x() - lado, p.y() + lado),
                QPointF(p.x() + lado, p.y() - lado),
            )

    def _paint_corte(self, painter, corte, grosor: float, color: QColor,
                     radio_v: float) -> None:
        """Línea de corte de una abertura, de cara a cara del muro. En
        una esquina se marca además con dos cuadritos (como el snap a
        vértice)."""
        p1, p2, en_quiebre = corte
        pen = QPen(color)
        pen.setWidthF(grosor * 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(p1, p2)
        if en_quiebre:
            lado = radio_v * 1.3
            relleno = QColor(color)
            relleno.setAlpha(90)
            pen_c = QPen(color)
            pen_c.setWidthF(grosor)
            painter.setPen(pen_c)
            painter.setBrush(QBrush(relleno))
            for p in (p1, p2):
                painter.drawRect(QRectF(
                    p.x() - lado, p.y() - lado, 2.0 * lado, 2.0 * lado,
                ))
            painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_abertura_prev(self, painter, scale: float, grosor: float) -> None:
        """Fantasma de la puerta/ventana en curso, dibujado con la MISMA
        geometría que tendrá al colocarla: zona que se abrirá en el
        muro (tinte azul, sólo dentro del muro), símbolo de la ventana y
        las líneas de corte de sus extremos."""
        datos = self._abertura_prev
        geo = datos.get("geo")
        contorno = datos.get("contorno")
        if geo is not None and not geo["hueco"].isEmpty():
            painter.save()
            painter.setClipPath(geo["hueco"], Qt.ClipOperation.IntersectClip)
            if contorno is not None and not contorno.isEmpty():
                tinte = QColor(COLOR_PREVIEW_LINEA)
                tinte.setAlpha(55)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(tinte))
                painter.drawPath(contorno)
            painter.restore()
            if datos.get("tipo") == "ventana":
                dibujar_simbolo_ventana(
                    painter, geo, scale,
                    QColor(COLOR_VENTANA_MARCO), QColor(COLOR_VENTANA),
                )
        radio_v = _RADIO_VERTICE_PT / scale
        for c in datos.get("cortes", []):
            self._paint_corte(painter, c, grosor,
                              QColor(COLOR_PREVIEW_LINEA), radio_v)

    def _paint_modo_polilinea(self, painter, grosor: float) -> None:
        # Polilínea de vértices fijos (sólida); los tramos en arco se
        # dibujan curvos.
        painter.setPen(self._pen_solido(grosor))
        for i in range(len(self._vertices) - 1):
            paso = self._arcos_trazo.get(i)
            arco = (
                _arco_path_por_3_puntos(
                    self._vertices[i], paso, self._vertices[i + 1],
                ) if paso is not None else None
            )
            if arco is not None:
                painter.drawPath(arco)
            else:
                painter.drawLine(self._vertices[i], self._vertices[i + 1])

        # Punto de paso del arco en curso: rombo pequeño
        if self._paso_trazo is not None:
            lado = max(_RADIO_VERTICE_PT * grosor / max(_GROSOR_PREVIEW_PT, 1e-6), 1.0)
            p = self._paso_trazo
            painter.setBrush(QBrush(QColor(COLOR_PREVIEW_LINEA)))
            painter.drawPolygon(QPolygonF([
                QPointF(p.x(), p.y() - lado), QPointF(p.x() + lado, p.y()),
                QPointF(p.x(), p.y() + lado), QPointF(p.x() - lado, p.y()),
            ]))
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # Tramo provisional del último vértice al cursor: arco si ya hay
        # punto de paso, recto si no.
        if self._cursor is not None and self._vertices:
            painter.setPen(self._pen_dashed(grosor))
            arco = (
                _arco_path_por_3_puntos(
                    self._vertices[-1], self._paso_trazo, self._cursor,
                ) if self._paso_trazo is not None else None
            )
            if arco is not None:
                painter.drawPath(arco)
            elif self._paso_trazo is not None:
                painter.drawLine(self._vertices[-1], self._paso_trazo)
                painter.drawLine(self._paso_trazo, self._cursor)
            else:
                painter.drawLine(self._vertices[-1], self._cursor)
            # Si es habitación y hay >=2 vértices, mostrar tenue el
            # cierre potencial al primer vértice.
            if self._cerrado_prov and len(self._vertices) >= 2:
                pen_close = QPen(QColor(COLOR_PREVIEW_LINEA))
                pen_close.setWidthF(grosor * 0.7)
                pen_close.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(pen_close)
                painter.drawLine(self._cursor, self._vertices[0])

    def _paint_modo_arco(self, painter, grosor: float) -> None:
        n = len(self._vertices)
        if n == 1 and self._cursor is not None:
            # Solo p1 fijo → línea recta dashed al cursor (aún no hay
            # información suficiente para dibujar arco).
            painter.setPen(self._pen_dashed(grosor))
            painter.drawLine(self._vertices[0], self._cursor)
            return
        if n == 2 and self._cursor is not None:
            # p1, p2 fijos + cursor → arco provisional por los 3 puntos,
            # con el cursor haciendo de "punto final".
            # Interpretación: p1 = inicio, p2 = punto medio del arco,
            # cursor = fin. Así el usuario ve la curva completa mientras
            # decide dónde termina.
            arco = _arco_path_por_3_puntos(
                self._vertices[0], self._vertices[1], self._cursor,
            )
            painter.setPen(self._pen_dashed(grosor))
            if arco is not None:
                painter.drawPath(arco)
            else:
                # 3 puntos colineales → línea recta p1 → cursor
                painter.drawLine(self._vertices[0], self._cursor)
            return
        if n == 2:
            # Sin cursor (mouse aún no se ha movido): línea sólida p1 → p2
            painter.setPen(self._pen_solido(grosor))
            painter.drawLine(self._vertices[0], self._vertices[1])

    def _paint_modo_circulo(self, painter, grosor: float) -> None:
        if len(self._vertices) != 1 or self._cursor is None:
            return
        centro = self._vertices[0]
        radio = math.hypot(
            self._cursor.x() - centro.x(),
            self._cursor.y() - centro.y(),
        )
        # Círculo provisional dashed
        painter.setPen(self._pen_dashed(grosor))
        painter.drawEllipse(centro, radio, radio)
        # Línea guía centro → cursor para leer el radio
        pen_guia = QPen(QColor(COLOR_PREVIEW_LINEA))
        pen_guia.setWidthF(grosor * 0.7)
        pen_guia.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen_guia)
        painter.drawLine(centro, self._cursor)

    def _paint_puerta_preview(self, painter, grosor: float) -> None:
        """Dibuja el arco de barrido de la puerta durante la elección
        de orientación (3° clic). Sigue al cursor: pivote+sentido se
        recalcularon en `set_puerta_preview` a partir del cursor."""
        pp = self._puerta_preview
        if pp is None:
            return
        pivote_en_a = pp.get("pivote_en_inicio", True)
        sentido     = pp.get("sentido", "der")
        punto_a: Optional[QPointF] = pp.get("punto_a")
        punto_b: Optional[QPointF] = pp.get("punto_b")
        normal:  Optional[QPointF] = pp.get("normal")
        ancho:   float             = float(pp.get("ancho_pt", 0.0))
        if (punto_a is None or punto_b is None
                or normal is None or ancho <= 0.0):
            return
        signo = +1.0 if sentido == "der" else -1.0
        # Bisagra sobre la CARA del muro hacia la que abre (misma
        # convención que PuertaItem): punto del cuerpo + medio grosor.
        cara = signo * float(pp.get("grosor_pt", 0.0)) / 2.0
        pivote_cuerpo = punto_a if pivote_en_a else punto_b
        otro_cuerpo = punto_b if pivote_en_a else punto_a
        pivote = QPointF(pivote_cuerpo.x() + normal.x() * cara,
                         pivote_cuerpo.y() + normal.y() * cara)
        otro = QPointF(otro_cuerpo.x() + normal.x() * cara,
                       otro_cuerpo.y() + normal.y() * cara)
        # Extremo abierto de la hoja: perpendicular al muro, largo = ancho.
        extremo_abierto = QPointF(
            pivote.x() + signo * normal.x() * ancho,
            pivote.y() + signo * normal.y() * ancho,
        )
        # Segmento entre los dos extremos del hueco (línea guía)
        pen_guia = QPen(QColor(COLOR_PREVIEW_LINEA))
        pen_guia.setWidthF(grosor * 0.9)
        pen_guia.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen_guia)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(punto_a, punto_b)
        # Hoja de la puerta (segmento pivote → extremo abierto)
        pen_hoja = QPen(QColor(COLOR_PREVIEW_LINEA))
        pen_hoja.setWidthF(grosor * 1.4)
        pen_hoja.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_hoja)
        painter.drawLine(pivote, extremo_abierto)
        # Arco de barrido (cuarto de círculo dashed), de la hoja
        # cerrada a la abierta — mismo cálculo que la puerta final.
        pen_arco = QPen(QColor(COLOR_PREVIEW_LINEA))
        pen_arco.setWidthF(grosor * 0.9)
        pen_arco.setStyle(Qt.PenStyle.CustomDashLine)
        pen_arco.setDashPattern([5.0, 3.0])
        painter.setPen(pen_arco)
        rect_arco = QRectF(
            pivote.x() - ancho, pivote.y() - ancho,
            2 * ancho, 2 * ancho,
        )
        a_ini, barrido = angulo_barrido_puerta(pivote, otro, extremo_abierto)
        painter.drawArc(
            rect_arco, int(round(a_ini * 16)), int(round(barrido * 16)),
        )


# ---------------------------------------------------------------------------
# MuroItem — visual persistente de un muro
# ---------------------------------------------------------------------------

class MuroItem(QGraphicsObject):
    """Visualización persistente de un `Muro` sobre el canvas.

    Se pinta como POLÍGONO (contorno del muro con su grosor físico),
    relleno con hatch según el material, y con los huecos de puertas
    y ventanas RESTADOS del polígono al momento de pintar.

    Interactivo:
      * ItemIsSelectable — clic para seleccionar.
      * hoverEnter/Leave — resalta en rojo cuando `modo_borrar_activo`
        está encendido.

    El item recibe getters de escala y aberturas para poder calcular
    su propia geometría sin depender de la página completa:
      * `escala_getter()` → Optional[EscalaCalibrada]
      * `aberturas_getter(muro_id)` → tuple[list[Puerta], list[Ventana]]

    Signals:
      * clic_recibido(str) — emit(muro.id) al clic en modo borrar.
    """

    clic_recibido = pyqtSignal(str)

    _MARGEN_BBOX = 20.0

    def __init__(
        self,
        muro: Muro,
        escala_getter=lambda: None,
        aberturas_getter=lambda _id: ([], []),
        remiendos_getter=lambda _id: [],
    ) -> None:
        super().__init__()
        self._rect_cache: Optional[QRectF] = None
        self._muro = muro
        self._escala_getter = escala_getter
        self._aberturas_getter = aberturas_getter
        # Polígonos que completan sus esquinas en L con otros muros
        # (ver `remiendos_esquinas_muros`).
        self._remiendos_getter = remiendos_getter
        self._resaltado_borrar: bool = False
        self._modo_borrar_activo: bool = False
        self._seleccionado: bool = False
        # True cuando un `BordesMurosItem` dibuja el contorno de todos
        # los muros juntos (uniones limpias en T, L, diagonales). En ese
        # caso este item sólo pinta el relleno.
        self._borde_compartido: bool = False
        # Cache del cuerpo (contorno − aberturas): (clave, path).
        self._cache_cuerpo: Optional[tuple] = None
        self.setZValue(400)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | Qt.MouseButton.NoButton
        )
        self.setAcceptHoverEvents(False)

    def muro(self) -> Muro:
        return self._muro

    def set_borde_compartido(self, activo: bool) -> None:
        if activo != self._borde_compartido:
            self._borde_compartido = activo
            self.update()

    def remiendos_path(self) -> QPainterPath:
        """Remiendos de esquinas en L de este muro (puede ser vacío)."""
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for poly in self._remiendos_getter(self._muro.id):
            path.addPolygon(poly)
            path.closeSubpath()
        return path

    def cuerpo_path(self) -> QPainterPath:
        """Polígono del muro con su grosor, con los huecos de puertas y
        ventanas ya restados. Se cachea: sólo se recalcula si cambia el
        muro, la escala o alguna de sus aberturas."""
        escala = self._escala_getter()
        puertas, ventanas = self._aberturas_getter(self._muro.id)
        m = self._muro
        clave = (
            tuple((v.x(), v.y()) for v in m.vertices),
            m.grosor_pt(escala),
            getattr(m.justificacion, "name", str(m.justificacion)),
            getattr(m.tipo_geometria, "name", str(m.tipo_geometria)),
            bool(m.cerrado),
            tuple(
                (ab.id, ab.d_desde_inicio_pt, ab.ancho_pt)
                for ab in list(puertas) + list(ventanas)
            ),
        )
        if self._cache_cuerpo is not None and self._cache_cuerpo[0] == clave:
            return self._cache_cuerpo[1]
        contorno = QPainterPath()
        if len(m.vertices) >= 2:
            contorno = _contorno_muro_con_grosor(m, m.grosor_pt(escala))
            aberturas = self._path_aberturas()
            if aberturas is not None and not contorno.isEmpty():
                contorno = contorno.subtracted(aberturas)
        self._cache_cuerpo = (clave, contorno)
        return contorno

    def actualizar_desde_modelo(self) -> None:
        # Primero se avisa a la escena con el rectángulo VIEJO (el que
        # tiene indexado) y luego se recalcula. Ver `boundingRect`.
        self.prepareGeometryChange()
        self._rect_cache = self._calcular_rect()
        self.update()

    def set_seleccionado_visual(self, sel: bool) -> None:
        if sel == self._seleccionado:
            return
        self._seleccionado = sel
        self.update()

    def set_modo_borrar_activo(self, activo: bool) -> None:
        self._modo_borrar_activo = activo
        self.setAcceptHoverEvents(activo)
        if not activo and self._resaltado_borrar:
            self._resaltado_borrar = False
            self.update()

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        if self._modo_borrar_activo:
            self._resaltado_borrar = True
            self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        if self._resaltado_borrar:
            self._resaltado_borrar = False
            self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            self._modo_borrar_activo
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.clic_recibido.emit(self._muro.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def _grosor_pt(self) -> float:
        """Grosor del muro en pt PDF, resolviendo escala."""
        return self._muro.grosor_pt(self._escala_getter())

    def boundingRect(self) -> QRectF:  # noqa: N802
        # Rectángulo CACHEADO: sólo cambia en `actualizar_desde_modelo`,
        # después de `prepareGeometryChange()`. Si se calculara en vivo
        # desde el modelo, al borrar/editar un muro el rectángulo
        # cambiaría "a escondidas" de la escena, su índice quedaría
        # apuntando al item viejo y al destruirlo el programa se cerraba
        # (pasaba al borrar un muro con puerta).
        if self._rect_cache is None:
            self._rect_cache = self._calcular_rect()
        return self._rect_cache

    def _calcular_rect(self) -> QRectF:
        if not self._muro.vertices:
            return QRectF()
        grosor = self._grosor_pt()
        margen = self._MARGEN_BBOX + grosor  # inflar por el grosor
        if self._muro.es_arco():
            rect = _rect_arco_3_puntos(
                self._muro.vertices[0],
                self._muro.vertices[1],
                self._muro.vertices[2],
            )
            return rect.adjusted(-margen, -margen, margen, margen)
        xs = [v.x() for v in self._muro.vertices]
        ys = [v.y() for v in self._muro.vertices]
        rect = QRectF(
            min(xs) - margen, min(ys) - margen,
            (max(xs) - min(xs)) + 2 * margen,
            (max(ys) - min(ys)) + 2 * margen,
        )
        remiendos = self.remiendos_path()
        if not remiendos.isEmpty():
            rect = rect.united(remiendos.boundingRect().adjusted(
                -self._MARGEN_BBOX, -self._MARGEN_BBOX,
                self._MARGEN_BBOX, self._MARGEN_BBOX,
            ))
        return rect

    def shape(self) -> QPainterPath:  # noqa: N802
        """Hit-testing usa el polígono real del muro (con grosor). Así
        el usuario puede dar clic en cualquier parte del muro, no solo
        en el eje."""
        grosor = self._grosor_pt()
        contorno = _contorno_muro_con_grosor(
            self._muro, max(grosor, 10.0),   # mínimo 10 pt para clic cómodo
        )
        return contorno

    def _path_aberturas(self) -> Optional[QPainterPath]:
        """Une los huecos de todas las aberturas (puertas + ventanas)
        de este muro, para restarlos del polígono del muro. Cada hueco
        sigue el trazo del muro (ver `geometria_abertura`): dobla en los
        quiebres y respeta el pico cuando la abertura termina en uno.
        None si no hay aberturas."""
        puertas, ventanas = self._aberturas_getter(self._muro.id)
        if not puertas and not ventanas:
            return None
        path_total = QPainterPath()
        path_total.setFillRule(Qt.FillRule.WindingFill)
        escala = self._escala_getter()
        for ab in list(puertas) + list(ventanas):
            geo = geometria_abertura(
                self._muro, ab.d_desde_inicio_pt, ab.ancho_pt, escala,
            )
            if geo is not None:
                path_total.addPath(geo["hueco"])
        if path_total.isEmpty():
            return None
        return path_total

    def paint(  # noqa: N802
        self, painter, option, widget=None,
    ) -> None:
        if len(self._muro.vertices) < 2:
            return
        scale = _painter_scale(painter)

        # Polígono del muro con los huecos de aberturas ya restados
        contorno = self.cuerpo_path()
        if contorno.isEmpty():
            return

        # Colores según estado
        if self._resaltado_borrar:
            color_fondo = QColor(255, 77, 77, 90)
            color_hatch = QColor(COLOR_MURO_HOVER_DEL)
            color_borde = QColor(COLOR_MURO_HOVER_DEL)
            hatch_style = Qt.BrushStyle.SolidPattern
            grosor_borde = max(2.0 / scale, 0.5)
        elif self._seleccionado:
            color_fondo = QColor(255, 184, 77, 60)
            color_hatch = QColor(COLOR_MURO_SEL)
            color_borde = QColor(COLOR_MURO_SEL)
            hatch_style = HATCH_POR_MATERIAL.get(
                self._muro.material, Qt.BrushStyle.Dense7Pattern,
            )
            grosor_borde = max(1.8 / scale, 0.4)
        else:
            color_fondo = QColor(COLOR_HATCH_POR_MATERIAL.get(
                self._muro.material, "#a8a8a8",
            ))
            color_hatch = QColor("#3a3a3a")
            color_borde = QColor("#1a1a1a")
            hatch_style = HATCH_POR_MATERIAL.get(
                self._muro.material, Qt.BrushStyle.Dense7Pattern,
            )
            grosor_borde = max(1.2 / scale, 0.3)

        # Relleno base + hatch por material (dos capas). Los remiendos
        # de esquina en L llevan el mismo relleno.
        remiendos = self.remiendos_path()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color_fondo))
        painter.drawPath(contorno)
        if not remiendos.isEmpty():
            painter.drawPath(remiendos)
        # Hatch encima
        brush_hatch = QBrush(color_hatch, hatch_style)
        painter.setBrush(brush_hatch)
        painter.drawPath(contorno)
        if not remiendos.isEmpty():
            painter.drawPath(remiendos)

        # Borde: si lo dibuja `BordesMurosItem` (debajo de todos los
        # rellenos, para que las uniones entre muros queden limpias),
        # aquí sólo se pinta en los estados resaltados.
        if (
            self._borde_compartido
            and not self._resaltado_borrar
            and not self._seleccionado
        ):
            return
        # Borde del polígono: en pico para muros rectos (esquinas del
        # zigzag nítidas); redondeado en arcos (evita picos diminutos
        # entre sus micro-segmentos).
        pen_borde = QPen(color_borde)
        pen_borde.setWidthF(grosor_borde)
        pen_borde.setCapStyle(Qt.PenCapStyle.FlatCap)
        if self._muro.es_arco():
            pen_borde.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        else:
            pen_borde.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            pen_borde.setMiterLimit(_MITER_MAX)
        painter.setPen(pen_borde)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(contorno)


class BordesMurosItem(QGraphicsObject):
    """Contorno de TODOS los muros del plano, dibujado DEBAJO de sus
    rellenos. Cada contorno se traza al doble de ancho: la mitad de
    afuera queda visible y la de adentro la tapa el relleno. Donde dos
    muros se tocan o se enciman (unión en T, esquina, muro en diagonal
    contra otro), la línea de la unión queda tapada por el relleno del
    otro muro y los dos se leen como una sola pieza — sin cálculos de
    unión/recorte de Qt, que fallan con bordes coincidentes.

    `items_getter()` devuelve los `MuroItem` actuales. La página llama
    `refrescar()` cuando se agregan, quitan o cambian muros."""

    def __init__(self, items_getter) -> None:
        super().__init__()
        self._items_getter = items_getter
        self._rect = QRectF()
        self.setZValue(399.5)   # justo debajo de los muros (z = 400)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True,
        )

    def refrescar(self) -> None:
        self.prepareGeometryChange()
        rect = QRectF()
        for it in self._items_getter():
            rect = rect.united(it.sceneBoundingRect())
        self._rect = rect
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._rect

    def shape(self) -> QPainterPath:  # noqa: N802
        # Nunca intercepta clics ni hover: no tiene forma "sólida".
        return QPainterPath()

    def paint(  # noqa: N802
        self, painter, option, widget=None,
    ) -> None:
        scale = _painter_scale(painter)
        ancho = 2.0 * max(1.2 / scale, 0.3)
        expuesto = option.exposedRect if option is not None else QRectF()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for it in self._items_getter():
            if not it.isVisible():
                continue
            if not expuesto.isNull() and not expuesto.intersects(
                it.sceneBoundingRect(),
            ):
                continue
            path = it.cuerpo_path()
            if path.isEmpty():
                continue
            pen = QPen(QColor("#1a1a1a"))
            pen.setWidthF(ancho)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            if it.muro().es_arco():
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            else:
                pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                pen.setMiterLimit(_MITER_MAX)
            painter.setPen(pen)
            painter.drawPath(path)
            remiendos = it.remiendos_path()
            if not remiendos.isEmpty():
                painter.drawPath(remiendos)


def _rectangulo_orientado(
    centro: QPointF, tangente: QPointF, ancho: float, alto: float,
) -> QPainterPath:
    """Rectángulo (como QPainterPath cerrado) centrado en `centro`,
    con la dimensión `ancho` alineada a `tangente` y la dimensión
    `alto` en la dirección normal (izquierda de la tangente).

    Usado para los huecos de puertas/ventanas y para el trazo de la
    ventana en su símbolo dibujado.
    """
    tx, ty = tangente.x(), tangente.y()
    # Vector normal (izquierda del sentido de recorrido en Y-down)
    nx, ny = -ty, tx
    hx = tx * (ancho / 2.0)
    hy = ty * (ancho / 2.0)
    kx = nx * (alto / 2.0)
    ky = ny * (alto / 2.0)
    p1 = QPointF(centro.x() - hx - kx, centro.y() - hy - ky)
    p2 = QPointF(centro.x() + hx - kx, centro.y() + hy - ky)
    p3 = QPointF(centro.x() + hx + kx, centro.y() + hy + ky)
    p4 = QPointF(centro.x() - hx + kx, centro.y() - hy + ky)
    path = QPainterPath()
    path.moveTo(p1)
    path.lineTo(p2)
    path.lineTo(p3)
    path.lineTo(p4)
    path.closeSubpath()
    return path


# ---------------------------------------------------------------------------
# HabitacionItem — visual persistente de una habitación
# ---------------------------------------------------------------------------

class HabitacionItem(QGraphicsObject):
    """Visualización persistente de una `Habitacion`: polígono cerrado
    con contorno azul + relleno translúcido + etiqueta central con
    nombre y área."""

    clic_recibido = pyqtSignal(str)

    _MARGEN_BBOX = 20.0

    def __init__(
        self,
        habitacion: Habitacion,
        escala_getter,
    ) -> None:
        super().__init__()
        self._rect_cache: Optional[QRectF] = None
        self._hab = habitacion
        self._escala_getter = escala_getter
        self._resaltado_borrar: bool = False
        self._modo_borrar_activo: bool = False
        self._seleccionado: bool = False
        self.setZValue(300)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | Qt.MouseButton.NoButton
        )
        self.setAcceptHoverEvents(False)

    def habitacion(self) -> Habitacion:
        return self._hab

    def actualizar_desde_modelo(self) -> None:
        # Primero se avisa a la escena con el rectángulo VIEJO (el que
        # tiene indexado) y luego se recalcula. Ver `boundingRect`.
        self.prepareGeometryChange()
        self._rect_cache = self._calcular_rect()
        self.update()

    def set_seleccionado_visual(self, sel: bool) -> None:
        if sel == self._seleccionado:
            return
        self._seleccionado = sel
        self.update()

    def set_modo_borrar_activo(self, activo: bool) -> None:
        self._modo_borrar_activo = activo
        self.setAcceptHoverEvents(activo)
        if not activo and self._resaltado_borrar:
            self._resaltado_borrar = False
            self.update()

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        if self._modo_borrar_activo:
            self._resaltado_borrar = True
            self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        if self._resaltado_borrar:
            self._resaltado_borrar = False
            self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            self._modo_borrar_activo
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.clic_recibido.emit(self._hab.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def boundingRect(self) -> QRectF:  # noqa: N802
        # Rectángulo CACHEADO: sólo cambia en `actualizar_desde_modelo`,
        # después de `prepareGeometryChange()`. Si se calculara en vivo
        # desde el modelo, al borrar/editar un muro el rectángulo
        # cambiaría "a escondidas" de la escena, su índice quedaría
        # apuntando al item viejo y al destruirlo el programa se cerraba
        # (pasaba al borrar un muro con puerta).
        if self._rect_cache is None:
            self._rect_cache = self._calcular_rect()
        return self._rect_cache

    def _poligono(self) -> list[QPointF]:
        """Contorno con los tramos en arco ya muestreados."""
        return self._hab.poligono()

    def _calcular_rect(self) -> QRectF:
        pts = self._poligono()
        if not pts:
            return QRectF()
        xs = [v.x() for v in pts]
        ys = [v.y() for v in pts]
        return QRectF(
            min(xs) - self._MARGEN_BBOX, min(ys) - self._MARGEN_BBOX,
            (max(xs) - min(xs)) + 2 * self._MARGEN_BBOX,
            (max(ys) - min(ys)) + 2 * self._MARGEN_BBOX,
        )

    def shape(self) -> QPainterPath:  # noqa: N802
        path = QPainterPath()
        pts = self._poligono()
        if len(pts) < 3:
            return path
        poly = QPolygonF(pts)
        path.addPolygon(poly)
        path.closeSubpath()
        return path

    def paint(  # noqa: N802
        self, painter, option, widget=None,
    ) -> None:
        pts = self._poligono()
        if len(pts) < 3:
            return
        scale = _painter_scale(painter)
        grosor = max(_GROSOR_HABITACION_PT / scale, 0.5)

        if self._resaltado_borrar:
            c_linea = QColor(COLOR_HAB_HOVER_DEL)
            c_fill = QColor(255, 77, 77, 60)
            grosor *= 1.5
        elif self._seleccionado:
            c_linea = QColor(COLOR_HAB_SEL)
            c_fill = QColor(255, 184, 77, 60)
            grosor *= 1.3
        else:
            c_linea = QColor(COLOR_HAB_LINEA)
            c_fill = QColor(90, 174, 252, 51)

        poly = QPolygonF(pts)
        pen = QPen(c_linea)
        pen.setWidthF(grosor)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(c_fill))
        painter.drawPolygon(poly)

        # Etiqueta central: nombre + área
        centro = self._centroide()
        escala_actual: Optional[EscalaCalibrada] = self._escala_getter()
        area_m2 = self._hab.area_m2(escala_actual)
        if area_m2 is not None:
            texto = f"{self._hab.nombre}\n{area_m2:.2f} m²"
        else:
            texto = self._hab.nombre

        painter.save()
        painter.translate(centro)
        painter.scale(1.0 / scale, 1.0 / scale)

        fuente = QFont()
        fuente.setPointSize(10)
        fuente.setBold(True)
        painter.setFont(fuente)
        metrics = QFontMetricsF(fuente)
        lineas = texto.split("\n")
        ancho_txt = max(metrics.horizontalAdvance(l) for l in lineas)
        alto_linea = metrics.height()
        alto_txt = alto_linea * len(lineas)

        pad_x, pad_y = 8.0, 4.0
        rect_bg = QRectF(
            -ancho_txt / 2 - pad_x, -alto_txt / 2 - pad_y,
            ancho_txt + 2 * pad_x, alto_txt + 2 * pad_y,
        )
        bg = QColor(26, 26, 26, 204)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(c_linea, 1.2))
        painter.drawRoundedRect(rect_bg, 4.0, 4.0)

        painter.setPen(QPen(QColor(COLOR_HAB_TEXTO)))
        y_actual = -alto_txt / 2
        for l in lineas:
            r = QRectF(
                -ancho_txt / 2, y_actual,
                ancho_txt, alto_linea,
            )
            painter.drawText(
                r, Qt.AlignmentFlag.AlignCenter, l,
            )
            y_actual += alto_linea

        painter.restore()

    def _centroide(self) -> QPointF:
        """Centro de área del contorno (con los arcos muestreados muchos
        puntos caen en la curva y el promedio simple se cargaría hacia
        ella)."""
        pts = self._poligono()
        n = len(pts)
        if n == 0:
            return QPointF(0, 0)
        a2 = cx = cy = 0.0
        for i in range(n):
            x1, y1 = pts[i].x(), pts[i].y()
            x2, y2 = pts[(i + 1) % n].x(), pts[(i + 1) % n].y()
            c = x1 * y2 - x2 * y1
            a2 += c
            cx += (x1 + x2) * c
            cy += (y1 + y2) * c
        if abs(a2) < 1e-9:
            return QPointF(sum(p.x() for p in pts) / n, sum(p.y() for p in pts) / n)
        return QPointF(cx / (3.0 * a2), cy / (3.0 * a2))


# ---------------------------------------------------------------------------
# PuertaItem — visual persistente de una puerta
# ---------------------------------------------------------------------------

# El plano de fondo es blanco (página del PDF): las líneas de puerta
# van oscuras para leerse igual que el borde del muro.
COLOR_PUERTA          = "#2a2a2a"    # hoja de la puerta
COLOR_PUERTA_ARCO     = "#707070"    # arco de barrido (más tenue)
COLOR_PUERTA_HOVER_DEL= "#ff4d4d"
COLOR_VENTANA         = "#3aa8e0"    # cristal (azul típico de plano)
COLOR_VENTANA_MARCO   = "#1a1a1a"    # caras del muro que cruzan el vano
COLOR_VENTANA_HOVER_DEL = "#ff4d4d"


class PuertaItem(QGraphicsObject):
    """Visualización persistente de una `Puerta` sobre el muro.

    Se pinta como:
      * Un rectángulo con color de fondo del canvas que "tapa" el
        hueco del muro (ya lo hace MuroItem al restar aberturas).
      * La HOJA de la puerta: un segmento del ancho del muro
        (perpendicular al eje) desde el eje del muro hacia el interior.
      * El ARCO de barrido: cuarto de círculo con radio = ancho del
        hueco, orientado según `sentido_apertura`.

    Los getters permiten al item recalcular su posición sin depender
    del layout de arriba:
      * `muro_getter(muro_id)` → Optional[Muro]
      * `escala_getter()` → Optional[EscalaCalibrada]

    Signals:
      * clic_recibido(str) — emit(puerta.id) al clic en modo borrar.
    """

    clic_recibido = pyqtSignal(str)

    _MARGEN_BBOX = 20.0

    def __init__(
        self,
        puerta: Puerta,
        muro_getter,
        escala_getter=lambda: None,
    ) -> None:
        super().__init__()
        self._rect_cache: Optional[QRectF] = None
        self._puerta = puerta
        self._muro_getter = muro_getter
        self._escala_getter = escala_getter
        self._resaltado_borrar: bool = False
        self._modo_borrar_activo: bool = False
        self.setZValue(500)   # arriba del muro (z=400) pero abajo del preview
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
        )
        self.setAcceptHoverEvents(False)

    def puerta(self) -> Puerta:
        return self._puerta

    def actualizar_desde_modelo(self) -> None:
        # Primero se avisa a la escena con el rectángulo VIEJO (el que
        # tiene indexado) y luego se recalcula. Ver `boundingRect`.
        self.prepareGeometryChange()
        self._rect_cache = self._calcular_rect()
        self.update()

    def set_modo_borrar_activo(self, activo: bool) -> None:
        self._modo_borrar_activo = activo
        self.setAcceptHoverEvents(activo)
        if not activo and self._resaltado_borrar:
            self._resaltado_borrar = False
            self.update()

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        if self._modo_borrar_activo:
            self._resaltado_borrar = True
            self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        if self._resaltado_borrar:
            self._resaltado_borrar = False
            self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            self._modo_borrar_activo
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.clic_recibido.emit(self._puerta.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def _info_muro(self):
        """Devuelve (muro, centro_cuerpo, tangente, normal, grosor_pt)
        o None si el muro ya no existe. El centro es el del CUERPO del
        muro (respeta la justificación), no la línea trazada."""
        muro = self._muro_getter(self._puerta.muro_id)
        if muro is None:
            return None
        info = punto_cuerpo_muro(
            muro, self._puerta.d_desde_inicio_pt, self._escala_getter(),
        )
        if info is None:
            return None
        centro, tang, normal, grosor = info
        return muro, centro, tang, normal, grosor

    def _geometria(self) -> Optional[dict]:
        """Puntos de dibujo de la puerta.

        Convención arquitectónica: la bisagra va en la CARA del muro
        hacia la que abre la hoja (no en el eje). La hoja abierta sale
        perpendicular desde ahí con largo = ancho del hueco, y el arco
        barre desde la posición cerrada (apoyada contra el otro
        extremo del hueco) hasta la abierta.
        """
        info = self._info_muro()
        if info is None:
            return None
        _muro, centro, tang, normal, grosor = info
        ancho = self._puerta.ancho_pt
        sentido = self._puerta.sentido_apertura
        if sentido == SentidoAperturaPuerta.DER:
            signo = +1.0
        elif sentido == SentidoAperturaPuerta.IZQ:
            signo = -1.0
        else:
            signo = 0.0
        # Extremo A (menor d) está en −tang·ancho/2; B en +tang·ancho/2.
        signo_pivote = -1.0 if self._puerta.pivote_en_inicio else +1.0
        cara = signo * grosor / 2.0   # desplazamiento a la cara de apertura
        pivote = QPointF(
            centro.x() + signo_pivote * tang.x() * ancho / 2.0 + normal.x() * cara,
            centro.y() + signo_pivote * tang.y() * ancho / 2.0 + normal.y() * cara,
        )
        otro = QPointF(
            centro.x() - signo_pivote * tang.x() * ancho / 2.0 + normal.x() * cara,
            centro.y() - signo_pivote * tang.y() * ancho / 2.0 + normal.y() * cara,
        )
        hoja = QPointF(
            pivote.x() + signo * normal.x() * ancho,
            pivote.y() + signo * normal.y() * ancho,
        )
        return {
            "centro": centro, "tang": tang, "grosor": grosor,
            "ancho": ancho, "signo": signo,
            "pivote": pivote, "otro": otro, "hoja": hoja,
        }

    def boundingRect(self) -> QRectF:  # noqa: N802
        # Rectángulo CACHEADO: sólo cambia en `actualizar_desde_modelo`,
        # después de `prepareGeometryChange()`. Si se calculara en vivo
        # desde el modelo, al borrar/editar un muro el rectángulo
        # cambiaría "a escondidas" de la escena, su índice quedaría
        # apuntando al item viejo y al destruirlo el programa se cerraba
        # (pasaba al borrar un muro con puerta).
        if self._rect_cache is None:
            self._rect_cache = self._calcular_rect()
        return self._rect_cache

    def _calcular_rect(self) -> QRectF:
        g = self._geometria()
        if g is None:
            return QRectF()
        # Círculo del arco centrado en el pivote + margen
        radio = g["ancho"] + g["grosor"]
        margen = self._MARGEN_BBOX
        p = g["pivote"]
        return QRectF(
            p.x() - radio - margen, p.y() - radio - margen,
            2 * (radio + margen), 2 * (radio + margen),
        )

    def shape(self) -> QPainterPath:  # noqa: N802
        g = self._geometria()
        if g is None:
            return QPainterPath()
        # Zona sensible: el rectángulo del hueco. Suficiente para
        # hit-testing cómodo (goma, selección).
        return _rectangulo_orientado(
            g["centro"], g["tang"], g["ancho"], max(g["grosor"] + 6.0, 12.0),
        )

    def paint(  # noqa: N802
        self, painter, option, widget=None,
    ) -> None:
        g = self._geometria()
        if g is None or g["signo"] == 0.0:
            # Sin sentido (puerta corrediza / vano): sólo el hueco,
            # que ya resta el MuroItem.
            return
        scale = _painter_scale(painter)
        grosor_ln = max(1.4 / scale, 0.3)
        color_linea = (
            QColor(COLOR_PUERTA_HOVER_DEL) if self._resaltado_borrar
            else QColor(COLOR_PUERTA)
        )
        pivote, otro, hoja, ancho = g["pivote"], g["otro"], g["hoja"], g["ancho"]

        # 1) HOJA abierta: del pivote, perpendicular al muro.
        pen_hoja = QPen(color_linea)
        pen_hoja.setWidthF(grosor_ln * 1.6)
        pen_hoja.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_hoja)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(pivote, hoja)

        # 2) ARCO de barrido: de la hoja cerrada a la hoja abierta.
        pen_arco = QPen(
            QColor(COLOR_PUERTA_HOVER_DEL) if self._resaltado_borrar
            else QColor(COLOR_PUERTA_ARCO)
        )
        pen_arco.setWidthF(grosor_ln)
        painter.setPen(pen_arco)
        rect_arco = QRectF(
            pivote.x() - ancho, pivote.y() - ancho, 2 * ancho, 2 * ancho,
        )
        a_ini, barrido = angulo_barrido_puerta(pivote, otro, hoja)
        painter.drawArc(
            rect_arco, int(round(a_ini * 16)), int(round(barrido * 16)),
        )


# ---------------------------------------------------------------------------
# VentanaItem — visual persistente de una ventana
# ---------------------------------------------------------------------------

class VentanaItem(QGraphicsObject):
    """Visualización persistente de una `Ventana` sobre el muro.

    Se pinta como dos líneas paralelas dentro del hueco (representando
    el cristal), con marcas laterales indicando los bordes de la
    ventana. Convención de plano arquitectónico mexicano.
    """

    clic_recibido = pyqtSignal(str)

    _MARGEN_BBOX = 15.0

    def __init__(
        self,
        ventana: Ventana,
        muro_getter,
        escala_getter=lambda: None,
    ) -> None:
        super().__init__()
        self._rect_cache: Optional[QRectF] = None
        self._ventana = ventana
        self._muro_getter = muro_getter
        self._escala_getter = escala_getter
        self._resaltado_borrar: bool = False
        self._modo_borrar_activo: bool = False
        self.setZValue(500)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(False)

    def ventana(self) -> Ventana:
        return self._ventana

    def actualizar_desde_modelo(self) -> None:
        # Primero se avisa a la escena con el rectángulo VIEJO (el que
        # tiene indexado) y luego se recalcula. Ver `boundingRect`.
        self.prepareGeometryChange()
        self._rect_cache = self._calcular_rect()
        self.update()

    def set_modo_borrar_activo(self, activo: bool) -> None:
        self._modo_borrar_activo = activo
        self.setAcceptHoverEvents(activo)
        if not activo and self._resaltado_borrar:
            self._resaltado_borrar = False
            self.update()

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        if self._modo_borrar_activo:
            self._resaltado_borrar = True
            self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        if self._resaltado_borrar:
            self._resaltado_borrar = False
            self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            self._modo_borrar_activo
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.clic_recibido.emit(self._ventana.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def _geometria(self) -> Optional[dict]:
        """Geometría compartida con el hueco del muro (ver
        `geometria_abertura`): la ventana sigue el trazo del muro, dobla
        en los quiebres y se queda dentro del cuerpo aunque el muro
        tenga justificación izquierda/derecha."""
        muro = self._muro_getter(self._ventana.muro_id)
        if muro is None:
            return None
        return geometria_abertura(
            muro, self._ventana.d_desde_inicio_pt, self._ventana.ancho_pt,
            self._escala_getter(),
        )

    def boundingRect(self) -> QRectF:  # noqa: N802
        # Rectángulo CACHEADO: sólo cambia en `actualizar_desde_modelo`,
        # después de `prepareGeometryChange()`. Si se calculara en vivo
        # desde el modelo, al borrar/editar un muro el rectángulo
        # cambiaría "a escondidas" de la escena, su índice quedaría
        # apuntando al item viejo y al destruirlo el programa se cerraba
        # (pasaba al borrar un muro con puerta).
        if self._rect_cache is None:
            self._rect_cache = self._calcular_rect()
        return self._rect_cache

    def _calcular_rect(self) -> QRectF:
        geo = self._geometria()
        if geo is None:
            return QRectF()
        m = self._MARGEN_BBOX
        return geo["hueco"].boundingRect().adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:  # noqa: N802
        # Zona sensible (goma, selección) = el propio hueco.
        geo = self._geometria()
        return geo["hueco"] if geo is not None else QPainterPath()

    def paint(  # noqa: N802
        self, painter, option, widget=None,
    ) -> None:
        geo = self._geometria()
        if geo is None:
            return
        borrar = self._resaltado_borrar
        # Todo el símbolo queda dentro del hueco (sigue el muro, dobla en
        # quiebres y llega a la diagonal de una esquina).
        dibujar_simbolo_ventana(
            painter, geo, _painter_scale(painter),
            QColor(COLOR_VENTANA_HOVER_DEL if borrar else COLOR_VENTANA_MARCO),
            QColor(COLOR_VENTANA_HOVER_DEL if borrar else COLOR_VENTANA),
        )


# ---------------------------------------------------------------------------
# VerticeEditableItem — círculo arrastrable para editar un vértice
# ---------------------------------------------------------------------------

class VerticeEditableItem(QGraphicsObject):
    """Círculo pequeño que representa un vértice editable de un muro
    o habitación seleccionada. Se puede arrastrar; al soltar, emite
    `vertice_movido(int, QPointF)` con el índice del vértice y su
    nueva posición.
    """

    vertice_movido = pyqtSignal(int, QPointF)

    def __init__(
        self, indice: int, posicion: QPointF,
    ) -> None:
        super().__init__()
        self._indice = indice
        self._pos = QPointF(posicion)
        self._arrastrando = False
        self._hover = False
        self.setZValue(9500)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True
        )

    def indice(self) -> int:
        return self._indice

    def set_posicion(self, p: QPointF) -> None:
        self.prepareGeometryChange()
        self._pos = QPointF(p)
        self.update()

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._arrastrando = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._arrastrando:
            nueva = event.scenePos()
            self._pos = nueva
            self.vertice_movido.emit(self._indice, nueva)
            self.prepareGeometryChange()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._arrastrando:
            self._arrastrando = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def boundingRect(self) -> QRectF:  # noqa: N802
        r = 20.0
        return QRectF(
            self._pos.x() - r, self._pos.y() - r, 2 * r, 2 * r,
        )

    def paint(  # noqa: N802
        self, painter, option, widget=None,
    ) -> None:
        scale = _painter_scale(painter)
        radio = _RADIO_VERTICE_PT / scale
        grosor = max(1.5 / scale, 0.3)
        color = QColor(
            COLOR_VERTICE_HOVER if (self._hover or self._arrastrando)
            else COLOR_VERTICE
        )
        painter.setPen(QPen(QColor(COLOR_TEXTO), grosor))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(self._pos, radio, radio)


# ---------------------------------------------------------------------------
# HerramientaDibujoPolilinea — base state machine para muros/habitaciones
# ---------------------------------------------------------------------------

class _EstadoDibujo(Enum):
    INACTIVO = 0
    DIBUJANDO = 1


class HerramientaDibujoPolilinea(QObject):
    """Base para herramientas que dibujan polilíneas con clics
    sucesivos. Las subclases implementan `_finalizar()` cuando el
    usuario hace doble clic / Enter / cierre.

    Flujo:
      1. activar() — pone el state en DIBUJANDO
      2. registrar_click(p) — añade vértice
      3. actualizar_cursor(p) — mueve el preview
      4. terminar() — llama _finalizar(vertices)
      5. cancelar() — descarta

    Signals:
      * primer_vertice_registrado(QPointF)
      * vertices_cambiados(list[QPointF])
      * cursor_movido(QPointF)
      * dibujo_terminado(list[QPointF])
      * dibujo_cancelado
      * estado_mensaje(str)
    """

    primer_vertice_registrado = pyqtSignal(QPointF)
    vertices_cambiados        = pyqtSignal(list)
    cursor_movido             = pyqtSignal(QPointF)
    dibujo_terminado          = pyqtSignal(list)
    dibujo_cancelado          = pyqtSignal()
    estado_mensaje            = pyqtSignal(str)

    # Distancia mínima entre vértices consecutivos (pt PDF). ~0.35 mm
    # en el papel — suficiente para distinguir dos puntos sin bloquear
    # trazos precisos en esquinas de muros gruesos.
    DIST_MIN_VERTICE_PT = 1.0

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._estado = _EstadoDibujo.INACTIVO
        self._vertices: list[QPointF] = []
        # Cuando True, el clic dentro del "radio de snap" del primer
        # vértice cierra automáticamente el polígono en ese punto
        # exacto — patrón AutoCAD. Las subclases lo activan según su
        # semántica (Habitación sí, Muro no).
        self._snap_al_primer_vertice: bool = False

    def snap_al_primer_vertice(self) -> bool:
        return self._snap_al_primer_vertice

    def esta_activa(self) -> bool:
        return self._estado != _EstadoDibujo.INACTIVO

    def vertices(self) -> list[QPointF]:
        return list(self._vertices)

    def cantidad_vertices(self) -> int:
        return len(self._vertices)

    def activar(self) -> None:
        self._estado = _EstadoDibujo.DIBUJANDO
        self._vertices = []
        self._emit_mensaje_inicial()

    def desactivar(self) -> None:
        if not self.esta_activa():
            return
        self._estado = _EstadoDibujo.INACTIVO
        self._vertices = []
        self.dibujo_cancelado.emit()

    def cancelar(self) -> None:
        if not self.esta_activa():
            return
        self._vertices = []
        self.dibujo_cancelado.emit()
        # No cambiamos estado — sigue activa esperando nuevo dibujo.
        self._emit_mensaje_inicial()

    def registrar_click(self, punto_pdf: QPointF) -> bool:
        if not self.esta_activa():
            return False
        # Rechazar vértices demasiado cercanos al último
        if self._vertices:
            ultimo = self._vertices[-1]
            d = math.hypot(
                punto_pdf.x() - ultimo.x(), punto_pdf.y() - ultimo.y()
            )
            if d < self.DIST_MIN_VERTICE_PT:
                self.estado_mensaje.emit(
                    "Punto demasiado cerca del anterior. Elige otro."
                )
                return True
        primer = not self._vertices
        self._vertices.append(QPointF(punto_pdf))
        if primer:
            self.primer_vertice_registrado.emit(QPointF(punto_pdf))
        self.vertices_cambiados.emit(list(self._vertices))
        self._emit_mensaje_progreso()
        return True

    def actualizar_cursor(self, punto_pdf: QPointF) -> None:
        if not self.esta_activa():
            return
        self.cursor_movido.emit(QPointF(punto_pdf))

    def terminar(self) -> bool:
        """Finaliza el dibujo. Cada subclase decide qué es válido."""
        if not self.esta_activa():
            return False
        vertices = list(self._vertices)
        if not self._es_valido_para_terminar(vertices):
            self.estado_mensaje.emit(self._mensaje_terminar_invalido())
            return False
        self._vertices = []
        self.dibujo_terminado.emit(vertices)
        self._emit_mensaje_inicial()
        return True

    def retroceder_ultimo_vertice(self) -> bool:
        """Quita el último vértice colocado sin cancelar el trazo
        completo. Equivalente a la opción 'U' de AutoCAD durante un
        `_line`, o al Ctrl+Z durante el dibujo en otros CAD. Si no hay
        vértices que quitar, no hace nada y devuelve False."""
        if not self.esta_activa() or not self._vertices:
            return False
        self._vertices.pop()
        self.vertices_cambiados.emit(list(self._vertices))
        if not self._vertices:
            self._emit_mensaje_inicial()
        else:
            self._emit_mensaje_progreso()
        return True

    def _es_valido_para_terminar(self, vertices: list[QPointF]) -> bool:
        return len(vertices) >= 2

    def _mensaje_terminar_invalido(self) -> str:
        return "Necesitas al menos 2 puntos para terminar."

    def _emit_mensaje_inicial(self) -> None:
        self.estado_mensaje.emit(
            "Clic para empezar. Enter/doble clic termina, Escape cancela."
        )

    def _emit_mensaje_progreso(self) -> None:
        n = len(self._vertices)
        self.estado_mensaje.emit(
            f"{n} vértice{'s' if n != 1 else ''}. "
            "Enter/doble clic termina."
        )


# ---------------------------------------------------------------------------
# HerramientaMuro y HerramientaHabitacion
# ---------------------------------------------------------------------------

class HerramientaMuro(HerramientaDibujoPolilinea):
    """Muro: polilínea abierta con >= 2 vértices."""

    def _emit_mensaje_inicial(self) -> None:
        self.estado_mensaje.emit(
            "Muro: clic para colocar vértices. Shift = ortogonal. "
            "Enter/doble clic termina."
        )

    def _es_valido_para_terminar(self, vertices: list[QPointF]) -> bool:
        return len(vertices) >= 2


class HerramientaHabitacion(HerramientaDibujoPolilinea):
    """Habitación: polígono cerrado que mezcla tramos RECTOS y ARCOS en
    el mismo trazo, sin cambiar de herramienta (como la polilínea de
    AutoCAD):

      * Tecla A → modo arco: cada arco son 2 clics, un punto por donde
        pasa la curva y su punto final (empieza en el último vértice).
        Se queda en modo arco para encadenar curvas.
      * Tecla L → vuelve a tramos rectos.
      * Ctrl+Z quita el último punto (o el arco completo) sin perder
        el resto del trazo.
      * Clic sobre el 1er vértice o Enter cierra. Si hay un punto de
        paso pendiente, el cierre también es arco (así salen círculos
        con dos semicírculos).

    Activa snap al primer vértice (patrón AutoCAD).

    Signal extra:
      * trazo_cambiado(dict) — {"arcos": {i: paso}, "paso": QPointF|None,
        "modo_arco": bool} para que el preview dibuje las curvas.
    """

    trazo_cambiado = pyqtSignal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._snap_al_primer_vertice = True
        self._modo_arco: bool = False
        # {i: punto de paso} del tramo vértice i → vértice i+1
        self._arcos: dict[int, QPointF] = {}
        # Punto de paso del arco en curso (esperando su punto final)
        self._paso: Optional[QPointF] = None
        # Arcos de la última habitación terminada (la página los lee al
        # recibir `dibujo_terminado`).
        self._ultimos_arcos: dict[int, QPointF] = {}

    # -------- estado del trazo
    def modo_arco(self) -> bool:
        return self._modo_arco

    def paso_pendiente(self) -> Optional[QPointF]:
        return QPointF(self._paso) if self._paso is not None else None

    def arcos(self) -> dict[int, QPointF]:
        return {i: QPointF(p) for i, p in self._arcos.items()}

    def ultimos_arcos(self) -> dict[int, QPointF]:
        return {i: QPointF(p) for i, p in self._ultimos_arcos.items()}

    def minimo_vertices_cierre(self) -> int:
        """Con curvas bastan 2 vértices para cerrar (dos semicírculos)."""
        return 2 if (self._arcos or self._paso is not None) else 3

    def _emitir_trazo(self) -> None:
        self.trazo_cambiado.emit({
            "arcos": self.arcos(),
            "paso": self.paso_pendiente(),
            "modo_arco": self._modo_arco,
        })

    def _limpiar_trazo(self) -> None:
        self._arcos = {}
        self._paso = None
        self._emitir_trazo()

    def set_modo_arco(self, activo: bool) -> None:
        if not self.esta_activa():
            return
        activo = bool(activo)
        if activo == self._modo_arco:
            return
        self._modo_arco = activo
        if not activo:
            self._paso = None          # un paso a medias se descarta
        self._emitir_trazo()
        if self._vertices:
            self._emit_mensaje_progreso()
        else:
            self._emit_mensaje_inicial()

    # -------- ciclo de vida
    def activar(self) -> None:
        self._modo_arco = False
        self._arcos = {}
        self._paso = None
        super().activar()
        self._emitir_trazo()

    def desactivar(self) -> None:
        self._arcos = {}
        self._paso = None
        super().desactivar()

    def cancelar(self) -> None:
        if not self.esta_activa():
            return
        self._arcos = {}
        self._paso = None
        super().cancelar()
        self._emitir_trazo()

    # -------- clics
    def registrar_click(self, punto_pdf: QPointF) -> bool:
        if not self.esta_activa():
            return False
        if not (self._modo_arco and self._vertices):
            return super().registrar_click(punto_pdf)
        ultimo = self._vertices[-1]

        def _cerca(a: QPointF, b: QPointF) -> bool:
            return math.hypot(a.x() - b.x(), a.y() - b.y()) < self.DIST_MIN_VERTICE_PT

        if self._paso is None:
            if _cerca(punto_pdf, ultimo):
                self.estado_mensaje.emit(
                    "Arco: el punto de paso debe estar lejos del inicio."
                )
                return True
            self._paso = QPointF(punto_pdf)
            self._emitir_trazo()
            self._emit_mensaje_progreso()
            return True
        if _cerca(punto_pdf, self._paso) or _cerca(punto_pdf, ultimo):
            self.estado_mensaje.emit(
                "Arco: el punto final debe estar lejos de los otros dos."
            )
            return True
        if len(self._vertices) >= 2 and _cerca(punto_pdf, self._vertices[0]):
            # Terminar el arco en el primer vértice = cerrar la habitación
            return self.terminar()
        indice = len(self._vertices) - 1
        paso = self._paso
        self._paso = None
        n_antes = len(self._vertices)
        ok = super().registrar_click(punto_pdf)
        if len(self._vertices) > n_antes:
            self._arcos[indice] = paso
        else:
            self._paso = paso
        self._emitir_trazo()
        return ok

    def terminar(self) -> bool:
        if not self.esta_activa():
            return False
        arcos = dict(self._arcos)
        if self._paso is not None and self._vertices:
            # Arco pendiente: cierra curvo hasta el primer vértice.
            arcos[len(self._vertices) - 1] = QPointF(self._paso)
        vertices = list(self._vertices)
        if len(vertices) < 3 and not (len(vertices) >= 2 and arcos):
            self.estado_mensaje.emit(self._mensaje_terminar_invalido())
            return False
        self._ultimos_arcos = arcos
        self._vertices = []
        self._arcos = {}
        self._paso = None
        self.dibujo_terminado.emit(vertices)
        self._emitir_trazo()
        self._emit_mensaje_inicial()
        return True

    def retroceder_ultimo_vertice(self) -> bool:
        """Ctrl+Z: quita el punto de paso pendiente, o el último vértice
        (si era el final de un arco, se va el arco completo)."""
        if not self.esta_activa():
            return False
        if self._paso is not None:
            self._paso = None
            self._emitir_trazo()
            self._emit_mensaje_progreso()
            return True
        if not self._vertices:
            return False
        self._arcos.pop(len(self._vertices) - 2, None)
        ok = super().retroceder_ultimo_vertice()
        self._emitir_trazo()
        return ok

    # -------- mensajes
    def _emit_mensaje_inicial(self) -> None:
        modo = "ARCO" if self._modo_arco else "RECTO"
        self.estado_mensaje.emit(
            f"Habitación [{modo}]: clic para colocar vértices. "
            "A = tramo en arco, L = tramo recto. Clic sobre el 1er "
            "vértice o Enter cierra."
        )

    def _emit_mensaje_progreso(self) -> None:
        if self._modo_arco:
            if self._paso is None:
                self.estado_mensaje.emit(
                    "Habitación [ARCO]: clic en un punto por donde pasa la "
                    "curva. L = volver a recto. Ctrl+Z deshace."
                )
            else:
                self.estado_mensaje.emit(
                    "Habitación [ARCO]: clic en el punto FINAL del arco "
                    "(o en el 1er vértice para cerrar). Ctrl+Z quita el "
                    "punto de paso."
                )
            return
        n = len(self._vertices)
        self.estado_mensaje.emit(
            f"Habitación [RECTO]: {n} vértice{'s' if n != 1 else ''}. "
            "A = arco. Clic sobre el 1er vértice o Enter cierra."
        )

    def _es_valido_para_terminar(self, vertices: list[QPointF]) -> bool:
        return len(vertices) >= 3

    def _mensaje_terminar_invalido(self) -> str:
        return "Necesitas al menos 3 puntos (o 2 con un arco) para cerrar la habitación."


# ---------------------------------------------------------------------------
# HerramientaMuroArco — 3 clics: inicio, paso, fin
# ---------------------------------------------------------------------------

class HerramientaMuroArco(HerramientaDibujoPolilinea):
    """Muro curvo: 3 clics — inicio, punto por el que pasa el arco, fin.
    Al colocar el tercer punto se finaliza automáticamente (no requiere
    Enter). Almacena los 3 puntos de control tal cual; la geometría
    del arco se calcula al renderizar / medir.

    El snap al primer vértice está DESACTIVADO (siempre son 3 puntos
    fijos, no un polígono cerrado)."""

    _MAX_CLICKS = 3

    def _emit_mensaje_inicial(self) -> None:
        self.estado_mensaje.emit(
            "Muro curvo: clic 1 = inicio del arco. "
            "Shift = ortogonal. Escape cancela."
        )

    def _emit_mensaje_progreso(self) -> None:
        n = len(self._vertices)
        if n == 1:
            self.estado_mensaje.emit(
                "Muro curvo: clic 2 = un punto por el que pase el arco."
            )
        elif n == 2:
            self.estado_mensaje.emit(
                "Muro curvo: clic 3 = fin del arco."
            )

    def registrar_click(self, punto_pdf: QPointF) -> bool:
        if not self.esta_activa():
            return False
        # Rechazar puntos demasiado cercanos al último
        if self._vertices:
            ultimo = self._vertices[-1]
            d = math.hypot(
                punto_pdf.x() - ultimo.x(), punto_pdf.y() - ultimo.y()
            )
            if d < self.DIST_MIN_VERTICE_PT:
                self.estado_mensaje.emit(
                    "Punto demasiado cerca del anterior. Elige otro."
                )
                return True
        primer = not self._vertices
        self._vertices.append(QPointF(punto_pdf))
        if primer:
            self.primer_vertice_registrado.emit(QPointF(punto_pdf))
        self.vertices_cambiados.emit(list(self._vertices))

        if len(self._vertices) >= self._MAX_CLICKS:
            # Finalización automática al 3er clic
            vertices = list(self._vertices)
            self._vertices = []
            self.dibujo_terminado.emit(vertices)
            self._emit_mensaje_inicial()
        else:
            self._emit_mensaje_progreso()
        return True

    def terminar(self) -> bool:
        """Enter/doble clic sólo termina si ya tenemos los 3 puntos.
        Con menos puntos, no hace nada — el usuario debe seguir haciendo
        clic. Cancelar sí es válido en cualquier momento."""
        if not self.esta_activa():
            return False
        if len(self._vertices) < self._MAX_CLICKS:
            self.estado_mensaje.emit(
                "Muro curvo: faltan puntos. Necesitas 3 clics (inicio, "
                "paso, fin)."
            )
            return False
        vertices = list(self._vertices)
        self._vertices = []
        self.dibujo_terminado.emit(vertices)
        self._emit_mensaje_inicial()
        return True

    def _es_valido_para_terminar(self, vertices: list[QPointF]) -> bool:
        return len(vertices) == self._MAX_CLICKS


# ---------------------------------------------------------------------------
# HerramientaAbertura — base para Puerta y Ventana (un clic sobre muro)
# ---------------------------------------------------------------------------

class HerramientaAbertura(QObject):
    """Herramienta base para colocar aberturas (puertas, ventanas)
    sobre un muro existente. DOS clics para definir el hueco (extremo
    A y extremo B, sobre el mismo muro). Opcionalmente un TERCER clic
    define la orientación del arco de barrido (sólo Puerta — Ventana
    se queda con 2 clics y símbolo simétrico).

    Requiere un `resolver_getter` (callable) que dado un QPointF del
    canvas devuelva `Optional[tuple[Muro, float]]` con el muro más
    cercano dentro del radio de captura + la distancia acumulada
    sobre el eje del muro hasta la proyección del cursor.

    Signals:
      * abertura_terminada(str, float, float, bool, str) —
        (muro_id, d_centro_pt, ancho_pt, pivote_en_inicio, sentido_str).
        - `pivote_en_inicio`: True = bisagra en el extremo de menor d.
        - `sentido_str`: "izq" | "der" | "ninguno" (str crudo del enum
          SentidoAperturaPuerta). Para Ventana siempre es "ninguno".
      * primer_punto_registrado(QPointF, str) — (punto, muro_id)
      * hover_muro_cambiado(object) — (muro_id, d) o None
      * preview_actualizado(object) — dict variable según el estado:
        - Sin primer clic  → None
        - Con primer clic  → {"muro_id","punto_a","punto_b","ancho_pt"}
        - Con dos clics (sólo Puerta antes del 3°) →
            {"muro_id","punto_a","punto_b","ancho_pt","centro_hueco",
             "tangente","normal","pivote_en_inicio","sentido"}
      * dibujo_cancelado
      * estado_mensaje(str)
    """

    abertura_terminada         = pyqtSignal(str, float, float, bool, str)
    primer_punto_registrado    = pyqtSignal(QPointF, str)
    hover_muro_cambiado        = pyqtSignal(object)
    preview_actualizado        = pyqtSignal(object)
    dibujo_cancelado           = pyqtSignal()
    estado_mensaje             = pyqtSignal(str)

    # Ancho mínimo de una abertura (pt PDF). Menos que esto es un clic
    # accidental doble en el mismo lugar — se ignora en vez de crear
    # una abertura de 0 cm.
    _ANCHO_MIN_PT = 2.0

    def __init__(
        self, resolver_getter, parent: Optional[QObject] = None,
        escala_getter=None,
    ) -> None:
        super().__init__(parent)
        self._activa: bool = False
        self._resolver = resolver_getter
        # La escala hace falta para saber el grosor del muro y ubicar
        # los puntos en el CENTRO DEL CUERPO (no en la línea trazada).
        self._escala_getter = escala_getter or (lambda: None)
        # Estado del primer clic. None ⇒ esperando el primer clic.
        self._primer_muro_id: Optional[str] = None
        self._primer_muro: Optional[Muro] = None
        self._primer_d: Optional[float] = None
        self._primer_punto: Optional[QPointF] = None
        # Estado del 3er clic (SÓLO puertas): si tras el 2° clic la
        # subclase pidió orientación, guardamos los datos del hueco
        # aquí y el próximo clic fija la orientación. None ⇒ no en
        # modo orientación.
        self._hueco_pend: Optional[dict] = None

    def necesita_orientacion(self) -> bool:
        """Subclases devuelven True si tras el 2° clic hay que elegir
        orientación con un 3° clic (Puerta). Default False (Ventana)."""
        return False

    def tipo_abertura(self) -> str:
        """"puerta" | "ventana" — decide cómo se dibuja el fantasma."""
        return "ventana"

    def esta_activa(self) -> bool:
        return self._activa

    def activar(self) -> None:
        self._activa = True
        self._resetear_estado()
        self._emit_mensaje_inicial()

    def desactivar(self) -> None:
        if not self._activa:
            return
        self._activa = False
        self._resetear_estado()
        self.hover_muro_cambiado.emit(None)
        self.preview_actualizado.emit(None)
        self.dibujo_cancelado.emit()

    def cancelar(self) -> None:
        if not self._activa:
            return
        self._resetear_estado()
        self.hover_muro_cambiado.emit(None)
        self.preview_actualizado.emit(None)
        self.dibujo_cancelado.emit()
        self._emit_mensaje_inicial()

    def _resetear_estado(self) -> None:
        self._primer_muro_id = None
        self._primer_muro = None
        self._primer_d = None
        # Punto EXACTO donde se marcó el primer extremo (ya enganchado si
        # el Snap lo llevó a una esquina). Su `d` depende de hacia qué lado
        # vaya la abertura, así que se recalcula con el segundo punto.
        self._primer_punto = None
        self._primer_enganchado = False
        self._lado_primero = +1
        self._hueco_pend = None

    # -------- Compatibilidad con el puente
    def vertices(self) -> list[QPointF]:
        if self._primer_punto is None:
            return []
        return [QPointF(self._primer_punto)]

    def cantidad_vertices(self) -> int:
        return 1 if self._primer_punto is not None else 0

    def snap_al_primer_vertice(self) -> bool:
        return False

    def punto_primero(self) -> Optional[QPointF]:
        return QPointF(self._primer_punto) if self._primer_punto else None

    def _en_cuerpo(self, muro: Muro, d: float) -> Optional[QPointF]:
        """Punto a distancia `d` del eje, llevado al CENTRO DEL CUERPO
        del muro."""
        info = punto_cuerpo_muro(muro, d, self._escala_getter())
        return QPointF(info[0]) if info is not None else None

    # -------- Resolución del punto marcado
    def _resolver_punto(
        self, punto_pdf: QPointF,
    ) -> Optional[tuple[Muro, QPointF, bool]]:
        """(muro, punto, enganchado): el muro bajo el cursor y el punto
        exacto a usar (el del cursor, o una esquina/extremo si el Snap lo
        enganchó). Acepta también resolvers viejos que devuelven
        (muro, d)."""
        info = self._resolver(punto_pdf)
        if info is None:
            return None
        muro, valor = info[0], info[1]
        enganchado = bool(info[2]) if len(info) > 2 else False
        if isinstance(valor, (int, float)):
            pe = _punto_y_normal_en_muro(muro, float(valor))
            if pe is None:
                return None
            return muro, QPointF(pe[0]), enganchado
        return muro, QPointF(valor), enganchado

    @staticmethod
    def _d_proyectado(muro: Muro, p: QPointF) -> float:
        proy = proyectar_punto_sobre_muro(p, muro)
        return proy[2] if proy is not None else 0.0

    def _lado_supuesto(self, muro: Muro, p: QPointF) -> int:
        """Antes de saber dónde va el otro extremo: se supone que la
        abertura sigue por el tramo donde cae `p` (alejándose de la
        esquina más cercana)."""
        d0 = self._d_proyectado(muro, p)
        cercano = None
        for _j, q in _quiebres_interiores(muro):
            if cercano is None or abs(d0 - q) < abs(d0 - cercano):
                cercano = q
        if cercano is None:
            return +1
        return -1 if d0 <= cercano else +1

    def _extremos(self, muro: Muro, p2: QPointF) -> tuple[float, float, int]:
        """(d1, d2, lado1) del primer punto marcado y `p2`. lado1 = +1 si
        la abertura va del primer punto hacia d mayores."""
        d01 = self._d_proyectado(muro, self._primer_punto)
        d02 = self._d_proyectado(muro, p2)
        if abs(d02 - d01) > 1e-6:
            self._lado_primero = +1 if d02 > d01 else -1
        lado1 = self._lado_primero
        esc = self._escala_getter()
        d1 = d_extremo_abertura(muro, self._primer_punto, lado1, esc)
        d2 = d_extremo_abertura(muro, p2, -lado1, esc)
        return d1, d2, lado1

    def punto_proyectado(self, punto_pdf: QPointF) -> Optional[QPointF]:
        """Compatibilidad: punto del cuerpo del muro bajo el cursor."""
        self._ultimo_en_quiebre = False
        if not self._activa:
            return None
        r = self._resolver_punto(punto_pdf)
        if r is None:
            return None
        muro, p, eng = r
        self._ultimo_en_quiebre = eng
        return self._en_cuerpo(muro, self._d_proyectado(muro, p))

    def ultimo_en_quiebre(self) -> bool:
        return getattr(self, "_ultimo_en_quiebre", False)

    def corte_proyectado(self, punto_pdf: QPointF) -> Optional[tuple]:
        """Línea de corte (de cara a cara del muro) que quedaría si se
        hace clic ahora: `(p1, p2, marcado)`, o None si no hay muro cerca
        o si la puerta ya espera su orientación. `marcado` = va por una
        esquina/extremo o el Snap enganchó el punto."""
        if not self._activa or self._hueco_pend is not None:
            return None
        r = self._resolver_punto(punto_pdf)
        if r is None:
            return None
        muro, p, eng = r
        esc = self._escala_getter()
        if self._primer_punto is not None and self._primer_muro_id == muro.id:
            _d1, d, lado1 = self._extremos(muro, p)
            lado = -lado1
        else:
            lado = self._lado_supuesto(muro, p)
            d = d_extremo_abertura(muro, p, lado, esc)
        c = corte_extremo_abertura(muro, d, lado, esc)
        if c is None:
            return None
        return c[0], c[1], eng or c[2] in ("esquina", "extremo")

    def _fantasma(self, muro: Muro, d_a: float, d_b: Optional[float],
                  cortes: list[tuple[float, int, bool]]) -> dict:
        """Datos para el fantasma del preview (ver
        `PreviewDibujoItem.set_abertura_preview`): la abertura entre d_a
        y d_b con la misma geometría que tendrá al colocarla, y las
        líneas de corte de los extremos ya fijados: (d, lado, enganchado)."""
        escala = self._escala_getter()
        geo = None
        if d_b is not None and d_b - d_a > 1e-6:
            geo = geometria_abertura(
                muro, (d_a + d_b) / 2.0, d_b - d_a, escala,
            )
        lineas = []
        for d, lado, eng in cortes:
            c = corte_extremo_abertura(muro, d, lado, escala)
            if c is not None:
                lineas.append((c[0], c[1], eng or c[2] in ("esquina", "extremo")))
        return {
            "tipo": self.tipo_abertura(),
            "geo": geo,
            "contorno": _contorno_muro_con_grosor(muro, muro.grosor_pt(escala)),
            "cortes": lineas,
        }

    def _preview_solo_primero(self) -> dict:
        """Preview cuando sólo está fijo el primer extremo."""
        datos = {
            "muro_id":  self._primer_muro_id,
            "punto_a":  QPointF(self._primer_punto) if self._primer_punto else None,
            "punto_b":  None,
            "ancho_pt": 0.0,
        }
        if self._primer_muro is not None and self._primer_punto is not None:
            d1 = d_extremo_abertura(
                self._primer_muro, self._primer_punto, self._lado_primero,
                self._escala_getter(),
            )
            datos["fantasma"] = self._fantasma(
                self._primer_muro, d1, None,
                [(d1, self._lado_primero, self._primer_enganchado)],
            )
        return datos

    def actualizar_cursor(self, punto_pdf: QPointF) -> None:
        if not self._activa:
            return
        # ----- Modo orientación (post 2° clic, sólo Puerta) -----
        if self._hueco_pend is not None:
            pivote_en_inicio, sentido = self._calcular_orientacion(
                punto_pdf, self._hueco_pend,
            )
            self.preview_actualizado.emit({
                **self._hueco_pend,
                "pivote_en_inicio": pivote_en_inicio,
                "sentido":          sentido,
            })
            return
        r = self._resolver_punto(punto_pdf)
        if r is None:
            self.hover_muro_cambiado.emit(None)
            if self._primer_punto is not None:
                self.preview_actualizado.emit(self._preview_solo_primero())
            else:
                self.preview_actualizado.emit(None)
            return
        muro, p, _eng = r
        self.hover_muro_cambiado.emit((muro.id, self._d_proyectado(muro, p)))
        if self._primer_punto is None:
            self.preview_actualizado.emit(None)
            return
        if self._primer_muro_id != muro.id:
            # Cursor sobre otro muro: sólo el primer extremo
            self.preview_actualizado.emit(self._preview_solo_primero())
            return
        d1, d2, lado1 = self._extremos(muro, p)
        d_a, d_b = (d1, d2) if lado1 > 0 else (d2, d1)
        if d_b - d_a <= 1e-6:
            self.preview_actualizado.emit(self._preview_solo_primero())
            return
        self.preview_actualizado.emit({
            "muro_id":  muro.id,
            "punto_a":  QPointF(self._primer_punto),
            "punto_b":  QPointF(p),
            "ancho_pt": d_b - d_a,
            "fantasma": self._fantasma(
                muro, d_a, d_b, [(d1, lado1, self._primer_enganchado)],
            ),
        })

    def _calcular_orientacion(
        self, cursor: QPointF, hueco: dict,
    ) -> tuple[bool, str]:
        """Dado el cursor y los datos del hueco pendiente, devuelve
        (pivote_en_inicio, sentido_str). Regla:

          * Descomponemos el vector (cursor - centro_hueco) en la
            base (tangente, normal) del muro:
              du = componente a lo largo del muro
              dv = componente perpendicular (lado del muro)
          * El PIVOTE va en el extremo OPUESTO al lado de `du` — así
            la hoja abierta apunta HACIA donde está el cursor y el
            arco de barrido queda visualmente en el cuadrante del
            cursor.
          * El SENTIDO es hacia el lado del muro donde está el cursor
            (signo de `dv`).
        """
        centro = hueco["centro_hueco"]
        tang   = hueco["tangente"]
        normal = hueco["normal"]
        du = ((cursor.x() - centro.x()) * tang.x()
              + (cursor.y() - centro.y()) * tang.y())
        dv = ((cursor.x() - centro.x()) * normal.x()
              + (cursor.y() - centro.y()) * normal.y())
        # du > 0 → cursor hacia el extremo B (mayor d) → pivote en A
        pivote_en_inicio = du > 0.0
        sentido = "der" if dv > 0.0 else "izq"
        return pivote_en_inicio, sentido

    def registrar_click(self, punto_pdf: QPointF) -> bool:
        if not self._activa:
            return False
        # ----- Modo orientación: el 3° clic la fija -----
        if self._hueco_pend is not None:
            pivote_en_inicio, sentido = self._calcular_orientacion(
                punto_pdf, self._hueco_pend,
            )
            hueco = self._hueco_pend
            self._resetear_estado()
            self.preview_actualizado.emit(None)
            self.abertura_terminada.emit(
                hueco["muro_id"],
                hueco["d_centro"],
                hueco["ancho_pt"],
                pivote_en_inicio,
                sentido,
            )
            self._emit_mensaje_inicial()
            return True
        r = self._resolver_punto(punto_pdf)
        if r is None:
            self.estado_mensaje.emit(
                "Coloca el cursor sobre un muro para marcar el extremo."
            )
            return True
        muro, p, eng = r
        esc = self._escala_getter()
        # Primer clic: se guarda el punto tal cual
        if self._primer_punto is None:
            self._primer_muro_id = muro.id
            self._primer_muro = muro
            self._primer_punto = QPointF(p)
            self._primer_enganchado = eng
            self._lado_primero = self._lado_supuesto(muro, p)
            self._primer_d = d_extremo_abertura(muro, p, self._lado_primero, esc)
            self.primer_punto_registrado.emit(QPointF(p), muro.id)
            self.preview_actualizado.emit(self._preview_solo_primero())
            self._emit_mensaje_segundo_clic()
            return True
        # Segundo clic — debe ser sobre el MISMO muro
        if muro.id != self._primer_muro_id:
            self.estado_mensaje.emit(
                "El segundo clic debe ser sobre el mismo muro. "
                "Escape para cancelar y empezar de nuevo."
            )
            return True
        d1, d2, lado1 = self._extremos(muro, p)
        d_a, d_b = (d1, d2) if lado1 > 0 else (d2, d1)
        ancho_pt = d_b - d_a
        if ancho_pt < self._ANCHO_MIN_PT:
            self.estado_mensaje.emit(
                "Ancho demasiado pequeño. Aleja el segundo clic."
            )
            return True
        d_centro = (d_a + d_b) / 2.0
        if geometria_abertura(muro, d_centro, ancho_pt, esc) is None:
            self.estado_mensaje.emit(
                "No cabe una abertura entre esos dos puntos. "
                "Marca el segundo extremo más lejos de la esquina."
            )
            return True
        # ¿Necesitamos un 3° clic para elegir orientación?
        if self.necesita_orientacion():
            info_centro = punto_cuerpo_muro(muro, d_centro, esc)
            if info_centro is None:
                return True
            centro_hueco, tang, normal, grosor = info_centro
            # Extremos A (menor d) y B (mayor d) calculados IGUAL que
            # los dibuja PuertaItem (centro del cuerpo ± tangente), para
            # que el preview del 3er clic sea idéntico a la puerta final.
            punto_a = QPointF(
                centro_hueco.x() - tang.x() * ancho_pt / 2.0,
                centro_hueco.y() - tang.y() * ancho_pt / 2.0,
            )
            punto_b = QPointF(
                centro_hueco.x() + tang.x() * ancho_pt / 2.0,
                centro_hueco.y() + tang.y() * ancho_pt / 2.0,
            )
            eng_a = self._primer_enganchado if lado1 > 0 else eng
            eng_b = eng if lado1 > 0 else self._primer_enganchado
            self._hueco_pend = {
                "muro_id":      muro.id,
                "d_centro":     d_centro,
                "ancho_pt":     ancho_pt,
                "grosor_pt":    grosor,
                "centro_hueco": QPointF(centro_hueco),
                "tangente":     QPointF(tang),
                "normal":       QPointF(normal),
                "punto_a":      punto_a,
                "punto_b":      punto_b,
                "fantasma":     self._fantasma(
                    muro, d_a, d_b, [(d_a, +1, eng_a), (d_b, -1, eng_b)],
                ),
            }
            self._emit_mensaje_orientacion()
            return True
        # Sin orientación (Ventana): emitir directo con valores neutros
        self._resetear_estado()
        self.preview_actualizado.emit(None)
        self.abertura_terminada.emit(
            muro.id, d_centro, ancho_pt, True, "ninguno",
        )
        self._emit_mensaje_inicial()
        return True

    def terminar(self) -> bool:
        # No aplica: la abertura se termina con el segundo clic.
        return False

    def retroceder_ultimo_vertice(self) -> bool:
        """Ctrl+Z durante el trazo de una abertura:
          * En modo orientación (3° clic pendiente) → vuelve al estado
            post-1° clic con el primer punto puesto: el operador puede
            re-colocar el segundo extremo.
          * Con sólo el 1° clic hecho → lo quita y vuelve a esperar el
            primer clic.
          * Sin clics todavía → no hace nada.
        """
        if not self._activa:
            return False
        if self._hueco_pend is not None:
            # Salir del modo orientación pero conservar el 1° clic.
            self._hueco_pend = None
            self.preview_actualizado.emit(self._preview_solo_primero())
            self._emit_mensaje_segundo_clic()
            return True
        if self._primer_punto is None:
            return False
        self._resetear_estado()
        self.preview_actualizado.emit(None)
        self._emit_mensaje_inicial()
        return True

    def _emit_mensaje_inicial(self) -> None:
        """Cada subclase pone su mensaje inicial (primer clic)."""
        pass

    def _emit_mensaje_segundo_clic(self) -> None:
        """Cada subclase pone su mensaje para el segundo clic."""
        pass

    def _emit_mensaje_orientacion(self) -> None:
        """Mensaje para el 3° clic (elección de orientación).
        Default vacío — Ventana no usa este estado."""
        pass


class HerramientaPuerta(HerramientaAbertura):
    def necesita_orientacion(self) -> bool:
        return True

    def tipo_abertura(self) -> str:
        return "puerta"

    def _emit_mensaje_inicial(self) -> None:
        self.estado_mensaje.emit(
            "Puerta: clic sobre un muro para marcar el INICIO del hueco."
        )

    def _emit_mensaje_segundo_clic(self) -> None:
        self.estado_mensaje.emit(
            "Puerta: clic para marcar el FIN del hueco (mismo muro). "
            "Escape para cancelar."
        )

    def _emit_mensaje_orientacion(self) -> None:
        self.estado_mensaje.emit(
            "Puerta: mueve el cursor al cuadrante donde debe abrir la "
            "hoja y clic para fijar. Ctrl+Z para re-marcar el hueco."
        )


class HerramientaVentana(HerramientaAbertura):
    def necesita_orientacion(self) -> bool:
        return False

    def _emit_mensaje_inicial(self) -> None:
        self.estado_mensaje.emit(
            "Ventana: clic sobre un muro para marcar el INICIO del hueco."
        )

    def _emit_mensaje_segundo_clic(self) -> None:
        self.estado_mensaje.emit(
            "Ventana: clic para marcar el FIN del hueco (mismo muro). "
            "Escape para cancelar."
        )


# ---------------------------------------------------------------------------
# Resolver: dado un punto, encuentra el muro más cercano + d sobre él
# ---------------------------------------------------------------------------

def proyectar_punto_sobre_muro(
    punto: QPointF, muro: Muro,
) -> Optional[tuple[QPointF, float, float]]:
    """Proyecta `punto` sobre el eje del muro. Devuelve
    `(punto_proyectado, distancia_al_muro_pt, d_desde_inicio_pt)`.

    Para muros LINEAL, proyecta al segmento más cercano.
    Para muros ARCO, proyecta al arco (aproximación por muestreo).
    """
    if not muro.vertices:
        return None
    if muro.es_arco():
        return _proyectar_punto_sobre_arco(punto, muro)
    return _proyectar_punto_sobre_polilinea(punto, muro)


def _proyectar_punto_sobre_polilinea(
    punto: QPointF, muro: Muro,
) -> Optional[tuple[QPointF, float, float]]:
    mejor: Optional[tuple[QPointF, float, float]] = None
    acc = 0.0
    segs = list(range(len(muro.vertices) - 1))
    if muro.cerrado and len(muro.vertices) >= 3:
        segs.append(-1)
    for i in segs:
        a = muro.vertices[i]
        b = muro.vertices[(i + 1) % len(muro.vertices)] if i == -1 \
            else muro.vertices[i + 1]
        dx = b.x() - a.x()
        dy = b.y() - a.y()
        largo_seg = math.hypot(dx, dy)
        if largo_seg < 1e-9:
            continue
        # t = clamp(((punto - a) · (b - a)) / |b-a|², 0, 1)
        vx = punto.x() - a.x()
        vy = punto.y() - a.y()
        t_raw = (vx * dx + vy * dy) / (largo_seg * largo_seg)
        t = max(0.0, min(1.0, t_raw))
        px = a.x() + t * dx
        py = a.y() + t * dy
        dist = math.hypot(punto.x() - px, punto.y() - py)
        d_desde_inicio = acc + t * largo_seg
        cand = (QPointF(px, py), dist, d_desde_inicio)
        if mejor is None or dist < mejor[1]:
            mejor = cand
        acc += largo_seg
    return mejor


def _proyectar_punto_sobre_arco(
    punto: QPointF, muro: Muro,
) -> Optional[tuple[QPointF, float, float]]:
    """Muestrea el arco a intervalos discretos y encuentra el más
    cercano. 60 muestras es suficiente para arcos normales."""
    p1, p2, p3 = muro.vertices
    largo_total = _longitud_arco_3_puntos(p1, p2, p3)
    if largo_total <= 0.0:
        return None
    N = 60
    mejor: Optional[tuple[QPointF, float, float]] = None
    for i in range(N + 1):
        d = largo_total * i / N
        info = _punto_y_normal_en_arco(muro, d)
        if info is None:
            continue
        pt, _t, _n = info
        dist = math.hypot(punto.x() - pt.x(), punto.y() - pt.y())
        if mejor is None or dist < mejor[1]:
            mejor = (pt, dist, d)
    return mejor


# ---------------------------------------------------------------------------
# HerramientaHabitacionCircular — 2 clics: centro, radio
# ---------------------------------------------------------------------------

class HerramientaHabitacionCircular(HerramientaDibujoPolilinea):
    """Habitación circular: 2 clics — centro y un punto en la
    circunferencia. Genera un polígono regular con N vértices que
    aproxima el círculo (N = 48 → error ≈ 0.3% en área, muy por debajo
    de la tolerancia práctica NOM). El polígono resultante se persiste
    como una `Habitacion` normal, por lo que todo el resto del pipeline
    (agrupación, cálculo) lo trata igual que una habitación dibujada a
    mano.

    El snap al primer vértice está DESACTIVADO."""

    _MAX_CLICKS = 2
    # Radio mínimo aceptable (pt PDF). Radios muy pequeños generan
    # habitaciones sin sentido físico.
    _RADIO_MIN_PT = 8.0

    def _emit_mensaje_inicial(self) -> None:
        self.estado_mensaje.emit(
            "Habitación circular: clic 1 = centro. "
            "Shift = ortogonal. Escape cancela."
        )

    def _emit_mensaje_progreso(self) -> None:
        n = len(self._vertices)
        if n == 1:
            self.estado_mensaje.emit(
                "Habitación circular: clic 2 = punto en el borde "
                "(define el radio)."
            )

    def registrar_click(self, punto_pdf: QPointF) -> bool:
        if not self.esta_activa():
            return False
        # Validación específica: el 2° clic no puede coincidir con el
        # centro (radio = 0) — rechazamos aún antes que la validación
        # genérica de DIST_MIN_VERTICE_PT.
        if self._vertices:
            centro = self._vertices[0]
            d = math.hypot(
                punto_pdf.x() - centro.x(), punto_pdf.y() - centro.y()
            )
            if d < self._RADIO_MIN_PT:
                self.estado_mensaje.emit(
                    "Radio demasiado pequeño. Aleja el cursor del centro."
                )
                return True
        primer = not self._vertices
        self._vertices.append(QPointF(punto_pdf))
        if primer:
            self.primer_vertice_registrado.emit(QPointF(punto_pdf))
        self.vertices_cambiados.emit(list(self._vertices))

        if len(self._vertices) >= self._MAX_CLICKS:
            centro = self._vertices[0]
            borde = self._vertices[1]
            radio = math.hypot(
                borde.x() - centro.x(), borde.y() - centro.y()
            )
            vertices_poligono = _generar_poligono_circular(centro, radio)
            self._vertices = []
            self.dibujo_terminado.emit(vertices_poligono)
            self._emit_mensaje_inicial()
        else:
            self._emit_mensaje_progreso()
        return True

    def terminar(self) -> bool:
        """Enter en un dibujo de círculo: sólo válido con los 2 puntos
        ya colocados (aunque en la práctica el 2º clic ya finaliza)."""
        if not self.esta_activa():
            return False
        if len(self._vertices) < self._MAX_CLICKS:
            self.estado_mensaje.emit(
                "Habitación circular: faltan puntos. Necesitas centro y "
                "un punto en el borde."
            )
            return False
        # Prácticamente inalcanzable — registrar_click ya cierra al 2°.
        centro = self._vertices[0]
        borde = self._vertices[1]
        radio = math.hypot(
            borde.x() - centro.x(), borde.y() - centro.y()
        )
        vertices_poligono = _generar_poligono_circular(centro, radio)
        self._vertices = []
        self.dibujo_terminado.emit(vertices_poligono)
        self._emit_mensaje_inicial()
        return True

    def _es_valido_para_terminar(self, vertices: list[QPointF]) -> bool:
        return len(vertices) == self._MAX_CLICKS
