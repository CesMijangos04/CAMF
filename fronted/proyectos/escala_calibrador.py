"""
escala_calibrador.py — Flujo de calibración de escala + medición del canvas.

Sesión B del canvas de Proyectos.

Calibración de escala (2 clicks + distancia real → EscalaCalibrada):
  * EscalaCalibrada — dataclass inmutable con la conversión pt PDF ↔ m.
  * CalibradorEscala — state machine del flujo de 2 clicks + diálogo.
  * GuiaCalibracion — item visual dibujado sobre el canvas durante la
    calibración (cruces + línea punteada, tamaños ajustados al zoom).
  * DialogoDistanciaReal — QDialog modal que pide la distancia real.

Medición (validación de la calibración usando la escala ya aplicada):
  * MedicionCalibrada — dataclass con los 2 puntos y su distancia real.
  * MedidorDistancia — state machine "continua": cada 2 clicks emiten
    una nueva MedicionCalibrada. Diseñado para validar la escala.
  * MedicionItem — item persistente dibujado en el canvas (línea con
    círculos + etiqueta con la distancia en metros).

Flujo típico:

    from escala_calibrador import CalibradorEscala, DialogoDistanciaReal

    cal = CalibradorEscala(canvas)
    cal.calibracion_completada.connect(canvas.set_escala)
    cal.listo_para_distancia.connect(lambda a, b, d: _pedir_distancia(cal, d))

    def _pedir_distancia(cal, dist_pt):
        dlg = DialogoDistanciaReal(dist_pt, parent=window)
        if dlg.exec():
            cal.confirmar_distancia_real(dlg.distancia_metros())
        else:
            cal.cancelar()

    cal.iniciar()   # el canvas empieza a delegarle clicks

Convenciones del módulo Proyectos:
  * Self-contained: paleta y estilos replicados aquí.
  * QFrame con border SIEMPRE via objectName.
  * QDoubleSpinBox con _NoWheelDoubleSpinBox local — la rueda del mouse
    NUNCA debe cambiar valores accidentalmente (en el canvas la rueda
    es zoom).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PyQt6.QtCore import Qt, QPointF, QRectF, QObject, pyqtSignal
from PyQt6.QtGui import (
    QColor, QPen, QPainter, QFont, QBrush, QFontMetricsF,
    QPainterPath, QPainterPathStroker,
)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QPushButton, QWidget, QGraphicsObject, QGraphicsItem,
    QStyleOptionGraphicsItem,
)


# ---------------------------------------------------------------------------
# Paleta CAMF (replicada localmente)
# ---------------------------------------------------------------------------

COLOR_FONDO         = "#121212"
COLOR_HEADER        = "#141414"
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

# Colores específicos de la guía de calibración
COLOR_GUIA_LINEA = "#0094ff"
COLOR_GUIA_PUNTO = "#00c8ff"


# ---------------------------------------------------------------------------
# EscalaCalibrada — modelo inmutable de la escala px↔m del plano
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PuntoDeCalibracion:
    """Un par de puntos del plano + la distancia real que representan.

    Es la unidad básica de la calibración: cada vez que el usuario
    hace 2 clics + ingresa una distancia, produce uno de estos. La
    EscalaCalibrada agrupa uno o más de estos para calcular el factor
    de conversión pt PDF ↔ metros.
    """
    punto_a_pdf: QPointF
    punto_b_pdf: QPointF
    distancia_real_m: float

    @property
    def distancia_pdf_pt(self) -> float:
        return math.hypot(
            self.punto_b_pdf.x() - self.punto_a_pdf.x(),
            self.punto_b_pdf.y() - self.punto_a_pdf.y(),
        )


@dataclass(frozen=True)
class EscalaCalibrada:
    """Escala calibrada del plano. Convierte puntos PDF ↔ metros reales.

    Se compone de UNO o MÁS `PuntoDeCalibracion`. Con 1 solo punto, la
    escala = distancia_real / distancia_pt. Con N puntos, la escala se
    calcula por **mínimos cuadrados** (línea que pasa por el origen):

        k = Σ(d_pt[i] × d_m[i]) / Σ(d_pt[i]²)

    Esta fórmula da más peso a mediciones largas (que son más
    confiables porque el error de clic tiene menor peso relativo).
    Con N puntos, el error de la escala disminuye aproximadamente
    por factor √N respecto a 1 punto.

    Es inmutable: `con_punto_adicional()` devuelve una nueva instancia
    con el punto agregado, sin mutar la existente.
    """
    puntos: tuple[PuntoDeCalibracion, ...]

    def __post_init__(self) -> None:
        if len(self.puntos) == 0:
            raise ValueError("EscalaCalibrada requiere al menos 1 punto")

    # ---- Propiedades legacy (compatibilidad con código de 1 punto) ----

    @property
    def punto_a_pdf(self) -> QPointF:
        """Primer punto A (del primer PuntoDeCalibracion)."""
        return self.puntos[0].punto_a_pdf

    @property
    def punto_b_pdf(self) -> QPointF:
        """Primer punto B (del primer PuntoDeCalibracion)."""
        return self.puntos[0].punto_b_pdf

    @property
    def distancia_real_m(self) -> float:
        """Distancia real del PRIMER punto (legacy)."""
        return self.puntos[0].distancia_real_m

    @property
    def distancia_pdf_pt(self) -> float:
        """Distancia en pt del PRIMER punto (legacy)."""
        return self.puntos[0].distancia_pdf_pt

    # ---- Factor de escala (mínimos cuadrados) ----

    @property
    def m_por_pt(self) -> float:
        """Metros por punto PDF, por mínimos cuadrados sobre todos los
        puntos de calibración."""
        num = sum(
            p.distancia_pdf_pt * p.distancia_real_m for p in self.puntos
        )
        den = sum(p.distancia_pdf_pt ** 2 for p in self.puntos)
        if den <= 0:
            return 0.0
        return num / den

    @property
    def pt_por_m(self) -> float:
        k = self.m_por_pt
        if k <= 0:
            return 0.0
        return 1.0 / k

    # ---- Conversiones ----

    def pt_a_m(self, dist_pt: float) -> float:
        return dist_pt * self.m_por_pt

    def m_a_pt(self, dist_m: float) -> float:
        return dist_m * self.pt_por_m

    def punto_pt_a_m(self, p: QPointF) -> QPointF:
        f = self.m_por_pt
        return QPointF(p.x() * f, p.y() * f)

    def punto_m_a_pt(self, p: QPointF) -> QPointF:
        f = self.pt_por_m
        return QPointF(p.x() * f, p.y() * f)

    # ---- Composición ----

    def con_punto_adicional(
        self, punto: PuntoDeCalibracion
    ) -> "EscalaCalibrada":
        """Devuelve una NUEVA EscalaCalibrada con el punto añadido al
        conjunto. La escala resultante se recalcula por mínimos
        cuadrados sobre todos los puntos."""
        return EscalaCalibrada(puntos=(*self.puntos, punto))

    # ---- Diagnóstico de calidad ----

    def error_maximo_m(self) -> float:
        """Máxima desviación (en metros) entre la distancia real
        ingresada por el usuario y lo que la escala calculada da para
        esos mismos dos puntos. Con 1 punto es siempre 0. Con N puntos
        es la medida de qué tan consistentes son entre sí — cuanto
        más chico, mejor calibración."""
        k = self.m_por_pt
        errores = [
            abs(p.distancia_pdf_pt * k - p.distancia_real_m)
            for p in self.puntos
        ]
        return max(errores) if errores else 0.0

    def error_promedio_m(self) -> float:
        k = self.m_por_pt
        errores = [
            abs(p.distancia_pdf_pt * k - p.distancia_real_m)
            for p in self.puntos
        ]
        return sum(errores) / len(errores) if errores else 0.0

    def cantidad_puntos(self) -> int:
        return len(self.puntos)

    # ---- Resúmenes legibles ----

    def resumen_legible(self) -> str:
        """Cadena corta para el status bar."""
        n = len(self.puntos)
        try:
            escala_1_a_n = 1.0 / (self.m_por_pt / 0.000352778)
            base = f"1 pt = {self.m_por_pt:.4f} m  ·  ≈ 1:{escala_1_a_n:.0f}"
        except Exception:  # noqa: BLE001
            base = f"1 pt = {self.m_por_pt:.4f} m"
        if n == 1:
            return base
        err_cm = self.error_maximo_m() * 100.0
        return f"{base}  ·  {n} pts  ·  máx ±{err_cm:.2f} cm"


# ---------------------------------------------------------------------------
# CalibradorEscala — state machine del flujo de calibración
# ---------------------------------------------------------------------------

class _EstadoCalibracion(Enum):
    INACTIVO = 0
    ESPERANDO_PRIMER_PUNTO = 1
    ESPERANDO_SEGUNDO_PUNTO = 2


class CalibradorEscala(QObject):
    """State machine del flujo de calibración.

    Calibra con N puntos de referencia (típicamente 3). Cada punto son
    2 clics + distancia real. Al completar todos, se calcula la escala
    por mínimos cuadrados sobre el conjunto.

    Flujo del usuario:
      1. iniciar(num_puntos=3)  →  state machine arranca.
      2. Para cada punto N:
         - Usuario hace primer clic → registrar_click(pt).
         - Usuario hace segundo clic → registrar_click(pt) → emite
           listo_para_distancia (el UI abre diálogo).
         - Usuario acepta distancia → confirmar_distancia_real(m).
         - Si aún faltan puntos, el state machine vuelve a esperar
           el primer clic del siguiente punto.
         - Si es el último, se emite calibracion_completada.
      3. En cualquier momento, cancelar() aborta TODO el flujo
         (los puntos ya completados en esta sesión se descartan).

    Signals emitidas:
      * calibracion_iniciada — al empezar el flujo.
      * primer_punto_cambiado(QPointF) — cuando se registra el 1er clic
        del punto actual (para actualizar la guía visual).
      * listo_para_distancia(QPointF a, QPointF b, float dist_pt, int
        indice_1_based, int total) — cuando se registra el 2do clic
        válido del punto actual. El receptor debe abrir el diálogo y
        llamar confirmar_distancia_real() o cancelar().
      * calibracion_completada(EscalaCalibrada) — cuando el ÚLTIMO
        punto se confirma y la escala completa queda aplicada.
      * calibracion_cancelada — en cualquier momento por Escape o el
        cancel del diálogo.
      * estado_mensaje(str) — texto para el status bar.
    """

    calibracion_iniciada    = pyqtSignal()
    primer_punto_cambiado   = pyqtSignal(QPointF)
    listo_para_distancia    = pyqtSignal(QPointF, QPointF, float, int, int)
    calibracion_completada  = pyqtSignal(object)   # EscalaCalibrada
    calibracion_cancelada   = pyqtSignal()
    estado_mensaje          = pyqtSignal(str)

    DISTANCIA_MIN_PT = 5.0

    # Número recomendado de puntos por default. Con 3 el error de la
    # escala baja ~42% respecto a 1 punto por la propagación de errores
    # aleatorios del clic humano.
    NUM_PUNTOS_DEFAULT = 3

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._estado = _EstadoCalibracion.INACTIVO
        self._punto_a: Optional[QPointF] = None
        self._punto_b: Optional[QPointF] = None

        # Multi-punto: puntos ya confirmados en la sesión actual
        self._puntos_completados: list[PuntoDeCalibracion] = []
        self._puntos_requeridos: int = 1

    # -------------------------------------------------------- consulta

    def esta_activo(self) -> bool:
        return self._estado != _EstadoCalibracion.INACTIVO

    def esperando_primer_punto(self) -> bool:
        return self._estado == _EstadoCalibracion.ESPERANDO_PRIMER_PUNTO

    def esperando_segundo_punto(self) -> bool:
        return self._estado == _EstadoCalibracion.ESPERANDO_SEGUNDO_PUNTO

    def punto_a(self) -> Optional[QPointF]:
        return self._punto_a

    # --------------------------------------------------------- control

    def iniciar(self, num_puntos: int = NUM_PUNTOS_DEFAULT) -> None:
        """Arranca el flujo de calibración con `num_puntos` puntos de
        referencia. Cada punto es una operación de 2 clics + distancia
        real. Con num_puntos=1 el comportamiento es idéntico al de una
        calibración simple; con >1 se acumulan y se aplica mínimos
        cuadrados al terminar.
        """
        self._puntos_requeridos = max(1, int(num_puntos))
        self._puntos_completados = []
        self._estado = _EstadoCalibracion.ESPERANDO_PRIMER_PUNTO
        self._punto_a = None
        self._punto_b = None
        self.calibracion_iniciada.emit()
        self._emitir_mensaje_esperar_primer()

    def cancelar(self) -> None:
        if not self.esta_activo():
            return
        self._reset()
        self.calibracion_cancelada.emit()
        self.estado_mensaje.emit("Calibración cancelada")

    def _indice_punto_actual(self) -> int:
        """Índice 1-based del punto que se está capturando ahora."""
        return len(self._puntos_completados) + 1

    def _emitir_mensaje_esperar_primer(self) -> None:
        idx = self._indice_punto_actual()
        total = self._puntos_requeridos
        if total <= 1:
            self.estado_mensaje.emit(
                "Calibración: clic en el primer punto de una distancia conocida"
            )
        else:
            self.estado_mensaje.emit(
                f"Calibración · Punto {idx} de {total}: "
                "clic en el primer punto de una distancia conocida"
            )

    def _emitir_mensaje_esperar_segundo(self) -> None:
        idx = self._indice_punto_actual()
        total = self._puntos_requeridos
        if total <= 1:
            self.estado_mensaje.emit(
                "Calibración: clic en el segundo punto"
            )
        else:
            self.estado_mensaje.emit(
                f"Calibración · Punto {idx} de {total}: "
                "clic en el segundo punto"
            )

    def registrar_click(self, punto_pdf: QPointF) -> bool:
        """Registra un clic del usuario en coords de puntos PDF.

        Devuelve True si el clic fue procesado, False si el calibrador
        no está activo o el clic no aplicaba.
        """
        if self._estado == _EstadoCalibracion.ESPERANDO_PRIMER_PUNTO:
            self._punto_a = QPointF(punto_pdf)
            self._estado = _EstadoCalibracion.ESPERANDO_SEGUNDO_PUNTO
            self.primer_punto_cambiado.emit(self._punto_a)
            self._emitir_mensaje_esperar_segundo()
            return True

        if self._estado == _EstadoCalibracion.ESPERANDO_SEGUNDO_PUNTO:
            if self._punto_a is None:
                return False
            dist = math.hypot(
                punto_pdf.x() - self._punto_a.x(),
                punto_pdf.y() - self._punto_a.y(),
            )
            if dist < self.DISTANCIA_MIN_PT:
                self.estado_mensaje.emit(
                    "Distancia muy pequeña. Elige otro punto."
                )
                return True
            self._punto_b = QPointF(punto_pdf)
            # Emitir con progreso para que el UI muestre "Punto N de M"
            self.listo_para_distancia.emit(
                self._punto_a, self._punto_b, dist,
                self._indice_punto_actual(),
                self._puntos_requeridos,
            )
            return True

        return False

    def confirmar_distancia_real(self, distancia_m: float) -> None:
        """Aplica la distancia real ingresada por el usuario para el
        punto actual. Si faltan puntos, avanza al siguiente. Si es el
        último, calcula la escala final por mínimos cuadrados y emite
        `calibracion_completada`."""
        if self._punto_a is None or self._punto_b is None:
            self.cancelar()
            return
        dist_pt = math.hypot(
            self._punto_b.x() - self._punto_a.x(),
            self._punto_b.y() - self._punto_a.y(),
        )
        if dist_pt <= 0 or distancia_m <= 0:
            self.cancelar()
            return

        punto = PuntoDeCalibracion(
            punto_a_pdf=QPointF(self._punto_a),
            punto_b_pdf=QPointF(self._punto_b),
            distancia_real_m=float(distancia_m),
        )
        self._puntos_completados.append(punto)

        # ¿Aún faltan puntos? — volver a esperar el primer clic del
        # siguiente par, sin resetear los puntos ya acumulados.
        if len(self._puntos_completados) < self._puntos_requeridos:
            self._punto_a = None
            self._punto_b = None
            self._estado = _EstadoCalibracion.ESPERANDO_PRIMER_PUNTO
            self._emitir_mensaje_esperar_primer()
            return

        # Último punto: aplicar escala con TODOS los puntos capturados.
        escala = EscalaCalibrada(puntos=tuple(self._puntos_completados))
        self._reset()
        self.calibracion_completada.emit(escala)
        self.estado_mensaje.emit(
            f"Escala aplicada: {escala.resumen_legible()}"
        )

    def escala_parcial(self) -> Optional[EscalaCalibrada]:
        """Devuelve la escala calculada con los puntos ya confirmados
        hasta ahora en la sesión actual, o None si no hay ninguno.
        Útil para que el diálogo muestre cuánto darían los puntos ya
        capturados sin comprometerse todavía a aplicar la escala."""
        if not self._puntos_completados:
            return None
        return EscalaCalibrada(puntos=tuple(self._puntos_completados))

    def _reset(self) -> None:
        self._estado = _EstadoCalibracion.INACTIVO
        self._punto_a = None
        self._punto_b = None
        self._puntos_completados = []


# ---------------------------------------------------------------------------
# GuiaCalibracion — item visual sobre el canvas
# ---------------------------------------------------------------------------

class GuiaCalibracion(QGraphicsObject):
    """Item visual que se dibuja en el canvas durante la calibración.

    Muestra:
      * Una cruz azul brillante en el primer punto seleccionado.
      * Cuando hay primer punto, una línea punteada del primer punto
        al cursor actual.
      * Una cruz azul brillante en el cursor (segundo punto potencial).

    Los tamaños se ajustan al zoom del viewport, así los elementos
    visuales se ven del mismo tamaño en pantalla independientemente
    del nivel de zoom.

    El item NO captura eventos — solo dibuja. Los clicks los recibe
    directamente el canvas (que se los pasa al CalibradorEscala).
    """

    def __init__(self, parent: Optional[QGraphicsItem] = None) -> None:
        super().__init__(parent)
        self._punto_a: Optional[QPointF] = None
        self._cursor: Optional[QPointF] = None
        self._page_rect: Optional[QRectF] = None
        # Z muy alto: por encima incluso de la etapa de elementos.
        self.setZValue(10_000)
        # No interactuable
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def set_page_rect(self, rect: QRectF) -> None:
        """Actualiza el boundingRect al tamaño del plano actual."""
        self.prepareGeometryChange()
        self._page_rect = QRectF(rect)

    def set_punto_a(self, punto: Optional[QPointF]) -> None:
        self._punto_a = QPointF(punto) if punto is not None else None
        self.update()

    def set_cursor(self, punto: Optional[QPointF]) -> None:
        self._cursor = QPointF(punto) if punto is not None else None
        self.update()

    def limpiar(self) -> None:
        self._punto_a = None
        self._cursor = None
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        if self._page_rect is not None:
            # Margen amplio para que la línea al cursor nunca quede
            # fuera del boundingRect (Qt clipearía el paint).
            margen = max(self._page_rect.width(), self._page_rect.height())
            return self._page_rect.adjusted(
                -margen, -margen, margen, margen
            )
        return QRectF(-10000, -10000, 30000, 30000)

    def paint(  # noqa: N802
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: Optional[QWidget] = None,
    ) -> None:
        if self._punto_a is None:
            return

        # Escalar tamaños al zoom del viewport para que los elementos
        # visuales tengan siempre el mismo tamaño en pantalla.
        transform = painter.worldTransform()
        scale = math.hypot(transform.m11(), transform.m12())
        if scale <= 0:
            scale = 1.0

        cruz_size = 10.0 / scale
        cruz_grosor = max(2.0 / scale, 0.5)
        linea_grosor = max(2.0 / scale, 0.5)

        cursor = self._cursor if self._cursor is not None else self._punto_a

        # --- Línea del primer punto al cursor
        pen_linea = QPen(QColor(COLOR_GUIA_LINEA))
        pen_linea.setWidthF(linea_grosor)
        pen_linea.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen_linea.setStyle(Qt.PenStyle.CustomDashLine)
        pen_linea.setDashPattern([5.0, 3.0])  # en múltiplos de grosor
        painter.setPen(pen_linea)
        painter.drawLine(self._punto_a, cursor)

        # --- Cruz en el primer punto
        pen_cruz = QPen(QColor(COLOR_GUIA_PUNTO))
        pen_cruz.setWidthF(cruz_grosor)
        pen_cruz.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_cruz)
        self._dibujar_cruz(painter, self._punto_a, cruz_size)

        # --- Cruz en el cursor (si es distinto del primer punto)
        if self._cursor is not None and self._cursor != self._punto_a:
            self._dibujar_cruz(painter, self._cursor, cruz_size)

    @staticmethod
    def _dibujar_cruz(
        painter: QPainter, centro: QPointF, size: float
    ) -> None:
        painter.drawLine(
            QPointF(centro.x() - size, centro.y() - size),
            QPointF(centro.x() + size, centro.y() + size),
        )
        painter.drawLine(
            QPointF(centro.x() + size, centro.y() - size),
            QPointF(centro.x() - size, centro.y() + size),
        )


# ---------------------------------------------------------------------------
# _NoWheelDoubleSpinBox — spinbox que NO cambia valor con la rueda
# ---------------------------------------------------------------------------

class _NoWheelDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox que ignora la rueda del mouse.

    Convención del módulo Proyectos: la rueda del mouse la usamos SOLO
    para zoom del canvas. Ningún spinbox debe interceptarla.
    """

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


# ---------------------------------------------------------------------------
# DialogoDistanciaReal — diálogo modal para la distancia real
# ---------------------------------------------------------------------------

class DialogoDistanciaReal(QDialog):
    """Diálogo modal para ingresar la distancia real entre los 2 puntos
    seleccionados en el plano."""

    def __init__(
        self,
        distancia_pdf_pt: float,
        parent: Optional[QWidget] = None,
        valor_sugerido_m: float = 1.0,
        escala_previa: Optional[EscalaCalibrada] = None,
        indice_punto: int = 1,
        total_puntos: int = 1,
        escala_parcial: Optional[EscalaCalibrada] = None,
    ) -> None:
        super().__init__(parent)
        self._indice = int(indice_punto)
        self._total = int(total_puntos)
        self._es_ultimo = (self._indice >= self._total)

        self.setWindowTitle("Calibrar escala del plano")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedSize(480, 360)
        self.setStyleSheet(self._stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)

        # Título con progreso: "Punto 2 de 3 · Distancia real"
        if self._total > 1:
            titulo_txt = (
                f"Punto {self._indice} de {self._total} · "
                "Distancia real entre los dos puntos"
            )
        else:
            titulo_txt = "Distancia real entre los dos puntos"
        titulo = QLabel(titulo_txt)
        titulo.setObjectName("tituloDialogo")
        layout.addWidget(titulo)

        explicacion = QLabel(
            f"Los dos puntos están a <b>{distancia_pdf_pt:.1f} pt</b> en el "
            "plano. Ingresa la distancia real que representa esa medida "
            "en el mundo:"
        )
        explicacion.setObjectName("descripcionDialogo")
        explicacion.setWordWrap(True)
        layout.addWidget(explicacion)

        # Comparativa: si hay escala PARCIAL (puntos ya capturados en
        # esta misma sesión), mostrar cuánto medirían los puntos
        # actuales con esa escala parcial. Muy útil para consistencia.
        if escala_parcial is not None:
            estimado_m = float(escala_parcial.pt_a_m(distancia_pdf_pt))
            n = escala_parcial.cantidad_puntos()
            comparativa = QLabel(
                f"<b>Con los {n} punto(s) ya capturados</b>, la distancia "
                f"actual daría <b>{estimado_m:.2f} m</b>. Si tu medida real "
                "coincide o es muy cercana, la calibración está siendo "
                "consistente."
            )
            comparativa.setObjectName("comparativaDialogo")
            comparativa.setWordWrap(True)
            layout.addWidget(comparativa)
        elif escala_previa is not None:
            # Comparativa contra la escala del plano vigente (una
            # recalibración desde cero, sin puntos parciales aún)
            estimado_m = float(escala_previa.pt_a_m(distancia_pdf_pt))
            comparativa = QLabel(
                f"<b>Escala vigente:</b> con la escala actual del plano, "
                f"esos dos puntos miden <b>{estimado_m:.2f} m</b>."
            )
            comparativa.setObjectName("comparativaDialogo")
            comparativa.setWordWrap(True)
            layout.addWidget(comparativa)

        # Tip de precisión
        if self._total > 1 and self._indice < self._total:
            tip_txt = (
                "<b>Para máxima precisión:</b> usa cotas <b>largas y "
                "distintas entre sí</b> (una horizontal, otra vertical, "
                "otra diagonal). Con <b>Shift</b> mantenido, los clics se "
                "ajustan a horizontal o vertical exactos."
            )
        else:
            tip_txt = (
                "<b>Para máxima precisión:</b> usa la cota más <b>larga</b> "
                "disponible. Con <b>Shift</b> mantenido, los clics se "
                "ajustan a horizontal o vertical exactos."
            )
        tip = QLabel(tip_txt)
        tip.setObjectName("tipDialogo")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # Spinbox
        fila = QHBoxLayout()
        fila.setSpacing(0)
        self._spinbox = _NoWheelDoubleSpinBox()
        self._spinbox.setObjectName("distanciaInput")
        self._spinbox.setDecimals(3)
        self._spinbox.setMinimum(0.001)
        self._spinbox.setMaximum(9999.999)
        self._spinbox.setValue(float(valor_sugerido_m))
        self._spinbox.setSingleStep(0.1)
        self._spinbox.setSuffix(" m")
        self._spinbox.setAlignment(Qt.AlignmentFlag.AlignRight)
        fila.addWidget(self._spinbox)
        layout.addLayout(fila)

        layout.addStretch(1)

        # Botones
        botones = QHBoxLayout()
        botones.setSpacing(8)
        botones.addStretch(1)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("secundario")
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_cancelar.clicked.connect(self.reject)
        botones.addWidget(btn_cancelar)

        # Texto del botón principal: "Siguiente punto" para los
        # intermedios, "Aplicar escala" para el último (o único).
        if self._es_ultimo:
            texto_ok = "Aplicar escala"
        else:
            texto_ok = "Siguiente punto →"
        btn_ok = QPushButton(texto_ok)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        botones.addWidget(btn_ok)

        layout.addLayout(botones)

        # Focus + selección total del texto para que el usuario
        # empiece a escribir la distancia sin ningún clic extra.
        self._spinbox.setFocus()
        self._spinbox.selectAll()

    def distancia_metros(self) -> float:
        return float(self._spinbox.value())

    def _stylesheet(self) -> str:
        return f"""
            QDialog {{
                background-color: {COLOR_FONDO};
                color: {COLOR_TEXTO_SUAVE};
            }}
            QLabel {{
                color: {COLOR_TEXTO_SUAVE};
                font-size: 12px;
            }}
            QLabel#tituloDialogo {{
                color: {COLOR_TEXTO};
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 4px;
            }}
            QLabel#descripcionDialogo {{
                color: {COLOR_TEXTO_MUTED};
                font-size: 12px;
                padding-bottom: 6px;
            }}
            QLabel#comparativaDialogo {{
                color: {COLOR_TEXTO_SUAVE};
                background-color: {COLOR_INPUT_BG};
                border: 1px solid {COLOR_BORDE_FUERTE};
                border-radius: 4px;
                padding: 8px 10px;
                font-size: 12px;
            }}
            QLabel#tipDialogo {{
                color: {COLOR_TEXTO_MUTED};
                background-color: transparent;
                border-left: 3px solid {COLOR_ACENTO};
                padding: 8px 10px;
                font-size: 11px;
            }}
            QDoubleSpinBox {{
                background-color: {COLOR_INPUT_BG};
                color: {COLOR_TEXTO};
                border: 1px solid {COLOR_BORDE_FUERTE};
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 14px;
                min-height: 20px;
                selection-background-color: {COLOR_ACENTO};
            }}
            QDoubleSpinBox:focus {{
                border-color: {COLOR_ACENTO};
            }}
            QPushButton {{
                background-color: {COLOR_ACENTO};
                color: {COLOR_TEXTO};
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 12px;
                min-width: 100px;
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {COLOR_ACENTO_BRILL};
            }}
            QPushButton:default {{
                border: 1px solid {COLOR_ACENTO_BRILL};
            }}
            QPushButton#secundario {{
                background-color: {COLOR_INPUT_BG};
                color: {COLOR_TEXTO_SUAVE};
            }}
            QPushButton#secundario:hover {{
                background-color: {COLOR_BORDE_FUERTE};
                color: {COLOR_TEXTO};
            }}
        """


# ---------------------------------------------------------------------------
# MedicionCalibrada — resultado de una medición ya calibrada
# ---------------------------------------------------------------------------

# Color de las mediciones. Distinto al azul de la calibración para que
# sea obvio de un vistazo cuál es cada cosa.
COLOR_MEDICION_LINEA  = "#ff9a3d"   # naranja cálido
COLOR_MEDICION_PUNTO  = "#ffb84d"
COLOR_MEDICION_TEXTO  = "#ffffff"
COLOR_MEDICION_BG     = "#1a1a1a"

# Color de resaltado cuando el usuario está en modo "borrar individual"
# y pasa el mouse sobre una medición. Rojo brillante → señal clara de
# "vas a eliminar esto".
COLOR_MEDICION_BORRAR = "#ff4d4d"


@dataclass(frozen=True)
class MedicionCalibrada:
    """Una medición hecha por el usuario sobre el plano.

    Si la escala estaba calibrada al hacer la medición, `distancia_m`
    tiene la distancia real. Si no había escala, `distancia_m` es None
    y solo `distancia_pt` está disponible.
    """
    punto_a: QPointF
    punto_b: QPointF
    distancia_pt: float
    distancia_m: Optional[float]

    def texto_legible(self) -> str:
        # Siempre en metros con 2 decimales, para poder comparar
        # directamente contra las cotas del arquitecto (que suelen venir
        # en el plano así: 0.85, 1.30, 2.61). Sin salto a cm/mm.
        if self.distancia_m is not None:
            return f"{self.distancia_m:.2f} m"
        return f"{self.distancia_pt:.1f} pt"


# ---------------------------------------------------------------------------
# MedidorDistancia — state machine "continua" de medición
# ---------------------------------------------------------------------------

class MedidorDistancia(QObject):
    """Herramienta de medición continua sobre el canvas.

    Diseñada para ser usada como una herramienta activa: mientras esté
    activo, cada par de clicks del usuario produce una MedicionCalibrada
    (que el canvas convierte en un MedicionItem persistente). Se activa
    y desactiva desde el canvas cuando el usuario cambia de herramienta.

    Signals:
      * primer_punto_registrado(QPointF) — actualiza la guía visual.
      * medicion_completada(MedicionCalibrada) — el canvas dibuja el item.
      * medicion_cancelada — usuario apretó Escape entre clicks.
      * estado_mensaje(str) — mensaje para el status bar.

    Recibe la escala actual por callable inyectado (`escala_getter`), en
    lugar de tener una referencia directa. Así el medidor no depende del
    canvas concretamente y la escala se consulta siempre a "última hora".
    """

    primer_punto_registrado = pyqtSignal(QPointF)
    medicion_completada     = pyqtSignal(object)   # MedicionCalibrada
    medicion_cancelada      = pyqtSignal()
    estado_mensaje          = pyqtSignal(str)

    DISTANCIA_MIN_PT = 2.0

    def __init__(self, escala_getter, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._escala_getter = escala_getter
        self._activo: bool = False
        self._punto_a: Optional[QPointF] = None

    def esta_activo(self) -> bool:
        return self._activo

    def esperando_segundo_punto(self) -> bool:
        return self._activo and self._punto_a is not None

    def punto_a(self) -> Optional[QPointF]:
        return self._punto_a

    def activar(self) -> None:
        self._activo = True
        self._punto_a = None
        self.estado_mensaje.emit(
            "Medir: clic en el primer punto"
        )

    def desactivar(self) -> None:
        if not self._activo:
            return
        self._activo = False
        self._punto_a = None
        self.medicion_cancelada.emit()

    def cancelar_medicion_en_curso(self) -> None:
        """Descarta un primer clic ya registrado, sin desactivar la
        herramienta. Se dispara con Escape."""
        if self._punto_a is not None:
            self._punto_a = None
            self.medicion_cancelada.emit()
            self.estado_mensaje.emit("Medir: clic en el primer punto")

    def registrar_click(self, punto_pdf: QPointF) -> bool:
        if not self._activo:
            return False
        if self._punto_a is None:
            self._punto_a = QPointF(punto_pdf)
            self.primer_punto_registrado.emit(self._punto_a)
            self.estado_mensaje.emit(
                "Medir: clic en el segundo punto"
            )
            return True

        dist_pt = math.hypot(
            punto_pdf.x() - self._punto_a.x(),
            punto_pdf.y() - self._punto_a.y(),
        )
        if dist_pt < self.DISTANCIA_MIN_PT:
            self.estado_mensaje.emit("Distancia muy pequeña, elige otro punto")
            return True

        escala = self._escala_getter()
        dist_m = escala.pt_a_m(dist_pt) if escala is not None else None

        medicion = MedicionCalibrada(
            punto_a=QPointF(self._punto_a),
            punto_b=QPointF(punto_pdf),
            distancia_pt=float(dist_pt),
            distancia_m=(float(dist_m) if dist_m is not None else None),
        )
        self._punto_a = None
        self.medicion_completada.emit(medicion)
        self.estado_mensaje.emit(
            f"Medido: {medicion.texto_legible()}  ·  clic para nueva medición"
        )
        return True


# ---------------------------------------------------------------------------
# MedicionItem — visual persistente de una medición sobre el canvas
# ---------------------------------------------------------------------------

class MedicionItem(QGraphicsObject):
    """Item persistente que dibuja una MedicionCalibrada sobre el canvas.

    Se dibuja como:
      * Línea sólida naranja entre los dos puntos.
      * Círculos rellenos en los extremos.
      * Etiqueta con la distancia (en metros o cm o pt según el rango)
        en el punto medio de la línea, con fondo semitransparente para
        legibilidad y tamaño constante en pantalla independientemente
        del zoom.

    El item ignora clicks — es solo un indicador visual. Se elimina
    llamando a `scene().removeItem(item)` desde el canvas.
    """

    _MARGEN_BBOX = 200.0  # espacio extra alrededor de la línea para la etiqueta

    def __init__(self, medicion: MedicionCalibrada, parent: Optional[QGraphicsItem] = None) -> None:
        super().__init__(parent)
        self._medicion = medicion
        self._resaltado_borrar: bool = False
        self._modo_borrar_activo: bool = False
        self.setZValue(500)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def medicion(self) -> MedicionCalibrada:
        return self._medicion

    def set_modo_borrar_activo(self, activo: bool) -> None:
        """Activa la interactividad del item para el flujo de borrar
        una-por-una. Cuando activo, el item acepta hover events y se
        colorea de rojo al pasar el mouse encima. Cuando inactivo, se
        comporta como decorativo (no captura mouse)."""
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

    def boundingRect(self) -> QRectF:  # noqa: N802
        pa = self._medicion.punto_a
        pb = self._medicion.punto_b
        rect = QRectF(
            min(pa.x(), pb.x()), min(pa.y(), pb.y()),
            abs(pb.x() - pa.x()), abs(pb.y() - pa.y()),
        )
        return rect.adjusted(
            -self._MARGEN_BBOX, -self._MARGEN_BBOX,
            self._MARGEN_BBOX, self._MARGEN_BBOX,
        )

    def shape(self) -> QPainterPath:  # noqa: N802
        """Geometría real del item para colisiones de mouse (hover, clic).

        Sin este método, Qt usa boundingRect() para decidir si el
        cursor está "sobre" el item — como boundingRect es un rect que
        envuelve línea + etiqueta + márgenes generosos, cuando dos
        mediciones están en zonas cercanas del plano sus bounding
        rects se solapan y Qt reporta ambos ítems como bajo el cursor,
        aunque el mouse esté sobre la línea de solo uno. Al devolver
        aquí un path que es solo la línea (con un grosor de tolerancia
        para hover) + círculos en los extremos, solo el item cuya
        LÍNEA realmente pase bajo el cursor reacciona.
        """
        pa = self._medicion.punto_a
        pb = self._medicion.punto_b

        line_path = QPainterPath()
        line_path.moveTo(pa)
        line_path.lineTo(pb)

        stroker = QPainterPathStroker()
        # Grosor de tolerancia de hover en pt PDF. ~10 pt ≈ 3.5 mm
        # reales, o ~1-2 cm en pantalla a zoom típico. Bastante para
        # no exigir precisión al usuario, poco para no solapar
        # mediciones cercanas.
        stroker.setWidth(10.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroked = stroker.createStroke(line_path)

        # Área hover generosa alrededor de los círculos de los extremos
        # (donde el usuario probablemente hace clic cuando quiere ese
        # extremo en particular).
        stroked.addEllipse(pa, 8.0, 8.0)
        stroked.addEllipse(pb, 8.0, 8.0)

        return stroked

    def paint(  # noqa: N802
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: Optional[QWidget] = None,
    ) -> None:
        # Escala del viewport — sirve para dibujar elementos con tamaño
        # constante en pantalla (dividimos por scale).
        transform = painter.worldTransform()
        scale = math.hypot(transform.m11(), transform.m12())
        if scale <= 0:
            scale = 1.0

        pa = self._medicion.punto_a
        pb = self._medicion.punto_b

        # Grosor ligeramente más grueso cuando resaltado, para que sea
        # aún más obvio "vas a eliminar esto".
        grosor_base = max(2.0 / scale, 0.5)
        grosor = grosor_base * (1.5 if self._resaltado_borrar else 1.0)
        radio_punto = 4.0 / scale

        color_principal = QColor(
            COLOR_MEDICION_BORRAR if self._resaltado_borrar
            else COLOR_MEDICION_LINEA
        )
        color_punto = QColor(
            COLOR_MEDICION_BORRAR if self._resaltado_borrar
            else COLOR_MEDICION_PUNTO
        )

        # --- Línea sólida
        pen = QPen(color_principal)
        pen.setWidthF(grosor)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(pa, pb)

        # --- Círculos en los extremos
        painter.setBrush(QBrush(color_punto))
        painter.setPen(QPen(color_principal, grosor))
        painter.drawEllipse(pa, radio_punto, radio_punto)
        painter.drawEllipse(pb, radio_punto, radio_punto)

        # --- Etiqueta con la distancia, tamaño constante en pantalla.
        # Truco: nos posicionamos en el centro (coords locales) y
        # deshacemos la escala del viewport para dibujar el texto en
        # tamaño lógico normal.
        centro = QPointF((pa.x() + pb.x()) / 2.0, (pa.y() + pb.y()) / 2.0)
        texto = self._medicion.texto_legible()

        painter.save()
        painter.translate(centro)
        painter.scale(1.0 / scale, 1.0 / scale)

        fuente = QFont()
        fuente.setPointSize(11)
        fuente.setBold(True)
        painter.setFont(fuente)
        metrics = QFontMetricsF(fuente)
        ancho_txt = metrics.horizontalAdvance(texto)
        alto_txt = metrics.height()

        pad_x = 8.0
        pad_y = 3.0
        rect_bg = QRectF(
            -ancho_txt / 2 - pad_x, -alto_txt / 2 - pad_y,
            ancho_txt + 2 * pad_x, alto_txt + 2 * pad_y,
        )
        # Fondo con leve transparencia
        bg = QColor(COLOR_MEDICION_BG)
        bg.setAlpha(230)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(color_principal, 1.2))
        painter.drawRoundedRect(rect_bg, 4.0, 4.0)

        painter.setPen(QPen(QColor(COLOR_MEDICION_TEXTO)))
        painter.drawText(rect_bg, Qt.AlignmentFlag.AlignCenter, texto)

        painter.restore()
