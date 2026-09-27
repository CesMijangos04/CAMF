"""
canvas_plano.py — Motor del canvas del módulo Proyectos de CAMF.

Sesión A + B del canvas (v8):

Sesión A (motor base):
  * Carga de plano (PDF con pymupdf, o imagen PNG/JPG).
  * Render UNA vez a factor alto (máx 8x, tope 60 MP RAM).
  * Zoom con rueda instantáneo, pan con botón central o herramienta Pan.
  * Sistema de capas.

Sesión B (calibración + medición + barra de escala):
  * Calibración de escala por 2 clicks + diálogo (Herramienta implícita
    accesible por botón "Calibrar" del ribbon).
  * Herramienta MEDIR: mide distancias en metros haciendo 2 clicks.
    Cada medición se dibuja de forma persistente sobre el plano. Sirve
    para validar la calibración contra las acotaciones del arquitecto.
  * Barra de escala visual en la esquina inferior izquierda del canvas
    (estilo Google Maps) — muestra permanentemente cuánto es 1 m / 5 m
    / 10 m según el zoom actual. Solo visible con escala calibrada.
  * Botón "Borrar" para limpiar todas las mediciones de una vez.

Coordenadas de escena: puntos del PDF nativo (72 DPI). La escala
calibrada convierte a metros para los cálculos y reportes eléctricos.

TODO (Etapa Documentación):
  Export a PDF vectorial usando el PDF original como base + los
  elementos dibujados como trazos vectoriales (ver docstring completo
  en versiones anteriores).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from enum import Enum
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, pyqtSignal
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QBrush, QMouseEvent, QWheelEvent,
    QKeyEvent, QPen, QFont, QFontMetricsF,
)
# QKeyEvent Type y modifiers ya vienen de arriba; usados en
# mouseDoubleClickEvent para simular Enter a la herramienta externa.
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsItemGroup, QFileDialog, QMessageBox, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QMainWindow, QFrame, QToolButton, QMenu,
)

try:
    import fitz
    _PYMUPDF_OK = True
except Exception:  # noqa: BLE001
    _PYMUPDF_OK = False

try:
    import qtawesome as qta
    _QTA_OK = True
except Exception:  # noqa: BLE001
    _QTA_OK = False

from escala_calibrador import (
    CalibradorEscala, DialogoDistanciaReal, EscalaCalibrada,
    GuiaCalibracion, MedidorDistancia, MedicionCalibrada, MedicionItem,
    PuntoDeCalibracion,
)


# ---------------------------------------------------------------------------
# Paleta CAMF
# ---------------------------------------------------------------------------

COLOR_FONDO         = "#121212"
COLOR_HEADER        = "#141414"
COLOR_SIDEBAR       = "#1a1a1a"
COLOR_SUPERFICIE    = "#1e1e1e"
COLOR_INPUT_BG      = "#2b2b2b"
COLOR_BORDE         = "#333"
COLOR_BORDE_FUERTE  = "#444"
COLOR_ACENTO        = "#0078d7"
COLOR_ACENTO_BRILL  = "#0094ff"
COLOR_ACENTO_HOVER  = "#005a9e"
COLOR_TEXTO         = "#fff"
COLOR_TEXTO_SUAVE   = "#ddd"
COLOR_TEXTO_MUTED   = "#aaa"
COLOR_TEXTO_APAGADO = "#666"

COLOR_CANVAS_VACIO       = "#0f0f0f"
COLOR_BARRA_ESCALA_BG    = "#1e1e1e"
COLOR_BARRA_ESCALA_BORDE = "#444"
COLOR_BARRA_ESCALA_TEXTO = "#eeeeee"


# ---------------------------------------------------------------------------
# Enums públicos
# ---------------------------------------------------------------------------

class Herramienta(Enum):
    SELECCIONAR = "seleccionar"
    PAN         = "pan"
    MEDIR       = "medir"
    DIBUJAR     = "dibujar"
    COLOCAR     = "colocar"


class Capa(Enum):
    PLANO_BASE     = "plano_base"
    DELIMITACION   = "delimitacion"
    ELEMENTOS      = "elementos"
    TABLEROS       = "tableros"
    CANALIZACIONES = "canalizaciones"


_Z_ORDER = {
    Capa.PLANO_BASE:     -100,
    Capa.DELIMITACION:      0,
    Capa.CANALIZACIONES:   10,
    Capa.TABLEROS:         20,
    Capa.ELEMENTOS:        30,
}


# ---------------------------------------------------------------------------
# Render del PDF
# ---------------------------------------------------------------------------

_FACTOR_RENDER_PDF_MAX = 8
_LIMITE_PIXELES_PIXMAP = 60_000_000


def _factor_render_para_pdf(page_rect: QRectF) -> int:
    area_puntos = page_rect.width() * page_rect.height()
    if area_puntos <= 0:
        return _FACTOR_RENDER_PDF_MAX
    factor_por_ram = math.sqrt(_LIMITE_PIXELES_PIXMAP / area_puntos)
    factor = min(float(_FACTOR_RENDER_PDF_MAX), factor_por_ram)
    return max(2, int(math.floor(factor)))


# ---------------------------------------------------------------------------
# Barra de escala visual — helpers
# ---------------------------------------------------------------------------

# Longitudes "redondas" preferidas para la barra de escala, en metros.
# Se elige la mayor que produzca una barra entre PX_MIN y PX_MAX de ancho.
_LONGITUDES_BARRA_M = [
    0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200,
    500, 1000, 2000, 5000, 10000,
]
_BARRA_PX_MIN = 70.0
_BARRA_PX_MAX = 180.0


def _formato_metros_barra(m: float) -> str:
    if m < 0.01:
        return f"{m * 1000:.0f} mm"
    if m < 1.0:
        return f"{m * 100:.0f} cm"
    if m == int(m):
        return f"{int(m)} m"
    return f"{m:.1f} m"


# ---------------------------------------------------------------------------
# Canvas principal
# ---------------------------------------------------------------------------

class CanvasPlano(QGraphicsView):
    """Motor de canvas 2D del módulo Proyectos.

    Coords de escena en puntos del PDF nativo (72 DPI). La escala
    calibrada convierte a metros; la herramienta MEDIR permite validar
    esa calibración contra las acotaciones existentes del plano.
    """

    plano_cargado           = pyqtSignal(str)
    plano_descargado        = pyqtSignal()
    zoom_cambiado           = pyqtSignal(float)
    herramienta_cambiada    = pyqtSignal(object)
    posicion_cursor         = pyqtSignal(QPointF)
    error_carga             = pyqtSignal(str)
    render_actualizado      = pyqtSignal(float)
    escala_cambiada         = pyqtSignal(object)
    posicion_cursor_metros  = pyqtSignal(QPointF)
    medicion_agregada       = pyqtSignal(object)   # MedicionCalibrada
    mediciones_borradas     = pyqtSignal()
    # Emitida al entrar (True) o salir (False) del modo "borrar uno
    # por uno". El UI la usa para resaltar/apagar el botón de Borrar
    # y para limpiar el mensaje del status bar.
    modo_borrar_individual_cambiado = pyqtSignal(bool)

    ZOOM_MIN = 0.05
    ZOOM_MAX = 40.0
    ZOOM_STEP = 1.15

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(QColor(COLOR_CANVAS_VACIO)))
        self.setScene(self._scene)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            f"QGraphicsView {{ background-color: {COLOR_CANVAS_VACIO}; "
            f"border: 1px solid {COLOR_BORDE}; outline: none; }}"
        )

        # Estado interno base
        self._herramienta: Herramienta = Herramienta.SELECCIONAR
        self._zoom_factor: float = 1.0
        self._plano_path: Optional[Path] = None
        self._plano_item: Optional[QGraphicsPixmapItem] = None
        self._panning_middle: bool = False
        self._pan_last_pos: Optional[QPointF] = None

        # Render del PDF
        self._es_pdf: bool = False
        self._pdf_page_rect: Optional[QRectF] = None
        self._pdf_factor_actual: float = 1.0

        # Calibración de escala
        self._escala: Optional[EscalaCalibrada] = None
        self._calibrador = CalibradorEscala(self)
        self._guia_calibracion = GuiaCalibracion()
        self._guia_calibracion.setVisible(False)
        self._scene.addItem(self._guia_calibracion)

        self._calibrador.primer_punto_cambiado.connect(
            self._on_primer_punto_calibracion
        )
        self._calibrador.listo_para_distancia.connect(
            self._on_listo_para_distancia
        )
        self._calibrador.calibracion_completada.connect(
            self._on_calibracion_completada
        )
        self._calibrador.calibracion_cancelada.connect(
            self._on_calibracion_cancelada
        )

        # Medición (herramienta MEDIR)
        self._medidor = MedidorDistancia(
            escala_getter=lambda: self._escala,
            parent=self,
        )
        self._guia_medicion = GuiaCalibracion()
        self._guia_medicion.setVisible(False)
        self._scene.addItem(self._guia_medicion)
        self._mediciones_items: list[MedicionItem] = []

        # Modo "borrar una por una" — cuando activo, los MedicionItem
        # aceptan hover (se ponen rojos) y el clic izquierdo del canvas
        # elimina el item bajo el cursor.
        self._modo_borrar_individual: bool = False

        # Modo "refinar calibración" — cuando activo, la próxima
        # calibración completada NO reemplaza la escala vigente sino
        # que se SUMA como punto adicional, y la escala se recalcula
        # por mínimos cuadrados sobre todos los puntos. (Feature
        # interna, no expuesta en el ribbon actual).
        self._modo_refinar_calibracion: bool = False

        # Herramienta externa registrable — patrón usado por Sesión D+
        # (delimitación, elementos, tableros) para insertar
        # herramientas custom sin modificar el canvas cada vez. El
        # objeto handler expone: esta_activa(), on_click(pt, shift),
        # on_move(pt, shift), on_key(key) → bool. Cuando está activa,
        # intercepta todos los clicks izquierdos y moves del canvas.
        self._herramienta_externa = None

        self._medidor.primer_punto_registrado.connect(
            self._on_primer_punto_medicion
        )
        self._medidor.medicion_completada.connect(
            self._on_medicion_completada
        )
        self._medidor.medicion_cancelada.connect(
            self._on_medicion_cancelada
        )

        # Capas
        self._capas: dict[Capa, QGraphicsItemGroup] = {}
        for capa in Capa:
            grupo = QGraphicsItemGroup()
            grupo.setZValue(_Z_ORDER.get(capa, 0))
            self._scene.addItem(grupo)
            self._capas[capa] = grupo

        self._actualizar_cursor()

    # ---------------------------------------------------------------- carga

    def cargar_plano(self, path: str | Path) -> bool:
        p = Path(path)
        if not p.exists():
            self.error_carga.emit(f"El archivo no existe:\n{p}")
            return False

        ext = p.suffix.lower()
        try:
            if ext == ".pdf":
                page_rect, pixmap, factor = self._cargar_pdf(p)
                es_pdf = True
            elif ext in {".png", ".jpg", ".jpeg", ".bmp"}:
                pixmap = QPixmap(str(p))
                if pixmap.isNull():
                    raise RuntimeError(
                        "La imagen no se pudo abrir o está corrupta."
                    )
                page_rect = QRectF(0, 0, pixmap.width(), pixmap.height())
                factor = 1.0
                es_pdf = False
            else:
                raise RuntimeError(
                    f"Formato no soportado: {ext}. "
                    "Formatos válidos: PDF, PNG, JPG."
                )
        except Exception as exc:  # noqa: BLE001
            self.error_carga.emit(str(exc))
            return False

        self._limpiar_plano_actual()

        item = QGraphicsPixmapItem(pixmap)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setScale(1.0 / factor)
        self._capas[Capa.PLANO_BASE].addToGroup(item)

        self._plano_item = item
        self._plano_path = p
        self._es_pdf = es_pdf
        self._pdf_page_rect = page_rect
        self._pdf_factor_actual = float(factor)

        self._guia_calibracion.set_page_rect(page_rect)
        self._guia_medicion.set_page_rect(page_rect)

        margen = max(page_rect.width(), page_rect.height()) * 0.05
        self._scene.setSceneRect(
            page_rect.adjusted(-margen, -margen, margen, margen)
        )

        self.encajar_plano_en_vista()

        self.plano_cargado.emit(str(p))
        self.render_actualizado.emit(self._pdf_factor_actual)
        self.escala_cambiada.emit(None)
        return True

    def descargar_plano(self) -> None:
        self._limpiar_plano_actual()
        self._scene.setSceneRect(QRectF())
        self._zoom_factor = 1.0
        self.resetTransform()
        self.zoom_cambiado.emit(self._zoom_factor)
        self.plano_descargado.emit()
        self.escala_cambiada.emit(None)

    def _limpiar_plano_actual(self) -> None:
        if self._calibrador.esta_activo():
            self._calibrador.cancelar()
        if self._medidor.esta_activo():
            self._medidor.desactivar()
        if self._modo_borrar_individual:
            self.salir_modo_borrar_individual()

        # Borrar mediciones antes de destruir el plano
        for item in self._mediciones_items:
            self._scene.removeItem(item)
        self._mediciones_items.clear()

        if self._plano_item is not None:
            self._capas[Capa.PLANO_BASE].removeFromGroup(self._plano_item)
            self._scene.removeItem(self._plano_item)
            self._plano_item = None
        self._plano_path = None
        self._es_pdf = False
        self._pdf_page_rect = None
        self._pdf_factor_actual = 1.0
        self._escala = None
        self._guia_calibracion.limpiar()
        self._guia_calibracion.setVisible(False)
        self._guia_medicion.limpiar()
        self._guia_medicion.setVisible(False)

    def _cargar_pdf(self, path: Path) -> tuple[QRectF, QPixmap, int]:
        if not _PYMUPDF_OK:
            raise RuntimeError(
                "pymupdf no está instalado. Ejecuta: pip install pymupdf"
            )
        doc = fitz.open(str(path))
        try:
            if doc.page_count == 0:
                raise RuntimeError("El PDF no contiene páginas.")
            page = doc.load_page(0)
            page_rect_fitz = page.rect
            page_rect = QRectF(
                0.0, 0.0,
                float(page_rect_fitz.width),
                float(page_rect_fitz.height),
            )
            factor = _factor_render_para_pdf(page_rect)
            matriz = fitz.Matrix(factor, factor)
            pix = page.get_pixmap(matrix=matriz, alpha=False)
            image = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format.Format_RGB888,
            ).copy()
            pixmap = QPixmap.fromImage(image)
            return page_rect, pixmap, factor
        finally:
            doc.close()

    def plano_path(self) -> Optional[Path]:
        return self._plano_path

    def factor_render_actual(self) -> float:
        return self._pdf_factor_actual if self._es_pdf else 1.0

    def es_pdf(self) -> bool:
        return self._es_pdf

    # --------------------------------------------- Sesión B: calibración

    def calibrador(self) -> CalibradorEscala:
        return self._calibrador

    def escala_actual(self) -> Optional[EscalaCalibrada]:
        return self._escala

    # Cantidad de puntos que se piden en una calibración desde cero.
    # 3 es el mínimo recomendado para bajar el error por mínimos
    # cuadrados; el operador siempre hace el mismo flujo consistente.
    NUM_PUNTOS_CALIBRACION = 3

    def iniciar_calibracion(self) -> bool:
        """Arranca una calibración DESDE CERO con NUM_PUNTOS_CALIBRACION
        puntos de referencia. El calibrador va pidiendo cada par de
        clics + distancia real secuencialmente. Al terminar, la escala
        se calcula por mínimos cuadrados y reemplaza cualquier escala
        previa.
        """
        if self._plano_item is None:
            return False
        if self._medidor.esta_activo():
            self._medidor.desactivar()
        self._modo_refinar_calibracion = False
        self._guia_calibracion.limpiar()
        self._guia_calibracion.setVisible(True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self._calibrador.iniciar(num_puntos=self.NUM_PUNTOS_CALIBRACION)
        return True

    def iniciar_refinamiento_calibracion(self) -> bool:
        """Arranca una calibración que SUMA un punto adicional a la
        escala vigente (en vez de reemplazarla). La escala resultante
        se recalcula por mínimos cuadrados sobre todos los puntos.

        Requiere una escala vigente (al menos 1 punto de calibración).
        Devuelve False si no hay plano cargado o si no hay escala
        previa que refinar.
        """
        if self._plano_item is None or self._escala is None:
            return False
        if self._medidor.esta_activo():
            self._medidor.desactivar()
        self._modo_refinar_calibracion = True
        self._guia_calibracion.limpiar()
        self._guia_calibracion.setVisible(True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self._calibrador.iniciar()
        return True

    def cancelar_calibracion(self) -> None:
        if self._calibrador.esta_activo():
            self._calibrador.cancelar()

    def set_escala(self, escala: Optional[EscalaCalibrada]) -> None:
        self._escala = escala
        self.escala_cambiada.emit(escala)
        # Repintar el viewport para actualizar la barra de escala.
        self.viewport().update()

    def _on_primer_punto_calibracion(self, punto_pdf: QPointF) -> None:
        self._guia_calibracion.set_punto_a(punto_pdf)

    def _on_listo_para_distancia(
        self,
        a: QPointF,
        b: QPointF,
        dist_pt: float,
        indice: int,
        total: int,
    ) -> None:
        # Congelar la guía en el estado final (línea completa a→b)
        self._guia_calibracion.set_punto_a(a)
        self._guia_calibracion.set_cursor(b)

        # La escala PARCIAL (con los puntos ya capturados en esta
        # sesión) es lo más útil para el operador — le dice si su
        # próxima medida es consistente con lo que ya lleva. Solo
        # existe a partir del punto 2.
        escala_parcial = self._calibrador.escala_parcial()

        # Valor sugerido: prioriza la escala parcial, luego la escala
        # vigente del plano, y por default 1.0.
        if escala_parcial is not None:
            valor_sugerido = float(escala_parcial.pt_a_m(dist_pt))
        elif self._escala is not None:
            valor_sugerido = float(self._escala.pt_a_m(dist_pt))
        else:
            valor_sugerido = 1.0

        dlg = DialogoDistanciaReal(
            distancia_pdf_pt=dist_pt,
            parent=self.window(),
            valor_sugerido_m=valor_sugerido,
            escala_previa=self._escala,
            indice_punto=indice,
            total_puntos=total,
            escala_parcial=escala_parcial,
        )
        if dlg.exec():
            self._calibrador.confirmar_distancia_real(dlg.distancia_metros())
        else:
            self._calibrador.cancelar()

    def _on_calibracion_completada(self, escala: EscalaCalibrada) -> None:
        # Si estamos en modo REFINAR, en vez de reemplazar tomamos el
        # nuevo punto y lo sumamos a la escala vigente.
        if self._modo_refinar_calibracion and self._escala is not None:
            nuevo_punto = escala.puntos[0]
            escala = self._escala.con_punto_adicional(nuevo_punto)
        self._modo_refinar_calibracion = False

        self._escala = escala
        self._guia_calibracion.limpiar()
        self._guia_calibracion.setVisible(False)
        self._reaplicar_herramienta_actual()
        self.escala_cambiada.emit(escala)
        self.viewport().update()  # actualizar barra de escala

    def _on_calibracion_cancelada(self) -> None:
        self._modo_refinar_calibracion = False
        self._guia_calibracion.limpiar()
        self._guia_calibracion.setVisible(False)
        self._reaplicar_herramienta_actual()

    def _reaplicar_herramienta_actual(self) -> None:
        h = self._herramienta
        if h == Herramienta.PAN:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        elif h == Herramienta.SELECCIONAR:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._actualizar_cursor()

    # --------------------------------------------- Sesión B: medición

    def medidor(self) -> MedidorDistancia:
        return self._medidor

    def mediciones(self) -> list[MedicionCalibrada]:
        return [item.medicion() for item in self._mediciones_items]

    def borrar_mediciones(self) -> None:
        if self._modo_borrar_individual:
            self.salir_modo_borrar_individual()
        for item in self._mediciones_items:
            self._scene.removeItem(item)
        self._mediciones_items.clear()
        self.mediciones_borradas.emit()

    def modo_borrar_individual_activo(self) -> bool:
        return self._modo_borrar_individual

    def iniciar_modo_borrar_individual(self) -> bool:
        """Entra al modo "clic para borrar una medición". Las
        mediciones se ponen interactivas y muestran color rojo al
        pasar el mouse encima. El siguiente clic izquierdo elimina el
        item bajo el cursor. Escape sale del modo.
        """
        if not self._mediciones_items:
            return False
        # Salir de otros modos activos
        if self._calibrador.esta_activo():
            self._calibrador.cancelar()
        if self._medidor.esta_activo():
            self._medidor.desactivar()
            # Restablecer herramienta a SELECCIONAR para consistencia
            self._herramienta = Herramienta.SELECCIONAR
            self.herramienta_cambiada.emit(self._herramienta)

        self._modo_borrar_individual = True
        for item in self._mediciones_items:
            item.set_modo_borrar_activo(True)
        # Cursor "eliminar"
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.modo_borrar_individual_cambiado.emit(True)
        return True

    def salir_modo_borrar_individual(self) -> None:
        if not self._modo_borrar_individual:
            return
        self._modo_borrar_individual = False
        for item in self._mediciones_items:
            item.set_modo_borrar_activo(False)
        self._actualizar_cursor()
        self.modo_borrar_individual_cambiado.emit(False)

    def _eliminar_medicion_bajo_cursor(self, view_pos) -> bool:
        """Busca la medición bajo la posición del viewport y la borra.
        Devuelve True si borró algo, False si no había ninguna."""
        for item in self.items(view_pos):
            if isinstance(item, MedicionItem):
                self._scene.removeItem(item)
                if item in self._mediciones_items:
                    self._mediciones_items.remove(item)
                # Si ya no quedan mediciones, salir del modo automáticamente
                if not self._mediciones_items:
                    self.salir_modo_borrar_individual()
                return True
        return False

    # -------------------------------------------- herramientas externas

    def set_herramienta_externa(self, handler) -> None:
        """Registra una herramienta externa que interceptará clicks y
        moves del canvas. El handler debe implementar:
          * esta_activa() -> bool
          * on_click(punto_pdf: QPointF, shift: bool) -> bool  (True = manejado)
          * on_move(punto_pdf: QPointF, shift: bool) -> None
          * on_key(event) -> bool  (True = manejado)
        Pasa None para desregistrar.
        """
        self._herramienta_externa = handler
        # Cambiar cursor a cruz cuando hay externa activa
        if handler is not None and hasattr(handler, "esta_activa"):
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def herramienta_externa(self):
        return self._herramienta_externa

    # Snap ortogonal para la herramienta MEDIR con Shift presionado
    @staticmethod
    def _snap_ortogonal(punto_a: QPointF, punto: QPointF) -> QPointF:
        """Ajusta `punto` para que la línea desde `punto_a` sea
        exactamente horizontal, vertical o a 45°. El más cercano gana.
        Ayuda a medir con precisión distancias que se sabe son
        ortogonales.
        """
        dx = punto.x() - punto_a.x()
        dy = punto.y() - punto_a.y()
        if dx == 0.0 and dy == 0.0:
            return punto
        angulo = math.atan2(dy, dx)
        paso = math.pi / 4.0
        snap = round(angulo / paso) * paso
        largo = math.hypot(dx, dy)
        return QPointF(
            punto_a.x() + largo * math.cos(snap),
            punto_a.y() + largo * math.sin(snap),
        )

    def _on_primer_punto_medicion(self, punto_pdf: QPointF) -> None:
        self._guia_medicion.set_punto_a(punto_pdf)
        self._guia_medicion.setVisible(True)

    def _on_medicion_completada(self, medicion: MedicionCalibrada) -> None:
        item = MedicionItem(medicion)
        self._scene.addItem(item)
        self._mediciones_items.append(item)
        self._guia_medicion.limpiar()
        self._guia_medicion.setVisible(False)
        self.medicion_agregada.emit(medicion)

    def _on_medicion_cancelada(self) -> None:
        self._guia_medicion.limpiar()
        self._guia_medicion.setVisible(False)

    # ------------------------------------------------------------ herramienta

    def set_herramienta(self, herramienta: Herramienta) -> None:
        # Guard: MEDIR requiere escala calibrada. Sin ella, medir da
        # distancias en pt PDF que no tienen sentido para el operador.
        if herramienta == Herramienta.MEDIR and self._escala is None:
            herramienta = Herramienta.SELECCIONAR

        # Cancelar calibración si estaba activa
        if self._calibrador.esta_activo():
            self._calibrador.cancelar()
        # Salir del modo borrar individual si estaba activo
        if self._modo_borrar_individual:
            self.salir_modo_borrar_individual()

        # Salir/entrar del modo MEDIR
        if self._herramienta == Herramienta.MEDIR and herramienta != Herramienta.MEDIR:
            self._medidor.desactivar()
        if herramienta == Herramienta.MEDIR and self._herramienta != Herramienta.MEDIR:
            if self._plano_item is not None:
                self._medidor.activar()

        if herramienta == self._herramienta:
            return
        self._herramienta = herramienta

        if herramienta == Herramienta.PAN:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        elif herramienta == Herramienta.SELECCIONAR:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

        self._actualizar_cursor()
        self.herramienta_cambiada.emit(herramienta)

    def herramienta_actual(self) -> Herramienta:
        return self._herramienta

    def _actualizar_cursor(self) -> None:
        if self._panning_middle:
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._calibrador.esta_activo() or self._medidor.esta_activo():
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            return
        h = self._herramienta
        if h == Herramienta.PAN:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif h == Herramienta.SELECCIONAR:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        elif h in (Herramienta.MEDIR, Herramienta.DIBUJAR, Herramienta.COLOCAR):
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------ capas

    def set_capa_visible(self, capa: Capa, visible: bool) -> None:
        grupo = self._capas.get(capa)
        if grupo is not None:
            grupo.setVisible(visible)

    def capa_visible(self, capa: Capa) -> bool:
        grupo = self._capas.get(capa)
        return bool(grupo and grupo.isVisible())

    def capa(self, capa: Capa) -> QGraphicsItemGroup:
        return self._capas[capa]

    # ------------------------------------------------------------------- zoom

    def encajar_plano_en_vista(self) -> None:
        if self._plano_item is None:
            return
        rect = self._plano_item.mapToScene(
            self._plano_item.boundingRect()
        ).boundingRect()
        self.resetTransform()
        self._zoom_factor = 1.0
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_factor = self.transform().m11()
        self.zoom_cambiado.emit(self._zoom_factor)
        self.viewport().update()

    def zoom_actual(self) -> float:
        return self._zoom_factor

    def zoom_in(self) -> None:
        self._aplicar_zoom(self.ZOOM_STEP)

    def zoom_out(self) -> None:
        self._aplicar_zoom(1.0 / self.ZOOM_STEP)

    def _aplicar_zoom(self, factor: float) -> None:
        nuevo = self._zoom_factor * factor
        if nuevo < self.ZOOM_MIN or nuevo > self.ZOOM_MAX:
            return
        self.scale(factor, factor)
        self._zoom_factor = nuevo
        self.zoom_cambiado.emit(self._zoom_factor)

    # ------------------------------------ overlay: barra de escala

    def drawForeground(  # noqa: N802
        self, painter: QPainter, rect: QRectF
    ) -> None:
        """Dibuja la barra de escala en la esquina inferior izquierda
        del viewport. Solo visible cuando hay escala calibrada."""
        super().drawForeground(painter, rect)

        if self._escala is None or self._plano_item is None:
            return

        painter.save()
        # Dibujamos en coords del viewport (píxeles lógicos).
        painter.resetTransform()

        # transform().m11() = zoom = píxeles lógicos por pt PDF.
        # Ojo: como estamos DENTRO de drawForeground, worldTransform()
        # NO tiene aún el reset; por eso guardamos self._zoom_factor.
        # (Antes se trataba como "pt por píxel" y se DIVIDÍA: la barra
        # sólo era correcta con zoom 100% — a 600% decía 20 m donde había
        # ~50 cm.)
        px_por_pt = self._zoom_factor
        if px_por_pt <= 0:
            painter.restore()
            return

        pt_por_m = self._escala.pt_por_m
        # pixeles lógicos por metro real
        px_por_m = pt_por_m * px_por_pt
        if px_por_m <= 0:
            painter.restore()
            return

        # Escoger la longitud "redonda" que dé una barra cómoda
        metros = self._escoger_longitud_barra(px_por_m)
        ancho_barra = metros * px_por_m

        # Posición: esquina inferior izquierda con margen
        margen_x = 16
        margen_y = 16
        alto = 40
        vw_w = self.viewport().width()
        vw_h = self.viewport().height()

        # Ancho total: barra + padding
        pad_x = 12
        pad_top = 8
        pad_bot = 8

        etiqueta = _formato_metros_barra(metros)
        fuente = QFont()
        fuente.setPointSize(10)
        fuente.setBold(True)
        painter.setFont(fuente)
        metrics = QFontMetricsF(fuente)
        alto_txt = metrics.height()
        ancho_txt = metrics.horizontalAdvance(etiqueta)

        rect_bg_w = max(ancho_barra, ancho_txt) + 2 * pad_x
        rect_bg_h = alto_txt + 12 + pad_top + pad_bot

        x = margen_x
        y = vw_h - margen_y - rect_bg_h
        rect_bg = QRectF(x, y, rect_bg_w, rect_bg_h)

        # Fondo del panel
        bg = QColor(COLOR_BARRA_ESCALA_BG)
        bg.setAlpha(220)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(QColor(COLOR_BARRA_ESCALA_BORDE), 1))
        painter.drawRoundedRect(rect_bg, 6, 6)

        # Texto centrado arriba
        painter.setPen(QPen(QColor(COLOR_BARRA_ESCALA_TEXTO)))
        rect_txt = QRectF(x, y + pad_top, rect_bg_w, alto_txt)
        painter.drawText(
            rect_txt,
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop,
            etiqueta,
        )

        # Barra al centro
        y_barra = y + pad_top + alto_txt + 4
        x_barra_ini = x + (rect_bg_w - ancho_barra) / 2
        x_barra_fin = x_barra_ini + ancho_barra
        pen_barra = QPen(QColor(COLOR_BARRA_ESCALA_TEXTO))
        pen_barra.setWidthF(2.0)
        pen_barra.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(pen_barra)
        painter.drawLine(
            QPointF(x_barra_ini, y_barra),
            QPointF(x_barra_fin, y_barra),
        )
        # Marcas verticales en los extremos
        alto_marca = 6
        painter.drawLine(
            QPointF(x_barra_ini, y_barra - alto_marca),
            QPointF(x_barra_ini, y_barra + alto_marca),
        )
        painter.drawLine(
            QPointF(x_barra_fin, y_barra - alto_marca),
            QPointF(x_barra_fin, y_barra + alto_marca),
        )
        # Marca central
        painter.drawLine(
            QPointF((x_barra_ini + x_barra_fin) / 2, y_barra - 3),
            QPointF((x_barra_ini + x_barra_fin) / 2, y_barra + 3),
        )

        painter.restore()

    @staticmethod
    def _escoger_longitud_barra(px_por_m: float) -> float:
        """Devuelve la longitud (en metros) más grande de la lista de
        preferidas que produce una barra dentro del rango de ancho."""
        candidatos = []
        for m in _LONGITUDES_BARRA_M:
            px = m * px_por_m
            if _BARRA_PX_MIN <= px <= _BARRA_PX_MAX:
                candidatos.append(m)
        if candidatos:
            return max(candidatos)
        # Fallback: la longitud cuya barra tenga ancho más cercano
        # al centro del rango objetivo (110 px).
        centro = (_BARRA_PX_MIN + _BARRA_PX_MAX) / 2
        return min(
            _LONGITUDES_BARRA_M,
            key=lambda m: abs(m * px_por_m - centro),
        )

    # ---------------------------------------------------- eventos: rueda

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._plano_item is None:
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        factor = self.ZOOM_STEP if delta > 0 else 1.0 / self.ZOOM_STEP
        self._aplicar_zoom(factor)
        event.accept()

    # ---------------------------------------------------- eventos: mouse

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning_middle = True
            self._pan_last_pos = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            # Prioridad 0: modo "borrar individual" activo → un clic
            # elimina la medición bajo el cursor.
            if self._modo_borrar_individual:
                self._eliminar_medicion_bajo_cursor(event.position().toPoint())
                event.accept()
                return

            punto_escena = self.mapToScene(event.position().toPoint())

            # Prioridad 0.5: herramienta externa registrada (Sesión D+).
            # Se le da prioridad sobre calibración/medición, pero por
            # detrás de "borrar individual" (que es UI-glue del canvas).
            ext = self._herramienta_externa
            if ext is not None and hasattr(ext, "esta_activa") and ext.esta_activa():
                shift = bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                if ext.on_click(punto_escena, shift):
                    event.accept()
                    return

            # Prioridad 1: calibración activa
            if self._calibrador.esta_activo():
                # Con Shift, snap ortogonal al segundo clic
                if (
                    self._calibrador.esperando_segundo_punto()
                    and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                ):
                    pa = self._calibrador.punto_a()
                    if pa is not None:
                        punto_escena = self._snap_ortogonal(pa, punto_escena)
                self._calibrador.registrar_click(punto_escena)
                event.accept()
                return

            # Prioridad 2: herramienta MEDIR activa
            if self._medidor.esta_activo():
                # Con Shift, snap ortogonal al segundo clic
                if (
                    self._medidor.esperando_segundo_punto()
                    and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                ):
                    pa = self._medidor.punto_a()
                    if pa is not None:
                        punto_escena = self._snap_ortogonal(pa, punto_escena)
                self._medidor.registrar_click(punto_escena)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._panning_middle and self._pan_last_pos is not None:
            delta = event.position() - self._pan_last_pos
            self._pan_last_pos = event.position()
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - int(delta.x()))
            v_bar.setValue(v_bar.value() - int(delta.y()))
            event.accept()
            return

        if self._plano_item is not None:
            escena = self.mapToScene(event.position().toPoint())
            self.posicion_cursor.emit(escena)

            shift_apretado = bool(
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            )

            # Herramienta externa (Sesión D+): informar del move
            ext = self._herramienta_externa
            if ext is not None and hasattr(ext, "esta_activa") and ext.esta_activa():
                ext.on_move(escena, shift_apretado)

            # Actualizar guía de calibración (con snap ortogonal si Shift)
            if self._calibrador.esperando_segundo_punto():
                punto_mostrado = escena
                pa = self._calibrador.punto_a()
                if shift_apretado and pa is not None:
                    punto_mostrado = self._snap_ortogonal(pa, escena)
                self._guia_calibracion.set_cursor(punto_mostrado)

            # Actualizar guía de medición (con snap ortogonal si Shift)
            if self._medidor.esperando_segundo_punto():
                punto_mostrado = escena
                pa = self._medidor.punto_a()
                if shift_apretado and pa is not None:
                    punto_mostrado = self._snap_ortogonal(pa, escena)
                self._guia_medicion.set_cursor(punto_mostrado)

            if self._escala is not None:
                self.posicion_cursor_metros.emit(
                    self._escala.punto_pt_a_m(escena)
                )

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self._panning_middle:
            self._panning_middle = False
            self._pan_last_pos = None
            self._actualizar_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Doble clic izquierdo con herramienta externa activa: dispara
        # un "terminar" (usado por delimitación para cerrar polilínea).
        # El handler decide si aplica.
        ext = self._herramienta_externa
        if (
            ext is not None
            and hasattr(ext, "esta_activa")
            and ext.esta_activa()
            and event.button() == Qt.MouseButton.LeftButton
        ):
            # Simular una tecla Enter para reusar el mismo camino
            fake_enter = QKeyEvent(
                QKeyEvent.Type.KeyPress, Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier,
            )
            if ext.on_key(fake_enter):
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    # -------------------------------------------------- eventos: teclado

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        # Herramienta externa: Enter/Escape prioridad
        ext = self._herramienta_externa
        if ext is not None and hasattr(ext, "esta_activa") and ext.esta_activa():
            if ext.on_key(event):
                event.accept()
                return
        if key == Qt.Key.Key_Escape:
            if self._modo_borrar_individual:
                self.salir_modo_borrar_individual()
                event.accept()
                return
            if self._calibrador.esta_activo():
                self._calibrador.cancelar()
                event.accept()
                return
            if self._medidor.esta_activo() and self._medidor.esperando_segundo_punto():
                # Solo cancelar el clic en curso, no salir de la herramienta
                self._medidor.cancelar_medicion_en_curso()
                event.accept()
                return
        if key == Qt.Key.Key_0:
            self.encajar_plano_en_vista()
            event.accept()
            return
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
            event.accept()
            return
        if key == Qt.Key.Key_Minus:
            self.zoom_out()
            event.accept()
            return
        if key == Qt.Key.Key_S:
            self.set_herramienta(Herramienta.SELECCIONAR)
            event.accept()
            return
        if key == Qt.Key.Key_P:
            self.set_herramienta(Herramienta.PAN)
            event.accept()
            return
        if key == Qt.Key.Key_M:
            self.set_herramienta(Herramienta.MEDIR)
            event.accept()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Demo standalone (estilo AutoCAD / Revit)
# ---------------------------------------------------------------------------

_ANCHO_BTN_CHICO  = 66
_ANCHO_BTN_GRANDE = 90
_SPACING_BOTONES  = 2


# ---------------------------------------------------------------------------
# _PopupBorrador — popup estilo AutoCAD/Paint con iconos horizontales
# ---------------------------------------------------------------------------

class _PopupBorrador(QWidget):
    """Popup flyout que aparece al hacer clic en la flecha del split
    button "Borrar". Contiene botones con iconos grandes y tooltips
    descriptivos, como los flyouts del ribbon de AutoCAD.
    """

    accion_todas = pyqtSignal()
    accion_una = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        # Qt.WindowType.Popup hace que el widget se cierre solo al
        # hacer clic fuera de él.
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("popupBorrador")
        self.setStyleSheet(self._stylesheet())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._btn_todas = self._crear_boton(
            "fa5s.trash-alt", "Todas",
            "Elimina TODAS las mediciones del plano de una vez.",
            self._on_todas,
        )
        self._btn_una = self._crear_boton(
            "fa5s.eraser", "Una por una",
            (
                "Modo de eliminación selectiva:\n"
                "pasa el mouse sobre una medición\n"
                "(se marcará en rojo) y haz clic para\n"
                "eliminarla individualmente."
            ),
            self._on_una,
        )
        layout.addWidget(self._btn_todas)
        layout.addWidget(self._btn_una)

    def _crear_boton(
        self,
        icono_nombre: str,
        texto: str,
        tooltip: str,
        on_click,
    ) -> QToolButton:
        btn = QToolButton()
        btn.setText(texto)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setIconSize(QSize(32, 32))
        btn.setFixedSize(96, 82)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if _QTA_OK:
            btn.setIcon(qta.icon(icono_nombre, color=COLOR_TEXTO_SUAVE))
        btn.clicked.connect(on_click)
        return btn

    def _on_todas(self) -> None:
        self.hide()
        self.accion_todas.emit()

    def _on_una(self) -> None:
        self.hide()
        self.accion_una.emit()

    def _stylesheet(self) -> str:
        return f"""
            QWidget#popupBorrador {{
                background-color: {COLOR_HEADER};
                border: 1px solid {COLOR_ACENTO_BRILL};
                border-radius: 6px;
            }}
            QToolButton {{
                background-color: transparent;
                color: {COLOR_TEXTO_SUAVE};
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px 6px;
                font-size: 11px;
                outline: none;
            }}
            QToolButton:hover {{
                background-color: {COLOR_INPUT_BG};
                border-color: {COLOR_BORDE_FUERTE};
                color: {COLOR_TEXTO};
            }}
            QToolButton:pressed {{
                background-color: {COLOR_BORDE_FUERTE};
            }}
            QToolTip {{
                background-color: {COLOR_SIDEBAR};
                color: {COLOR_TEXTO};
                border: 1px solid {COLOR_BORDE_FUERTE};
                padding: 6px 8px;
                font-size: 11px;
            }}
        """


# ---------------------------------------------------------------------------
# _SplitBorrarButton — QToolButton con dos zonas de clic detectadas
# ---------------------------------------------------------------------------

class _SplitBorrarButton(QToolButton):
    """QToolButton estilo split: la mitad izquierda ejecuta la acción
    principal (borrar todas), la mitad derecha muestra el popup con
    opciones adicionales. Detectamos manualmente en qué mitad cae el
    clic — más control que el flujo default de setMenu().
    """

    accion_principal = pyqtSignal()
    solicita_popup   = pyqtSignal()

    ANCHO_ZONA_FLECHA = 16

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        # ¿Clic en la mitad derecha (zona de la flecha)?
        if event.position().x() >= self.width() - self.ANCHO_ZONA_FLECHA:
            self.solicita_popup.emit()
        else:
            self.accion_principal.emit()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Consumimos el release para que Qt no dispare clicked() propia.
        event.accept()


class _DemoWindow(QMainWindow):
    # Modo actual del split button de borrar. Recuerda cuál fue la
    # última opción usada, como la brocha de Photoshop: un clic en el
    # botón principal repite la última acción, y la flecha permite
    # cambiar de modo.
    MODO_BORRAR_TODAS = "todas"
    MODO_BORRAR_UNA   = "una"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Canvas Plano — Demo Sesión A + B")
        self.resize(1420, 820)
        self.setStyleSheet(self._stylesheet())

        # Modo actual del split button de borrar
        self._modo_borrar_actual: str = self.MODO_BORRAR_TODAS

        central = QWidget()
        central.setObjectName("centralDemo")
        self.setCentralWidget(central)
        vlayout = QVBoxLayout(central)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(0)

        self._ribbon = self._crear_ribbon()
        vlayout.addWidget(self._ribbon)

        self._canvas = CanvasPlano()
        vlayout.addWidget(self._canvas, stretch=1)

        self._status = self._crear_status_bar()
        vlayout.addWidget(self._status)

        # Sesión A
        self._canvas.plano_cargado.connect(self._on_plano_cargado)
        self._canvas.plano_descargado.connect(self._on_plano_descargado)
        self._canvas.zoom_cambiado.connect(self._on_zoom_cambiado)
        self._canvas.herramienta_cambiada.connect(self._on_herramienta_cambiada)
        self._canvas.posicion_cursor.connect(self._on_cursor)
        self._canvas.posicion_cursor_metros.connect(self._on_cursor_metros)
        self._canvas.error_carga.connect(self._on_error_carga)
        self._canvas.render_actualizado.connect(self._on_render_actualizado)

        # Sesión B — calibración
        self._canvas.escala_cambiada.connect(self._on_escala_cambiada)
        self._canvas.calibrador().estado_mensaje.connect(
            self._on_mensaje_estado
        )

        # Sesión B — medición
        self._canvas.medicion_agregada.connect(self._on_medicion_agregada)
        self._canvas.mediciones_borradas.connect(self._on_mediciones_borradas)
        self._canvas.medidor().estado_mensaje.connect(
            self._on_mensaje_estado
        )
        self._canvas.modo_borrar_individual_cambiado.connect(
            self._on_modo_borrar_individual_cambiado
        )

        self._marcar_boton_herramienta(Herramienta.SELECCIONAR)

    def _stylesheet(self) -> str:
        return f"""
            QMainWindow, QWidget#centralDemo {{
                background-color: {COLOR_FONDO};
            }}
            QFrame#ribbon {{
                background-color: {COLOR_HEADER};
                border-bottom: 1px solid {COLOR_BORDE};
            }}
            QFrame#ribbonSeparator {{
                background-color: {COLOR_BORDE};
                min-width: 1px;
                max-width: 1px;
                margin: 4px 6px 22px 6px;
            }}
            QLabel#grupoLabel {{
                color: {COLOR_TEXTO_APAGADO};
                font-size: 10px;
                font-weight: bold;
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
            QToolButton:pressed {{
                background-color: {COLOR_BORDE_FUERTE};
            }}
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
                border-color: {COLOR_ACENTO_BRILL};
            }}
            /* Split button: la mitad derecha con la flechita del menú */
            QToolButton::menu-button {{
                background-color: transparent;
                border: none;
                border-left: 1px solid {COLOR_BORDE};
                width: 14px;
            }}
            QToolButton::menu-button:hover {{
                background-color: {COLOR_BORDE_FUERTE};
            }}
            QToolButton::menu-arrow {{
                image: none;
            }}
            QFrame#statusBar {{
                background-color: {COLOR_SIDEBAR};
                border-top: 1px solid {COLOR_BORDE};
            }}
            QLabel#statusCell {{
                color: {COLOR_TEXTO_SUAVE};
                font-size: 11px;
                padding: 4px 12px;
            }}
            QLabel#statusCellMuted {{
                color: {COLOR_TEXTO_APAGADO};
                font-size: 11px;
                padding: 4px 12px;
            }}
            QLabel#statusCellCalibracion {{
                color: {COLOR_ACENTO_BRILL};
                font-size: 11px;
                padding: 4px 12px;
                font-weight: bold;
            }}
            QFrame#statusSeparator {{
                background-color: {COLOR_BORDE};
                min-width: 1px;
                max-width: 1px;
                margin: 4px 0px;
            }}
        """

    def _crear_ribbon(self) -> QFrame:
        ribbon = QFrame()
        ribbon.setObjectName("ribbon")
        ribbon.setFixedHeight(88)

        h = QHBoxLayout(ribbon)
        h.setContentsMargins(10, 4, 10, 2)
        h.setSpacing(4)

        # ARCHIVO
        grupo_archivo = self._crear_grupo("ARCHIVO", [_ANCHO_BTN_GRANDE])
        self._btn_abrir = self._crear_boton_ribbon(
            "fa5s.folder-open", "Cargar plano",
            _ANCHO_BTN_GRANDE, self._abrir_plano,
        )
        grupo_archivo["contenido"].addWidget(self._btn_abrir)
        h.addWidget(grupo_archivo["widget"])

        h.addWidget(self._separador_ribbon())

        # VISTA
        grupo_vista = self._crear_grupo(
            "VISTA", [_ANCHO_BTN_CHICO, _ANCHO_BTN_CHICO, _ANCHO_BTN_CHICO]
        )
        self._btn_fit = self._crear_boton_ribbon(
            "fa5s.expand", "Encajar",
            _ANCHO_BTN_CHICO, self._canvas_encajar,
        )
        self._btn_zoom_in = self._crear_boton_ribbon(
            "fa5s.search-plus", "Zoom +",
            _ANCHO_BTN_CHICO, lambda: self._canvas.zoom_in(),
        )
        self._btn_zoom_out = self._crear_boton_ribbon(
            "fa5s.search-minus", "Zoom −",
            _ANCHO_BTN_CHICO, lambda: self._canvas.zoom_out(),
        )
        grupo_vista["contenido"].addWidget(self._btn_fit)
        grupo_vista["contenido"].addWidget(self._btn_zoom_in)
        grupo_vista["contenido"].addWidget(self._btn_zoom_out)
        h.addWidget(grupo_vista["widget"])

        h.addWidget(self._separador_ribbon())

        # HERRAMIENTAS
        grupo_tools = self._crear_grupo(
            "HERRAMIENTAS", [_ANCHO_BTN_GRANDE, _ANCHO_BTN_CHICO]
        )
        self._btn_sel = self._crear_boton_ribbon(
            "fa5s.mouse-pointer", "Seleccionar",
            _ANCHO_BTN_GRANDE,
            lambda: self._canvas.set_herramienta(Herramienta.SELECCIONAR),
        )
        self._btn_pan = self._crear_boton_ribbon(
            "fa5s.hand-paper", "Pan",
            _ANCHO_BTN_CHICO,
            lambda: self._canvas.set_herramienta(Herramienta.PAN),
        )
        grupo_tools["contenido"].addWidget(self._btn_sel)
        grupo_tools["contenido"].addWidget(self._btn_pan)
        h.addWidget(grupo_tools["widget"])

        h.addWidget(self._separador_ribbon())

        # MEDICIÓN — Calibrar + Medir + Borrar (split button)
        # Calibrar hace flujo de N puntos secuencial (ver
        # CanvasPlano.NUM_PUNTOS_CALIBRACION). El operador aprende UN
        # flujo consistente en vez de tener botón separado de refinar.
        _ANCHO_BTN_BORRAR = 82
        grupo_medicion = self._crear_grupo(
            "MEDICIÓN",
            [_ANCHO_BTN_GRANDE, _ANCHO_BTN_CHICO, _ANCHO_BTN_BORRAR]
        )
        self._btn_calibrar = self._crear_boton_ribbon(
            "fa5s.ruler-combined", "Calibrar",
            _ANCHO_BTN_GRANDE, self._iniciar_calibracion,
        )
        self._btn_calibrar.setToolTip(
            f"Calibra la escala con "
            f"{CanvasPlano.NUM_PUNTOS_CALIBRACION} puntos de referencia.\n"
            "El calibrador te pide 3 pares de clics con su distancia\n"
            "real, y calcula la escala por mínimos cuadrados sobre los\n"
            "3 puntos para máxima precisión."
        )
        self._btn_medir = self._crear_boton_ribbon(
            "fa5s.ruler", "Medir",
            _ANCHO_BTN_CHICO,
            lambda: self._canvas.set_herramienta(Herramienta.MEDIR),
        )
        # Medir arranca deshabilitado — sin escala calibrada, medir
        # devuelve pt del PDF (inútil para el operador). Se habilita
        # cuando la escala se aplica (ver _on_escala_cambiada).
        self._btn_medir.setEnabled(False)
        self._btn_medir.setToolTip(
            "Medir distancias en metros.\n"
            "Requiere calibrar el plano primero."
        )
        self._btn_borrar_med = self._crear_split_borrar(_ANCHO_BTN_BORRAR)
        grupo_medicion["contenido"].addWidget(self._btn_calibrar)
        grupo_medicion["contenido"].addWidget(self._btn_medir)
        grupo_medicion["contenido"].addWidget(self._btn_borrar_med)
        h.addWidget(grupo_medicion["widget"])

        h.addStretch(1)

        return ribbon

    def _crear_grupo(
        self, etiqueta: str, anchos_botones: list[int]
    ) -> dict:
        ancho_total = sum(anchos_botones) + \
            _SPACING_BOTONES * max(0, len(anchos_botones) - 1)

        wrap = QWidget()
        wrap.setFixedWidth(ancho_total)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        contenido = QHBoxLayout()
        contenido.setContentsMargins(0, 0, 0, 0)
        contenido.setSpacing(_SPACING_BOTONES)
        v.addLayout(contenido)

        lbl = QLabel(etiqueta)
        lbl.setObjectName("grupoLabel")
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lbl.setFixedWidth(ancho_total)
        v.addWidget(lbl)

        return {"widget": wrap, "contenido": contenido}

    def _separador_ribbon(self) -> QFrame:
        sep = QFrame()
        sep.setObjectName("ribbonSeparator")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        return sep

    def _crear_boton_ribbon(
        self, icono_nombre: str, texto: str, ancho: int, on_click,
    ) -> QToolButton:
        btn = QToolButton()
        btn.setText(texto)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setIconSize(QSize(22, 22))
        btn.setFixedWidth(ancho)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(texto)

        btn.setProperty("iconName", icono_nombre)
        self._aplicar_icono(btn, activo=False)

        btn.clicked.connect(on_click)
        return btn

    def _aplicar_icono(self, btn: QToolButton, activo: bool) -> None:
        nombre = btn.property("iconName")
        if not nombre:
            return
        color = COLOR_TEXTO if activo else COLOR_TEXTO_SUAVE
        if _QTA_OK:
            btn.setIcon(qta.icon(nombre, color=color))

    def _crear_split_borrar(self, ancho: int) -> _SplitBorrarButton:
        """Split button estilo Photoshop/AutoCAD.

        La mitad izquierda repite la ÚLTIMA opción usada (como la
        brocha de Photoshop). La mitad derecha (flecha) despliega un
        popup con iconos grandes para elegir otro modo. Al elegir del
        popup, el botón principal se transforma para mostrar el nuevo
        modo activo y desde ese momento un clic directo lo ejecuta.
        """
        btn = _SplitBorrarButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setIconSize(QSize(22, 22))
        btn.setFixedWidth(ancho)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # setPopupMode(MenuButtonPopup) SOLO para que Qt dibuje la flecha
        # visualmente en la mitad derecha (el clic lo manejamos nosotros).
        btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        btn.setMenu(QMenu(btn))  # menu vacío; nunca se muestra

        btn.accion_principal.connect(self._ejecutar_borrar_actual)
        btn.solicita_popup.connect(self._mostrar_popup_borrador)

        # Guardamos referencia para posicionar el popup y actualizar
        # el visual cuando cambia el modo.
        self._btn_borrar_ref = btn

        # Aplicar visual inicial (modo default: TODAS)
        self._aplicar_visual_split_borrar(self._modo_borrar_actual)

        return btn

    def _aplicar_visual_split_borrar(self, modo: str) -> None:
        """Actualiza el texto, icono y tooltip del split button para
        reflejar el modo actual — el que se ejecutará al clic directo."""
        btn = self._btn_borrar_ref
        if modo == self.MODO_BORRAR_UNA:
            btn.setText("Una")
            btn.setProperty("iconName", "fa5s.eraser")
            btn.setToolTip(
                "Clic: activar modo eliminar uno por uno\n"
                "(última opción usada)\n"
                "Clic en la flecha: elegir otro modo de borrado"
            )
        else:  # MODO_BORRAR_TODAS
            btn.setText("Todas")
            btn.setProperty("iconName", "fa5s.trash-alt")
            btn.setToolTip(
                "Clic: borrar todas las mediciones\n"
                "(última opción usada)\n"
                "Clic en la flecha: elegir otro modo de borrado"
            )
        self._aplicar_icono(btn, activo=False)

    def _ejecutar_borrar_actual(self) -> None:
        """Slot del clic en la mitad izquierda del split. Ejecuta la
        acción del modo actualmente memorizado."""
        if self._modo_borrar_actual == self.MODO_BORRAR_UNA:
            self._iniciar_borrar_individual()
        else:
            self._borrar_mediciones()

    def _elegir_modo_borrar_todas(self) -> None:
        """Callback del popup "Todas": memoriza el modo, actualiza el
        visual del botón y ejecuta la acción."""
        self._modo_borrar_actual = self.MODO_BORRAR_TODAS
        self._aplicar_visual_split_borrar(self.MODO_BORRAR_TODAS)
        self._borrar_mediciones()

    def _elegir_modo_borrar_una(self) -> None:
        """Callback del popup "Una por una": memoriza el modo, actualiza
        el visual del botón y activa el modo de eliminación selectiva."""
        self._modo_borrar_actual = self.MODO_BORRAR_UNA
        self._aplicar_visual_split_borrar(self.MODO_BORRAR_UNA)
        self._iniciar_borrar_individual()

    def _mostrar_popup_borrador(self) -> None:
        """Crea (si hace falta) el popup y lo muestra debajo del split
        button de Borrar."""
        if not hasattr(self, "_popup_borrador"):
            self._popup_borrador = _PopupBorrador(self)
            self._popup_borrador.accion_todas.connect(
                self._elegir_modo_borrar_todas
            )
            self._popup_borrador.accion_una.connect(
                self._elegir_modo_borrar_una
            )
        popup = self._popup_borrador
        popup.adjustSize()
        btn = self._btn_borrar_ref
        pos = btn.mapToGlobal(btn.rect().bottomRight())
        popup.move(pos.x() - popup.width(), pos.y() + 2)
        popup.show()
        popup.raise_()

    def _crear_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(28)

        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self._lbl_archivo = QLabel("Sin plano cargado")
        self._lbl_archivo.setObjectName("statusCellMuted")
        h.addWidget(self._lbl_archivo)

        h.addWidget(self._separador_status())

        self._lbl_cursor = QLabel("cursor: —")
        self._lbl_cursor.setObjectName("statusCellMuted")
        h.addWidget(self._lbl_cursor)

        h.addStretch(1)

        self._lbl_mensaje = QLabel("")
        self._lbl_mensaje.setObjectName("statusCellCalibracion")
        h.addWidget(self._lbl_mensaje)

        h.addWidget(self._separador_status())

        self._lbl_escala = QLabel("escala: sin calibrar")
        self._lbl_escala.setObjectName("statusCellMuted")
        h.addWidget(self._lbl_escala)

        h.addWidget(self._separador_status())

        self._lbl_render = QLabel("render: —")
        self._lbl_render.setObjectName("statusCellMuted")
        h.addWidget(self._lbl_render)

        h.addWidget(self._separador_status())

        self._lbl_zoom = QLabel("zoom: —")
        self._lbl_zoom.setObjectName("statusCell")
        h.addWidget(self._lbl_zoom)

        return bar

    def _separador_status(self) -> QFrame:
        sep = QFrame()
        sep.setObjectName("statusSeparator")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        return sep

    # ---------------- callbacks --------------------------------------------

    def _abrir_plano(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar plano",
            "",
            "Planos (*.pdf *.png *.jpg *.jpeg *.bmp);;Todos los archivos (*.*)",
        )
        if path:
            self._canvas.cargar_plano(path)

    def _canvas_encajar(self) -> None:
        self._canvas.encajar_plano_en_vista()

    def _iniciar_calibracion(self) -> None:
        if not self._canvas.iniciar_calibracion():
            QMessageBox.information(
                self, "Calibrar escala",
                "Primero carga un plano antes de calibrar la escala."
            )

    def _borrar_mediciones(self) -> None:
        self._canvas.borrar_mediciones()

    def _iniciar_borrar_individual(self) -> None:
        if not self._canvas.iniciar_modo_borrar_individual():
            QMessageBox.information(
                self, "Borrar una por una",
                "No hay mediciones que borrar. Primero mide algo."
            )
        else:
            self._lbl_mensaje.setText(
                "Borrar una por una: clic sobre la medición que quieras "
                "eliminar. Escape para salir."
            )

    def _on_plano_cargado(self, path: str) -> None:
        self._lbl_archivo.setObjectName("statusCell")
        self._lbl_archivo.setText(Path(path).name)
        self._reaplicar_stylesheet(self._lbl_archivo)

    def _on_plano_descargado(self) -> None:
        self._lbl_archivo.setObjectName("statusCellMuted")
        self._lbl_archivo.setText("Sin plano cargado")
        self._reaplicar_stylesheet(self._lbl_archivo)
        self._lbl_render.setText("render: —")

    def _on_zoom_cambiado(self, factor: float) -> None:
        self._lbl_zoom.setText(f"zoom: {factor * 100:.0f}%")

    def _on_render_actualizado(self, factor: float) -> None:
        if self._canvas.plano_path() is None:
            self._lbl_render.setText("render: —")
        elif self._canvas.es_pdf():
            self._lbl_render.setText(f"render: {factor:.0f}x")
        else:
            self._lbl_render.setText("render: nativo")

    def _on_herramienta_cambiada(self, herramienta: Herramienta) -> None:
        self._marcar_boton_herramienta(herramienta)

    def _on_cursor(self, pos: QPointF) -> None:
        if self._canvas.escala_actual() is None:
            self._lbl_cursor.setObjectName("statusCell")
            self._lbl_cursor.setText(
                f"cursor: {pos.x():.0f}, {pos.y():.0f} pt"
            )
            self._reaplicar_stylesheet(self._lbl_cursor)

    def _on_cursor_metros(self, pos_m: QPointF) -> None:
        self._lbl_cursor.setObjectName("statusCell")
        self._lbl_cursor.setText(
            f"cursor: {pos_m.x():.3f}, {pos_m.y():.3f} m"
        )
        self._reaplicar_stylesheet(self._lbl_cursor)

    def _on_error_carga(self, mensaje: str) -> None:
        QMessageBox.warning(self, "No se pudo cargar el plano", mensaje)

    def _on_escala_cambiada(self, escala: Optional[EscalaCalibrada]) -> None:
        if escala is None:
            self._lbl_escala.setObjectName("statusCellMuted")
            self._lbl_escala.setText("escala: sin calibrar")
        else:
            self._lbl_escala.setObjectName("statusCell")
            self._lbl_escala.setText(f"escala: {escala.resumen_legible()}")
        self._reaplicar_stylesheet(self._lbl_escala)
        # Medir requiere escala calibrada
        tiene_escala = (escala is not None)
        self._btn_medir.setEnabled(tiene_escala)
        if tiene_escala:
            self._btn_medir.setToolTip(
                "Medir distancias en metros usando la escala calibrada."
            )
        else:
            self._btn_medir.setToolTip(
                "Medir distancias en metros.\n"
                "Requiere calibrar el plano primero."
            )

    def _on_mensaje_estado(self, mensaje: str) -> None:
        self._lbl_mensaje.setText(mensaje)

    def _on_medicion_agregada(self, medicion: MedicionCalibrada) -> None:
        # El mensaje ya lo emite el propio medidor; aquí no hace falta más.
        pass

    def _on_mediciones_borradas(self) -> None:
        self._lbl_mensaje.setText("Mediciones borradas")

    def _on_modo_borrar_individual_cambiado(self, activo: bool) -> None:
        """Sincroniza el UI cuando el canvas entra o sale del modo
        "borrar una por una":
          * Resalta o apaga visualmente el botón principal del split
            de Borrar, para que el operador vea qué modo está activo.
          * Limpia el mensaje del status bar cuando el modo termina.
        """
        btn = self._btn_borrar_ref
        if activo:
            btn.setObjectName("toolActivo")
        else:
            btn.setObjectName("")
            # Limpiar el mensaje de guía ("Borrar una por una: …")
            # solo si sigue siendo ese mensaje — no pisar otros mensajes
            # posteriores.
            txt = self._lbl_mensaje.text()
            if txt.startswith("Borrar una por una"):
                self._lbl_mensaje.setText("")
        self._aplicar_icono(btn, activo=activo)
        self._reaplicar_stylesheet(btn)

    def _marcar_boton_herramienta(self, herramienta: Herramienta) -> None:
        mapping = {
            Herramienta.SELECCIONAR: self._btn_sel,
            Herramienta.PAN:         self._btn_pan,
            Herramienta.MEDIR:       self._btn_medir,
        }
        for h, btn in mapping.items():
            activo = (h == herramienta)
            btn.setObjectName("toolActivo" if activo else "")
            self._aplicar_icono(btn, activo=activo)
            self._reaplicar_stylesheet(btn)

    @staticmethod
    def _reaplicar_stylesheet(widget: QWidget) -> None:
        s = widget.style()
        if s is not None:
            s.unpolish(widget)
            s.polish(widget)


def _main() -> int:
    app = QApplication(sys.argv)
    try:
        app.setStyle("windows11")
    except Exception:  # noqa: BLE001
        try:
            app.setStyle("Fusion")
        except Exception:  # noqa: BLE001
            pass
    ventana = _DemoWindow()
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(_main())
