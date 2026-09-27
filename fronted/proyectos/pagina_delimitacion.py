"""
pagina_delimitacion.py
======================

UI de la etapa "Delimitación" del espacio de trabajo.

Sesión D del módulo Proyectos.

Layout:
  * Panel izquierdo (260 px): lista de habitaciones del plano activo
    con nombre + área en m², contador de muros.
  * Panel derecho: ribbon (Vista + Herramientas + Borrar) + canvas
    (compartiendo el plano activo con la etapa Planos) + status bar.

Herramientas del ribbon:
  * Seleccionar, Pan — heredadas del canvas.
  * Muro — dibujar polilíneas (2+ vértices). Shift = ortogonal.
    Enter/doble clic = terminar. Escape = cancelar. Ctrl+Z quita el
    último vértice sin cancelar el trazo entero.
  * Habitación — dibujar polígono cerrado (3+ vértices). Al cerrar,
    diálogo modal pide el nombre. Área en m² calculada por escala.
  * Goma — modo hover rojo + clic para eliminar el ítem cubierto por
    el cursor. (No hay "Borrar todo" — es demasiado destructivo con
    un solo clic; la goma cubre el caso legítimo.)

Comunicación con el modelo:
  * Se escucha `plano_activo_cambiado` del `ProyectoAbierto` para
    recargar el plano cuando la etapa Planos lo cambia.
  * Cuando el usuario termina de dibujar un muro o habitación, se
    llama a `proyecto.agregar_muro / agregar_habitacion`. El modelo
    emite la señal correspondiente y esta página crea el ítem visual.
  * Al eliminar, mismo patrón inverso.

Convenciones:
  * Self-contained: paleta local.
  * Rueda del mouse = zoom del canvas.
  * Delimitación solo tiene sentido con un plano cargado; sin plano
    activo se muestra un placeholder.
"""

from __future__ import annotations

import sys
from typing import Optional

from PyQt6.QtCore import Qt, QSize, QPointF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QKeyEvent, QKeySequence, QPainterPath, QPen,
    QPolygonF, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsRectItem, QHBoxLayout,
    QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget,
)

try:
    import qtawesome as qta
    _QTA_OK = True
except Exception:  # noqa: BLE001
    _QTA_OK = False

from canvas_plano import CanvasPlano, Herramienta
from datos_proyecto import (
    GROSOR_DEFAULT_POR_MATERIAL, Habitacion, JustificacionMuro,
    MATERIAL_MURO_LABELS, Muro, PlanoDeProyecto, ProyectoAbierto,
    Puerta, SentidoAperturaPuerta, TipoGeometriaMuro, TipoMaterialMuro,
    TipoUsoHabitacion, USO_HABITACION_LABELS, Ventana,
)
from delimitacion import (
    BordesMurosItem, DialogoMaterialMuro, DialogoNombreHabitacion,
    HabitacionItem,
    HerramientaAbertura, HerramientaHabitacion,
    HerramientaHabitacionCircular, HerramientaMuro, HerramientaMuroArco,
    HerramientaPuerta, HerramientaVentana, ModoPreview, MuroItem,
    PreviewDibujoItem, PuertaItem, VentanaItem,
    _longitud_arco_3_puntos, _proyeccion_a_muro,
    _punto_medio_arco_3_puntos, _snap_ortogonal,
    aplicar_extensiones_muro, desplazar_trazo_muro, detectar_hueco_divisorio,
    _contorno_muro_con_grosor,
    calcular_extensiones_muro, distancias_quiebres_muro,
    esquinas_contorno_muro, geometria_abertura, proyeccion_a_caras_muro,
    proyectar_punto_sobre_muro, punto_cuerpo_muro, puntos_enganche_abertura,
    remiendos_esquinas_muros,
)
from escala_calibrador import EscalaCalibrada

import math


# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------

COLOR_FONDO           = "#121212"
COLOR_HEADER          = "#141414"
COLOR_SIDEBAR         = "#1a1a1a"
COLOR_SUPERFICIE      = "#1e1e1e"
COLOR_SUPERFICIE_HOVER= "#242424"
COLOR_INPUT_BG        = "#2b2b2b"
COLOR_BORDE           = "#333333"
COLOR_BORDE_FUERTE    = "#444444"
COLOR_ACENTO          = "#0078d7"
COLOR_ACENTO_BRILL    = "#0094ff"
COLOR_TEXTO           = "#ffffff"
COLOR_TEXTO_SUAVE     = "#dddddd"
COLOR_TEXTO_MUTED     = "#aaaaaa"
COLOR_TEXTO_APAGADO   = "#666666"
COLOR_HAB_LINEA       = "#5aaefc"

_ANCHO_PANEL      = 260
_ANCHO_TOOL_CHICO = 66
_ANCHO_TOOL_GRAN  = 90
_SPACING          = 2


# ---------------------------------------------------------------------------
# _PuenteHerramientas — glue entre canvas y las HerramientaMuro/Habitacion
# ---------------------------------------------------------------------------

class _PuenteHerramientas:
    """Implementa la interfaz que espera CanvasPlano.set_herramienta_externa.

    Direcciona eventos del canvas a la herramienta activa (Muro,
    Muro curvo, Habitación o Habitación circular) y aplica un stack
    de snaps estilo AutoCAD:

      1. Endpoint/Midpoint (cuadrado cian / rombo cian). Puntos
         geométricamente notables ya trazados: vértices de muros y
         habitaciones, y puntos medios de segmentos y arcos. Radio
         normal.
      2. Cerrar polígono (círculo naranja). Sólo herramientas de
         polígono cerrado (Habitación).
      3. Nearest sobre muro (X cian). Proyección del cursor a la CARA
         más cercana de un muro (su contorno grueso, no el eje) —
         engancha en cualquier punto del recorrido. Radio ligeramente
         menor para no ganarle a un endpoint cercano.
      4. Ortogonal respecto al último vértice (Shift o toggle Orto).

    Además, mientras se dibuja un muro, si un extremo queda cerca de
    otro muro sin tocarlo, se muestra en cian hasta dónde lo prolongará
    el auto-extend al terminar (ver `calcular_extensiones_muro`).

    El toggle Orto es un modo persistente: se activa/desactiva desde
    el botón del ribbon o con F8. Independientemente de Shift, cuando
    está activo todos los clics/movimientos aplican snap ortogonal.
    """

    # Radio de snap en píxeles LÓGICOS de pantalla. Se traduce a pt PDF
    # dividiendo por el zoom del canvas.
    _RADIO_SNAP_PX = 18.0
    # Radio menor para el snap "nearest" para no competir con endpoints
    # y midpoints (que tienen mayor prioridad).
    _RADIO_SNAP_NEAREST_PX = 12.0

    def __init__(
        self,
        herramientas: list,
        canvas_getter,
        preview: PreviewDibujoItem,
        puntos_snap_getter=None,
        muros_getter=None,
        extension_preview_fn=None,
    ) -> None:
        self._herramientas = herramientas
        self._canvas_getter = canvas_getter
        self._preview = preview
        # Callable(herramienta, cursor) → lista de (desde, hasta) con las
        # prolongaciones que haría el auto-extend si el muro terminara
        # ahora. La página lo implementa; None ⇒ sin preview.
        self._extension_preview_fn = extension_preview_fn or (lambda _h, _p: [])
        # Callable que devuelve la lista actual de puntos snapables
        # tipados del plano: [(QPointF, "endpoint"|"midpoint"), ...].
        # Se consulta en cada movimiento del cursor. None ⇒ sin snap.
        self._puntos_snap_getter = puntos_snap_getter or (lambda: [])
        # Callable que devuelve la lista de muros del plano, para
        # calcular la proyección "nearest" del cursor al muro más
        # cercano. None ⇒ sin nearest.
        self._muros_getter = muros_getter or (lambda: [])
        # Estado del toggle Orto (persistente entre clics). El shift
        # sigue funcionando como override momentáneo cuando el toggle
        # está apagado.
        self._orto_activo: bool = False
        # Snaps a objetos (endpoint/midpoint/nearest), como OSNAP de
        # AutoCAD: F3 o el botón "Snap" los apaga para poner el punto
        # exactamente donde se hace clic (p. ej. calcando el plano).
        self._snaps_activos: bool = True

    def _activa(self):
        for h in self._herramientas:
            if h.esta_activa():
                return h
        return None

    def esta_activa(self) -> bool:
        return self._activa() is not None

    def set_orto_activo(self, activo: bool) -> None:
        self._orto_activo = bool(activo)

    def orto_activo(self) -> bool:
        return self._orto_activo

    def set_snaps_activos(self, activo: bool) -> None:
        self._snaps_activos = bool(activo)
        if not activo:
            self._preview.set_indicador_snap_extremo(None)
            self._preview.set_indicador_snap_nearest(None)

    def snaps_activos(self) -> bool:
        return self._snaps_activos

    def _orto_efectivo(self, shift: bool) -> bool:
        """Snap ortogonal efectivo: toggle O shift (cualquiera de los
        dos lo activa; ninguno lo desactiva)."""
        return self._orto_activo or shift

    def _radio_snap_pdf(self) -> float:
        """Traduce _RADIO_SNAP_PX a pt PDF usando el zoom actual del
        canvas. A más zoom, radio en pt PDF más chico."""
        canvas = self._canvas_getter()
        if canvas is None:
            return 20.0
        zoom = canvas.zoom_actual()
        if zoom <= 0:
            return 20.0
        return self._RADIO_SNAP_PX / zoom

    @staticmethod
    def _eligiendo_paso_arco(h) -> bool:
        """True si el próximo clic es el PUNTO DE PASO de un arco de
        habitación: ahí el Orto no aplica (la curva pasa por donde sea)."""
        modo = getattr(h, "modo_arco", None)
        paso = getattr(h, "paso_pendiente", None)
        return bool(modo and modo() and paso is not None and paso() is None)

    def _snap_al_primer_activo(self, h) -> bool:
        return getattr(h, "snap_al_primer_vertice", lambda: False)()

    def _en_zona_snap(self, h, punto_pdf: QPointF) -> bool:
        """True si el cursor está a menos de _radio_snap_pdf del
        primer vértice, y la herramienta permite cierre por snap."""
        if not self._snap_al_primer_activo(h):
            return False
        minimo = getattr(h, "minimo_vertices_cierre", lambda: 3)()
        if h.cantidad_vertices() < minimo:
            return False
        primer = h.vertices()[0]
        d = math.hypot(
            punto_pdf.x() - primer.x(), punto_pdf.y() - primer.y()
        )
        return d < self._radio_snap_pdf()

    def _buscar_snap_extremo(
        self, punto_pdf: QPointF,
    ) -> tuple[Optional[QPointF], str]:
        """Devuelve el punto snapable tipado más cercano al cursor
        dentro del radio de snap, junto con su tipo ("endpoint" o
        "midpoint"). Si no hay ninguno cerca, devuelve (None, "").

        Endpoints ganan sobre midpoints a igual distancia — el endpoint
        es siempre el snap más deseable cuando el usuario está
        conectando muros. Para hacerlo, buscamos primero endpoints; si
        no hay ninguno, buscamos midpoints.
        """
        if not self._snaps_activos:
            return None, ""
        puntos = self._puntos_snap_getter()
        if not puntos:
            return None, ""
        radio = self._radio_snap_pdf()
        radio_cuad = radio * radio
        mejor_ep: Optional[QPointF] = None
        mejor_ep_d2 = radio_cuad
        mejor_mp: Optional[QPointF] = None
        mejor_mp_d2 = radio_cuad
        for punto, tipo in puntos:
            dx = punto.x() - punto_pdf.x()
            dy = punto.y() - punto_pdf.y()
            d2 = dx * dx + dy * dy
            if tipo == "midpoint":
                if d2 < mejor_mp_d2:
                    mejor_mp_d2 = d2
                    mejor_mp = punto
            else:
                if d2 < mejor_ep_d2:
                    mejor_ep_d2 = d2
                    mejor_ep = punto
        if mejor_ep is not None:
            return QPointF(mejor_ep), "endpoint"
        if mejor_mp is not None:
            return QPointF(mejor_mp), "midpoint"
        return None, ""

    def _buscar_snap_nearest(
        self, punto_pdf: QPointF,
    ) -> Optional[QPointF]:
        """Proyecta el cursor a la CARA más cercana de un muro (su
        contorno grueso, no el eje) dentro del radio
        `_RADIO_SNAP_NEAREST_PX`. Así un muro o habitación nuevo queda
        pegado a la cara del muro existente en vez de meterse hasta su
        centro. Radio menor que endpoints/midpoints para no competir
        con ellos."""
        if not self._snaps_activos:
            return None
        muros = self._muros_getter()
        if not muros:
            return None
        canvas = self._canvas_getter()
        zoom = canvas.zoom_actual() if canvas is not None else 1.0
        if zoom <= 0:
            zoom = 1.0
        escala = canvas.escala_actual() if canvas is not None else None
        radio = self._RADIO_SNAP_NEAREST_PX / zoom
        radio_cuad = radio * radio
        mejor: Optional[QPointF] = None
        mejor_d2 = radio_cuad
        for m in muros:
            p_proy, d2 = proyeccion_a_caras_muro(punto_pdf, m, escala, radio)
            if p_proy is None:
                continue
            if d2 < mejor_d2:
                mejor_d2 = d2
                mejor = p_proy
        return QPointF(mejor) if mejor is not None else None

    def on_click(self, punto_pdf: QPointF, shift: bool) -> bool:
        h = self._activa()
        if h is None:
            return False
        # Herramientas de abertura tienen su propio resolver (proyecta
        # al muro más cercano). Los snaps de canvas no aplican — la
        # abertura no debe engancharse al vértice de un muro cualquiera,
        # sino al muro que el usuario está apuntando.
        if isinstance(h, HerramientaAbertura):
            self._preview.set_indicador_snap_extremo(None)
            self._preview.set_indicador_snap(None)
            self._preview.set_indicador_snap_nearest(None)
            return h.registrar_click(punto_pdf)
        # Prioridad 1: snap a endpoint/midpoint (punto exacto)
        snap_pt, _tipo = self._buscar_snap_extremo(punto_pdf)
        if snap_pt is not None:
            return h.registrar_click(snap_pt)
        # Prioridad 2: cerrar polígono
        if self._en_zona_snap(h, punto_pdf):
            return h.terminar()
        # Prioridad 3: nearest en muro (engancha a cualquier punto del
        # recorrido)
        snap_near = self._buscar_snap_nearest(punto_pdf)
        if snap_near is not None:
            return h.registrar_click(snap_near)
        # Prioridad 4: ortogonal (Orto o Shift)
        if (
            self._orto_efectivo(shift) and h.cantidad_vertices() > 0
            and not self._eligiendo_paso_arco(h)
        ):
            ultimo = h.vertices()[-1]
            punto_pdf = _snap_ortogonal(ultimo, punto_pdf)
        return h.registrar_click(punto_pdf)

    def on_move(self, punto_pdf: QPointF, shift: bool) -> None:
        h = self._activa()
        if h is None:
            return
        # En herramienta de abertura no se aplican los snaps de canvas
        # (ver on_click). El propio resolver proyecta al muro más
        # cercano. PERO sí mostramos un marcador cian del punto
        # proyectado — así el operador ve, ANTES del 1° clic, dónde va
        # a caer.
        if isinstance(h, HerramientaAbertura):
            # Marcador = la LÍNEA DE CORTE exacta, de cara a cara del
            # muro: perpendicular donde está el cursor, o la diagonal de
            # la esquina si cae en su zona. Es la misma línea que tendrá
            # la abertura al hacer clic.
            self._preview.set_indicador_snap(None)
            self._preview.set_indicador_snap_extremo(None)
            self._preview.set_indicador_snap_nearest(None)
            self._preview.set_corte_hover(h.corte_proyectado(punto_pdf))
            h.actualizar_cursor(punto_pdf)
            return
        punto_final = self._resolver_cursor_dibujo(h, punto_pdf, shift)
        h.actualizar_cursor(punto_final)
        # Auto-extend: mostrar hasta dónde se prolongarán los extremos
        # del muro en curso si quedan cerca de otro muro.
        self._preview.set_extensiones_preview(
            self._extension_preview_fn(h, punto_final),
        )

    def _resolver_cursor_dibujo(
        self, h, punto_pdf: QPointF, shift: bool,
    ) -> QPointF:
        """Aplica la cadena de snaps (endpoint/midpoint → cerrar →
        nearest → orto), actualiza los indicadores y devuelve el punto
        donde debe quedar el cursor."""
        # Prioridad 1: endpoint/midpoint
        snap_pt, tipo = self._buscar_snap_extremo(punto_pdf)
        if snap_pt is not None:
            self._preview.set_indicador_snap_extremo(snap_pt, tipo)
            self._preview.set_indicador_snap(None)
            self._preview.set_indicador_snap_nearest(None)
            return snap_pt
        self._preview.set_indicador_snap_extremo(None)
        # Prioridad 2: cerrar polígono
        if self._en_zona_snap(h, punto_pdf):
            primer = h.vertices()[0]
            self._preview.set_indicador_snap(primer)
            self._preview.set_indicador_snap_nearest(None)
            return QPointF(primer)
        self._preview.set_indicador_snap(None)
        # Prioridad 3: nearest en muro
        snap_near = self._buscar_snap_nearest(punto_pdf)
        if snap_near is not None:
            self._preview.set_indicador_snap_nearest(snap_near)
            return snap_near
        self._preview.set_indicador_snap_nearest(None)
        # Prioridad 4: ortogonal (Orto o Shift)
        if (
            self._orto_efectivo(shift) and h.cantidad_vertices() > 0
            and not self._eligiendo_paso_arco(h)
        ):
            ultimo = h.vertices()[-1]
            return _snap_ortogonal(ultimo, punto_pdf)
        return punto_pdf

    def on_key(self, event: QKeyEvent) -> bool:
        h = self._activa()
        if h is None:
            return False
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return h.terminar()
        if key == Qt.Key.Key_Escape:
            h.cancelar()
            return True
        # Habitación: A = siguiente tramo en arco, L = recto (como la
        # polilínea de AutoCAD), sin perder lo ya trazado.
        if hasattr(h, "set_modo_arco") and key in (Qt.Key.Key_A, Qt.Key.Key_L):
            h.set_modo_arco(key == Qt.Key.Key_A)
            return True
        return False

    def retroceder_ultimo(self) -> bool:
        """Ctrl+Z durante dibujo: pide a la herramienta activa que
        quite el último punto que colocó, sin cancelar el trazo. Si no
        hay herramienta activa o el método no aplica, devuelve False."""
        h = self._activa()
        if h is None:
            return False
        return h.retroceder_ultimo_vertice()


# ---------------------------------------------------------------------------
# CardHabitacion — item de la lista lateral
# ---------------------------------------------------------------------------

class CardHabitacion(QFrame):
    """Card compacta en el panel lateral con nombre + área. Menú
    contextual para renombrar / eliminar."""

    renombrar_solicitado = pyqtSignal(str)
    eliminar_solicitado  = pyqtSignal(str)

    def __init__(
        self,
        hab: Habitacion,
        escala: Optional[EscalaCalibrada],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._hab = hab
        self.setObjectName("cardHabDelim")
        self.setFixedHeight(58)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu_contexto)

        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(8)

        # Chip de color con inicial
        chip = QLabel("H")
        chip.setFixedSize(28, 28)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setStyleSheet(f"""
            QLabel {{
                background: {COLOR_HAB_LINEA};
                color: {COLOR_TEXTO};
                border-radius: 14px;
                font-size: 12px;
                font-weight: bold;
            }}
        """)
        h.addWidget(chip)

        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)

        self._lbl_nombre = QLabel(hab.nombre)
        self._lbl_nombre.setObjectName("nombreHab")

        area_m2 = hab.area_m2(escala)
        tipo_txt = hab.tipo_uso_legible()
        if area_m2 is not None:
            txt_area = f"{tipo_txt}  ·  {area_m2:.2f} m²"
        else:
            txt_area = f"{tipo_txt}  ·  — m² (sin escala)"
        self._lbl_area = QLabel(txt_area)
        self._lbl_area.setObjectName("areaHab")

        v.addWidget(self._lbl_nombre)
        v.addWidget(self._lbl_area)
        h.addLayout(v, 1)

        self._aplicar_estilo()

    def actualizar(
        self, hab: Habitacion, escala: Optional[EscalaCalibrada],
    ) -> None:
        self._hab = hab
        self._lbl_nombre.setText(hab.nombre)
        area_m2 = hab.area_m2(escala)
        tipo_txt = hab.tipo_uso_legible()
        if area_m2 is not None:
            self._lbl_area.setText(f"{tipo_txt}  ·  {area_m2:.2f} m²")
        else:
            self._lbl_area.setText(f"{tipo_txt}  ·  — m² (sin escala)")

    def _aplicar_estilo(self) -> None:
        self.setStyleSheet(f"""
            QFrame#cardHabDelim {{
                background: {COLOR_SUPERFICIE};
                border: 1px solid {COLOR_BORDE};
                border-radius: 6px;
            }}
            QFrame#cardHabDelim:hover {{
                background: {COLOR_SUPERFICIE_HOVER};
                border-color: {COLOR_HAB_LINEA};
            }}
            QFrame#cardHabDelim QLabel {{ background: transparent; }}
            QLabel#nombreHab {{
                color: {COLOR_TEXTO}; font-size: 12px; font-weight: 600;
            }}
            QLabel#areaHab {{
                color: {COLOR_TEXTO_MUTED}; font-size: 10px;
            }}
        """)

    def _menu_contexto(self, pos) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLOR_SUPERFICIE};
                color: {COLOR_TEXTO_SUAVE};
                border: 1px solid {COLOR_BORDE_FUERTE};
                padding: 4px 0px;
                font-size: 12px;
            }}
            QMenu::item {{ padding: 6px 20px; }}
            QMenu::item:selected {{
                background-color: {COLOR_ACENTO}; color: {COLOR_TEXTO};
            }}
        """)
        act_r = QAction("Renombrar…", menu)
        act_r.triggered.connect(
            lambda: self.renombrar_solicitado.emit(self._hab.id)
        )
        act_d = QAction("Eliminar habitación", menu)
        act_d.triggered.connect(
            lambda: self.eliminar_solicitado.emit(self._hab.id)
        )
        menu.addAction(act_r)
        menu.addSeparator()
        menu.addAction(act_d)
        menu.exec(self.mapToGlobal(pos))


# ---------------------------------------------------------------------------
# Ribbon helpers (mismos que pagina_planos.py; replicados)
# ---------------------------------------------------------------------------

def _crear_grupo(etiqueta: str, anchos: list[int]) -> dict:
    total = sum(anchos) + _SPACING * max(0, len(anchos) - 1)
    wrap = QWidget()
    wrap.setFixedWidth(total)
    v = QVBoxLayout(wrap)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    cont = QHBoxLayout()
    cont.setContentsMargins(0, 0, 0, 0)
    cont.setSpacing(_SPACING)
    v.addLayout(cont)
    lbl = QLabel(etiqueta)
    lbl.setObjectName("grupoLabel")
    lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    lbl.setFixedWidth(total)
    v.addWidget(lbl)
    return {"widget": wrap, "contenido": cont}


def _sep_v() -> QFrame:
    s = QFrame()
    s.setObjectName("ribbonSeparator")
    s.setFrameShape(QFrame.Shape.NoFrame)
    return s


def _boton(icono_nombre: str, texto: str, ancho: int, on_click) -> QToolButton:
    b = QToolButton()
    b.setText(texto)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    b.setIconSize(QSize(22, 22))
    b.setFixedWidth(ancho)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setToolTip(texto)
    b.setProperty("iconName", icono_nombre)
    _aplicar_icono(b, activo=False)
    b.clicked.connect(on_click)
    return b


def _aplicar_icono(btn: QToolButton, activo: bool) -> None:
    nombre = btn.property("iconName")
    if not nombre or not _QTA_OK:
        return
    color = COLOR_TEXTO if activo else COLOR_TEXTO_SUAVE
    btn.setIcon(qta.icon(nombre, color=color))


def _reaplicar(w: QWidget) -> None:
    s = w.style()
    if s is not None:
        s.unpolish(w)
        s.polish(w)


def _ribbon_stylesheet() -> str:
    return f"""
        QFrame#ribbonDelim {{
            background-color: {COLOR_HEADER};
            border-bottom: 1px solid {COLOR_BORDE};
        }}
        QFrame#ribbonSeparator {{
            background-color: {COLOR_BORDE};
            min-width: 1px; max-width: 1px;
            margin: 4px 6px 22px 6px;
        }}
        QLabel#grupoLabel {{
            color: {COLOR_TEXTO_APAGADO};
            font-size: 10px; font-weight: bold;
            letter-spacing: 0.5px;
            padding: 2px 0px 0px 0px;
            background-color: transparent;
        }}
        QToolButton {{
            background-color: transparent;
            color: {COLOR_TEXTO_SUAVE};
            border: 1px solid transparent;
            border-radius: 4px;
            padding: 4px 6px;
            min-height: 54px;
            font-size: 11px;
            outline: none;
        }}
        QToolButton:hover {{
            background-color: {COLOR_INPUT_BG};
            border-color: {COLOR_BORDE_FUERTE};
            color: {COLOR_TEXTO};
        }}
        QToolButton:pressed {{ background-color: {COLOR_BORDE_FUERTE}; }}
        QToolButton:disabled {{
            background-color: transparent;
            color: {COLOR_TEXTO_APAGADO};
            border-color: transparent;
        }}
        QToolButton#toolActivo {{
            background-color: {COLOR_ACENTO};
            border-color: {COLOR_ACENTO_BRILL};
            color: {COLOR_TEXTO};
        }}
        QToolButton#toolActivo:hover {{
            background-color: {COLOR_ACENTO_BRILL};
        }}
    """


# ---------------------------------------------------------------------------
# _RibbonScrollArea — scroll horizontal que reserva espacio para la
# barra SOLO cuando esta se necesita (evita el "hueco" vacío abajo
# cuando la ventana es lo bastante ancha para mostrar todo el ribbon).
# ---------------------------------------------------------------------------

class _RibbonScrollArea(QScrollArea):
    """QScrollArea con altura auto-ajustable según la barra horizontal.

    Cuando el viewport es lo bastante ancho para que quepa todo el
    contenido, la altura es 88 px (solo el ribbon). Cuando el
    contenido excede el viewport y aparece la barra, la altura sube
    a 102 px (88 + 14 de la barra) para que la barra no se dibuje
    sobre los botones."""

    ALTO_SIN_BARRA = 88
    ALTO_CON_BARRA = 102

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.ALTO_SIN_BARRA)
        self._ajustando = False
        # Reaccionar a cambios de rango (contenido o viewport)
        self.horizontalScrollBar().rangeChanged.connect(
            self._solicitar_ajuste
        )

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._solicitar_ajuste()

    def _solicitar_ajuste(self, *_args) -> None:
        if self._ajustando:
            return
        # Defer al siguiente evento de Qt para dar tiempo a que el
        # scrollbar recalcule su rango tras el resize.
        QTimer.singleShot(0, self._ajustar_altura)

    def _ajustar_altura(self) -> None:
        if self._ajustando:
            return
        needs_bar = self.horizontalScrollBar().maximum() > 0
        target = self.ALTO_CON_BARRA if needs_bar else self.ALTO_SIN_BARRA
        if self.height() == target:
            return
        self._ajustando = True
        try:
            self.setFixedHeight(target)
        finally:
            self._ajustando = False


# ---------------------------------------------------------------------------
# PaginaDelimitacion
# ---------------------------------------------------------------------------

class PaginaDelimitacion(QWidget):

    def __init__(
        self,
        proyecto: ProyectoAbierto,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._proyecto = proyecto
        self._plano_id: Optional[str] = None

        # Herramientas de dibujo — instanciadas una vez, siempre vivas.
        self._h_muro = HerramientaMuro(self)
        self._h_muro_arco = HerramientaMuroArco(self)
        self._h_hab = HerramientaHabitacion(self)
        self._h_hab_circ = HerramientaHabitacionCircular(self)
        # Aberturas: necesitan un resolver que dada una coordenada
        # devuelva (muro, d_desde_inicio) del muro más cercano, y la
        # escala para ubicar los puntos en el centro del cuerpo del
        # muro (respetando la justificación).
        self._h_puerta = HerramientaPuerta(
            resolver_getter=self._resolver_muro_bajo_cursor, parent=self,
            escala_getter=lambda: self._canvas.escala_actual(),
        )
        self._h_ventana = HerramientaVentana(
            resolver_getter=self._resolver_muro_bajo_cursor, parent=self,
            escala_getter=lambda: self._canvas.escala_actual(),
        )

        # Preview visual efímero (compartido entre herramientas)
        self._preview = PreviewDibujoItem()
        self._preview.setVisible(False)

        # Puente que direcciona eventos del canvas a la herramienta
        # activa. Aplica el stack de snaps estilo AutoCAD (endpoint /
        # midpoint / cerrar / nearest / ortogonal).
        self._puente = _PuenteHerramientas(
            [
                self._h_muro, self._h_muro_arco,
                self._h_hab, self._h_hab_circ,
                self._h_puerta, self._h_ventana,
            ],
            canvas_getter=lambda: self._canvas,
            preview=self._preview,
            puntos_snap_getter=self._puntos_snap_del_plano,
            muros_getter=self._muros_del_plano,
            extension_preview_fn=self._preview_extension,
        )

        # Último material de muro usado — se recuerda para no
        # interrumpir al operador cuando dibuja muros del mismo material
        # en serie. Se inicializa en BLOCK, el más común en construcción
        # mexicana; el operador puede cambiarlo desde el primer diálogo.
        self._ultimo_material_muro: TipoMaterialMuro = TipoMaterialMuro.BLOCK
        # Último grosor de muro (cm) — se recuerda; default del material
        # BLOCK = 12 cm.
        self._ultimo_grosor_cm: float = GROSOR_DEFAULT_POR_MATERIAL[
            TipoMaterialMuro.BLOCK
        ]
        # Última cara (justificación) usada — se recuerda.
        self._ultima_justificacion: JustificacionMuro = JustificacionMuro.CENTRO
        # Si el último muro se hizo "topando con la siguiente división"
        # (muro divisorio), el diálogo la propone marcada otra vez.
        self._ultimo_uso_tope: bool = False
        # Último tipo de uso de habitación usado — mismo patrón.
        self._ultimo_tipo_hab: TipoUsoHabitacion = TipoUsoHabitacion.OTRO

        # Anchos default (pt PDF) de aberturas — se recuerdan.
        # Antes de calibrar el plano son valores nominales; después
        # de calibrar los recalculamos para que representen 0.90 m
        # / 1.20 m físicos.
        self._ultimo_ancho_puerta_pt: float = 60.0
        self._ultimo_ancho_ventana_pt: float = 80.0

        # Items visuales persistentes.
        self._muros_items: dict[str, MuroItem] = {}
        self._habs_items: dict[str, HabitacionItem] = {}
        self._puertas_items: dict[str, PuertaItem] = {}
        self._ventanas_items: dict[str, VentanaItem] = {}

        # Estado del modo plantilla (PDF de fondo atenuado).
        self._modo_plantilla_activo: bool = False
        # Item del overlay de plantilla: rectángulo blanco semi-
        # transparente que se pone encima del PDF y debajo de los
        # muros/habitaciones para "lavar" los colores del fondo.
        self._overlay_plantilla_item: Optional[QGraphicsRectItem] = None
        # Intensidad de la atenuación (0..100 → alpha 0..255). Default
        # 65 = plantilla lavada pero legible (equivalente al viejo
        # comportamiento fijo). Se ajusta con el slider al lado del
        # botón Plantilla. Ninguna herramienta la cambia sola.
        self._atenuacion_plantilla_pct: int = 65

        # Modo borrar individual — cuando activo, hover pinta de rojo
        # y clic elimina el item.
        self._modo_borrar_individual: bool = False

        # Barra de estado: último mensaje de la herramienta activa y el
        # aviso de auto-extend (si se está mostrando), para restaurar el
        # primero cuando el cursor sale de la zona de auto-extend.
        self._ultimo_msg_herramienta: str = ""
        self._aviso_extension: Optional[str] = None
        # Items quitados de la escena que se mantienen vivos hasta la
        # siguiente vuelta del ciclo de eventos (ver `_retirar_item`).
        self._items_retirados: list = []

        self.setStyleSheet(f"background: {COLOR_FONDO};")

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        raiz.addWidget(self._construir_panel_lateral())
        raiz.addWidget(self._construir_panel_canvas(), 1)

        # Conexiones al modelo
        proyecto.plano_activo_cambiado.connect(self._on_plano_activo_cambiado)
        proyecto.muro_agregado.connect(self._on_muro_agregado)
        proyecto.muro_eliminado.connect(self._on_muro_eliminado)
        proyecto.muro_actualizado.connect(self._on_muro_actualizado)
        proyecto.habitacion_agregada.connect(self._on_hab_agregada)
        proyecto.habitacion_eliminada.connect(self._on_hab_eliminada)
        proyecto.habitacion_actualizada.connect(self._on_hab_actualizada)
        proyecto.escala_actualizada.connect(self._on_escala_actualizada)
        # Aberturas
        proyecto.puerta_agregada.connect(self._on_puerta_agregada)
        proyecto.puerta_eliminada.connect(self._on_puerta_eliminada)
        proyecto.puerta_actualizada.connect(self._on_puerta_actualizada)
        proyecto.ventana_agregada.connect(self._on_ventana_agregada)
        proyecto.ventana_eliminada.connect(self._on_ventana_eliminada)
        proyecto.ventana_actualizada.connect(self._on_ventana_actualizada)

        # Conexiones a las herramientas de dibujo
        self._h_muro.primer_vertice_registrado.connect(self._on_primer_vertice)
        self._h_muro.vertices_cambiados.connect(self._on_vertices_cambiados)
        self._h_muro.cursor_movido.connect(self._on_cursor_dibujo)
        self._h_muro.dibujo_terminado.connect(self._on_muro_terminado)
        self._h_muro.dibujo_cancelado.connect(self._on_dibujo_cancelado)
        self._h_muro.estado_mensaje.connect(self._on_mensaje)

        self._h_muro_arco.primer_vertice_registrado.connect(self._on_primer_vertice)
        self._h_muro_arco.vertices_cambiados.connect(self._on_vertices_cambiados_arco)
        self._h_muro_arco.cursor_movido.connect(self._on_cursor_dibujo)
        self._h_muro_arco.dibujo_terminado.connect(self._on_muro_arco_terminado)
        self._h_muro_arco.dibujo_cancelado.connect(self._on_dibujo_cancelado)
        self._h_muro_arco.estado_mensaje.connect(self._on_mensaje)

        self._h_hab.primer_vertice_registrado.connect(self._on_primer_vertice)
        self._h_hab.vertices_cambiados.connect(self._on_vertices_cambiados_hab)
        self._h_hab.cursor_movido.connect(self._on_cursor_dibujo)
        self._h_hab.dibujo_terminado.connect(self._on_hab_terminada)
        self._h_hab.trazo_cambiado.connect(self._on_trazo_hab)
        self._h_hab.dibujo_cancelado.connect(self._on_dibujo_cancelado)
        self._h_hab.estado_mensaje.connect(self._on_mensaje)

        self._h_hab_circ.primer_vertice_registrado.connect(self._on_primer_vertice)
        self._h_hab_circ.vertices_cambiados.connect(self._on_vertices_cambiados_circ)
        self._h_hab_circ.cursor_movido.connect(self._on_cursor_dibujo)
        self._h_hab_circ.dibujo_terminado.connect(self._on_hab_circular_terminada)
        self._h_hab_circ.dibujo_cancelado.connect(self._on_dibujo_cancelado)
        self._h_hab_circ.estado_mensaje.connect(self._on_mensaje)

        # Herramientas de abertura (Puerta y Ventana) — 2 clics con
        # preview del ancho actual.
        self._h_puerta.abertura_terminada.connect(self._on_puerta_terminada)
        self._h_puerta.hover_muro_cambiado.connect(self._on_hover_muro_abertura)
        self._h_puerta.preview_actualizado.connect(self._on_preview_abertura)
        self._h_puerta.dibujo_cancelado.connect(self._on_dibujo_cancelado)
        self._h_puerta.estado_mensaje.connect(self._on_mensaje)

        self._h_ventana.abertura_terminada.connect(self._on_ventana_terminada)
        self._h_ventana.hover_muro_cambiado.connect(self._on_hover_muro_abertura)
        self._h_ventana.preview_actualizado.connect(self._on_preview_abertura)
        self._h_ventana.dibujo_cancelado.connect(self._on_dibujo_cancelado)
        self._h_ventana.estado_mensaje.connect(self._on_mensaje)

        # Registrar puente como herramienta externa del canvas
        self._canvas.set_herramienta_externa(self._puente)
        self._canvas.scene().addItem(self._preview)
        # Contorno de todos los muros, dibujado debajo de sus rellenos:
        # así las uniones (T, esquinas, diagonales) se ven como una sola
        # pieza en vez de muros encimados con su línea.
        self._bordes_muros = BordesMurosItem(
            lambda: list(self._muros_items.values()),
        )
        # Remiendos de esquinas en L por muro (ver `_refrescar_uniones`).
        self._remiendos: dict = {}
        self._cargando_plano: bool = False
        self._canvas.scene().addItem(self._bordes_muros)

        # F3 (como OSNAP de AutoCAD): enciende/apaga los snaps.
        self._sc_snaps = QShortcut(QKeySequence("F3"), self)
        self._sc_snaps.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_snaps.activated.connect(self._toggle_snaps)

        # Shortcut F8 (estilo AutoCAD) para alternar el modo Orto.
        # Se ancla al widget para no interferir con otras páginas.
        self._sc_orto = QShortcut(QKeySequence("F8"), self)
        self._sc_orto.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_orto.activated.connect(self._toggle_orto)

        # Ctrl+Z durante un trazo activo: quita el último vértice
        # colocado sin cancelar el dibujo completo. Fuera de un trazo
        # activo, el shortcut no hace nada (más adelante puede usarse
        # como undo global sobre el modelo).
        self._sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._sc_undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_undo.activated.connect(self._on_undo)

        # Estado inicial: cargar plano activo si lo hay
        pid = proyecto.plano_activo_id()
        if pid is not None:
            self._cargar_plano_activo(pid)
        else:
            self._actualizar_placeholder()

    # ------------------------------------------------------- construcción UI

    def _construir_panel_lateral(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panelDelim")
        panel.setFixedWidth(_ANCHO_PANEL)
        panel.setStyleSheet(f"""
            QFrame#panelDelim {{
                background: {COLOR_SIDEBAR};
                border-right: 1px solid {COLOR_BORDE};
            }}
        """)
        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        # Título del plano actual
        self._lbl_plano_titulo = QLabel("Sin plano activo")
        self._lbl_plano_titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO}; font-size: 13px; font-weight: 600;
            padding: 2px 0px; background: transparent;
        """)
        v.addWidget(self._lbl_plano_titulo)

        # Contadores
        self._lbl_contadores = QLabel("0 muros · 0 habitaciones")
        self._lbl_contadores.setStyleSheet(f"""
            color: {COLOR_TEXTO_MUTED}; font-size: 11px;
            padding-bottom: 4px; background: transparent;
        """)
        v.addWidget(self._lbl_contadores)

        # Título de sección
        sec = QLabel("HABITACIONES")
        sec.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO};
            font-size: 10px; font-weight: bold;
            letter-spacing: 0.5px;
            padding: 8px 0px 2px 2px;
            background: transparent;
        """)
        v.addWidget(sec)

        # Scroll de habitaciones
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {COLOR_BORDE_FUERTE}; border-radius: 3px;
                min-height: 30px; margin: 2px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                background: none; height: 0; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)
        self._cont_cards = QWidget()
        self._cont_cards.setStyleSheet("background: transparent;")
        self._layout_cards = QVBoxLayout(self._cont_cards)
        self._layout_cards.setContentsMargins(0, 0, 4, 0)
        self._layout_cards.setSpacing(4)
        self._layout_cards.addStretch(1)
        self._scroll.setWidget(self._cont_cards)
        v.addWidget(self._scroll, 1)

        # Mensaje "sin habitaciones"
        self._lbl_vacio = QLabel(
            "Aún no hay habitaciones dibujadas.\n"
            "Usa la herramienta 'Habitación' del ribbon."
        )
        self._lbl_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_vacio.setWordWrap(True)
        self._lbl_vacio.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO};
            font-size: 11px; padding: 20px 6px;
            background: transparent;
        """)
        v.addWidget(self._lbl_vacio)

        return panel

    def _construir_panel_canvas(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet(f"background: {COLOR_FONDO};")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._canvas = CanvasPlano()

        # Ribbon envuelto en scroll horizontal auto-ajustable — la barra
        # aparece solo cuando la ventana es más angosta que el ribbon,
        # y en ese caso el scroll gana +14 px de altura para hacer
        # espacio a la barra. Cuando no aparece, no hay hueco vacío.
        ribbon = self._construir_ribbon()
        ribbon.setMinimumWidth(ribbon.sizeHint().width())
        scroll_ribbon = _RibbonScrollArea()
        scroll_ribbon.setWidget(ribbon)
        scroll_ribbon.setWidgetResizable(True)
        scroll_ribbon.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll_ribbon.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll_ribbon.setFrameShape(QFrame.Shape.NoFrame)
        scroll_ribbon.setStyleSheet(f"""
            QScrollArea {{
                background-color: {COLOR_HEADER};
                border: none;
                border-bottom: 1px solid {COLOR_BORDE};
            }}
            QScrollBar:horizontal {{
                background: {COLOR_HEADER};
                height: 10px; margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {COLOR_BORDE_FUERTE}; border-radius: 4px;
                min-width: 30px; margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {COLOR_ACENTO};
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{
                background: none; width: 0; border: none;
            }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """)
        v.addWidget(scroll_ribbon)

        # Placeholder cuando no hay plano
        area = QWidget()
        area_v = QVBoxLayout(area)
        area_v.setContentsMargins(0, 0, 0, 0)
        area_v.setSpacing(0)
        self._placeholder = QLabel(
            "Abre un plano en la etapa Planos para empezar a delimitar."
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO}; font-size: 13px;
            background: {COLOR_FONDO};
        """)
        area_v.addWidget(self._canvas, 1)
        area_v.addWidget(self._placeholder)
        v.addWidget(area, 1)

        # Status bar
        v.addWidget(self._construir_status_bar())

        # Conexiones del canvas
        self._canvas.zoom_cambiado.connect(self._on_zoom)
        self._canvas.posicion_cursor_metros.connect(self._on_cursor_m)
        self._canvas.posicion_cursor.connect(self._on_cursor_pt)
        self._canvas.herramienta_cambiada.connect(self._on_herramienta_canvas)

        return wrap

    def _construir_ribbon(self) -> QFrame:
        ribbon = QFrame()
        ribbon.setObjectName("ribbonDelim")
        ribbon.setFixedHeight(88)
        ribbon.setStyleSheet(_ribbon_stylesheet())

        h = QHBoxLayout(ribbon)
        h.setContentsMargins(10, 4, 10, 2)
        h.setSpacing(4)

        # VISTA
        g_vista = _crear_grupo("VISTA", [_ANCHO_TOOL_CHICO] * 3)
        b_fit = _boton("fa5s.expand", "Encajar", _ANCHO_TOOL_CHICO,
                        lambda: self._canvas.encajar_plano_en_vista())
        b_zin = _boton("fa5s.search-plus", "Zoom +", _ANCHO_TOOL_CHICO,
                        lambda: self._canvas.zoom_in())
        b_zout = _boton("fa5s.search-minus", "Zoom −", _ANCHO_TOOL_CHICO,
                         lambda: self._canvas.zoom_out())
        g_vista["contenido"].addWidget(b_fit)
        g_vista["contenido"].addWidget(b_zin)
        g_vista["contenido"].addWidget(b_zout)
        h.addWidget(g_vista["widget"])

        h.addWidget(_sep_v())

        # HERRAMIENTAS (Seleccionar / Pan)
        g_h = _crear_grupo(
            "HERRAMIENTAS", [_ANCHO_TOOL_GRAN, _ANCHO_TOOL_CHICO],
        )
        self._btn_sel = _boton(
            "fa5s.mouse-pointer", "Seleccionar", _ANCHO_TOOL_GRAN,
            self._activar_seleccionar,
        )
        self._btn_pan = _boton(
            "fa5s.hand-paper", "Pan", _ANCHO_TOOL_CHICO,
            self._activar_pan,
        )
        g_h["contenido"].addWidget(self._btn_sel)
        g_h["contenido"].addWidget(self._btn_pan)
        h.addWidget(g_h["widget"])

        h.addWidget(_sep_v())

        # MUROS (recto / curvo)
        g_m = _crear_grupo(
            "MUROS", [_ANCHO_TOOL_CHICO, _ANCHO_TOOL_GRAN],
        )
        self._btn_muro = _boton(
            "fa5s.grip-lines", "Muro", _ANCHO_TOOL_CHICO,
            self._activar_muro,
        )
        self._btn_muro_arco = _boton(
            "fa5s.bezier-curve", "Muro curvo", _ANCHO_TOOL_GRAN,
            self._activar_muro_arco,
        )
        g_m["contenido"].addWidget(self._btn_muro)
        g_m["contenido"].addWidget(self._btn_muro_arco)
        h.addWidget(g_m["widget"])

        h.addWidget(_sep_v())

        # HABITACIONES — una sola herramienta que mezcla tramos rectos y
        # arcos (A / L). "Hab. circular" ya no va en el ribbon: un círculo
        # se traza con dos arcos y así se ajusta aunque el del plano no
        # sea perfecto.
        g_hb = _crear_grupo("HABITACIONES", [_ANCHO_TOOL_GRAN])
        self._btn_hab = _boton(
            "fa5s.vector-square", "Habitación", _ANCHO_TOOL_GRAN,
            self._activar_habitacion,
        )
        self._btn_hab.setToolTip(
            "Habitación: clic para vértices.\n"
            "A = siguiente tramo en arco (punto de paso + punto final)\n"
            "L = tramo recto · Ctrl+Z quita el último punto\n"
            "Clic en el 1er vértice o Enter cierra."
        )
        # Se conserva el botón (oculto) por compatibilidad con el resto de
        # la página; la herramienta circular sigue disponible por código.
        self._btn_hab_circ = _boton(
            "fa5s.circle-notch", "Hab. circular", _ANCHO_TOOL_GRAN,
            self._activar_habitacion_circular,
        )
        self._btn_hab_circ.setVisible(False)
        g_hb["contenido"].addWidget(self._btn_hab)
        h.addWidget(g_hb["widget"])

        h.addWidget(_sep_v())

        # ABERTURAS (puerta / ventana)
        g_ab = _crear_grupo(
            "ABERTURAS", [_ANCHO_TOOL_CHICO, _ANCHO_TOOL_CHICO],
        )
        self._btn_puerta = _boton(
            "fa5s.door-open", "Puerta", _ANCHO_TOOL_CHICO,
            self._activar_puerta,
        )
        self._btn_ventana = _boton(
            "fa5s.window-maximize", "Ventana", _ANCHO_TOOL_CHICO,
            self._activar_ventana,
        )
        g_ab["contenido"].addWidget(self._btn_puerta)
        g_ab["contenido"].addWidget(self._btn_ventana)
        h.addWidget(g_ab["widget"])

        h.addWidget(_sep_v())

        # MODO (Orto toggle — F8 / Plantilla toggle + slider de opacidad)
        _ANCHO_SLIDER = 22
        g_mo = _crear_grupo(
            "MODO",
            [_ANCHO_TOOL_CHICO, _ANCHO_TOOL_CHICO, _ANCHO_TOOL_CHICO,
             _ANCHO_SLIDER],
        )
        self._btn_snap = _boton(
            "fa5s.magnet", "Snap", _ANCHO_TOOL_CHICO, self._toggle_snaps,
        )
        self._btn_snap.setToolTip(
            "Snap a objetos (F3): engancha a vértices, puntos medios\n"
            "y caras de muros. Apágalo para poner el punto exactamente\n"
            "donde haces clic, por ejemplo al calcar el plano."
        )
        self._btn_orto = _boton(
            "fa5s.ruler-combined", "Orto", _ANCHO_TOOL_CHICO,
            self._toggle_orto,
        )
        self._btn_orto.setToolTip(
            "Modo ortogonal (F8): fuerza líneas a 0°/45°/90°.\n"
            "Puedes hacer lo mismo momentáneamente manteniendo Shift."
        )
        self._btn_plantilla = _boton(
            "fa5s.eye", "Plantilla", _ANCHO_TOOL_CHICO,
            self._toggle_plantilla,
        )
        self._btn_plantilla.setToolTip(
            "Modo plantilla: atenúa el PDF de fondo para que\n"
            "tus dibujos destaquen. Ajusta la intensidad con el\n"
            "slider a la derecha."
        )
        # Slider vertical de atenuación. Invertido para que "arriba"
        # sea "más atenuada" (más blanco encima) y "abajo" sea "más
        # visible" (menos blanco). Intuitivo tipo cortina.
        self._slider_plantilla = QSlider(Qt.Orientation.Vertical)
        self._slider_plantilla.setMinimum(0)
        self._slider_plantilla.setMaximum(100)
        self._slider_plantilla.setValue(self._atenuacion_plantilla_pct)
        self._slider_plantilla.setInvertedAppearance(True)
        self._slider_plantilla.setFixedWidth(_ANCHO_SLIDER)
        self._slider_plantilla.setToolTip(
            "Atenuación de la plantilla.\n"
            "Arriba = más lavada. Abajo = más visible."
        )
        self._slider_plantilla.valueChanged.connect(
            self._on_slider_plantilla,
        )
        g_mo["contenido"].addWidget(self._btn_snap)
        g_mo["contenido"].addWidget(self._btn_orto)
        g_mo["contenido"].addWidget(self._btn_plantilla)
        g_mo["contenido"].addWidget(self._slider_plantilla)
        h.addWidget(g_mo["widget"])

        h.addWidget(_sep_v())

        # BORRAR — sólo borrador individual estilo goma. El "Borrar
        # todo" se quitó a propósito: era demasiado destructivo para
        # un solo clic, y la goma cubre el caso legítimo.
        g_b = _crear_grupo("BORRAR", [_ANCHO_TOOL_CHICO])
        self._btn_borrar_una = _boton(
            "fa5s.eraser", "Goma", _ANCHO_TOOL_CHICO,
            self._toggle_borrar_individual,
        )
        g_b["contenido"].addWidget(self._btn_borrar_una)
        h.addWidget(g_b["widget"])

        h.addStretch(1)

        # Marcar Seleccionar como activo por default visualmente
        self._marcar_boton(self._btn_sel, activo=True)
        # Snap encendido por default
        self._marcar_boton(self._btn_snap, activo=True)

        return ribbon

    def _construir_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("statusBarDelim")
        bar.setFixedHeight(28)
        bar.setStyleSheet(f"""
            QFrame#statusBarDelim {{
                background: {COLOR_SIDEBAR};
                border-top: 1px solid {COLOR_BORDE};
            }}
            QLabel {{
                color: {COLOR_TEXTO_SUAVE}; font-size: 11px;
                padding: 4px 12px; background: transparent;
            }}
            QLabel#muted {{ color: {COLOR_TEXTO_APAGADO}; }}
            QLabel#msg {{ color: {COLOR_ACENTO_BRILL}; font-weight: bold; }}
            QFrame#sep {{
                background: {COLOR_BORDE};
                min-width: 1px; max-width: 1px;
                margin: 4px 0px;
            }}
        """)
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self._lbl_cursor = QLabel("cursor: —")
        self._lbl_cursor.setObjectName("muted")
        h.addWidget(self._lbl_cursor)

        h.addStretch(1)

        self._lbl_msg = QLabel("")
        self._lbl_msg.setObjectName("msg")
        h.addWidget(self._lbl_msg)

        sep = QFrame()
        sep.setObjectName("sep")
        h.addWidget(sep)

        self._lbl_zoom = QLabel("zoom: —")
        h.addWidget(self._lbl_zoom)

        return bar

    # ---------------------------------------------------- Ribbon: acciones

    def _desactivar_herramientas_dibujo(self) -> None:
        for h in (
            self._h_muro, self._h_muro_arco,
            self._h_hab, self._h_hab_circ,
            self._h_puerta, self._h_ventana,
        ):
            if h.esta_activa():
                h.desactivar()
        self._preview.limpiar()
        self._preview.setVisible(False)
        self._preview.set_modo(ModoPreview.POLILINEA)
        for btn in (
            self._btn_muro, self._btn_muro_arco,
            self._btn_hab, self._btn_hab_circ,
            self._btn_puerta, self._btn_ventana,
        ):
            self._marcar_boton(btn, activo=False)
        # Muros y habitaciones vuelven a opacidad completa (se habían
        # vuelto translúcidos en modo Puerta/Ventana).
        self._restaurar_opacidad_muros_y_habs()

    def _preparar_dibujo(self, modo_preview: ModoPreview) -> None:
        """Estado común antes de activar cualquier herramienta de
        dibujo: sale del modo borrar, resetea el preview y lo hace
        visible con el modo pedido."""
        self._salir_modo_borrar_ind()
        self._preview.set_vertices([])
        self._preview.set_cursor(None)
        self._preview.set_modo(modo_preview)
        self._preview.setVisible(True)

    def _activar_seleccionar(self) -> None:
        self._desactivar_herramientas_dibujo()
        self._salir_modo_borrar_ind()
        self._canvas.set_herramienta(Herramienta.SELECCIONAR)
        self._marcar_boton_tools(self._btn_sel)

    def _activar_pan(self) -> None:
        self._desactivar_herramientas_dibujo()
        self._salir_modo_borrar_ind()
        self._canvas.set_herramienta(Herramienta.PAN)
        self._marcar_boton_tools(self._btn_pan)

    def _activar_muro(self) -> None:
        if self._plano_id is None:
            QMessageBox.information(
                self, "Dibujar muro",
                "Primero abre un plano en la etapa Planos."
            )
            return
        # Desactivar cualquier otra herramienta de dibujo activa
        for h in (self._h_muro_arco, self._h_hab, self._h_hab_circ):
            if h.esta_activa():
                h.desactivar()
        self._preparar_dibujo(ModoPreview.POLILINEA)
        self._h_muro.activar()
        self._canvas.set_herramienta(Herramienta.DIBUJAR)
        self._marcar_boton_tools(self._btn_muro)

    def _activar_muro_arco(self) -> None:
        if self._plano_id is None:
            QMessageBox.information(
                self, "Dibujar muro curvo",
                "Primero abre un plano en la etapa Planos."
            )
            return
        for h in (self._h_muro, self._h_hab, self._h_hab_circ):
            if h.esta_activa():
                h.desactivar()
        self._preparar_dibujo(ModoPreview.ARCO)
        self._h_muro_arco.activar()
        self._canvas.set_herramienta(Herramienta.DIBUJAR)
        self._marcar_boton_tools(self._btn_muro_arco)

    def _activar_habitacion(self) -> None:
        if self._plano_id is None:
            QMessageBox.information(
                self, "Dibujar habitación",
                "Primero abre un plano en la etapa Planos."
            )
            return
        for h in (self._h_muro, self._h_muro_arco, self._h_hab_circ):
            if h.esta_activa():
                h.desactivar()
        self._preparar_dibujo(ModoPreview.POLILINEA)
        self._h_hab.activar()
        self._canvas.set_herramienta(Herramienta.DIBUJAR)
        self._marcar_boton_tools(self._btn_hab)

    def _activar_habitacion_circular(self) -> None:
        if self._plano_id is None:
            QMessageBox.information(
                self, "Dibujar habitación circular",
                "Primero abre un plano en la etapa Planos."
            )
            return
        for h in (self._h_muro, self._h_muro_arco, self._h_hab):
            if h.esta_activa():
                h.desactivar()
        self._preparar_dibujo(ModoPreview.CIRCULO)
        self._h_hab_circ.activar()
        self._canvas.set_herramienta(Herramienta.DIBUJAR)
        self._marcar_boton_tools(self._btn_hab_circ)

    def _activar_puerta(self) -> None:
        if self._plano_id is None:
            QMessageBox.information(
                self, "Colocar puerta",
                "Primero abre un plano en la etapa Planos."
            )
            return
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None or not plano.muros:
            QMessageBox.information(
                self, "Colocar puerta",
                "Primero dibuja al menos un muro. Las puertas se colocan sobre un muro."
            )
            return
        for h in (
            self._h_muro, self._h_muro_arco,
            self._h_hab, self._h_hab_circ, self._h_ventana,
        ):
            if h.esta_activa():
                h.desactivar()
        # Preview en modo polilínea — la puerta se dibuja con 2 clics
        # (extremo A y extremo B sobre el mismo muro) y el preview
        # muestra el primer punto + segmento dashed al segundo.
        self._preparar_dibujo(ModoPreview.POLILINEA)
        # Los muros se vuelven translúcidos para que se vea la puerta
        # original del CAD debajo. La plantilla NO se toca: su
        # atenuación es preferencia del operador (slider).
        self._atenuar_muros_y_habs(0.4)
        self._h_puerta.activar()
        self._canvas.set_herramienta(Herramienta.DIBUJAR)
        self._marcar_boton_tools(self._btn_puerta)

    def _activar_ventana(self) -> None:
        if self._plano_id is None:
            QMessageBox.information(
                self, "Colocar ventana",
                "Primero abre un plano en la etapa Planos."
            )
            return
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None or not plano.muros:
            QMessageBox.information(
                self, "Colocar ventana",
                "Primero dibuja al menos un muro. Las ventanas se colocan sobre un muro."
            )
            return
        for h in (
            self._h_muro, self._h_muro_arco,
            self._h_hab, self._h_hab_circ, self._h_puerta,
        ):
            if h.esta_activa():
                h.desactivar()
        # Preview polilínea — 2 clics (extremo A y B sobre el muro).
        self._preparar_dibujo(ModoPreview.POLILINEA)
        # Los muros se vuelven translúcidos para que se vea la ventana
        # original del CAD debajo. La plantilla NO se toca: su
        # atenuación es preferencia del operador (slider).
        self._atenuar_muros_y_habs(0.4)
        self._h_ventana.activar()
        self._canvas.set_herramienta(Herramienta.DIBUJAR)
        self._marcar_boton_tools(self._btn_ventana)

    def _resolver_muro_bajo_cursor(
        self, punto: QPointF,
    ) -> Optional[tuple[Muro, QPointF, bool]]:
        """Dado un punto en coordenadas del plano, encuentra el muro
        más cercano dentro de un radio de captura y devuelve
        (muro, punto, enganchado): el punto es EXACTAMENTE el del cursor,
        salvo que el Snap esté encendido y el cursor esté a menos de 8 px
        de una esquina del muro o de su extremo (entonces es ese punto).
        None si ningún muro está en radio."""
        if self._plano_id is None:
            return None
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None or not plano.muros:
            return None
        # Radio de captura en pt PDF: convertimos ~20 px de pantalla
        # usando el zoom actual del canvas.
        try:
            zoom = self._canvas.zoom_actual()
        except Exception:  # noqa: BLE001
            zoom = 1.0
        if zoom <= 0:
            zoom = 1.0
        radio_captura = 30.0 / zoom
        mejor: Optional[tuple[Muro, float, float]] = None
        for m in plano.muros:
            proj = proyectar_punto_sobre_muro(punto, m)
            if proj is None:
                continue
            _pt_proj, dist, d_ini = proj
            # Distancia al CUERPO del muro (no a la línea trazada): con
            # justificación izquierda/derecha el cuerpo está desplazado
            # medio grosor. Si el cursor cae dentro del cuerpo, cuenta
            # como hover directo (distancia efectiva 0) — así se puede
            # apuntar sobre cualquiera de las dos caras del muro.
            cuerpo = punto_cuerpo_muro(m, d_ini, self._canvas.escala_actual())
            if cuerpo is not None:
                centro_c, _t, _n, grosor_efectivo = cuerpo
                dist_c = math.hypot(
                    punto.x() - centro_c.x(), punto.y() - centro_c.y(),
                )
                dist_efectiva = max(0.0, dist_c - grosor_efectivo / 2.0)
            else:
                grosor_efectivo = m.grosor_pt(self._canvas.escala_actual())
                dist_efectiva = max(0.0, dist - grosor_efectivo / 2.0)
            if dist_efectiva > radio_captura:
                continue
            if mejor is None or dist_efectiva < mejor[2]:
                mejor = (m, d_ini, dist_efectiva)
        if mejor is None:
            return None
        muro = mejor[0]
        if not self._puente.snaps_activos():
            return (muro, QPointF(punto), False)
        # Snap: esquinas del muro (interior y punta) y sus extremos.
        tol = 8.0 / zoom
        enganche = None
        for visible, valor in puntos_enganche_abertura(
            muro, self._canvas.escala_actual(),
        ):
            dist = math.hypot(punto.x() - visible.x(), punto.y() - visible.y())
            if dist <= tol and (enganche is None or dist < enganche[0]):
                enganche = (dist, valor)
        if enganche is not None:
            return (muro, QPointF(enganche[1]), True)
        return (muro, QPointF(punto), False)

    def _toggle_orto(self) -> None:
        """Alterna el modo Orto. F8 llama aquí también."""
        nuevo = not self._puente.orto_activo()
        self._puente.set_orto_activo(nuevo)
        self._marcar_boton(self._btn_orto, activo=nuevo)
        # Feedback en la status bar (sin pisar mensajes de herramienta
        # en curso: sólo lo mostramos si no hay dibujo activo).
        if not self._puente.esta_activa():
            if nuevo:
                self._lbl_msg.setText(
                    "Orto activado — todos los segmentos serán a 0°/45°/90°."
                )
            else:
                self._lbl_msg.setText("Orto desactivado.")

    def _toggle_snaps(self) -> None:
        """Enciende/apaga los snaps a objetos (F3 o botón Snap)."""
        nuevo = not self._puente.snaps_activos()
        self._puente.set_snaps_activos(nuevo)
        self._marcar_boton(self._btn_snap, activo=nuevo)
        self._lbl_msg.setText(
            "Snap activado — engancha a vértices, puntos medios y caras de muros."
            if nuevo else
            "Snap desactivado (F3) — el punto queda exactamente donde haces clic."
        )

    def _on_undo(self) -> None:
        """Ctrl+Z durante un trazo activo: quita el último vértice
        colocado. Fuera de un trazo, no hace nada (por ahora)."""
        if not self._puente.esta_activa():
            return
        self._puente.retroceder_ultimo()

    def _marcar_boton_tools(self, activo_btn: QToolButton) -> None:
        for btn in (
            self._btn_sel, self._btn_pan,
            self._btn_muro, self._btn_muro_arco,
            self._btn_hab, self._btn_hab_circ,
            self._btn_puerta, self._btn_ventana,
        ):
            self._marcar_boton(btn, activo=(btn is activo_btn))

    def _toggle_plantilla(self) -> None:
        """Alterna el modo plantilla del PDF de fondo: escala de grises
        + opacidad 50% (para que muros y dibujos destaquen).

        Se aplica un `QGraphicsColorizeEffect` gris + `setOpacity(0.5)`
        al item del plano. El canvas debe exponer `plano_item()` o
        atributo compatible; si no está disponible, se aplica al
        canvas completo como fallback (menos limpio)."""
        self._modo_plantilla_activo = not self._modo_plantilla_activo
        self._aplicar_modo_plantilla_al_canvas(self._modo_plantilla_activo)
        self._marcar_boton(
            self._btn_plantilla, activo=self._modo_plantilla_activo,
        )
        if not self._puente.esta_activa():
            self._lbl_msg.setText(
                "Plantilla activada: PDF atenuado, dibujos destacan."
                if self._modo_plantilla_activo
                else "Plantilla desactivada: PDF en su forma original."
            )

    def _aplicar_modo_plantilla_al_canvas(self, activo: bool) -> None:
        """Aplica/quita el efecto de modo plantilla.

        Estrategia: en lugar de intentar aplicar un efecto al item
        del PDF (que puede no existir como QGraphicsItem si el canvas
        lo dibuja en `drawBackground()`), agregamos un rectángulo
        blanco semi-transparente que cubre toda la escena. Se pone
        con Z = 100 — encima del PDF (Z ≈ 0-50) y debajo de los
        muros (Z = 400), habitaciones (Z = 300) y aberturas (Z = 500).

        El resultado visual es equivalente: el plano se ve "lavado"
        y los dibujos encima destacan con sus colores propios.
        Funciona sin importar cómo el CanvasPlano renderice el PDF.
        """
        try:
            scene = self._canvas.scene()
        except Exception:  # noqa: BLE001
            scene = None
        if scene is None:
            return

        if activo:
            # Recrear el overlay si no existe o si su escena ya no
            # es la escena actual (caso: se cargó plano nuevo).
            needs_new = (
                self._overlay_plantilla_item is None
                or self._overlay_plantilla_item.scene() is not scene
            )
            if needs_new:
                rect_item = QGraphicsRectItem()
                # QGraphicsRectItem.setPen requiere un QPen, no un
                # Qt.PenStyle directamente (a diferencia de QPainter).
                rect_item.setPen(QPen(Qt.PenStyle.NoPen))
                rect_item.setZValue(100)
                # No captura clicks — que pase el evento al canvas
                rect_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                rect_item.setAcceptHoverEvents(False)
                scene.addItem(rect_item)
                self._overlay_plantilla_item = rect_item
            # Alpha del blanco = intensidad de atenuación (0..255).
            # El slider guarda el porcentaje 0..100; convertimos aquí.
            alpha = int(round(self._atenuacion_plantilla_pct * 2.55))
            self._overlay_plantilla_item.setBrush(
                QBrush(QColor(255, 255, 255, alpha)),
            )
            # Ajustar el rect al sceneRect actual (siempre, por si
            # el sceneRect cambió tras un zoom o carga)
            self._overlay_plantilla_item.setRect(scene.sceneRect())
            self._overlay_plantilla_item.show()
        else:
            if (
                self._overlay_plantilla_item is not None
                and self._overlay_plantilla_item.scene() is scene
            ):
                self._overlay_plantilla_item.hide()

    def _on_slider_plantilla(self, valor: int) -> None:
        """El slider ajusta la intensidad de atenuación (0..100).
        0 = plantilla se ve tal cual (sin blanco encima); 100 = blanco
        total (plantilla apenas visible). Aplica sólo cuando el modo
        plantilla está activo — si no, sólo se guarda el valor."""
        self._atenuacion_plantilla_pct = max(0, min(100, int(valor)))
        if self._modo_plantilla_activo:
            self._aplicar_modo_plantilla_al_canvas(True)

    def _atenuar_muros_y_habs(self, opacidad: float = 0.4) -> None:
        """Baja la opacidad de todos los muros y habitaciones para
        que la plantilla del CAD debajo se vea a través. Se usa al
        entrar en modo Puerta/Ventana — así el operador puede
        distinguir dónde el CAD original tenía huecos y colocar sus
        aberturas exactamente ahí."""
        for it in self._muros_items.values():
            it.setOpacity(opacidad)
        self._bordes_muros.setOpacity(opacidad)
        for it in self._habs_items.values():
            it.setOpacity(opacidad)

    def _restaurar_opacidad_muros_y_habs(self) -> None:
        """Devuelve la opacidad de muros y habitaciones a 1.0. Se
        llama al salir del modo Puerta/Ventana."""
        for it in self._muros_items.values():
            it.setOpacity(1.0)
        self._bordes_muros.setOpacity(1.0)
        for it in self._habs_items.values():
            it.setOpacity(1.0)

    def _marcar_boton(self, btn: QToolButton, activo: bool) -> None:
        btn.setObjectName("toolActivo" if activo else "")
        _aplicar_icono(btn, activo=activo)
        _reaplicar(btn)

    def _toggle_borrar_individual(self) -> None:
        if self._modo_borrar_individual:
            self._salir_modo_borrar_ind()
        else:
            self._entrar_modo_borrar_ind()

    def _entrar_modo_borrar_ind(self) -> None:
        if self._plano_id is None:
            return
        # Salir de dibujo si estaba activo
        self._desactivar_herramientas_dibujo()
        self._modo_borrar_individual = True
        for it in self._muros_items.values():
            it.set_modo_borrar_activo(True)
        for it in self._habs_items.values():
            it.set_modo_borrar_activo(True)
        for it in self._puertas_items.values():
            it.set_modo_borrar_activo(True)
        for it in self._ventanas_items.values():
            it.set_modo_borrar_activo(True)
        self._marcar_boton(self._btn_borrar_una, activo=True)
        self._lbl_msg.setText(
            "Borrar una por una: clic sobre el muro, habitación, "
            "puerta o ventana a eliminar. Vuelve a hacer clic en "
            "'Una' para salir."
        )

    def _salir_modo_borrar_ind(self) -> None:
        if not self._modo_borrar_individual:
            return
        self._modo_borrar_individual = False
        for it in self._muros_items.values():
            it.set_modo_borrar_activo(False)
        for it in self._habs_items.values():
            it.set_modo_borrar_activo(False)
        for it in self._puertas_items.values():
            it.set_modo_borrar_activo(False)
        for it in self._ventanas_items.values():
            it.set_modo_borrar_activo(False)
        self._marcar_boton(self._btn_borrar_una, activo=False)
        txt = self._lbl_msg.text()
        if txt.startswith("Borrar una por una"):
            self._lbl_msg.setText("")

    # -------------------------------------- callbacks del modelo (proyecto)

    def _on_plano_activo_cambiado(self, plano_id) -> None:
        if plano_id is None:
            self._descargar_plano_actual()
            return
        if plano_id == self._plano_id:
            return
        self._cargar_plano_activo(plano_id)

    def _cargar_plano_activo(self, plano_id: str) -> None:
        plano = self._proyecto.plano_por_id(plano_id)
        if plano is None or not plano.existe_archivo():
            self._descargar_plano_actual()
            return
        # Limpiar visuales del plano anterior
        self._limpiar_visuales()
        self._salir_modo_borrar_ind()
        self._desactivar_herramientas_dibujo()

        if not self._canvas.cargar_plano(plano.path):
            return
        if plano.esta_calibrado():
            self._canvas.set_escala(plano.escala)
        # Re-agregar preview a la escena nueva
        if self._preview.scene() is None:
            self._canvas.scene().addItem(self._preview)
        if self._bordes_muros.scene() is None:
            self._canvas.scene().addItem(self._bordes_muros)

        self._plano_id = plano_id
        self._lbl_plano_titulo.setText(plano.titulo)
        self._placeholder.setVisible(False)
        self._canvas.setVisible(True)

        # Cargar muros y habitaciones existentes del modelo (las uniones
        # se calculan una sola vez al final, no por cada muro).
        self._cargando_plano = True
        for m in plano.muros:
            self._crear_item_muro(m)
        self._cargando_plano = False
        for h in plano.habitaciones:
            self._crear_item_hab(h)
        # Cargar aberturas existentes
        for p in plano.puertas:
            self._crear_item_puerta(p)
        for w in plano.ventanas:
            self._crear_item_ventana(w)
        self._refrescar_uniones()
        # Reaplicar modo plantilla si estaba activo (el canvas nuevo
        # no tiene el efecto puesto).
        if self._modo_plantilla_activo:
            self._aplicar_modo_plantilla_al_canvas(True)
        # Recalibrar los "últimos anchos" si el plano ya tiene escala
        escala = plano.escala
        if escala is not None and escala.m_por_pt > 0.0:
            m_por_pt = escala.m_por_pt
            self._ultimo_ancho_puerta_pt = 0.90 / m_por_pt
            self._ultimo_ancho_ventana_pt = 1.20 / m_por_pt
        self._refrescar_lista_habs()
        self._actualizar_contadores()

    def _descargar_plano_actual(self) -> None:
        self._limpiar_visuales()
        self._salir_modo_borrar_ind()
        self._desactivar_herramientas_dibujo()
        self._plano_id = None
        self._lbl_plano_titulo.setText("Sin plano activo")
        self._canvas.descargar_plano()
        self._actualizar_placeholder()
        self._refrescar_lista_habs()
        self._actualizar_contadores()

    def _actualizar_placeholder(self) -> None:
        sin_plano = (self._plano_id is None)
        self._placeholder.setVisible(sin_plano)
        self._canvas.setVisible(not sin_plano)

    def _limpiar_visuales(self) -> None:
        scene = self._canvas.scene()
        for it in self._muros_items.values():
            self._retirar_item(it)
        for it in self._habs_items.values():
            self._retirar_item(it)
        for it in self._puertas_items.values():
            self._retirar_item(it)
        for it in self._ventanas_items.values():
            self._retirar_item(it)
        self._muros_items.clear()
        self._habs_items.clear()
        self._puertas_items.clear()
        self._ventanas_items.clear()
        self._refrescar_uniones()
        # Overlay de plantilla (si la escena cambia, se rehace al
        # aplicar el modo plantilla nuevamente).
        if (
            self._overlay_plantilla_item is not None
            and self._overlay_plantilla_item.scene() is scene
        ):
            scene.removeItem(self._overlay_plantilla_item)
        self._overlay_plantilla_item = None

    def _on_muro_agregado(self, plano_id: str, muro: Muro) -> None:
        if plano_id != self._plano_id:
            return
        self._crear_item_muro(muro)
        self._actualizar_contadores()

    def _on_muro_eliminado(self, plano_id: str, muro_id: str) -> None:
        if plano_id != self._plano_id:
            return
        it = self._muros_items.pop(muro_id, None)
        if it is not None:
            self._retirar_item(it)
        self._refrescar_uniones()
        self._actualizar_contadores()

    def _on_muro_actualizado(self, plano_id: str, muro: Muro) -> None:
        if plano_id != self._plano_id:
            return
        it = self._muros_items.get(muro.id)
        if it is not None:
            it.actualizar_desde_modelo()
        # Sus puertas y ventanas se reubican con el muro.
        for it_ab in list(self._puertas_items.values()) + list(self._ventanas_items.values()):
            ab = it_ab.puerta() if isinstance(it_ab, PuertaItem) else it_ab.ventana()
            if ab.muro_id == muro.id:
                it_ab.actualizar_desde_modelo()
        self._refrescar_uniones()

    def _on_hab_agregada(self, plano_id: str, hab: Habitacion) -> None:
        if plano_id != self._plano_id:
            return
        self._crear_item_hab(hab)
        self._refrescar_lista_habs()
        self._actualizar_contadores()

    def _on_hab_eliminada(self, plano_id: str, hab_id: str) -> None:
        if plano_id != self._plano_id:
            return
        it = self._habs_items.pop(hab_id, None)
        if it is not None:
            self._retirar_item(it)
        self._refrescar_lista_habs()
        self._actualizar_contadores()

    def _on_hab_actualizada(self, plano_id: str, hab: Habitacion) -> None:
        if plano_id != self._plano_id:
            return
        it = self._habs_items.get(hab.id)
        if it is not None:
            it.actualizar_desde_modelo()
        self._refrescar_lista_habs()

    def _on_escala_actualizada(self, plano_id: str, escala) -> None:
        if plano_id != self._plano_id:
            return
        # CRÍTICO: propagar la nueva escala al canvas local de esta
        # etapa. Sin esto, `canvas.escala_actual()` sigue devolviendo
        # None aunque el modelo ya tenga la escala aplicada, y los
        # muros se pintan con el fallback fijo (4 pt) en vez del
        # grosor físico real.
        self._canvas.set_escala(escala)
        # Refrescar habs (áreas cambian con la escala)
        for it in self._habs_items.values():
            it.actualizar_desde_modelo()
        # Refrescar muros (grosor visual cambia con la escala)
        for it in self._muros_items.values():
            it.actualizar_desde_modelo()
        self._refrescar_uniones()
        # Refrescar aberturas
        for it in list(self._puertas_items.values()):
            it.actualizar_desde_modelo()
        for it in list(self._ventanas_items.values()):
            it.actualizar_desde_modelo()
        # Recalibrar los "últimos anchos" de aberturas para que
        # correspondan a 0.90 m / 1.20 m físicos.
        if escala is not None:
            m_por_pt = escala.m_por_pt
            if m_por_pt > 0.0:
                self._ultimo_ancho_puerta_pt = 0.90 / m_por_pt
                self._ultimo_ancho_ventana_pt = 1.20 / m_por_pt
        self._refrescar_lista_habs()

    # ------------------ callbacks del modelo — aberturas -------------------

    def _on_puerta_agregada(self, plano_id: str, puerta: Puerta) -> None:
        if plano_id != self._plano_id:
            return
        self._crear_item_puerta(puerta)
        # Refrescar el muro para que se dibuje con el hueco restado
        it_muro = self._muros_items.get(puerta.muro_id)
        if it_muro is not None:
            it_muro.actualizar_desde_modelo()
            self._bordes_muros.update()
        self._actualizar_contadores()

    def _on_puerta_eliminada(self, plano_id: str, puerta_id: str) -> None:
        if plano_id != self._plano_id:
            return
        it = self._puertas_items.pop(puerta_id, None)
        if it is not None:
            muro_id = it.puerta().muro_id
            self._retirar_item(it)
            # Refrescar muro (hueco desaparece)
            it_muro = self._muros_items.get(muro_id)
            if it_muro is not None:
                it_muro.actualizar_desde_modelo()
            self._bordes_muros.update()
        self._actualizar_contadores()

    def _on_puerta_actualizada(self, plano_id: str, puerta: Puerta) -> None:
        if plano_id != self._plano_id:
            return
        it = self._puertas_items.get(puerta.id)
        if it is not None:
            it.actualizar_desde_modelo()
        it_muro = self._muros_items.get(puerta.muro_id)
        if it_muro is not None:
            it_muro.actualizar_desde_modelo()
            self._bordes_muros.update()

    def _on_ventana_agregada(self, plano_id: str, ventana: Ventana) -> None:
        if plano_id != self._plano_id:
            return
        self._crear_item_ventana(ventana)
        it_muro = self._muros_items.get(ventana.muro_id)
        if it_muro is not None:
            it_muro.actualizar_desde_modelo()
            self._bordes_muros.update()
        self._actualizar_contadores()

    def _on_ventana_eliminada(self, plano_id: str, ventana_id: str) -> None:
        if plano_id != self._plano_id:
            return
        it = self._ventanas_items.pop(ventana_id, None)
        if it is not None:
            muro_id = it.ventana().muro_id
            self._retirar_item(it)
            it_muro = self._muros_items.get(muro_id)
            if it_muro is not None:
                it_muro.actualizar_desde_modelo()
            self._bordes_muros.update()
        self._actualizar_contadores()

    def _on_ventana_actualizada(self, plano_id: str, ventana: Ventana) -> None:
        if plano_id != self._plano_id:
            return
        it = self._ventanas_items.get(ventana.id)
        if it is not None:
            it.actualizar_desde_modelo()
        it_muro = self._muros_items.get(ventana.muro_id)
        if it_muro is not None:
            it_muro.actualizar_desde_modelo()
            self._bordes_muros.update()

    # -------------- callbacks de herramientas de aberturas -----------------

    def _on_puerta_terminada(
        self, muro_id: str, d_centro: float, ancho_pt: float,
        pivote_en_inicio: bool, sentido_str: str,
    ) -> None:
        """Dispara cuando el 3° clic fija la orientación de la puerta.
        Los 2 primeros clics definen el hueco (ancho); el 3° define
        el pivote (extremo A o B) y el sentido (lado del muro)."""
        if self._plano_id is None:
            return
        self._ultimo_ancho_puerta_pt = ancho_pt
        try:
            sentido = SentidoAperturaPuerta(sentido_str)
        except ValueError:
            sentido = SentidoAperturaPuerta.DER
        self._proyecto.agregar_puerta(
            self._plano_id, muro_id, d_centro,
            ancho_pt=ancho_pt,
            sentido=sentido,
            pivote_en_inicio=pivote_en_inicio,
        )

    def _on_ventana_terminada(
        self, muro_id: str, d_centro: float, ancho_pt: float,
        _pivote_en_inicio: bool, _sentido_str: str,
    ) -> None:
        """Dispara cuando la Ventana termina el 2° clic. Los dos
        últimos parámetros se ignoran (la ventana es simétrica)."""
        if self._plano_id is None:
            return
        self._ultimo_ancho_ventana_pt = ancho_pt
        self._proyecto.agregar_ventana(
            self._plano_id, muro_id, d_centro,
            ancho_pt=ancho_pt,
        )

    def _on_preview_abertura(self, datos) -> None:
        """Recibe el preview de la herramienta de abertura. Dos formas:

          * Fase 1 (marcando ancho): {"muro_id","punto_a","punto_b",
            "ancho_pt"}. Alimenta el PreviewDibujoItem con vértice fijo
            + cursor.
          * Fase 2 (eligiendo orientación de puerta): mismo dict pero
            con `centro_hueco`, `tangente`, `normal`, `pivote_en_inicio`,
            `sentido`. Se dibuja el arco de barrido.

          * None → limpiar todo.
        """
        # El preview de aberturas NO usa vértices ni la línea al cursor
        # (esa cuerda cruzaba las esquinas y no se parecía al resultado):
        # se dibuja un "fantasma" con la misma geometría final + las
        # líneas de corte de sus extremos.
        self._preview.set_vertices([])
        self._preview.set_cursor(None)
        if datos is None:
            self._preview.set_puerta_preview(None)
            self._preview.set_abertura_preview(None)
            return
        self._preview.set_abertura_preview(datos.get("fantasma"))
        # ¿Fase de orientación? Se distingue porque llegan pivote/sentido.
        if "pivote_en_inicio" in datos and "sentido" in datos:
            # Ancho ya está fijo: sólo falta el arco de la hoja.
            self._preview.set_corte_hover(None)
            self._preview.set_puerta_preview(datos)
            self._lbl_msg.setText(
                "Puerta: mueve el cursor al cuadrante donde debe abrir "
                "la hoja. Clic para fijar."
            )
            return
        # Fase 1: preview del ancho.
        self._preview.set_puerta_preview(None)
        punto_b = datos.get("punto_b")
        ancho_pt = datos.get("ancho_pt", 0.0)
        # Mensaje con el ancho en curso, en metros si hay escala.
        escala = self._canvas.escala_actual()
        if punto_b is not None and ancho_pt > 0.0:
            if escala is not None:
                ancho_m = ancho_pt * escala.m_por_pt
                self._lbl_msg.setText(
                    f"Ancho actual: {ancho_m:.2f} m. Clic para fijar."
                )
            else:
                self._lbl_msg.setText(
                    f"Ancho actual: {ancho_pt:.1f} pt. Clic para fijar."
                )

    def _on_hover_muro_abertura(self, info) -> None:
        """El puente de aberturas emite `hover_muro_cambiado(info)` con
        (muro_id, d) o None. Aquí podríamos dibujar un preview del
        rectángulo de la abertura sobre el muro. Por simplicidad de
        esta iteración, solo actualizamos el mensaje de la status bar."""
        if info is None:
            self._lbl_msg.setText(
                "Acerca el cursor a un muro para insertar la abertura."
            )
        else:
            muro_id, _d = info
            self._lbl_msg.setText(
                f"Insertando sobre {muro_id} — clic para colocar."
            )

    def _refrescar_uniones(self) -> None:
        """Recalcula las esquinas en L entre muros y repinta contornos.
        Se llama cada vez que se agrega, quita o cambia un muro."""
        muros = [it.muro() for it in self._muros_items.values()]
        self._remiendos = remiendos_esquinas_muros(
            muros, self._canvas.escala_actual(),
        )
        for it in self._muros_items.values():
            it.actualizar_desde_modelo()
        self._bordes_muros.refrescar()

    def _crear_item_muro(self, muro: Muro) -> None:
        it = MuroItem(
            muro,
            escala_getter=self._canvas.escala_actual,
            aberturas_getter=self._aberturas_de_muro,
            remiendos_getter=lambda mid: self._remiendos.get(mid, []),
        )
        it.set_modo_borrar_activo(self._modo_borrar_individual)
        it.set_borde_compartido(True)
        it.clic_recibido.connect(self._on_clic_muro_borrar)
        # Si estamos en Puerta/Ventana, el muro nuevo nace atenuado igual
        # que los demás.
        it.setOpacity(self._bordes_muros.opacity())
        self._canvas.scene().addItem(it)
        self._muros_items[muro.id] = it
        if not self._cargando_plano:
            self._refrescar_uniones()

    def _crear_item_hab(self, hab: Habitacion) -> None:
        it = HabitacionItem(hab, escala_getter=self._canvas.escala_actual)
        it.set_modo_borrar_activo(self._modo_borrar_individual)
        it.clic_recibido.connect(self._on_clic_hab_borrar)
        self._canvas.scene().addItem(it)
        self._habs_items[hab.id] = it

    def _crear_item_puerta(self, puerta: Puerta) -> None:
        it = PuertaItem(
            puerta,
            muro_getter=self._muro_por_id,
            escala_getter=self._canvas.escala_actual,
        )
        it.set_modo_borrar_activo(self._modo_borrar_individual)
        it.clic_recibido.connect(self._on_clic_puerta_borrar)
        self._canvas.scene().addItem(it)
        self._puertas_items[puerta.id] = it

    def _crear_item_ventana(self, ventana: Ventana) -> None:
        it = VentanaItem(
            ventana,
            muro_getter=self._muro_por_id,
            escala_getter=self._canvas.escala_actual,
        )
        it.set_modo_borrar_activo(self._modo_borrar_individual)
        it.clic_recibido.connect(self._on_clic_ventana_borrar)
        self._canvas.scene().addItem(it)
        self._ventanas_items[ventana.id] = it

    def _muro_por_id(self, muro_id: str) -> Optional[Muro]:
        if self._plano_id is None:
            return None
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None:
            return None
        for m in plano.muros:
            if m.id == muro_id:
                return m
        return None

    def _aberturas_de_muro(
        self, muro_id: str,
    ) -> tuple[list[Puerta], list[Ventana]]:
        if self._plano_id is None:
            return [], []
        puertas = self._proyecto.puertas_de_muro(self._plano_id, muro_id)
        ventanas = self._proyecto.ventanas_de_muro(self._plano_id, muro_id)
        return puertas, ventanas

    def _puntos_snap_del_plano(self) -> list[tuple[QPointF, str]]:
        """Recolecta todos los puntos snapables tipados del plano
        activo. Cada punto viene con su categoría:

          * ("endpoint", ...) — vértices geométricamente notables:
              - Muros: vértices del EJE (extremos y quiebres) MÁS las
                esquinas del contorno grueso (donde se cortan las
                caras del muro). Un muro lineal recto aporta 2 vértices
                del eje + 4 esquinas del contorno.
              - Habitaciones: todos los vértices del polígono.

          * ("midpoint", ...) — puntos medios:
              - Muros LINEALES: mitad de cada segmento del eje.
              - Muros ARCO: punto medio geométrico del arco.
              - Habitaciones: mitad de cada lado del polígono cerrado.

        Los duplicados no se filtran — el buscador elige el más cercano
        y no hay diferencia visual. Endpoints y midpoints se
        distinguen en el preview (cuadrado vs. rombo cian).
        """
        if self._plano_id is None:
            return []
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None:
            return []
        escala = self._canvas.escala_actual()
        puntos: list[tuple[QPointF, str]] = []
        for m in plano.muros:
            if not m.vertices:
                continue
            if m.es_arco():
                puntos.append((QPointF(m.vertices[0]), "endpoint"))
                puntos.append((QPointF(m.vertices[2]), "endpoint"))
                pm = _punto_medio_arco_3_puntos(
                    m.vertices[0], m.vertices[1], m.vertices[2],
                )
                if pm is not None:
                    puntos.append((pm, "midpoint"))
            else:
                for v in m.vertices:
                    puntos.append((QPointF(v), "endpoint"))
                for i in range(len(m.vertices) - 1):
                    a, b = m.vertices[i], m.vertices[i + 1]
                    puntos.append((QPointF(
                        (a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0,
                    ), "midpoint"))
                if m.cerrado and len(m.vertices) >= 3:
                    a, b = m.vertices[-1], m.vertices[0]
                    puntos.append((QPointF(
                        (a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0,
                    ), "midpoint"))
            # Esquinas del contorno grueso — snap a las CARAS del muro.
            # Sólo aportan si el muro tiene grosor calibrado.
            for esq in esquinas_contorno_muro(m, escala):
                puntos.append((esq, "endpoint"))
        for h in plano.habitaciones:
            n = len(h.vertices)
            for v in h.vertices:
                puntos.append((QPointF(v), "endpoint"))
            for i in range(n):
                a = h.vertices[i]
                b = h.vertices[(i + 1) % n]
                paso = h.arcos.get(i) if getattr(h, "arcos", None) else None
                if paso is not None:
                    pm = _punto_medio_arco_3_puntos(a, paso, b)
                    if pm is not None:
                        puntos.append((pm, "midpoint"))
                    continue
                puntos.append((QPointF(
                    (a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0,
                ), "midpoint"))
        return puntos

    def _muros_del_plano(self) -> list[Muro]:
        """Lista de muros del plano activo, usada por el snap 'nearest'
        (proyección del cursor al muro más cercano)."""
        if self._plano_id is None:
            return []
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None:
            return []
        return list(plano.muros)

    # Goma: el clic llega DESDE el item que se va a borrar (su
    # mousePressEvent). Si el modelo lo elimina ahí mismo, el item se
    # destruye mientras Qt todavía está entregándole el evento → el
    # programa se cierra (pasaba al borrar un muro con puerta: la cascada
    # hacía más cambios y la memoria liberada se reutilizaba). Por eso el
    # borrado se agenda para justo después de que termine el clic.

    def _borrar_despues(self, borrar, elem_id: str) -> None:
        if not self._modo_borrar_individual or self._plano_id is None:
            return
        plano_id = self._plano_id
        QTimer.singleShot(0, lambda: borrar(plano_id, elem_id))

    def _on_clic_muro_borrar(self, muro_id: str) -> None:
        # En cascada se van también sus puertas y ventanas (ver
        # `ProyectoAbierto.eliminar_muro`).
        self._borrar_despues(self._proyecto.eliminar_muro, muro_id)

    def _on_clic_hab_borrar(self, hab_id: str) -> None:
        self._borrar_despues(self._proyecto.eliminar_habitacion, hab_id)

    def _on_clic_puerta_borrar(self, puerta_id: str) -> None:
        self._borrar_despues(self._proyecto.eliminar_puerta, puerta_id)

    def _on_clic_ventana_borrar(self, ventana_id: str) -> None:
        self._borrar_despues(self._proyecto.eliminar_ventana, ventana_id)

    def _retirar_item(self, it) -> None:
        """Quita un item de la escena sin destruirlo en ese instante: se
        conserva una referencia hasta la siguiente vuelta del ciclo de
        eventos, por si Qt todavía lo está usando (evento en curso,
        hover, repintado)."""
        scene = it.scene()
        if scene is not None:
            scene.removeItem(it)
        self._items_retirados.append(it)
        if len(self._items_retirados) == 1:
            QTimer.singleShot(0, self._items_retirados.clear)

    # ------------------------------------------- callbacks de herramientas

    def _on_primer_vertice(self, punto: QPointF) -> None:
        # El preview ya se refresca vía vertices_cambiados; nada extra
        pass

    def _on_vertices_cambiados(self, vertices) -> None:
        # Herramienta Muro — polilínea abierta (no cierre visual)
        self._preview._cerrado_prov = False  # noqa: SLF001
        self._preview.set_vertices(vertices)

    def _on_vertices_cambiados_hab(self, vertices) -> None:
        # Herramienta Habitación — mostrar cierre potencial
        self._preview._cerrado_prov = True  # noqa: SLF001
        self._preview.set_vertices(vertices)

    def _on_vertices_cambiados_arco(self, vertices) -> None:
        # Herramienta Muro curvo — modo ARCO en el preview
        self._preview._cerrado_prov = False  # noqa: SLF001
        self._preview.set_vertices(vertices)

    def _on_vertices_cambiados_circ(self, vertices) -> None:
        # Herramienta Habitación circular — modo CIRCULO en el preview
        self._preview._cerrado_prov = False  # noqa: SLF001
        self._preview.set_vertices(vertices)

    def _on_cursor_dibujo(self, punto: QPointF) -> None:
        self._preview.set_cursor(punto)

    def _on_muro_terminado(self, vertices) -> None:
        self._pedir_material_y_agregar_muro(
            vertices, tipo_geometria=TipoGeometriaMuro.LINEAL,
        )

    def _on_muro_arco_terminado(self, vertices) -> None:
        # Muro curvo: los 3 vértices son los puntos de control del arco.
        self._pedir_material_y_agregar_muro(
            vertices, tipo_geometria=TipoGeometriaMuro.ARCO,
        )

    def _pedir_material_y_agregar_muro(
        self, vertices, tipo_geometria: TipoGeometriaMuro,
    ) -> None:
        """Flujo compartido entre Muro y Muro curvo: calcula longitud,
        pide material, grosor y cara (recordando los últimos) y
        persiste en el modelo."""
        if self._plano_id is None:
            return
        longitud_m = self._longitud_muro_m(vertices, tipo_geometria)
        es_arco = getattr(tipo_geometria, "name", None) == "ARCO"
        tope = self._detectar_tope(vertices, es_arco)
        dlg = DialogoMaterialMuro(
            parent=self.window(),
            material_sugerido=self._ultimo_material_muro,
            grosor_sugerido_cm=self._ultimo_grosor_cm,
            justificacion_sugerida=self._ultima_justificacion,
            longitud_m=longitud_m,
            escala=self._canvas.escala_actual(),
            tope=tope,
            usar_tope=self._ultimo_uso_tope,
        )
        # Cancelar el diálogo NO cancela el muro; se guarda con el
        # material/grosor/cara anterior (el operador siempre puede
        # editar después).
        if dlg.exec() == QDialog.DialogCode.Accepted:
            material = dlg.material()
            self._ultimo_material_muro = material
            if tope is not None:
                self._ultimo_uso_tope = dlg.usar_tope()
            if tope is not None and dlg.usar_tope():
                # Muro divisorio: el grosor es el hueco entre las dos
                # divisiones; el trazo se mueve lo necesario para que el
                # cuerpo lo llene exacto. No se recuerda como "último
                # grosor" (el siguiente muro normal conserva el suyo).
                grosor_cm = tope["grosor_cm"]
                justificacion = tope["justificacion"]
                vertices = desplazar_trazo_muro(
                    vertices, es_arco, tope["desplazamiento_pt"],
                )
            else:
                grosor_cm = dlg.grosor_cm()
                justificacion = dlg.justificacion()
                self._ultimo_grosor_cm = grosor_cm
                self._ultima_justificacion = justificacion
        else:
            material = self._ultimo_material_muro
            grosor_cm = self._ultimo_grosor_cm
            justificacion = self._ultima_justificacion
        # Auto-extend: con el grosor y la cara definitivos, prolongar los
        # extremos que quedaron cerca de otro muro para cerrar el hueco.
        extensiones = self._calcular_extensiones(self._muro_temporal(
            vertices, tipo_geometria, grosor_cm, justificacion, material,
        ))
        vertices = aplicar_extensiones_muro(vertices, extensiones)
        self._proyecto.agregar_muro(
            self._plano_id, vertices, cerrado=False, material=material,
            tipo_geometria=tipo_geometria, grosor_cm=grosor_cm,
            justificacion=justificacion,
        )
        self._preview.limpiar()
        if extensiones:
            partes = [
                f"{e['muro_id']} (se alargó {self._texto_distancia(e['dist_pt'])})"
                for e in extensiones
            ]
            texto = "Muro unido a " + " y a ".join(partes) + "."
            # La herramienta escribe su mensaje inicial justo después de
            # emitir `dibujo_terminado`; diferimos el nuestro para que
            # no se pierda.
            QTimer.singleShot(0, lambda t=texto: self._lbl_msg.setText(t))

    # ------------------------------------------- muro divisorio (topar)

    def _detectar_tope(self, vertices, es_arco: bool) -> Optional[dict]:
        """Hueco entre las dos divisiones (habitaciones o muros) a los
        lados del trazo, para la opción "Topar con la siguiente división"
        del diálogo. None si no hay división de los dos lados (a menos de
        1 m) o si el plano no está calibrado.

        Devuelve {"grosor_cm", "justificacion", "desplazamiento_pt",
        "centrado", "descripcion", "variacion_cm"}."""
        escala = self._canvas.escala_actual()
        if self._plano_id is None or escala is None or not escala.m_por_pt:
            return None
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None:
            return None
        nombres: dict[str, str] = {}
        obstaculos = []
        for h in plano.habitaciones:
            pts = h.poligono()
            if len(pts) < 3:
                continue
            path = QPainterPath()
            path.addPolygon(QPolygonF(pts))
            path.closeSubpath()
            obstaculos.append((h.id, path))
            nombres[h.id] = h.nombre or h.id
        for m in plano.muros:
            if len(m.vertices) < 2:
                continue
            obstaculos.append(
                (m.id, _contorno_muro_con_grosor(m, m.grosor_pt(escala))),
            )
            nombres[m.id] = m.id
        if not obstaculos:
            return None
        try:
            zoom = self._canvas.zoom_actual() or 1.0
        except Exception:  # noqa: BLE001
            zoom = 1.0
        pt_por_m = 1.0 / escala.m_por_pt
        # Holgura para "trazaste sobre la orilla": ~6 px o 2 cm.
        tol = max(6.0 / zoom, 0.02 * pt_por_m)
        r = detectar_hueco_divisorio(
            vertices, es_arco, obstaculos, 1.0 * pt_por_m, tol,
        )
        if r is None:
            return None
        t1, t2 = r["t1"], r["t2"]
        grosor_pt = t2 - t1
        if grosor_pt <= 0.01 * pt_por_m:       # menos de 1 cm: no es hueco
            return None
        # ¿Trazaste sobre la orilla de una división? El grosor crece desde
        # tu trazo hacia la otra (cara izquierda/derecha). Si trazaste por
        # en medio, el muro se centra en el hueco.
        if abs(t1) <= tol:
            just, desp, centrado = JustificacionMuro.DERECHA, t1, False
        elif abs(t2) <= tol:
            just, desp, centrado = JustificacionMuro.IZQUIERDA, t2, False
        else:
            just, desp, centrado = JustificacionMuro.CENTRO, (t1 + t2) / 2.0, True
        cm = lambda pt: pt * escala.m_por_pt * 100.0  # noqa: E731
        id1, id2 = r["ids"]
        descripcion = f"entre {nombres.get(id1, id1)} y {nombres.get(id2, id2)}"
        if cm(r["max"] - r["min"]) >= 1.0:
            descripcion += (
                f"; varía de {cm(r['min']):.0f} a {cm(r['max']):.0f} cm "
                "a lo largo del trazo"
            )
        return {
            "grosor_cm": cm(grosor_pt),
            "justificacion": just,
            "desplazamiento_pt": desp,
            "centrado": centrado,
            "descripcion": descripcion,
            "variacion_cm": (cm(r["min"]), cm(r["max"])),
        }

    # ------------------------------------------------ auto-extend (muros)

    def _umbral_extension_pt(self, grosor_pt: float = 0.0) -> float:
        """Distancia máxima que el auto-extend puede prolongar un
        extremo: ~30 px en pantalla o 1.5 veces el grosor del muro (lo
        que sea mayor — con mucho zoom, 30 px es muy poco), sin pasar de
        60 cm reales cuando hay escala (evita saltos grandes con mucho
        zoom out)."""
        try:
            zoom = self._canvas.zoom_actual()
        except Exception:  # noqa: BLE001
            zoom = 1.0
        umbral = max(
            30.0 / (zoom if zoom and zoom > 0 else 1.0), 1.5 * grosor_pt,
        )
        escala = self._canvas.escala_actual()
        if escala is not None and escala.m_por_pt:
            umbral = min(umbral, 0.60 / escala.m_por_pt)
        return umbral

    def _muro_temporal(
        self, vertices, tipo_geometria, grosor_cm, justificacion, material,
    ) -> Muro:
        """Muro en memoria (no persistido) para calcular geometría del
        muro que se está dibujando."""
        return Muro(
            id="__nuevo__", vertices=[QPointF(v) for v in vertices],
            material=material, tipo_geometria=tipo_geometria,
            grosor_cm=grosor_cm, justificacion=justificacion,
        )

    def _calcular_extensiones(self, muro_tmp: Muro) -> list[dict]:
        if self._plano_id is None:
            return []
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None or not plano.muros:
            return []
        # Extremos enganchados a propósito con el snap (vértices y
        # esquinas de otros muros/habitaciones) no se tocan.
        fijos = [
            p for p, tipo in self._puntos_snap_del_plano()
            if tipo == "endpoint"
        ]
        escala = self._canvas.escala_actual()
        return calcular_extensiones_muro(
            muro_tmp, list(plano.muros), escala,
            self._umbral_extension_pt(muro_tmp.grosor_pt(escala)), fijos,
        )

    def _preview_extension(self, h, cursor: QPointF) -> list:
        """Para el puente: prolongaciones que haría el auto-extend si
        el muro en curso terminara con el cursor en su posición actual.
        Usa el último grosor/cara/material (los que el diálogo va a
        proponer)."""
        if isinstance(h, HerramientaMuroArco):
            vs = h.vertices()
            if len(vs) != 2:
                return []
            puntos, tipo = vs + [cursor], TipoGeometriaMuro.ARCO
        elif isinstance(h, HerramientaMuro):
            vs = h.vertices()
            if not vs:
                return []
            puntos, tipo = vs + [cursor], TipoGeometriaMuro.LINEAL
        else:
            return []
        tmp = self._muro_temporal(
            puntos, tipo, self._ultimo_grosor_cm,
            self._ultima_justificacion, self._ultimo_material_muro,
        )
        extensiones = self._calcular_extensiones(tmp)
        # Aviso en la barra de estado mientras el cursor esté en la zona
        # de auto-extend (el tramo cian puede ser corto a mucho zoom).
        if extensiones:
            partes = [
                f"{e['muro_id']} (+{self._texto_distancia(e['dist_pt'])})"
                for e in extensiones
            ]
            self._aviso_extension = (
                "Al terminar, el muro se alargará hasta " + " y ".join(partes)
                + " para quedar unido."
            )
            self._lbl_msg.setText(self._aviso_extension)
        elif self._aviso_extension is not None:
            if self._lbl_msg.text() == self._aviso_extension:
                self._lbl_msg.setText(self._ultimo_msg_herramienta)
            self._aviso_extension = None
        return [(e["desde"], e["hasta"]) for e in extensiones]

    def _texto_distancia(self, dist_pt: float) -> str:
        escala = self._canvas.escala_actual()
        if escala is not None and escala.m_por_pt:
            return f"{dist_pt * escala.m_por_pt * 100.0:.0f} cm"
        return f"{dist_pt:.1f} pt"

    def _on_hab_terminada(self, vertices) -> None:
        self._pedir_nombre_y_agregar_hab(vertices, self._h_hab.ultimos_arcos())

    def _on_trazo_hab(self, datos) -> None:
        """Tramos en arco del trazo de habitación → preview."""
        self._preview.set_trazo_arcos(datos.get("arcos", {}), datos.get("paso"))

    def _on_hab_circular_terminada(self, vertices) -> None:
        # Hab. circular ya llega tesela como polígono de N vértices.
        self._pedir_nombre_y_agregar_hab(vertices)

    def _pedir_nombre_y_agregar_hab(self, vertices, arcos=None) -> None:
        if self._plano_id is None:
            return
        # Área provisional para mostrar en el diálogo (con sus curvas)
        hab_prov = Habitacion(
            id="temp", nombre="temp", vertices=vertices, arcos=dict(arcos or {}),
        )
        area_m2 = hab_prov.area_m2(self._canvas.escala_actual())
        dlg = DialogoNombreHabitacion(
            area_m2, parent=self.window(),
            tipo_sugerido=self._ultimo_tipo_hab,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._preview.limpiar()
            return
        nombre = dlg.nombre()
        tipo = dlg.tipo_uso()
        if not nombre:
            self._preview.limpiar()
            return
        self._ultimo_tipo_hab = tipo
        self._proyecto.agregar_habitacion(
            self._plano_id, nombre, vertices, tipo_uso=tipo, arcos=arcos,
        )
        self._preview.limpiar()

    def _longitud_muro_m(
        self, vertices, tipo_geometria: TipoGeometriaMuro,
    ) -> Optional[float]:
        """Longitud del muro en metros (usa la escala del canvas).
        Discrimina por tipo de geometría: LINEAL suma segmentos,
        ARCO calcula longitud del arco por 3 puntos. None si no hay
        escala."""
        escala = self._canvas.escala_actual()
        if escala is None or len(vertices) < 2:
            return None
        if tipo_geometria == TipoGeometriaMuro.ARCO and len(vertices) == 3:
            largo_pt = _longitud_arco_3_puntos(
                vertices[0], vertices[1], vertices[2],
            )
        else:
            largo_pt = 0.0
            for i in range(len(vertices) - 1):
                dx = vertices[i + 1].x() - vertices[i].x()
                dy = vertices[i + 1].y() - vertices[i].y()
                largo_pt += math.hypot(dx, dy)
        return largo_pt * escala.m_por_pt

    def _on_dibujo_cancelado(self) -> None:
        self._preview.limpiar()

    def _on_mensaje(self, msg: str) -> None:
        self._ultimo_msg_herramienta = msg
        self._lbl_msg.setText(msg)

    # --------------------------------------------- callbacks canvas base

    def _on_zoom(self, f: float) -> None:
        self._lbl_zoom.setText(f"zoom: {f * 100:.0f}%")

    def _on_cursor_pt(self, p: QPointF) -> None:
        if self._canvas.escala_actual() is None:
            self._lbl_cursor.setText(f"cursor: {p.x():.0f}, {p.y():.0f} pt")

    def _on_cursor_m(self, p: QPointF) -> None:
        self._lbl_cursor.setText(f"cursor: {p.x():.3f}, {p.y():.3f} m")

    def _on_herramienta_canvas(self, h: Herramienta) -> None:
        # Si el canvas cambia a SELECCIONAR/PAN por su cuenta,
        # desactivamos las de dibujo.
        if h in (Herramienta.SELECCIONAR, Herramienta.PAN):
            if self._h_muro.esta_activa() or self._h_hab.esta_activa():
                self._desactivar_herramientas_dibujo()
            if h == Herramienta.SELECCIONAR:
                self._marcar_boton_tools(self._btn_sel)
            else:
                self._marcar_boton_tools(self._btn_pan)

    # ------------------------------------------------------ Lista habs UI

    def _refrescar_lista_habs(self) -> None:
        # Vaciar cards actuales
        while self._layout_cards.count() > 1:  # dejar el stretch final
            item = self._layout_cards.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

        plano = None
        if self._plano_id is not None:
            plano = self._proyecto.plano_por_id(self._plano_id)

        if plano is None or not plano.habitaciones:
            self._lbl_vacio.setVisible(True)
            return
        self._lbl_vacio.setVisible(False)

        escala = plano.escala
        for hab in plano.habitaciones:
            card = CardHabitacion(hab, escala)
            card.renombrar_solicitado.connect(self._renombrar_hab)
            card.eliminar_solicitado.connect(self._eliminar_hab_desde_lista)
            self._layout_cards.insertWidget(
                self._layout_cards.count() - 1, card
            )

    def _actualizar_contadores(self) -> None:
        plano = None
        if self._plano_id is not None:
            plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None:
            self._lbl_contadores.setText(
                "0 muros · 0 habitaciones · 0 aberturas"
            )
            return
        nm = len(plano.muros)
        nh = len(plano.habitaciones)
        nab = len(plano.puertas) + len(plano.ventanas)
        self._lbl_contadores.setText(
            f"{nm} muro{'s' if nm != 1 else ''} · "
            f"{nh} habitaci{'ones' if nh != 1 else 'ón'} · "
            f"{nab} abertura{'s' if nab != 1 else ''}"
        )

    def _renombrar_hab(self, hab_id: str) -> None:
        if self._plano_id is None:
            return
        plano = self._proyecto.plano_por_id(self._plano_id)
        if plano is None:
            return
        hab = next((h for h in plano.habitaciones if h.id == hab_id), None)
        if hab is None:
            return
        nuevo, ok = QInputDialog.getText(
            self, "Renombrar habitación",
            f"Nuevo nombre para '{hab.nombre}':",
            text=hab.nombre,
        )
        if ok and nuevo.strip():
            self._proyecto.renombrar_habitacion(
                self._plano_id, hab_id, nuevo.strip()
            )

    def _eliminar_hab_desde_lista(self, hab_id: str) -> None:
        if self._plano_id is None:
            return
        resp = QMessageBox.question(
            self, "Eliminar habitación",
            "¿Eliminar esta habitación del plano?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self._proyecto.eliminar_habitacion(self._plano_id, hab_id)


# ---------------------------------------------------------------------------
# Ejecución independiente (desarrollo)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    proy = ProyectoAbierto({
        "id": "PRJ-DEMO", "nombre": "Demo",
        "cliente": "Demo", "tipo": "edificio",
        "subtipo": "Demo", "estado": "borrador",
    })
    main = QMainWindow()
    main.setWindowTitle("PaginaDelimitacion — Demo")
    main.resize(1400, 820)
    main.setStyleSheet(f"QMainWindow {{ background: {COLOR_FONDO}; }}")
    main.setCentralWidget(PaginaDelimitacion(proy))
    main.show()
    sys.exit(app.exec())
