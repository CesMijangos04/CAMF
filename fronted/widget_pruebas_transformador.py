"""
Widget para captura de pruebas y mantenimiento en cierre de mantenimiento
de transformadores.

Rediseño 2026-XX-XX (segundo pass): la captura es un registro simple de
lo que se hizo — el ingeniero solo pone el valor medido (o deja vacío
si no lo hizo) y opcionalmente una nota. El veredicto normativo NO se
calcula ni muestra durante la captura; eso queda para la ficha finalizada
(`_bloque_cierre` en `ficha_mantenimiento.py`) usando el motor de
`evaluacion_transformador.py`.

Este módulo es AUTOCONTENIDO: se replican las constantes de estilo y el
helper `_NoWheelComboBox` para evitar dependencias circulares con
`dialogs_mantenimiento.py`. Es la misma convención que ya usa
`widget_cambios_tablero.py` y `notificaciones.py`.

Layout de la sección (de arriba a abajo):

    [ Header PRUEBAS DEL TRANSFORMADOR + hint ]
    [ QComboBox de transformador           ]   ← solo si hay > 1
    ┌────────────────────────────────────────┐
    │ [ Header card del transformador       ]│
    │                                        │
    │ PRUEBAS ELÉCTRICAS                     │
    │   fila 1   [valor] [ud] [📝]           │
    │   fila 2   [valor] [ud] [📝]           │
    │   ...                                  │
    │                                        │
    │ PRUEBAS AL ACEITE · sumergido          │
    │   fila n   ...                         │
    │                                        │
    │ POSICIÓN DEL TAP                       │
    │   Posición   Antes [3] → [2] Modificado│
    │   JUSTIFICACIÓN · ...                  │
    │                                        │
    │ INSPECCIÓN FÍSICA                      │
    │   punto1  [OK ▼]   |  punto2 [OK ▼]    │
    │   ...              |                   │
    └────────────────────────────────────────┘

Sin label de resumen inferior — Cesar decidió que no aporta con este
enfoque simplificado (si se dejó algo vacío, se ve claramente en el
input). La ausencia del label también evita el bug visual de superposición
que se veía cuando el scroll era muy corto.
"""
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QFrame, QLineEdit,
)
import qtawesome as qta


# ── Estilos replicados de dialogs_mantenimiento.py ──────────────────────
WARNING = "#EF9F27"

COMBO_STYLE = """
    QComboBox {
        background-color: #1e1e1e; color: white;
        border: 1px solid #444; border-radius: 5px;
        padding: 4px 6px;
    }
    QComboBox QAbstractItemView {
        background-color: #1e1e1e; color: white;
        selection-background-color: #0078d7;
        border: 1px solid #444;
    }
"""

INPUT_STYLE = """
    QTextEdit, QLineEdit {
        background-color: #1e1e1e; color: white;
        border: 1px solid #444; border-radius: 5px;
        padding: 6px 8px;
        selection-background-color: #0078d7;
    }
    QTextEdit:focus, QLineEdit:focus {
        border: 1px solid #0078d7;
    }
"""


class _NoWheelComboBox(QComboBox):
    """
    QComboBox que ignora la rueda del mouse — evita cambios accidentales
    de valor cuando el usuario intenta scrollear la ventana. Duplicado
    aquí para mantener el módulo autocontenido.
    """

    def wheelEvent(self, event):
        event.ignore()


def _split_nombre_prueba(nombre: str) -> tuple:
    """
    Separa el nombre de una prueba en (principal, subtítulo) para
    renderizado visual: el principal se muestra en color normal, el
    subtítulo en gris más pequeño.

    Convención: todo antes del primer paréntesis `(` o punto medio `·`
    es el principal. El resto es subtítulo. Se preserva el separador
    en el subtítulo (para poder mostrar `(Megger)` o `· error %`
    tal cual).

    Ejemplos:
        "Resistencia de aislamiento AT → tierra (Megger)"
            → ("Resistencia de aislamiento AT → tierra", "(Megger)")
        "Termografía · rise máximo sobre ambiente"
            → ("Termografía", "· rise máximo sobre ambiente")
        "Índice de polarización (IP = R@10min / R@1min)"
            → ("Índice de polarización", "(IP = R@10min / R@1min)")
        "Aterrizaje"
            → ("Aterrizaje", "")
    """
    if not nombre:
        return ("", "")
    # Buscar el primer separador: '(' o ' · '
    i_paren = nombre.find(" (")
    i_punto = nombre.find(" · ")
    candidatos = [i for i in (i_paren, i_punto) if i > 0]
    if not candidatos:
        return (nombre.strip(), "")
    i = min(candidatos)
    principal = nombre[:i].strip()
    subtitulo = nombre[i + 1:].strip()
    return (principal, subtitulo)


# ─── Fila de captura de prueba numérica ─────────────────────────────────
class _FilaPruebaCaptura(QWidget):
    """
    Fila de captura para una prueba de transformador. Muestra:
        [nombre + subtítulo gris]     [valor]  [unidad]  [📝]

    Sin combo de estado — la captura es solo el valor medido. El veredicto
    (aprobada/atención/falla) lo calcula el motor normativo en la ficha
    finalizada, no aquí.

    Al hacer clic en el ícono de nota se despliega una sub-fila con
    QLineEdit para la observación. Si la nota ya tiene contenido, el
    ícono aparece resaltado ámbar aunque el panel esté colapsado.

    Emite `dato_cambiado(prueba_codigo)` cada vez que cambia cualquier
    campo — el widget padre lee el estado completo con `snapshot()`.
    """

    dato_cambiado = pyqtSignal(str)  # prueba_codigo

    def __init__(self, prueba_codigo: str, nombre: str, unidad: str,
                 parent=None):
        super().__init__(parent)
        self._codigo = prueba_codigo
        self._nombre = nombre
        self._unidad = unidad
        self._nota_visible = False
        self._emit_bloqueado = True

        self._build_ui()
        self._emit_bloqueado = False

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Fila principal
        fila = QFrame()
        fila.setObjectName("fila_prueba")
        fila.setStyleSheet(
            "#fila_prueba { background: transparent; border-radius: 4px; }"
            "#fila_prueba:hover { background: rgba(255,255,255,0.02); }"
        )
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)

        # Nombre con subtítulo gris al mismo nivel de línea. Usamos un
        # QLabel con rich-text (<span>) para que el subtítulo pueda ir
        # inline en la misma línea, con color y tamaño distintos.
        principal, sub = _split_nombre_prueba(self._nombre)
        if sub:
            html = (
                f"<span style='color:#ddd; font-size:12.5px;'>{principal}</span> "
                f"<span style='color:#777; font-size:12px;'>{sub}</span>"
            )
        else:
            html = (
                f"<span style='color:#ddd; font-size:12.5px;'>{principal}</span>"
            )
        self.lbl_nombre = QLabel(html)
        self.lbl_nombre.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_nombre.setWordWrap(True)
        self.lbl_nombre.setStyleSheet("background: transparent;")
        self.lbl_nombre.setMinimumWidth(240)
        lay.addWidget(self.lbl_nombre, 1)

        # Input de valor (numérico)
        self.input_valor = QLineEdit()
        self.input_valor.setValidator(QDoubleValidator(-1e9, 1e9, 4))
        self.input_valor.setPlaceholderText("—")
        self.input_valor.setFixedWidth(100)
        self.input_valor.setFixedHeight(26)
        self.input_valor.setStyleSheet(INPUT_STYLE)
        self.input_valor.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.input_valor.textChanged.connect(self._on_cambio)
        lay.addWidget(self.input_valor)

        # Unidad (label)
        self.lbl_unidad = QLabel(self._unidad or "")
        self.lbl_unidad.setStyleSheet(
            "color: #999; font-size: 11.5px; font-family: 'Consolas', monospace; "
            "background: transparent;"
        )
        self.lbl_unidad.setFixedWidth(70)
        lay.addWidget(self.lbl_unidad)

        # Botón toggle de nota
        self.btn_nota = QPushButton()
        self.btn_nota.setIcon(qta.icon("fa5s.sticky-note", color="#888"))
        self.btn_nota.setFixedSize(28, 26)
        self.btn_nota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_nota.setToolTip("Agregar nota / observación")
        self.btn_nota.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.05); }"
        )
        self.btn_nota.clicked.connect(self._toggle_nota)
        lay.addWidget(self.btn_nota)

        outer.addWidget(fila)

        # Sub-fila de nota (oculta por default)
        self.fila_nota = QFrame()
        self.fila_nota.setObjectName("fila_nota_prueba")
        self.fila_nota.setStyleSheet(
            "#fila_nota_prueba { background: rgba(239,159,39,0.05); "
            f"border-left: 2px solid {WARNING}; border-radius: 0 4px 4px 0; }}"
        )
        nlay = QHBoxLayout(self.fila_nota)
        nlay.setContentsMargins(12, 4, 8, 6)
        nlay.setSpacing(8)

        lbl_n = QLabel("NOTA")
        lbl_n.setStyleSheet(
            f"color: {WARNING}; font-size: 10.5px; letter-spacing: 0.06em; "
            "background: transparent; font-weight: 500;"
        )
        lbl_n.setFixedWidth(50)
        nlay.addWidget(lbl_n)

        self.input_nota = QLineEdit()
        self.input_nota.setFixedHeight(24)
        self.input_nota.setPlaceholderText("Observación (opcional)")
        self.input_nota.setStyleSheet(
            "QLineEdit { background: transparent; color: #ddd; border: none; "
            "font-size: 12px; font-style: italic; padding: 2px 4px; }"
            "QLineEdit:focus { color: white; }"
        )
        self.input_nota.textChanged.connect(self._on_cambio)
        nlay.addWidget(self.input_nota, 1)

        # Margen izquierdo para alinear la sub-fila con el nombre de arriba
        wrap = QWidget()
        wlay = QHBoxLayout(wrap)
        wlay.setContentsMargins(30, 2, 8, 4)
        wlay.setSpacing(0)
        wlay.addWidget(self.fila_nota)

        wrap.setVisible(False)
        self._wrap_nota = wrap
        outer.addWidget(wrap)

    def _toggle_nota(self):
        self._nota_visible = not self._nota_visible
        self._wrap_nota.setVisible(self._nota_visible)
        self._refrescar_icon_nota()

    def _refrescar_icon_nota(self):
        tiene_nota = bool(self.input_nota.text().strip())
        # Auto-expandir la nota si el ingeniero empieza a escribir sin
        # haber tocado el botón. Comodidad de captura.
        if tiene_nota and not self._nota_visible:
            self._nota_visible = True
            self._wrap_nota.setVisible(True)
        if self._nota_visible:
            color = WARNING if tiene_nota else "#ccc"
        else:
            color = WARNING if tiene_nota else "#888"
        self.btn_nota.setIcon(qta.icon("fa5s.sticky-note", color=color))

    def _on_cambio(self, *_):
        if self._emit_bloqueado:
            return
        self._refrescar_icon_nota()
        self.dato_cambiado.emit(self._codigo)

    # ── API pública ─────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        """
        Devuelve el estado actual de la fila (para que la sección padre
        arme el payload al cerrar). Retorna dict con:
            valor:       float o None
            observacion: str o None
        """
        v_txt = self.input_valor.text().strip()
        try:
            valor = float(v_txt) if v_txt else None
        except ValueError:
            valor = None
        return {
            "valor":       valor,
            "observacion": self.input_nota.text().strip() or None,
        }

    def esta_vacia(self) -> bool:
        """
        True si el usuario no capturó absolutamente nada (ni valor,
        ni nota). El widget padre no genera fila en BD para pruebas vacías.
        """
        s = self.snapshot()
        return s["valor"] is None and not s["observacion"]


# ─── Fila de captura de inspección física ───────────────────────────────
class _FilaInspeccionCaptura(QWidget):
    """
    Fila de captura para un punto de inspección física. Muestra:
        [nombre]                              [Estado ▼]  [📝]

    Sin valor numérico — solo estado categórico con nota opcional.

    Estados (rediseño 2026): 3 opciones + vacío = 4 casos.
        —          (vacío):   no se revisó → no se registra en BD
        OK:        revisado, sin intervención
        Atención:  se atendió algo durante el mantenimiento
                   (limpieza, ajuste, cambio menor). Nota recomendada.
        N/A:       no aplica al equipo (ej. silica gel en un seco)

    Cuando el estado es "Atención" el combo se pinta en ámbar para
    llamar la atención visualmente. Cuando hay nota, el ícono también.
    """

    dato_cambiado = pyqtSignal(str)  # punto_codigo

    _ESTADOS = [
        ("—",         None),
        ("OK",        "ok"),
        ("Atención",  "atencion"),
        ("N/A",       "na"),
    ]

    def __init__(self, punto_codigo: str, nombre: str, parent=None):
        super().__init__(parent)
        self._codigo = punto_codigo
        self._nombre = nombre
        self._nota_visible = False
        self._emit_bloqueado = True

        self._build_ui()
        self._emit_bloqueado = False

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        fila = QFrame()
        fila.setObjectName("fila_insp")
        fila.setStyleSheet(
            "#fila_insp { background: transparent; border-radius: 4px; }"
            "#fila_insp:hover { background: rgba(255,255,255,0.02); }"
        )
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)

        self.lbl_nombre = QLabel(self._nombre)
        self.lbl_nombre.setStyleSheet(
            "color: #ddd; font-size: 12.5px; background: transparent;"
        )
        lay.addWidget(self.lbl_nombre, 1)

        # Selector de estado — 3 opciones + vacío. Estilo se recalcula
        # cuando cambia el índice (ámbar si "Atención").
        self.combo_estado = _NoWheelComboBox()
        self.combo_estado.setFixedWidth(130)
        self.combo_estado.setFixedHeight(26)
        self.combo_estado.setCursor(Qt.CursorShape.PointingHandCursor)
        for label, value in self._ESTADOS:
            self.combo_estado.addItem(label, userData=value)
        self.combo_estado.currentIndexChanged.connect(self._on_cambio)
        lay.addWidget(self.combo_estado)

        # Botón nota
        self.btn_nota = QPushButton()
        self.btn_nota.setIcon(qta.icon("fa5s.sticky-note", color="#888"))
        self.btn_nota.setFixedSize(24, 26)
        self.btn_nota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_nota.setToolTip("Agregar nota / observación")
        self.btn_nota.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.05); }"
        )
        self.btn_nota.clicked.connect(self._toggle_nota)
        lay.addWidget(self.btn_nota)

        outer.addWidget(fila)

        # Sub-fila de nota (oculta por default)
        self.fila_nota = QFrame()
        self.fila_nota.setObjectName("fila_nota_insp")
        self.fila_nota.setStyleSheet(
            "#fila_nota_insp { background: rgba(239,159,39,0.05); "
            f"border-left: 2px solid {WARNING}; border-radius: 0 4px 4px 0; }}"
        )
        nlay = QHBoxLayout(self.fila_nota)
        nlay.setContentsMargins(12, 4, 8, 6)
        nlay.setSpacing(8)

        self.lbl_n = QLabel("NOTA")
        self.lbl_n.setStyleSheet(
            f"color: {WARNING}; font-size: 10.5px; letter-spacing: 0.06em; "
            "background: transparent; font-weight: 500;"
        )
        self.lbl_n.setFixedWidth(50)
        nlay.addWidget(self.lbl_n)

        self.input_nota = QLineEdit()
        self.input_nota.setFixedHeight(24)
        self.input_nota.setPlaceholderText("Observación (opcional)")
        self.input_nota.setStyleSheet(
            "QLineEdit { background: transparent; color: #ddd; border: none; "
            "font-size: 12px; font-style: italic; padding: 2px 4px; }"
            "QLineEdit:focus { color: white; }"
        )
        self.input_nota.textChanged.connect(self._on_cambio)
        nlay.addWidget(self.input_nota, 1)

        # Margen izquierdo alineado con el nombre de arriba
        wrap = QWidget()
        wlay = QHBoxLayout(wrap)
        wlay.setContentsMargins(20, 2, 8, 4)
        wlay.setSpacing(0)
        wlay.addWidget(self.fila_nota)

        wrap.setVisible(False)
        self._wrap_nota = wrap
        outer.addWidget(wrap)

        self._refrescar_estilo_combo()

    def _toggle_nota(self):
        self._nota_visible = not self._nota_visible
        self._wrap_nota.setVisible(self._nota_visible)
        self._refrescar_icon_nota()

    def _refrescar_icon_nota(self):
        tiene_nota = bool(self.input_nota.text().strip())
        estado = self.combo_estado.currentData()
        # Auto-expandir la nota si el ingeniero escribe sin abrir el panel
        if tiene_nota and not self._nota_visible:
            self._nota_visible = True
            self._wrap_nota.setVisible(True)
        if self._nota_visible:
            color = WARNING if (tiene_nota or estado == "atencion") else "#ccc"
        else:
            color = WARNING if (tiene_nota or estado == "atencion") else "#888"
        self.btn_nota.setIcon(qta.icon("fa5s.sticky-note", color=color))

    def _refrescar_estilo_combo(self):
        """
        Pinta el combo en ámbar cuando el estado es "Atención". Estados
        OK / N/A / vacío usan el estilo normal.

        Nota técnica: usamos QSS con selectores + color condicional en
        Python (no propiedad dinámica) porque QSS con propiedades dinámicas
        requiere `style().unpolish(); style().polish()` y en PyQt6 6.9.1
        con estilo windows11 el polish no siempre refresca el border. Es
        más confiable reasignar el stylesheet completo.
        """
        estado = self.combo_estado.currentData()
        if estado == "atencion":
            self.combo_estado.setStyleSheet(f"""
                QComboBox {{
                    background-color: rgba(239,159,39,0.08); color: {WARNING};
                    border: 1px solid {WARNING}; border-radius: 5px;
                    padding: 4px 6px; font-weight: 500;
                }}
                QComboBox QAbstractItemView {{
                    background-color: #1e1e1e; color: white;
                    selection-background-color: #0078d7;
                    border: 1px solid #444;
                }}
            """)
        else:
            self.combo_estado.setStyleSheet(COMBO_STYLE)

    def _on_cambio(self, *_):
        if self._emit_bloqueado:
            return
        self._refrescar_estilo_combo()
        self._refrescar_icon_nota()
        self.dato_cambiado.emit(self._codigo)

    # ── API pública ─────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {
            "estado":      self.combo_estado.currentData(),
            "observacion": self.input_nota.text().strip() or None,
        }

    def esta_vacia(self) -> bool:
        s = self.snapshot()
        return s["estado"] is None and not s["observacion"]


# ─── Bloque de captura de posición del TAP ──────────────────────────────
class _BloquePosicionTap(QWidget):
    """
    Bloque de captura para la posición del cambiador de derivaciones (tap).
    Muestra dos QLineEdit numéricos: antes y después.

    Cuando los valores difieren:
        - El input `después` se pinta con borde ámbar
        - Aparece un chip "Modificado" en ámbar a la derecha
        - Aparece una sub-fila JUSTIFICACIÓN obligatoria abajo

    Estados posibles:
        - Ambos vacíos: no se registra nada al guardar.
        - Ambos iguales: se registra la fila (constancia de revisión),
          justificación opcional.
        - Distintos: fila obligatoria + justificación obligatoria.
    """

    dato_cambiado = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._emit_bloqueado = True
        self._build_ui()
        self._emit_bloqueado = False

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        fila_wrap = QFrame()
        fila_wrap.setStyleSheet("background: transparent;")
        fila = QHBoxLayout(fila_wrap)
        fila.setContentsMargins(8, 6, 8, 6)
        fila.setSpacing(10)

        lbl = QLabel("Posición")
        lbl.setStyleSheet(
            "color: #ddd; font-size: 12.5px; background: transparent;"
        )
        fila.addWidget(lbl)

        fila.addStretch()

        lbl_antes = QLabel("Antes")
        lbl_antes.setStyleSheet(
            "color: #999; font-size: 10.5px; letter-spacing: 0.05em; "
            "background: transparent;"
        )
        fila.addWidget(lbl_antes)

        self.input_antes = QLineEdit()
        self.input_antes.setValidator(QIntValidator(1, 33))
        self.input_antes.setPlaceholderText("—")
        self.input_antes.setFixedWidth(55)
        self.input_antes.setFixedHeight(26)
        self.input_antes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_antes.setStyleSheet(INPUT_STYLE)
        self.input_antes.textChanged.connect(self._on_cambio)
        fila.addWidget(self.input_antes)

        lbl_arrow = QLabel("→")
        lbl_arrow.setStyleSheet(
            "color: #888; font-size: 14px; background: transparent;"
        )
        fila.addWidget(lbl_arrow)

        lbl_desp = QLabel("Después")
        lbl_desp.setStyleSheet(
            "color: #999; font-size: 10.5px; letter-spacing: 0.05em; "
            "background: transparent;"
        )
        fila.addWidget(lbl_desp)

        self.input_despues = QLineEdit()
        self.input_despues.setValidator(QIntValidator(1, 33))
        self.input_despues.setPlaceholderText("—")
        self.input_despues.setFixedWidth(55)
        self.input_despues.setFixedHeight(26)
        self.input_despues.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_despues.setStyleSheet(INPUT_STYLE)
        self.input_despues.textChanged.connect(self._on_cambio)
        fila.addWidget(self.input_despues)

        # Chip "Modificado" — visible solo cuando antes != despues
        self.chip_modificado = QLabel("Modificado")
        self.chip_modificado.setStyleSheet(
            f"color: {WARNING}; font-size: 11px; font-weight: 500; "
            "letter-spacing: 0.05em; background: transparent; padding: 0 4px;"
        )
        self.chip_modificado.setVisible(False)
        fila.addWidget(self.chip_modificado)

        outer.addWidget(fila_wrap)

        # Sub-fila de justificación (visible solo si antes != despues)
        self.fila_just = QFrame()
        self.fila_just.setObjectName("fila_just_tap")
        self.fila_just.setStyleSheet(
            "#fila_just_tap { background: rgba(239,159,39,0.05); "
            f"border-left: 2px solid {WARNING}; border-radius: 0 4px 4px 0; }}"
        )
        jlay = QHBoxLayout(self.fila_just)
        jlay.setContentsMargins(12, 4, 8, 6)
        jlay.setSpacing(8)

        self.lbl_just = QLabel("JUSTIFICACIÓN *")
        self.lbl_just.setStyleSheet(
            f"color: {WARNING}; font-size: 10.5px; letter-spacing: 0.06em; "
            "background: transparent; font-weight: 500;"
        )
        self.lbl_just.setFixedWidth(120)
        jlay.addWidget(self.lbl_just)

        self.input_just = QLineEdit()
        self.input_just.setFixedHeight(24)
        self.input_just.setPlaceholderText(
            "¿Por qué se cambió la posición del tap? (obligatorio)"
        )
        self.input_just.setStyleSheet(
            "QLineEdit { background: transparent; color: #ddd; border: none; "
            "font-size: 12px; font-style: italic; padding: 2px 4px; }"
            "QLineEdit:focus { color: white; }"
        )
        self.input_just.textChanged.connect(self._on_cambio)
        jlay.addWidget(self.input_just, 1)

        # Wrapper con margen izquierdo consistente
        wrap = QWidget()
        wlay = QHBoxLayout(wrap)
        wlay.setContentsMargins(8, 2, 8, 4)
        wlay.setSpacing(0)
        wlay.addWidget(self.fila_just)

        wrap.setVisible(False)
        self._wrap_just = wrap
        outer.addWidget(wrap)

    def _on_cambio(self, *_):
        if self._emit_bloqueado:
            return
        # Mostrar/ocultar justificación y chip según si difieren
        antes = self._leer_int(self.input_antes)
        despues = self._leer_int(self.input_despues)
        difieren = (antes is not None and despues is not None
                    and antes != despues)
        self._wrap_just.setVisible(difieren)
        self.chip_modificado.setVisible(difieren)
        # Borde ámbar en 'después' cuando difiere
        if difieren:
            self.input_despues.setStyleSheet(
                "QLineEdit { background: #1e1e1e; color: white; "
                f"border: 1px solid {WARNING}; border-radius: 5px; "
                "padding: 6px 8px; selection-background-color: #0078d7; }"
                f"QLineEdit:focus {{ border: 1px solid {WARNING}; }}"
            )
        else:
            self.input_despues.setStyleSheet(INPUT_STYLE)
        self.dato_cambiado.emit()

    @staticmethod
    def _leer_int(w) -> Optional[int]:
        t = w.text().strip()
        if not t:
            return None
        try:
            return int(t)
        except ValueError:
            return None

    # ── API pública ─────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        antes = self._leer_int(self.input_antes)
        despues = self._leer_int(self.input_despues)
        return {
            "antes":         antes,
            "despues":       despues,
            "justificacion": self.input_just.text().strip() or None,
            "difieren":      (antes is not None and despues is not None
                              and antes != despues),
        }

    def esta_vacio(self) -> bool:
        s = self.snapshot()
        return s["antes"] is None and s["despues"] is None

    def falta_justificacion(self) -> bool:
        """True si antes != después pero justificación está vacía."""
        s = self.snapshot()
        return s["difieren"] and not s["justificacion"]


# ─── Header card del transformador ──────────────────────────────────────
class _HeaderTransformador(QFrame):
    """
    Card informativa del transformador activo. Muestra en dos columnas:
        Izquierda:  TR001 · 500 kVA · Dyn11
                    UPAEP · Subestación principal
        Derecha:    13.2 / 0.44 kV
                    Aceite mineral · ONAN

    Sin acciones ni botones — es puramente informativa (Cesar: Inicio es
    panorámico, no un launcher; misma filosofía aquí).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header_tr")
        self.setStyleSheet(
            "#header_tr { background: #262626; border-radius: 8px; }"
            "#header_tr QLabel { background: transparent; }"
        )
        self._build_ui()

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 16, 12)
        lay.setSpacing(12)

        # Columna izquierda
        col_izq = QVBoxLayout()
        col_izq.setContentsMargins(0, 0, 0, 0)
        col_izq.setSpacing(4)

        self.lbl_titulo = QLabel("—")
        self.lbl_titulo.setStyleSheet(
            "color: #eee; font-size: 15px; font-weight: 500;"
        )
        col_izq.addWidget(self.lbl_titulo)

        self.lbl_ubicacion = QLabel("")
        self.lbl_ubicacion.setStyleSheet(
            "color: #999; font-size: 12.5px;"
        )
        col_izq.addWidget(self.lbl_ubicacion)

        lay.addLayout(col_izq, 1)

        # Columna derecha (alineada a la derecha)
        col_der = QVBoxLayout()
        col_der.setContentsMargins(0, 0, 0, 0)
        col_der.setSpacing(4)

        self.lbl_tension = QLabel("")
        self.lbl_tension.setStyleSheet(
            "color: #ddd; font-size: 13px; font-family: 'Consolas', monospace;"
        )
        self.lbl_tension.setAlignment(Qt.AlignmentFlag.AlignRight)
        col_der.addWidget(self.lbl_tension)

        self.lbl_medio = QLabel("")
        self.lbl_medio.setStyleSheet(
            "color: #999; font-size: 12px;"
        )
        self.lbl_medio.setAlignment(Qt.AlignmentFlag.AlignRight)
        col_der.addWidget(self.lbl_medio)

        lay.addLayout(col_der)

    def actualizar(self, info: dict):
        """
        Recibe un dict con keys opcionales:
            tid, capacidad, vector, ubicacion, tension,
            medio_aislante, tipo_enfriamiento
        Los faltantes se rellenan con "—" o se omiten.
        """
        tid = info.get("tid", "") or ""
        cap = info.get("capacidad", "") or ""
        vec = info.get("vector", "") or ""
        partes_titulo = [x for x in [tid, cap, vec] if x]
        self.lbl_titulo.setText(" · ".join(partes_titulo) if partes_titulo else "—")

        ubi = info.get("ubicacion", "") or ""
        self.lbl_ubicacion.setText(ubi)

        tension = info.get("tension", "") or ""
        # Si viene como "13.2/0.44 kV" ok; si no viene unidad, la agregamos.
        if tension and "kv" not in tension.lower():
            tension = f"{tension} kV"
        self.lbl_tension.setText(tension)

        medio = info.get("medio_aislante", "") or ""
        tipo_enf = info.get("tipo_enfriamiento", "") or ""
        partes_medio = [x for x in [medio, tipo_enf] if x]
        self.lbl_medio.setText(" · ".join(partes_medio))


# ─── Sección principal ──────────────────────────────────────────────────
class _SeccionPruebasTransformador(QWidget):
    """
    Sección insertada en DialogCerrarMantenimiento cuando el mantenimiento
    es de transformadores. Permite al ingeniero capturar pruebas eléctricas,
    pruebas al aceite (solo si enfriamiento == "Aceite"), inspección física
    y posición del tap.

    Comportamiento:
      - Layout tipo formulario (no acordeón). El ingeniero llena los campos
        de arriba abajo sin abrir/cerrar filas.
      - `pruebas_aplicables(enfriamiento)` del motor decide qué pruebas
        mostrar.
      - Las filas que quedan vacías NO se registran en BD.
      - Sin evaluación en vivo — el veredicto normativo se aplica solo en
        la vista finalizada del mantenimiento.

    Al cerrar el diálogo expone 3 payloads (pruebas, inspección, tap)
    listos para pasar a `cerrar_mantenimiento_pendiente`.
    """

    datos_cambiaron = pyqtSignal()

    # Puntos de inspección física por categoría. Los comunes aplican a
    # todos los transformadores; los de aceite solo cuando corresponde.
    _INSPECCION_COMUN = [
        ("bushings_at",        "Bushings AT"),
        ("bushings_bt",        "Bushings BT"),
        ("aterrizaje",         "Aterrizaje"),
        ("apriete_conexiones", "Apriete de conexiones"),
        ("gabinete",           "Gabinete · limpieza y ventilación"),
    ]
    _INSPECCION_ACEITE = [
        ("nivel_aceite",       "Nivel de aceite"),
        ("silica_gel",         "Silica gel"),
        ("tanque",             "Tanque · fugas y oxidación"),
        ("radiadores",         "Radiadores · obstrucciones"),
        ("protecciones",       "Protecciones · Buchholz, VSP"),
    ]

    def __init__(self, transformadores: list, parent=None):
        super().__init__(parent)
        # `transformadores` viene de la ficha (self.equipos filtrados por tipo)
        # con al menos {id, nombre, ubicacion}.
        self._transformadores = list(transformadores)

        # Cache de datos de inventario (enfriamiento, capacidad, tension...)
        self._info_por_transformador = {}  # {tid: {...}}

        # Widgets vivos por transformador y por prueba/punto — preservan
        # el estado del ingeniero al cambiar entre transformadores.
        # {tid: {"pruebas": {codigo: _FilaPruebaCaptura, ...},
        #        "inspeccion": {punto: _FilaInspeccionCaptura, ...},
        #        "tap": _BloquePosicionTap}}
        self._widgets = {}

        self._precargar_info()
        self._build_ui()
        self._render_transformador_activo()

    def _precargar_info(self):
        """
        Fetch autocontenido de datos de inventario relevantes para el
        widget:
            enfriamiento     → decide qué pruebas mostrar
            capacidad        → header
            tension          → header
            vector (grupo)   → header
            marca            → reservado, se muestra si viene
            tipo             → reservado

        `enfriamiento` en BD hoy es "Aceite" o "Aire" (post-migración).
        `tipo` puede ser el subtipo específico (ONAN/ONAF/AF/AN...).
        Para el header dividimos en:
            medio_aislante:      "Aceite mineral" | "Aire seco" | ""
            tipo_enfriamiento:   "ONAN" | "ONAF" | "AN" | "AF" | ""
        """
        try:
            from db_manager import ejecutar_query
        except Exception as e:
            print(f"[SeccionPruebas] No se pudo importar db_manager: {e}")
            return
        for t in self._transformadores:
            tid = t.get("id")
            if not tid:
                continue
            try:
                filas = ejecutar_query(
                    "SELECT enfriamiento, capacidad, tension, marca, tipo, "
                    "COALESCE(vector, '') AS vector "
                    "FROM transformadores WHERE id = ?",
                    (tid,)
                )
            except Exception:
                # Fallback: la columna 'vector' puede no existir en BDs
                # antiguas — reintentamos sin ella.
                try:
                    filas = ejecutar_query(
                        "SELECT enfriamiento, capacidad, tension, marca, tipo "
                        "FROM transformadores WHERE id = ?",
                        (tid,)
                    )
                    if filas:
                        f = filas[0]
                        filas = [tuple(list(f) + [""])]
                except Exception as e:
                    print(f"[SeccionPruebas] Falla al cargar {tid}: {e}")
                    filas = None

            if filas:
                enf, cap, ten, marca, tipo, vec = filas[0]
                enf_lower = (enf or "").strip().lower()
                # Etiqueta descriptiva del medio aislante
                if enf_lower == "aceite":
                    medio = "Aceite mineral"
                elif enf_lower == "aire":
                    medio = "Aire seco"
                else:
                    medio = enf or ""
                self._info_por_transformador[tid] = {
                    "enfriamiento":       enf or "Aceite",
                    "capacidad":          cap or "",
                    "tension":            ten or "",
                    "marca":              marca or "",
                    "tipo":               tipo or "",
                    "vector":             vec or "",
                    "medio_aislante":     medio,
                    "tipo_enfriamiento":  tipo or "",
                }
            else:
                # Fallback conservador: asumir aceite (más común)
                self._info_por_transformador[tid] = {
                    "enfriamiento": "Aceite", "capacidad": "", "tension": "",
                    "marca": "", "tipo": "", "vector": "",
                    "medio_aislante": "Aceite mineral", "tipo_enfriamiento": "",
                }

    def _build_ui(self):
        # QSS raíz: todos los QLabel transparentes (mismo patrón que
        # _SeccionCambiosTablero, evita las "cajas" oscuras de Windows 11).
        self.setStyleSheet("QLabel { background: transparent; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        hdr = QLabel("PRUEBAS DEL TRANSFORMADOR")
        hdr.setStyleSheet(
            "color: #888; font-size: 11px; letter-spacing: 0.09em; "
            "font-weight: 500;"
        )
        lay.addWidget(hdr)

        hint = QLabel(
            "Captura los valores medidos. Deja vacías las pruebas que no "
            "se hicieron."
        )
        hint.setStyleSheet("color: #777; font-size: 11px; font-style: italic;")
        lay.addWidget(hint)

        # Dropdown de transformadores (visible solo si hay > 1) —
        # mismo patrón que widget_cambios_tablero.py.
        self.combo_transformadores = _NoWheelComboBox()
        self.combo_transformadores.setStyleSheet(COMBO_STYLE)
        self.combo_transformadores.setFixedHeight(30)
        for t in self._transformadores:
            tid = t.get("id", "")
            info = self._info_por_transformador.get(tid, {})
            cap = info.get("capacidad", "")
            texto = f"{tid}" + (f" · {cap}" if cap else "")
            self.combo_transformadores.addItem(texto, userData=tid)
        self.combo_transformadores.currentIndexChanged.connect(
            self._render_transformador_activo)
        # Solo se muestra cuando hay más de un transformador — con uno
        # solo, la card del header ya deja claro cuál es.
        self.combo_transformadores.setVisible(len(self._transformadores) > 1)
        lay.addWidget(self.combo_transformadores)

        # Contenedor del formulario. Ya NO se envuelve en QScrollArea: el
        # DialogCerrarMantenimiento (padre) tiene un scroll global sobre
        # todo su body, así que el widget crece a su tamaño natural (~930
        # px con todas las pruebas + inspección + TAP) y el scroll global
        # se encarga de que el usuario pueda ver todo con un solo scroll.
        #
        # Look visual: QFrame con borde #333 y fondo #1a1a1a — replica la
        # apariencia "de caja" que tenía cuando existía el scroll interno,
        # para mantener la separación visual con el resto del diálogo.
        #
        # QLabel transparent explícito: PyQt6 6.9.1 en Windows 11 rompe
        # la cascada de `QLabel { background: transparent; }` del widget
        # raíz cuando un descendiente (este QFrame) tiene su propio
        # stylesheet con selector por objectName. Los QLabels dentro se
        # pintan con la palette del sistema (fondo oscuro) causando los
        # "rectángulos negros" alrededor de títulos de sección, labels de
        # unidad, íconos, etc. Se declara `#cont_pruebas QLabel` en el
        # mismo stylesheet para blindar todo el árbol descendiente.
        # Mismo patrón se aplica en widget_cambios_tablero.py.
        self.contenedor = QFrame()
        self.contenedor.setObjectName("cont_pruebas")
        self.contenedor.setStyleSheet(
            "#cont_pruebas { border: 1px solid #333; border-radius: 4px; "
            "background: #1a1a1a; } "
            "#cont_pruebas QLabel { background: transparent; }"
        )
        self.contenedor_lay = QVBoxLayout(self.contenedor)
        self.contenedor_lay.setContentsMargins(12, 12, 12, 16)
        self.contenedor_lay.setSpacing(4)
        lay.addWidget(self.contenedor)

    def _render_transformador_activo(self):
        """
        Reconstruye el layout del contenedor del scroll para el
        transformador activo. Los widgets vivos se preservan en cache
        (`self._widgets`) y solo se reparent-ean — así el ingeniero no
        pierde lo que ya capturó cuando alterna entre transformadores.
        """
        # Limpiar contenedor (los widgets vivos van a cache, no se destruyen)
        while self.contenedor_lay.count():
            item = self.contenedor_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # No destruimos filas de captura (están cacheadas), solo
                # las de sección/separadores. Diferenciamos por atributo.
                if getattr(w, "_es_seccion", False):
                    w.hide()
                    w.deleteLater()
                else:
                    w.hide()
                    w.setParent(None)

        tid = self.combo_transformadores.currentData()
        if not tid:
            return

        if tid not in self._widgets:
            self._widgets[tid] = {
                "pruebas": {}, "inspeccion": {}, "tap": None,
                "header": None,
            }

        info = self._info_por_transformador.get(tid, {})
        enf = info.get("enfriamiento", "Aceite")

        # ── Header card del transformador ──
        t = next((x for x in self._transformadores if x.get("id") == tid), None)
        header_info = dict(info)
        header_info["tid"] = tid
        header_info["ubicacion"] = (t.get("ubicacion", "") if t else "") or ""
        if self._widgets[tid]["header"] is None:
            hdr_card = _HeaderTransformador(parent=self.contenedor)
            self._widgets[tid]["header"] = hdr_card
        hdr_card = self._widgets[tid]["header"]
        hdr_card.actualizar(header_info)
        hdr_card.setParent(self.contenedor)
        hdr_card.show()
        self.contenedor_lay.addWidget(hdr_card)

        # ── Sección PRUEBAS ELÉCTRICAS ──
        from evaluacion_transformador import (
            pruebas_aplicables, obtener_metadata,
        )
        codigos = pruebas_aplicables(enf)
        # Separar en dos grupos: comunes (aire+aceite) y solo aceite
        codigos_comunes = [c for c in codigos
                           if "aire" in obtener_metadata(c)["aplica_a"]]
        codigos_aceite = [c for c in codigos if c not in codigos_comunes]

        self._agregar_seccion("PRUEBAS ELÉCTRICAS")
        for codigo in codigos_comunes:
            fila = self._obtener_o_crear_prueba(tid, codigo)
            self.contenedor_lay.addWidget(fila)

        if codigos_aceite:
            self._agregar_seccion("PRUEBAS AL ACEITE",
                                  sub="transformador sumergido")
            for codigo in codigos_aceite:
                fila = self._obtener_o_crear_prueba(tid, codigo)
                self.contenedor_lay.addWidget(fila)

        # ── Sección POSICIÓN DEL TAP ──
        self._agregar_seccion("POSICIÓN DEL CAMBIADOR DE DERIVACIONES (TAP)")
        tap = self._obtener_o_crear_tap(tid)
        self.contenedor_lay.addWidget(tap)

        # ── Sección INSPECCIÓN FÍSICA (grid 2 columnas) ──
        self._agregar_seccion("INSPECCIÓN FÍSICA")
        puntos = list(self._INSPECCION_COMUN)
        if enf and enf.lower() == "aceite":
            puntos = puntos + list(self._INSPECCION_ACEITE)

        grid_wrap = QWidget()
        grid_wrap._es_seccion = True  # marca para limpieza
        gl = QGridLayout(grid_wrap)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setHorizontalSpacing(20)
        gl.setVerticalSpacing(0)
        gl.setColumnStretch(0, 1)
        gl.setColumnStretch(1, 1)
        # Distribuir en 2 columnas: pares → columna 0, impares → columna 1
        for idx, (punto_codigo, nombre) in enumerate(puntos):
            fila = self._obtener_o_crear_inspeccion(tid, punto_codigo, nombre)
            col = idx % 2
            row = idx // 2
            gl.addWidget(fila, row, col)
        self.contenedor_lay.addWidget(grid_wrap)

        self.contenedor_lay.addStretch()

    def _agregar_seccion(self, titulo: str, sub: str = None):
        """
        Añade un separador visual con título de sección. Marcado con
        `_es_seccion = True` para que el limpiador del contenedor sepa
        que debe destruirlo (a diferencia de las filas, que van a cache).
        """
        wrap = QWidget()
        wrap._es_seccion = True
        wlay = QVBoxLayout(wrap)
        wlay.setContentsMargins(0, 12, 0, 4)
        wlay.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(6)
        t = QLabel(titulo)
        t.setStyleSheet(
            "color: #888; font-size: 11px; letter-spacing: 0.09em; "
            "font-weight: 500; background: transparent;"
        )
        row.addWidget(t)
        if sub:
            s = QLabel(f"· {sub}")
            s.setStyleSheet(
                "color: #666; font-size: 10.5px; font-style: italic; "
                "background: transparent;"
            )
            row.addWidget(s)
        row.addStretch()
        wlay.addLayout(row)

        # Línea horizontal fina como separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            "background: rgba(255,255,255,0.05); max-height: 1px; border: none;"
        )
        wlay.addWidget(sep)

        self.contenedor_lay.addWidget(wrap)

    def _obtener_o_crear_prueba(self, tid: str,
                                codigo: str) -> _FilaPruebaCaptura:
        cache = self._widgets[tid]["pruebas"]
        if codigo not in cache:
            from evaluacion_transformador import obtener_metadata
            meta = obtener_metadata(codigo) or {"nombre": codigo, "unidad": ""}
            fila = _FilaPruebaCaptura(
                prueba_codigo=codigo,
                nombre=meta["nombre"],
                unidad=meta["unidad"],
                parent=self.contenedor,
            )
            fila.dato_cambiado.connect(self._on_datos_cambiaron)
            cache[codigo] = fila
        else:
            cache[codigo].setParent(self.contenedor)
            cache[codigo].show()
        return cache[codigo]

    def _obtener_o_crear_inspeccion(self, tid: str, punto: str,
                                    nombre: str) -> _FilaInspeccionCaptura:
        cache = self._widgets[tid]["inspeccion"]
        if punto not in cache:
            fila = _FilaInspeccionCaptura(
                punto_codigo=punto, nombre=nombre, parent=self.contenedor,
            )
            fila.dato_cambiado.connect(self._on_datos_cambiaron)
            cache[punto] = fila
        else:
            cache[punto].setParent(self.contenedor)
            cache[punto].show()
        return cache[punto]

    def _obtener_o_crear_tap(self, tid: str) -> _BloquePosicionTap:
        if self._widgets[tid]["tap"] is None:
            tap = _BloquePosicionTap(parent=self.contenedor)
            tap.dato_cambiado.connect(self._on_datos_cambiaron)
            self._widgets[tid]["tap"] = tap
        else:
            self._widgets[tid]["tap"].setParent(self.contenedor)
            self._widgets[tid]["tap"].show()
        return self._widgets[tid]["tap"]

    def _on_datos_cambiaron(self, *_):
        self.datos_cambiaron.emit()

    # ── API pública para el diálogo padre ────────────────────────────────
    def falta_justificacion_tap(self) -> bool:
        """True si algún tap tiene antes != despues pero sin justificación."""
        for tid, packs in self._widgets.items():
            tap = packs["tap"]
            if tap is not None and tap.falta_justificacion():
                return True
        return False

    def hay_incompletos(self) -> bool:
        """
        Solo bloquea el cierre si hay algo obligatorio pendiente. Hoy
        únicamente la justificación del tap cuando la posición cambió.
        Las pruebas vacías o inspecciones sin marcar son válidas (opcional).
        """
        return self.falta_justificacion_tap()

    def obtener_payload_pruebas(self) -> list:
        """
        Devuelve la lista lista para `pruebas_transformador` de
        cerrar_mantenimiento_pendiente. Solo incluye pruebas con al menos
        un dato capturado (valor u observación).

        Estados persistidos:
            "capturada"     → hay valor numérico
            "no_ejecutada"  → hay nota pero sin valor (el ingeniero dejó
                              constancia de por qué no se hizo)
            (vacío)         → no se incluye en el payload
        """
        payload = []
        for tid, packs in self._widgets.items():
            for codigo, fila in packs["pruebas"].items():
                if fila.esta_vacia():
                    continue
                s = fila.snapshot()
                from evaluacion_transformador import obtener_metadata
                meta = obtener_metadata(codigo) or {"unidad": ""}
                if s["valor"] is not None:
                    estado_bd = "capturada"
                else:
                    # Sin valor pero con nota — se registra como no_ejecutada
                    # para preservar el motivo en la historia del equipo.
                    estado_bd = "no_ejecutada"
                payload.append({
                    "transformador_id": tid,
                    "prueba_codigo":    codigo,
                    "valor":            s["valor"],
                    "unidad":           meta["unidad"],
                    "estado":           estado_bd,
                    "observacion":      s["observacion"],
                })
        return payload

    def obtener_payload_inspeccion(self) -> list:
        """
        Devuelve la lista lista para `inspeccion_transformador`. Solo
        incluye puntos con estado marcado o con observación.

        Estados posibles en la BD:
            "ok" | "atencion" | "na" | "no_revisado"
        """
        payload = []
        for tid, packs in self._widgets.items():
            for punto, fila in packs["inspeccion"].items():
                if fila.esta_vacia():
                    continue
                s = fila.snapshot()
                # Si tiene observación pero no estado, marcar 'no_revisado'
                estado = s["estado"] or "no_revisado"
                payload.append({
                    "transformador_id": tid,
                    "punto":            punto,
                    "estado":           estado,
                    "observacion":      s["observacion"],
                })
        return payload

    def obtener_payload_tap(self) -> list:
        """
        Devuelve la lista lista para `posicion_tap_transformador`. Solo
        incluye taps con AMBOS valores (antes y después) capturados.
        """
        payload = []
        for tid, packs in self._widgets.items():
            tap = packs["tap"]
            if tap is None:
                continue
            s = tap.snapshot()
            if s["antes"] is None or s["despues"] is None:
                continue
            payload.append({
                "transformador_id": tid,
                "posicion_antes":   s["antes"],
                "posicion_despues": s["despues"],
                "justificacion":    s["justificacion"],
            })
        return payload
