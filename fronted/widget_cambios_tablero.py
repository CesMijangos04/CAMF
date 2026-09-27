"""
Widget para captura de cambios al equipo en cierre de mantenimiento de tableros.

Extraído de dialogs_mantenimiento.py durante el refactor de organización
(2026-XX). Este módulo es AUTOCONTENIDO: se replican las constantes de
estilo y el helper _NoWheelComboBox para evitar dependencias circulares
con dialogs_mantenimiento.py. Es la misma convención que ya usa
notificaciones.py replicando helpers de programados.py.
"""
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
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


# ── Catálogos NOM replicados de circuito.py ─────────────────────────────
CALIBRES_NOM = [
    "14 AWG", "12 AWG", "10 AWG", "8 AWG", "6 AWG",
    "4 AWG", "3 AWG", "2 AWG", "1 AWG",
    "1/0 AWG", "2/0 AWG", "3/0 AWG", "4/0 AWG",
    "250 KCM", "300 KCM", "350 KCM", "400 KCM",
    "500 KCM", "600 KCM", "700 KCM", "750 KCM",
    "800 KCM", "900 KCM", "1000 KCM",
    "1250 KCM", "1500 KCM", "1750 KCM", "2000 KCM",
]
TUBERIAS_NOM = [
    ('16 mm (1/2")',    16.0),
    ('21 mm (3/4")',    21.0),
    ('27 mm (1")',      27.0),
    ('35 mm (1-1/4")',  35.0),
    ('41 mm (1-1/2")',  41.0),
    ('53 mm (2")',      53.0),
    ('63 mm (2-1/2")',  63.0),
    ('78 mm (3")',      78.0),
    ('91 mm (3-1/2")',  91.0),
    ('103 mm (4")',     103.0),
    ('129 mm (5")',     129.0),
    ('155 mm (6")',     155.0),
]
MATERIALES_NOM = [("Cobre", "cobre"), ("Aluminio", "aluminio")]


class _FilaCircuitoColapsada(QWidget):
    """
    Fila LIGERA que representa un circuito en la lista. Muestra solo:
        C-XX   Descripción   Resumen (cal · ITM · material)   Estado   [✎]

    NO contiene widgets editables — cuando el usuario hace clic en el ícono
    lápiz, el widget padre (_SeccionCambiosTablero) monta on-demand el
    panel pesado debajo (acordeón: solo uno abierto a la vez).

    Ventaja de performance: renderizar 20 circuitos son 20 filas ×
    5 QLabels = trivial. Los ~15 widgets pesados del editor solo existen
    para el circuito que está en edición.

    La fila reacciona al estado (sin cambios / modificado / editando) vía
    refresh_visual(mods_actuales, en_edicion).
    """

    solicitar_toggle = pyqtSignal(int)  # circuito_id: alterna abrir/cerrar edición

    # Campos que aparecen en el "resumen" compacto de la fila colapsada.
    # Se eligieron los que técnicamente definen al circuito de un vistazo:
    # calibre de fase, capacidad del ITM y material. Si el ingeniero cambia
    # otros campos (tubería, kA, obs), la fila se marca como "modificado"
    # pero el resumen visible no cambia — solo el chip de estado.
    _CAMPOS_RESUMEN = ("calibre_fase", "amperaje_a", "material")

    def __init__(self, circuito: dict, parent=None):
        super().__init__(parent)
        self._circuito_id = int(circuito["id"])
        self._originales = dict(circuito)
        self._en_edicion = False
        self._modificaciones_actuales = {}  # se actualiza vía refresh_visual

        self._build_ui()

    def _build_ui(self):
        # Grid: C-XX | descripción | resumen | estado | botón
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(12)

        # C-XX (monospace, ámbar suave)
        try:
            esp = int(self._originales.get("espacio_inicio", 0))
            id_txt = f"C-{esp:02d}"
        except (TypeError, ValueError):
            id_txt = "C-??"
        self.lbl_id = QLabel(id_txt)
        self.lbl_id.setStyleSheet(
            f"color: {WARNING}; font-family: 'Consolas', monospace; "
            "font-size: 12px; letter-spacing: 0.02em; font-weight: 500; "
            "background: transparent;"
        )
        self.lbl_id.setFixedWidth(50)
        lay.addWidget(self.lbl_id)

        # Descripción (nombre del circuito)
        desc = self._originales.get("nombre") or "(sin descripción)"
        self.lbl_desc = QLabel(desc)
        self.lbl_desc.setStyleSheet(
            "color: #eee; font-size: 13px; background: transparent;"
        )
        self.lbl_desc.setMinimumWidth(180)
        lay.addWidget(self.lbl_desc, 1)

        # Resumen compacto (calibre · ITM · material)
        self.lbl_resumen = QLabel(self._formatear_resumen(self._originales))
        self.lbl_resumen.setStyleSheet(
            "color: #aaa; font-family: 'Consolas', monospace; font-size: 12.5px; "
            "background: transparent;"
        )
        self.lbl_resumen.setMinimumWidth(220)
        lay.addWidget(self.lbl_resumen)

        # Chip de estado (sin cambios / modificado)
        self.lbl_estado = QLabel("sin cambios")
        self.lbl_estado.setStyleSheet(
            "color: #888; font-size: 11.5px; padding: 0 6px; background: transparent;"
        )
        self.lbl_estado.setFixedWidth(90)
        self.lbl_estado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.lbl_estado)

        # Botón toggle (lápiz colapsado / chevron up expandido)
        self.btn_toggle = QPushButton()
        self.btn_toggle.setIcon(qta.icon("fa5s.pen", color="#888"))
        self.btn_toggle.setFixedSize(28, 28)
        self.btn_toggle.setToolTip("Editar este circuito")
        self.btn_toggle.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.05); }"
        )
        self.btn_toggle.clicked.connect(lambda: self.solicitar_toggle.emit(self._circuito_id))
        lay.addWidget(self.btn_toggle)

        # Hover en toda la fila (visual feedback antes del clic)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._aplicar_estilo_neutral()

    # ── API pública para el padre ───────────────────────────────────────
    def refresh_visual(self, modificaciones: dict, en_edicion: bool):
        """
        Actualiza el aspecto de la fila según el estado externo:
            - `modificaciones`: dict {campo: valor_nuevo} del circuito
                                (vacío si no hay cambios)
            - `en_edicion`: True si el panel de edición está abierto para
                            este circuito (afecta ícono del botón toggle)
        """
        self._modificaciones_actuales = dict(modificaciones or {})
        self._en_edicion = bool(en_edicion)

        tiene_cambios = bool(self._modificaciones_actuales)

        # Estilo de fondo
        if tiene_cambios:
            self._aplicar_estilo_modificado()
        elif self._en_edicion:
            self._aplicar_estilo_editando_sin_cambios()
        else:
            self._aplicar_estilo_neutral()

        # Ícono del botón toggle: chevron-up si abierto, lápiz si cerrado
        if self._en_edicion:
            self.btn_toggle.setIcon(qta.icon("fa5s.chevron-up", color="#ccc"))
            self.btn_toggle.setToolTip("Cerrar edición")
        else:
            color = WARNING if tiene_cambios else "#888"
            self.btn_toggle.setIcon(qta.icon("fa5s.pen", color=color))
            self.btn_toggle.setToolTip("Editar este circuito")

        # Chip de estado + resumen
        if tiene_cambios:
            self.lbl_estado.setText("modificado")
            self.lbl_estado.setStyleSheet(
                f"color: {WARNING}; font-size: 11.5px; padding: 0 6px; "
                "font-weight: 500; background: transparent;"
            )
            self._pintar_resumen_con_cambios()
        else:
            self.lbl_estado.setText("sin cambios")
            self.lbl_estado.setStyleSheet(
                "color: #888; font-size: 11.5px; padding: 0 6px; background: transparent;"
            )
            self.lbl_resumen.setText(self._formatear_resumen(self._originales))
            self.lbl_resumen.setStyleSheet(
                "color: #aaa; font-family: 'Consolas', monospace; font-size: 12.5px; "
                "background: transparent;"
            )

    # ── Helpers de estilo ───────────────────────────────────────────────
    def _aplicar_estilo_neutral(self):
        self.setStyleSheet(
            "_FilaCircuitoColapsada { background: transparent; border-radius: 4px; }"
            "_FilaCircuitoColapsada:hover { background: rgba(255,255,255,0.03); }"
        )

    def _aplicar_estilo_editando_sin_cambios(self):
        self.setStyleSheet(
            "_FilaCircuitoColapsada { background: rgba(255,255,255,0.04); "
            "border-radius: 4px; }"
        )

    def _aplicar_estilo_modificado(self):
        self.setStyleSheet(
            "_FilaCircuitoColapsada { background: rgba(239, 159, 39, 0.08); "
            "border-radius: 4px; }"
        )

    # ── Formateo del resumen ────────────────────────────────────────────
    def _formatear_resumen(self, valores: dict) -> str:
        """
        Devuelve el resumen compacto `cal · ITM · material`.
        Toma valores del dict (originales o mezclados con modificaciones).
        """
        cal = valores.get("calibre_fase") or "—"
        itm = valores.get("amperaje_a")
        mat = valores.get("material") or "—"

        if isinstance(itm, float) and itm == int(itm):
            itm_txt = f"{int(itm)} A"
        elif itm is None or itm == "":
            itm_txt = "— A"
        else:
            itm_txt = f"{itm} A"

        return f"{cal} · {itm_txt} · {mat}"

    def _pintar_resumen_con_cambios(self):
        """
        Cuando hay cambios en calibre/ITM/material, muestra el resumen
        original tachado + flecha + nuevo en verde. Si los cambios son
        SOLO en otros campos (tubería, kA, obs), muestra resumen normal
        (que sigue siendo el original) — el chip "modificado" ya lo dice.
        """
        # ¿Alguno de los 3 campos del resumen fue modificado?
        cambia_resumen = any(
            k in self._modificaciones_actuales for k in self._CAMPOS_RESUMEN
        )
        if not cambia_resumen:
            # Cambio en otros campos: dejar resumen original con tinte suave
            self.lbl_resumen.setText(self._formatear_resumen(self._originales))
            self.lbl_resumen.setStyleSheet(
                f"color: {WARNING}; font-family: 'Consolas', monospace; "
                "font-size: 12.5px; background: transparent;"
            )
            return

        # Mezcla original + modificaciones para calcular el nuevo resumen
        nuevo = dict(self._originales)
        for campo, valor in self._modificaciones_actuales.items():
            nuevo[campo] = valor

        original_txt = self._formatear_resumen(self._originales)
        nuevo_txt = self._formatear_resumen(nuevo)

        # HTML con tachado + flecha verde. Sin ancho de columna fijo,
        # que se ajuste al contenido; el layout del padre da el espacio.
        html = (
            f'<span style="color: #666; text-decoration: line-through; '
            f'font-family: Consolas, monospace; font-size: 12px;">{original_txt}</span>'
            f'<br>'
            f'<span style="color: #5DCAA5; font-family: Consolas, monospace; '
            f'font-size: 12.5px; font-weight: 500;">&rarr; {nuevo_txt}</span>'
        )
        self.lbl_resumen.setText(html)
        self.lbl_resumen.setTextFormat(Qt.TextFormat.RichText)
        # Estilo base sin color (los <span> lo definen) + transparente
        self.lbl_resumen.setStyleSheet("padding: 2px 0; background: transparent;")


class _PanelEdicionCircuito(QWidget):
    """
    Panel PESADO con los 8 campos editables + justificación + revertir.
    Se instancia bajo demanda cuando el ingeniero abre una fila para
    editar, y se destruye al cerrar (acordeón).

    Emite `cambio_registrado(circuito_id, dict_mods, justificacion)` cada
    vez que el estado cambia, para que _SeccionCambiosTablero actualice
    sus diccionarios de persistencia.
    """

    _CAMPOS = [
        ("calibre_fase",     "Cal F",    "combo_cal"),
        ("calibre_neutro",   "Cal N",    "combo_cal"),
        ("calibre_tierra",   "Cal T",    "combo_cal"),
        ("material",         "Material", "combo_mat"),
        ("amperaje_a",       "ITM (A)",  "numero"),
        ("capacidad_int_ka", "kA",       "numero"),
        ("tuberia_mm",       "Tubería",  "combo_tub"),
        ("observaciones",    "Obs.",     "texto"),
    ]

    # (circuito_id, dict de campos modificados, justificacion)
    cambio_registrado = pyqtSignal(int, dict, str)
    solicitar_cerrar = pyqtSignal(int)  # circuito_id: revertir + cerrar

    def __init__(self, circuito: dict,
                 modificaciones_previas: dict, justificacion_previa: str,
                 parent=None):
        super().__init__(parent)
        self._circuito_id = int(circuito["id"])
        self._originales = dict(circuito)
        self._modificaciones = dict(modificaciones_previas or {})
        self._justificacion = justificacion_previa or ""
        self._emit_bloqueado = True
        self._widgets_por_campo = {}

        self._build_ui()
        self._aplicar_valores_iniciales()
        self._emit_bloqueado = False

    def _build_ui(self):
        # Card con borde izquierdo ámbar (comunica "cambio pendiente")
        self.setObjectName("panel_edicion")
        self.setStyleSheet(
            "#panel_edicion { background: rgba(255,255,255,0.02); "
            f"border-left: 2px solid {WARNING}; "
            "border-radius: 0 6px 6px 0; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(60, 10, 12, 12)  # sangría izq. para alinear con desc
        outer.setSpacing(10)

        # ── Grilla de campos 4x2 ─────────────────────────────────────
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        for i, (key, label, tipo) in enumerate(self._CAMPOS):
            row = i // 4
            col = i % 4
            grid.addWidget(self._crear_wrapper(key, label, tipo), row, col)
        outer.addLayout(grid)

        # ── Separador visual sutil ───────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: rgba(255,255,255,0.06); max-height: 1px;")
        outer.addWidget(sep)

        # ── Bloque de justificación + revertir ───────────────────────
        just_row = QHBoxLayout()
        just_row.setSpacing(10)

        lbl_j = QLabel("JUSTIFICACIÓN *")
        lbl_j.setStyleSheet(
            f"color: {WARNING}; font-size: 10.5px; letter-spacing: 0.06em; "
            "font-weight: 500;"
        )
        lbl_j.setFixedWidth(120)
        just_row.addWidget(lbl_j)

        self.input_just = QLineEdit()
        self.input_just.setPlaceholderText(
            "¿Por qué se hizo este cambio? (obligatorio)"
        )
        self.input_just.setFixedHeight(28)
        self.input_just.setStyleSheet(
            "QLineEdit { background: #1a1a1a; color: white; "
            f"border: 0.5px solid {WARNING}; border-radius: 4px; "
            "padding: 4px 10px; font-size: 12.5px; }"
            "QLineEdit:focus { border-color: #f5b34f; }"
        )
        self.input_just.textChanged.connect(self._on_justif_cambio)
        just_row.addWidget(self.input_just, 1)

        self.btn_revertir = QPushButton("  Revertir")
        self.btn_revertir.setIcon(qta.icon("fa5s.undo", color="#aaa"))
        self.btn_revertir.setFixedHeight(28)
        self.btn_revertir.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; "
            "border: 0.5px solid #444; border-radius: 4px; padding: 4px 10px; "
            "font-size: 11.5px; }"
            "QPushButton:hover { color: " + WARNING + "; border-color: " + WARNING + "; }"
        )
        self.btn_revertir.clicked.connect(self._on_revertir)
        just_row.addWidget(self.btn_revertir)

        outer.addLayout(just_row)

    # ── Construcción de widgets editores ─────────────────────────────
    def _crear_wrapper(self, key: str, label: str, tipo: str) -> QWidget:
        """Mini-widget con label pequeño arriba y editor abajo."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)

        lbl = QLabel(label.upper())
        lbl.setStyleSheet(
            "color: #777; font-size: 9.5px; letter-spacing: 0.05em; font-weight: 500;"
        )
        v.addWidget(lbl)

        editor = self._crear_editor(key, tipo)
        editor.setFixedHeight(26)
        v.addWidget(editor)

        self._widgets_por_campo[key] = editor
        return w

    def _crear_editor(self, key: str, tipo: str) -> QWidget:
        if tipo == "combo_cal":
            c = _NoWheelComboBox()
            c.setStyleSheet(COMBO_STYLE)
            c.addItem("—", userData=None)
            for cal in CALIBRES_NOM:
                c.addItem(cal, userData=cal)
            c.currentIndexChanged.connect(lambda _=None, k=key: self._on_widget_cambio(k))
            return c
        if tipo == "combo_mat":
            c = _NoWheelComboBox()
            c.setStyleSheet(COMBO_STYLE)
            c.addItem("—", userData=None)
            for label, val in MATERIALES_NOM:
                c.addItem(label, userData=val)
            c.currentIndexChanged.connect(lambda _=None, k=key: self._on_widget_cambio(k))
            return c
        if tipo == "combo_tub":
            c = _NoWheelComboBox()
            c.setStyleSheet(COMBO_STYLE)
            c.addItem("—", userData=None)
            for label, mm in TUBERIAS_NOM:
                c.addItem(label, userData=mm)
            c.currentIndexChanged.connect(lambda _=None, k=key: self._on_widget_cambio(k))
            return c
        if tipo == "numero":
            le = QLineEdit()
            le.setStyleSheet(INPUT_STYLE)
            le.setValidator(QDoubleValidator(0.0, 1e6, 2))
            le.setPlaceholderText("—")
            le.textChanged.connect(lambda _=None, k=key: self._on_widget_cambio(k))
            return le
        # tipo == "texto"
        le = QLineEdit()
        le.setStyleSheet(INPUT_STYLE)
        le.setPlaceholderText("—")
        le.textChanged.connect(lambda _=None, k=key: self._on_widget_cambio(k))
        return le

    # ── Aplicación de valores iniciales ──────────────────────────────
    def _aplicar_valores_iniciales(self):
        for key, _, _ in self._CAMPOS:
            w = self._widgets_por_campo.get(key)
            if w is None:
                continue
            valor = (self._modificaciones[key]
                     if key in self._modificaciones
                     else self._originales.get(key))
            self._setear_valor(w, key, valor)
            # Resaltar visualmente si el valor es una modificación
            self._marcar_editor_como_modificado(w, key in self._modificaciones)
        self.input_just.blockSignals(True)
        self.input_just.setText(self._justificacion or "")
        self.input_just.blockSignals(False)

    def _setear_valor(self, w, key, valor):
        w.blockSignals(True)
        try:
            if isinstance(w, QComboBox):
                if valor is None:
                    w.setCurrentIndex(0)
                else:
                    idx = w.findData(valor)
                    if idx < 0 and isinstance(valor, (int, float)):
                        idx = w.findData(float(valor))
                    w.setCurrentIndex(idx if idx >= 0 else 0)
            elif isinstance(w, QLineEdit):
                if valor is None or valor == "":
                    w.setText("")
                elif isinstance(valor, float) and valor == int(valor):
                    w.setText(str(int(valor)))
                else:
                    w.setText(str(valor))
        finally:
            w.blockSignals(False)

    def _leer_valor(self, w, key):
        if isinstance(w, QComboBox):
            return w.currentData()
        if isinstance(w, QLineEdit):
            texto = w.text().strip()
            if not texto:
                return None
            if key in ("amperaje_a", "capacidad_int_ka", "tuberia_mm"):
                try:
                    return float(texto)
                except ValueError:
                    return None
            return texto
        return None

    def _marcar_editor_como_modificado(self, w, es_mod: bool):
        """Aplica un borde ámbar al editor si su valor difiere del original."""
        if isinstance(w, QComboBox):
            base = COMBO_STYLE
            if es_mod:
                extra = (
                    " QComboBox { border: 1px solid " + WARNING +
                    "; background: rgba(239,159,39,0.06); }"
                )
                w.setStyleSheet(base + extra)
            else:
                w.setStyleSheet(base)
        elif isinstance(w, QLineEdit):
            if es_mod:
                w.setStyleSheet(
                    "QLineEdit { background: rgba(239,159,39,0.06); color: white; "
                    f"border: 1px solid {WARNING}; border-radius: 5px; "
                    "padding: 4px 8px; }"
                )
            else:
                w.setStyleSheet(INPUT_STYLE)

    # ── Detección de cambios ────────────────────────────────────────
    @staticmethod
    def _son_iguales(a, b) -> bool:
        if a is None and (b is None or b == ""):
            return True
        if b is None and (a is None or a == ""):
            return True
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) == float(b)
        return a == b

    def _recalcular_modificaciones(self):
        self._modificaciones.clear()
        for key, _, _ in self._CAMPOS:
            w = self._widgets_por_campo.get(key)
            if w is None:
                continue
            actual = self._leer_valor(w, key)
            original = self._originales.get(key)
            if not self._son_iguales(actual, original):
                self._modificaciones[key] = actual

    # ── Handlers ─────────────────────────────────────────────────────
    def _on_widget_cambio(self, key: str):
        if self._emit_bloqueado:
            return
        self._recalcular_modificaciones()
        # Marca visual del editor que cambió
        w = self._widgets_por_campo.get(key)
        if w is not None:
            self._marcar_editor_como_modificado(w, key in self._modificaciones)
        self.cambio_registrado.emit(
            self._circuito_id,
            dict(self._modificaciones),
            self._justificacion
        )

    def _on_justif_cambio(self, texto: str):
        if self._emit_bloqueado:
            return
        self._justificacion = texto.strip()
        self.cambio_registrado.emit(
            self._circuito_id,
            dict(self._modificaciones),
            self._justificacion
        )

    def _on_revertir(self):
        """Restaura originales, limpia justificación, y solicita cerrar el panel."""
        self._emit_bloqueado = True
        self._modificaciones.clear()
        self._justificacion = ""
        self._aplicar_valores_iniciales()
        self._emit_bloqueado = False
        # Notifica al padre y solicita cerrar
        self.cambio_registrado.emit(self._circuito_id, {}, "")
        self.solicitar_cerrar.emit(self._circuito_id)


class _SeccionCambiosTablero(QWidget):
    """
    Sección insertada en DialogCerrarMantenimiento cuando el mantenimiento
    es de tableros. Permite al ingeniero registrar cambios al inventario
    (calibres, ITMs, materiales, tubería, observaciones) con justificación
    obligatoria por cambio.

    Comportamiento:
      - Filas colapsadas por defecto (widgets ligeros → apertura rápida).
      - Al hacer clic en el ícono lápiz de una fila, se monta on-demand
        un _PanelEdicionCircuito debajo (acordeón: uno abierto a la vez).
      - El estado de cambios y justificaciones vive en la sección, no en
        los widgets — al cerrar un panel, el estado se conserva; al
        re-abrirlo, se restaura visualmente.
      - Lazy fetch: solo se hace SELECT de circuitos del tablero activo.
        Los otros se cargan cuando el usuario los elige en el dropdown.
    """

    cambios_cambiaron = pyqtSignal()  # para que el diálogo re-evalúe "Cerrar"

    def __init__(self, tableros: list, parent=None):
        super().__init__(parent)
        self._tableros = list(tableros)

        # Estado persistente
        self._modificaciones = {}    # {tablero_id: {circuito_id: {campo: valor}}}
        self._justificaciones = {}   # {tablero_id: {circuito_id: str}}
        self._originales_por_circuito = {}  # {circuito_id: dict}

        # Cache lazy de circuitos por tablero
        self._circuitos_por_tablero = {}  # {tablero_id: [dict, ...]}

        # Estado del acordeón: id del circuito en edición y widgets vivos
        self._circuito_en_edicion = None  # int | None
        self._panel_edicion = None        # _PanelEdicionCircuito | None
        self._filas_por_circuito = {}     # {circuito_id: _FilaCircuitoColapsada}

        self._build_ui()
        self._render_tablero_activo()

    def _build_ui(self):
        # QSS raíz: aplica en cascada a TODOS los QLabels descendientes.
        # En Windows 11 los QLabel hijos de un QWidget con background propio
        # dibujan un color de fondo default distinto que aparece como "cajas"
        # oscuras alrededor de cada texto. Forzar transparent aquí resuelve
        # el problema para todos los labels de la sección (filas y panel de
        # edición) sin tener que tocar cada uno individualmente.
        self.setStyleSheet("QLabel { background: transparent; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        hdr = QLabel("CAMBIOS AL EQUIPO")
        hdr.setStyleSheet(
            "color: #888; font-size: 11px; letter-spacing: 0.09em; font-weight: 500;"
        )
        lay.addWidget(hdr)

        hint = QLabel(
            "Selecciona el tablero. Si no editas nada, no se registra ningún cambio."
        )
        hint.setStyleSheet("color: #777; font-size: 11px; font-style: italic;")
        lay.addWidget(hint)

        # Dropdown de tableros
        self.combo_tableros = _NoWheelComboBox()
        self.combo_tableros.setStyleSheet(COMBO_STYLE)
        self.combo_tableros.setFixedHeight(30)
        for tab in self._tableros:
            tid = tab.get("id", "")
            nombre = tab.get("nombre", "") or ""
            texto = f"{tid} · {nombre}"
            self.combo_tableros.addItem(texto, userData=tid)
        self.combo_tableros.currentIndexChanged.connect(self._render_tablero_activo)
        lay.addWidget(self.combo_tableros)

        # Info del tablero activo
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color: #999; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_info)

        # Contenedor de circuitos. Ya NO se envuelve en QScrollArea: el
        # DialogCerrarMantenimiento (padre) tiene un scroll global sobre
        # todo su body, así que el widget crece a su tamaño natural (~40 px
        # por circuito × N circuitos, un tablero de 42 circuitos son ~1700
        # px) y el scroll global se encarga de que el usuario pueda ver
        # todos los circuitos con un solo scroll.
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
        # "rectángulos negros" alrededor de códigos de circuito, chips
        # de estado, etc. Se declara `#cont_tableros QLabel` en el mismo
        # stylesheet para blindar todo el árbol descendiente.
        self.contenedor = QFrame()
        self.contenedor.setObjectName("cont_tableros")
        self.contenedor.setStyleSheet(
            "#cont_tableros { border: 1px solid #333; border-radius: 4px; "
            "background: #1a1a1a; } "
            "#cont_tableros QLabel { background: transparent; }"
        )
        self.contenedor_lay = QVBoxLayout(self.contenedor)
        self.contenedor_lay.setContentsMargins(4, 4, 4, 8)
        self.contenedor_lay.setSpacing(1)
        lay.addWidget(self.contenedor)

        # Se eliminó el label global "Sin cambios pendientes" que iba
        # aquí: causaba superposición visual con el último circuito del
        # scroll cuando la altura del widget quedaba comprimida. La
        # información redundante (cada tarjeta de circuito ya tiene su
        # propio chip "sin cambios / N cambios") + el conteo en el
        # dropdown de tableros ("N pendientes") ya comunican lo mismo.

    # ── Carga lazy de circuitos ─────────────────────────────────────
    def _asegurar_circuitos_de(self, tablero_id: str):
        """Fetch on-demand: solo la primera vez que el tablero se selecciona."""
        if tablero_id in self._circuitos_por_tablero:
            return
        try:
            from circuito import CircuitoManager
            cm = CircuitoManager(parent=None)
            circs = cm.cargar_circuitos_de_tablero(tablero_id)
        except Exception as e:
            print(f"[SeccionCambios] Falla al cargar circuitos de {tablero_id}: {e}")
            circs = []
        self._circuitos_por_tablero[tablero_id] = circs
        for c in circs:
            self._originales_por_circuito[int(c["id"])] = dict(c)

    # ── Render del tablero activo ───────────────────────────────────
    def _render_tablero_activo(self):
        # Cierra edición si estaba abierta (cambio de tablero)
        self._cerrar_panel_edicion()

        # Limpiar contenedor
        while self.contenedor_lay.count():
            item = self.contenedor_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self._filas_por_circuito.clear()

        tid = self.combo_tableros.currentData()
        if not tid:
            return

        # Fetch lazy si es la primera vez
        self._asegurar_circuitos_de(tid)

        # Info del tablero (ubicación)
        tab = next((t for t in self._tableros if t.get("id") == tid), None)
        ubi = (tab.get("ubicacion", "") if tab else "") or ""
        self.lbl_info.setText(ubi)

        # Actualizar dropdown con conteo real
        self._actualizar_dropdown_texto()

        # Renderizar filas colapsadas
        circuitos = self._circuitos_por_tablero.get(tid, [])
        if not circuitos:
            vacio = QLabel("Este tablero no tiene circuitos capturados en inventario.")
            vacio.setStyleSheet("color: #666; padding: 20px; font-style: italic;")
            vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.contenedor_lay.addWidget(vacio)
            self.contenedor_lay.addStretch()
            return

        for c in circuitos:
            cid = int(c["id"])
            fila = _FilaCircuitoColapsada(c, parent=self.contenedor)
            fila.solicitar_toggle.connect(self._on_toggle_edicion)
            self.contenedor_lay.addWidget(fila)
            self._filas_por_circuito[cid] = fila

            # Aplicar estado visual si ya tenía modificaciones previas
            mods = self._modificaciones.get(tid, {}).get(cid, {})
            fila.refresh_visual(mods, en_edicion=False)

        self.contenedor_lay.addStretch()

    # ── Acordeón de edición ─────────────────────────────────────────
    def _on_toggle_edicion(self, circuito_id: int):
        """Abre o cierra el panel de edición del circuito solicitado."""
        if self._circuito_en_edicion == circuito_id:
            # Toggle: si ya está abierto, cerrar
            self._cerrar_panel_edicion()
            return

        # Cerrar el panel anterior si había uno abierto
        self._cerrar_panel_edicion()

        # Abrir el nuevo
        tid = self.combo_tableros.currentData()
        c = next(
            (x for x in self._circuitos_por_tablero.get(tid, [])
             if int(x["id"]) == circuito_id), None
        )
        if c is None:
            return

        mods = self._modificaciones.get(tid, {}).get(circuito_id, {})
        just = self._justificaciones.get(tid, {}).get(circuito_id, "")

        panel = _PanelEdicionCircuito(
            circuito=c,
            modificaciones_previas=mods,
            justificacion_previa=just,
            parent=self.contenedor,
        )
        panel.cambio_registrado.connect(self._on_panel_cambio)
        panel.solicitar_cerrar.connect(lambda _=None: self._cerrar_panel_edicion())

        # Insertar el panel JUSTO DEBAJO de la fila correspondiente
        idx = self.contenedor_lay.indexOf(self._filas_por_circuito[circuito_id])
        self.contenedor_lay.insertWidget(idx + 1, panel)

        self._circuito_en_edicion = circuito_id
        self._panel_edicion = panel

        # Actualizar aspecto de la fila (chevron up)
        self._filas_por_circuito[circuito_id].refresh_visual(mods, en_edicion=True)

    def _cerrar_panel_edicion(self):
        """Destruye el panel de edición si está abierto y actualiza la fila."""
        if self._panel_edicion is None:
            return
        cid = self._circuito_en_edicion
        self._panel_edicion.hide()
        self._panel_edicion.deleteLater()
        self._panel_edicion = None
        self._circuito_en_edicion = None

        # Refrescar la fila para que vuelva a mostrar lápiz
        fila = self._filas_por_circuito.get(cid)
        if fila is not None:
            tid = self.combo_tableros.currentData()
            mods = self._modificaciones.get(tid, {}).get(cid, {})
            fila.refresh_visual(mods, en_edicion=False)

    # ── Handler del panel de edición ────────────────────────────────
    def _on_panel_cambio(self, circuito_id: int,
                         cambios_dict: dict, justificacion: str):
        """Actualiza el estado persistente y sincroniza la fila colapsada."""
        tid = self.combo_tableros.currentData()
        if not tid:
            return

        if cambios_dict:
            self._modificaciones.setdefault(tid, {})[circuito_id] = cambios_dict
            self._justificaciones.setdefault(tid, {})[circuito_id] = justificacion
        else:
            if tid in self._modificaciones:
                self._modificaciones[tid].pop(circuito_id, None)
                if not self._modificaciones[tid]:
                    self._modificaciones.pop(tid, None)
            if tid in self._justificaciones:
                self._justificaciones[tid].pop(circuito_id, None)
                if not self._justificaciones[tid]:
                    self._justificaciones.pop(tid, None)

        # Refresco de la fila (mostrar tachado + flecha + nuevo)
        fila = self._filas_por_circuito.get(circuito_id)
        if fila is not None:
            fila.refresh_visual(cambios_dict, en_edicion=True)

        self._actualizar_dropdown_texto()
        self._actualizar_resumen()
        self.cambios_cambiaron.emit()

    # ── Refrescos ───────────────────────────────────────────────────
    def _actualizar_dropdown_texto(self):
        """Añade indicador '• N pendiente(s)' a tableros con cambios."""
        for i in range(self.combo_tableros.count()):
            tid = self.combo_tableros.itemData(i)
            tab = next((t for t in self._tableros if t.get("id") == tid), None)
            if tab is None:
                continue
            nombre = tab.get("nombre", "") or ""
            n_circ = len(self._circuitos_por_tablero.get(tid, []))
            if n_circ > 0:
                base = f"{tid} · {nombre} · {n_circ} circuito{'s' if n_circ != 1 else ''}"
            else:
                base = f"{tid} · {nombre}"
            n_cambios = len(self._modificaciones.get(tid, {}))
            if n_cambios > 0:
                base = f"{base}   •  {n_cambios} pendiente{'s' if n_cambios != 1 else ''}"
            self.combo_tableros.setItemText(i, base)

    def _actualizar_resumen(self):
        # No-op. El label global de resumen fue eliminado para evitar la
        # superposición visual sobre el último circuito del scroll. Se
        # mantiene el método como no-op porque otras rutas lo invocan;
        # el conteo de cambios ahora se comunica solo vía dropdown
        # ("N pendientes" en el texto del combo).
        return

    def _contar_sin_justificar(self) -> int:
        n = 0
        for tid, cids in self._modificaciones.items():
            for cid in cids:
                if not self._justificaciones.get(tid, {}).get(cid, "").strip():
                    n += 1
        return n

    # ── API pública (misma firma que la versión anterior) ───────────
    def hay_cambios_sin_justificar(self) -> bool:
        return self._contar_sin_justificar() > 0

    def total_cambios(self) -> int:
        return sum(
            sum(len(campos) for campos in cids.values())
            for cids in self._modificaciones.values()
        )

    def obtener_payload_updates(self) -> list:
        payload = []
        for tid, cids in self._modificaciones.items():
            for cid, campos in cids.items():
                for campo, valor_nuevo in campos.items():
                    payload.append({
                        "circuito_id": cid,
                        "campo": campo,
                        "valor_nuevo": valor_nuevo,
                    })
        return payload

    def obtener_payload_cambios(self, responsable_nombre: str = None) -> list:
        payload = []
        for tid, cids in self._modificaciones.items():
            for cid, campos in cids.items():
                justif = self._justificaciones.get(tid, {}).get(cid, "").strip()
                originales = self._originales_por_circuito.get(cid, {})
                for campo, valor_nuevo in campos.items():
                    payload.append({
                        "equipo_tipo":    "circuitos",
                        "equipo_id":      str(cid),
                        "tablero_id":     tid,
                        "campo":          campo,
                        "valor_anterior": originales.get(campo),
                        "valor_nuevo":    valor_nuevo,
                        "justificacion":  justif,
                        "responsable":    responsable_nombre,
                    })
        return payload


