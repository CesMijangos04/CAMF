"""
wizard_nuevo_proyecto.py
========================

Asistente de creación de nuevo proyecto en CAMF.

Diálogo modal de 4 pasos que captura la información necesaria para
crear un proyecto eléctrico. Los pasos:

    1. Datos generales    — nombre, cliente, dirección, responsable
    2. Tipo y región      — categoría (edificio / comercial / vivienda)
                            + estado geográfico
    3. Detalles           — arquitectónicos, condicionales según el tipo
                            (panel azul con los mínimos necesarios)
    4. Configuración      — voltaje, sistema y criterios para el motor

Al terminar (botón "Finalizar"), emite:

    proyecto_creado(dict)

que ``VentanaProyectos`` escucha para agregar el proyecto al listado.

Este archivo NO se ejecuta como parte de CAMF de manera aislada
(siempre se abre desde ``ventana_proyectos.py``), pero se puede
lanzar solo con:

    python proyectos/wizard_nuevo_proyecto.py

para desarrollar/probar el wizard aislado del listado.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

import qtawesome as qta


# ═════════════════════════════════════════════════════════════════════════
#  PALETA (misma que ventana_proyectos.py; local para autonomía)
# ═════════════════════════════════════════════════════════════════════════
COLOR_FONDO            = "#1a1a1a"   # más oscuro que la ventana principal (modal)
COLOR_FONDO_PANEL      = "#141414"   # panel condicional (más oscuro aún)
COLOR_SUPERFICIE       = "#1e1e1e"
COLOR_INPUT_BG         = "#1e1e1e"   # coincide con inputs del mockup del wizard
COLOR_INPUT_BG_HOVER   = "#242424"
COLOR_BORDE            = "#333333"
COLOR_BORDE_FUERTE     = "#444444"
COLOR_ACENTO           = "#0078d7"
COLOR_ACENTO_SUAVE     = "#85B7EB"   # texto azul claro del header del panel
COLOR_ACENTO_BRILLANTE = "#0094ff"
COLOR_ACENTO_HOVER     = "#005a9e"
COLOR_TEXTO            = "#ffffff"
COLOR_TEXTO_SUAVE      = "#dddddd"
COLOR_TEXTO_MUTED      = "#aaaaaa"
COLOR_TEXTO_APAGADO    = "#666666"


# ═════════════════════════════════════════════════════════════════════════
#  ESTADOS DE MÉXICO (para el combo de región del paso 2)
# ═════════════════════════════════════════════════════════════════════════
ESTADOS_MX = [
    "Aguascalientes", "Baja California", "Baja California Sur", "Campeche",
    "Chiapas", "Chihuahua", "Ciudad de México", "Coahuila", "Colima",
    "Durango", "Estado de México", "Guanajuato", "Guerrero", "Hidalgo",
    "Jalisco", "Michoacán", "Morelos", "Nayarit", "Nuevo León", "Oaxaca",
    "Puebla", "Querétaro", "Quintana Roo", "San Luis Potosí", "Sinaloa",
    "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala", "Veracruz",
    "Yucatán", "Zacatecas",
]


# ═════════════════════════════════════════════════════════════════════════
#  TIPOS DE PROYECTO
#  Solo los tres primeros están habilitados en el MVP.
#  El resto aparece con estilo apagado y tooltip "Próximamente".
# ═════════════════════════════════════════════════════════════════════════
TIPOS_PROYECTO = [
    ("edificio",     "Edificio",     "fa5s.building",       True),
    ("comercial",    "Comercial",    "fa5s.store",          True),
    ("vivienda",     "Vivienda",     "fa5s.home",           True),
    ("industrial",   "Industrial",   "fa5s.industry",       False),
    ("hospitalario", "Hospitalario", "fa5s.hospital",       False),
    ("educativo",    "Educativo",    "fa5s.school",         False),
    ("hotelero",     "Hotelero",     "fa5s.bed",            False),
    ("otro",         "Otro",         "fa5s.ellipsis-h",     False),
]


# ═════════════════════════════════════════════════════════════════════════
#  WIDGETS SIN RUEDA DEL MOUSE
#  Convención ya establecida en CAMF: evita cambios accidentales con scroll.
# ═════════════════════════════════════════════════════════════════════════
class _NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class _NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


# ═════════════════════════════════════════════════════════════════════════
#  ESTILOS REUTILIZABLES
# ═════════════════════════════════════════════════════════════════════════
def _estilo_input() -> str:
    return f"""
        QLineEdit {{
            background: {COLOR_INPUT_BG}; color: {COLOR_TEXTO};
            border: 1px solid {COLOR_BORDE_FUERTE};
            border-radius: 4px; padding: 6px 8px; font-size: 11px;
        }}
        QLineEdit:focus {{ border: 1px solid {COLOR_ACENTO}; }}
    """


def _estilo_combo() -> str:
    # Sin QComboBox::drop-down ni QComboBox::down-arrow custom:
    # el chevron nativo funciona bien en Windows 11 y evita el bug
    # de SVG data-URI de PyQt6 6.9.1 (memoria del proyecto).
    return f"""
        QComboBox {{
            background: {COLOR_INPUT_BG}; color: {COLOR_TEXTO};
            border: 1px solid {COLOR_BORDE_FUERTE};
            border-radius: 4px; padding: 6px 8px; font-size: 11px;
        }}
        QComboBox:hover {{ border: 1px solid #555; }}
        QComboBox:focus {{ border: 1px solid {COLOR_ACENTO}; }}
        QComboBox QAbstractItemView {{
            background: {COLOR_SUPERFICIE}; color: {COLOR_TEXTO_SUAVE};
            border: 1px solid {COLOR_BORDE_FUERTE};
            selection-background-color: {COLOR_ACENTO};
            selection-color: white; outline: 0;
        }}
    """


def _estilo_spinbox() -> str:
    return f"""
        QSpinBox {{
            background: {COLOR_INPUT_BG}; color: {COLOR_TEXTO};
            border: 1px solid {COLOR_BORDE_FUERTE};
            border-radius: 4px; padding: 6px 8px; font-size: 11px;
        }}
        QSpinBox:focus {{ border: 1px solid {COLOR_ACENTO}; }}
        QSpinBox::up-button, QSpinBox::down-button {{ width: 0; height: 0; }}
    """


def _estilo_checkbox() -> str:
    # El check nativo de Windows 11 se dibuja correctamente sobre un
    # indicator con background sólido azul (sin image: personalizada,
    # que rompería el render igual que en QComboBox).
    return f"""
        QCheckBox {{
            color: {COLOR_TEXTO_MUTED}; font-size: 11px; spacing: 6px;
            background: transparent;
        }}
        QCheckBox::indicator {{
            width: 12px; height: 12px; border-radius: 2px;
            background: {COLOR_INPUT_BG};
            border: 1px solid #555;
        }}
        QCheckBox::indicator:hover {{
            border: 1px solid {COLOR_ACENTO_SUAVE};
        }}
        QCheckBox::indicator:checked {{
            background: {COLOR_ACENTO};
            border: 1px solid {COLOR_ACENTO};
        }}
    """


def _estilo_boton_primario() -> str:
    return f"""
        QPushButton {{
            background: {COLOR_ACENTO}; color: white; border: none;
            border-radius: 6px; padding: 8px 18px;
            font-size: 12px; font-weight: 500;
        }}
        QPushButton:hover {{ background: {COLOR_ACENTO_BRILLANTE}; }}
        QPushButton:disabled {{
            background: #2a2a2a; color: {COLOR_TEXTO_APAGADO};
        }}
    """


def _estilo_boton_secundario() -> str:
    return f"""
        QPushButton {{
            background: #3a3a3a; color: white;
            border: none;
            border-radius: 6px; padding: 8px 16px; font-size: 12px;
        }}
        QPushButton:hover {{ background: #4a4a4a; }}
        QPushButton:disabled {{
            background: #232323; color: {COLOR_TEXTO_APAGADO};
        }}
    """


# ═════════════════════════════════════════════════════════════════════════
#  HELPERS DE UI
# ═════════════════════════════════════════════════════════════════════════
def _mini_label(texto: str) -> QLabel:
    """Label pequeño gris, usado arriba de cada input dentro del panel."""
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"""
        color: #888; font-size: 11px; background: transparent;
        margin-bottom: 0px;
    """)
    return lbl


def _campo_col(label_txt: str, widget: QWidget) -> QWidget:
    """
    Contenedor vertical: [mini label] + [widget de input].
    Espacio suficiente entre label e input para que no se vean pegados.
    """
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    v.addWidget(_mini_label(label_txt))
    v.addWidget(widget)
    return w


def _seccion_label(texto: str) -> QLabel:
    """Subheading gris que agrupa varios campos relacionados."""
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"""
        color: {COLOR_TEXTO_MUTED}; font-size: 11px; font-weight: 600;
        background: transparent; margin-top: 4px;
    """)
    return lbl


def _limpiar_layout_recursivo(layout) -> None:
    """
    Limpia un layout eliminando TODOS sus hijos (widgets y sub-layouts).
    Sin esto, al reconstruir el paso 3 los layouts anidados (HBoxLayout /
    QGridLayout dentro del QVBoxLayout del panel) no se limpian y sus
    widgets internos se solapan visualmente con los nuevos.
    """
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.deleteLater()
        else:
            sublayout = item.layout()
            if sublayout is not None:
                _limpiar_layout_recursivo(sublayout)
                sublayout.deleteLater()


# ═════════════════════════════════════════════════════════════════════════
#  STEPPER VISUAL
# ═════════════════════════════════════════════════════════════════════════
class Stepper(QWidget):
    """Indicador visual de progreso del wizard."""

    def __init__(self, pasos: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self._labels = pasos
        self._paso_actual = 0
        self.setStyleSheet(f"background: {COLOR_FONDO_PANEL};")
        self._construir()

    def _construir(self) -> None:
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(20, 14, 20, 14)
        self._lay.setSpacing(6)

        self._circulos: list[QLabel] = []
        self._textos: list[QLabel] = []
        self._lineas: list[QFrame] = []

        for idx, texto in enumerate(self._labels):
            # Círculo con número o check
            circ = QLabel()
            circ.setFixedSize(22, 22)
            circ.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._circulos.append(circ)

            # Texto al lado
            lbl = QLabel(texto)
            self._textos.append(lbl)

            self._lay.addWidget(circ)
            self._lay.addWidget(lbl)

            # Línea conectora (excepto al final)
            if idx < len(self._labels) - 1:
                linea = QFrame()
                linea.setFrameShape(QFrame.Shape.HLine)
                linea.setFixedHeight(1)
                linea.setMinimumWidth(20)
                self._lineas.append(linea)
                self._lay.addWidget(linea, 1)

        self._actualizar_estilos()

    def set_paso(self, idx: int) -> None:
        self._paso_actual = idx
        self._actualizar_estilos()

    def _actualizar_estilos(self) -> None:
        for i, circ in enumerate(self._circulos):
            if i < self._paso_actual:
                # Completado: círculo azul con check
                circ.setPixmap(
                    qta.icon("fa5s.check", color="white").pixmap(11, 11)
                )
                circ.setStyleSheet(f"""
                    background: {COLOR_ACENTO};
                    border-radius: 11px;
                """)
            elif i == self._paso_actual:
                # Actual: círculo azul con número
                circ.clear()
                circ.setText(str(i + 1))
                circ.setStyleSheet(f"""
                    background: {COLOR_ACENTO}; color: white;
                    font-size: 11px; font-weight: 500;
                    border-radius: 11px;
                """)
            else:
                # Futuro: círculo gris con número
                circ.clear()
                circ.setText(str(i + 1))
                circ.setStyleSheet(f"""
                    background: #2a2a2a; color: {COLOR_TEXTO_APAGADO};
                    font-size: 11px; font-weight: 500;
                    border-radius: 11px;
                """)

            # Texto del paso
            if i == self._paso_actual:
                self._textos[i].setStyleSheet(f"""
                    color: {COLOR_TEXTO}; font-size: 11px; font-weight: 500;
                    background: transparent;
                """)
            elif i < self._paso_actual:
                self._textos[i].setStyleSheet(f"""
                    color: {COLOR_TEXTO_MUTED}; font-size: 11px;
                    background: transparent;
                """)
            else:
                self._textos[i].setStyleSheet(f"""
                    color: {COLOR_TEXTO_APAGADO}; font-size: 11px;
                    background: transparent;
                """)

        # Líneas: azul si el paso anterior está completado
        for i, linea in enumerate(self._lineas):
            color = COLOR_ACENTO if i < self._paso_actual else "#333"
            linea.setStyleSheet(f"background: {color}; border: none;")


# ═════════════════════════════════════════════════════════════════════════
#  PASO 1: DATOS GENERALES
# ═════════════════════════════════════════════════════════════════════════
class Paso1DatosGenerales(QWidget):
    """
    Datos de identificación del proyecto y del responsable técnico.
    Todos estos campos alimentan la portada del reporte final y la
    firma UVIE, así que ninguno es opcional excepto los que indicamos.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {COLOR_FONDO};")

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(14)

        titulo = QLabel("Datos generales")
        titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO}; font-size: 15px; font-weight: 600;
            background: transparent;
        """)
        sub = QLabel("Información básica del proyecto y del responsable técnico.")
        sub.setStyleSheet(f"""
            color: {COLOR_TEXTO_MUTED}; font-size: 11px;
            background: transparent;
        """)
        v.addWidget(titulo)
        v.addWidget(sub)
        v.addSpacing(6)

        # Nombre del proyecto (obligatorio)
        self.ed_nombre = QLineEdit()
        self.ed_nombre.setPlaceholderText("Ej. Edificio aulas UAM Iztapalapa")
        self.ed_nombre.setStyleSheet(_estilo_input())
        v.addWidget(_campo_col("Nombre del proyecto *", self.ed_nombre))

        # Cliente (obligatorio)
        self.ed_cliente = QLineEdit()
        self.ed_cliente.setPlaceholderText("Nombre del cliente o razón social")
        self.ed_cliente.setStyleSheet(_estilo_input())
        v.addWidget(_campo_col("Cliente *", self.ed_cliente))

        # Dirección
        self.ed_direccion = QLineEdit()
        self.ed_direccion.setPlaceholderText("Calle, número, colonia, ciudad")
        self.ed_direccion.setStyleSheet(_estilo_input())
        v.addWidget(_campo_col("Dirección del predio", self.ed_direccion))

        # Fila: responsable + cédula
        fila_resp = QHBoxLayout()
        fila_resp.setSpacing(10)

        self.ed_responsable = QLineEdit()
        self.ed_responsable.setPlaceholderText("Nombre del ing. responsable")
        self.ed_responsable.setStyleSheet(_estilo_input())

        self.ed_cedula = QLineEdit()
        self.ed_cedula.setPlaceholderText("Cédula profesional")
        self.ed_cedula.setStyleSheet(_estilo_input())

        w_resp = _campo_col("Responsable técnico", self.ed_responsable)
        w_ced = _campo_col("Cédula profesional", self.ed_cedula)
        fila_resp.addWidget(w_resp, 2)
        fila_resp.addWidget(w_ced, 1)
        v.addLayout(fila_resp)

        # Fecha (autofill hoy, editable)
        self.ed_fecha = QLineEdit(date.today().strftime("%d/%m/%Y"))
        self.ed_fecha.setStyleSheet(_estilo_input())
        self.ed_fecha.setMaximumWidth(180)
        v.addWidget(_campo_col("Fecha de inicio", self.ed_fecha))

        v.addStretch()

    # -----------------------------------------------------------------
    def capturar(self) -> dict:
        return {
            "nombre":       self.ed_nombre.text().strip(),
            "cliente":      self.ed_cliente.text().strip(),
            "direccion":    self.ed_direccion.text().strip(),
            "responsable":  self.ed_responsable.text().strip(),
            "cedula":       self.ed_cedula.text().strip(),
            "fecha_inicio": self.ed_fecha.text().strip(),
        }

    def validar(self) -> str | None:
        d = self.capturar()
        if not d["nombre"]:
            return "El nombre del proyecto es obligatorio."
        if not d["cliente"]:
            return "El cliente es obligatorio."
        return None


# ═════════════════════════════════════════════════════════════════════════
#  PASO 2: TIPO Y REGIÓN
# ═════════════════════════════════════════════════════════════════════════
class Paso2TipoRegion(QWidget):
    """
    Categoría del proyecto (edificio / comercial / vivienda) y estado
    donde se ubica. El estado determina temperatura ambiente y voltaje
    típico de CFE para el motor de cálculo.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {COLOR_FONDO};")

        self._tipo_seleccionado: str | None = None
        self._botones_tipo: dict[str, QPushButton] = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(14)

        titulo = QLabel("Tipo de proyecto")
        titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO}; font-size: 15px; font-weight: 600;
            background: transparent;
        """)
        sub = QLabel(
            "Selecciona la categoría del proyecto. El estado define voltaje "
            "típico de suministro y temperatura ambiente para el cálculo."
        )
        sub.setStyleSheet(f"""
            color: {COLOR_TEXTO_MUTED}; font-size: 11px;
            background: transparent;
        """)
        sub.setWordWrap(True)
        v.addWidget(titulo)
        v.addWidget(sub)
        v.addSpacing(6)

        # Grid de tipos: 4 columnas
        v.addWidget(_mini_label("Categoría"))

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 4, 0, 0)
        for idx, (tipo, label, icono, habilitado) in enumerate(TIPOS_PROYECTO):
            btn = self._crear_boton_tipo(tipo, label, icono, habilitado)
            self._botones_tipo[tipo] = btn
            grid.addWidget(btn, idx // 4, idx % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)

        v.addSpacing(10)

        # Región (combo)
        self.combo_region = _NoWheelComboBox()
        self.combo_region.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_region.addItems(ESTADOS_MX)
        self.combo_region.setCurrentText("Ciudad de México")
        self.combo_region.setStyleSheet(_estilo_combo())
        v.addWidget(_campo_col("Estado *", self.combo_region))

        v.addStretch()

    # -----------------------------------------------------------------
    def _crear_boton_tipo(self, tipo: str, label: str, icono: str,
                          habilitado: bool) -> QPushButton:
        btn = QPushButton()
        btn.setFixedHeight(72)
        btn.setCursor(
            Qt.CursorShape.PointingHandCursor if habilitado
            else Qt.CursorShape.ForbiddenCursor
        )
        if not habilitado:
            btn.setToolTip("Próximamente")
            btn.setEnabled(False)

        # Contenido interno: ícono grande + label debajo
        interior = QVBoxLayout(btn)
        interior.setContentsMargins(6, 8, 6, 8)
        interior.setSpacing(4)
        interior.setAlignment(Qt.AlignmentFlag.AlignCenter)

        color_icono = COLOR_TEXTO_MUTED if habilitado else COLOR_TEXTO_APAGADO
        color_texto = COLOR_TEXTO_SUAVE if habilitado else COLOR_TEXTO_APAGADO

        ico = QLabel()
        ico.setPixmap(qta.icon(icono, color=color_icono).pixmap(22, 22))
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet("background: transparent;")

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"""
            color: {color_texto}; font-size: 11px; background: transparent;
        """)

        interior.addWidget(ico)
        interior.addWidget(lbl)

        self._aplicar_estilo_boton_tipo(btn, activo=False, habilitado=habilitado)
        if habilitado:
            btn.clicked.connect(lambda: self._seleccionar_tipo(tipo))
        return btn

    def _aplicar_estilo_boton_tipo(self, btn: QPushButton,
                                    activo: bool, habilitado: bool) -> None:
        if activo:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #0d3a5c;
                    border: 2px solid {COLOR_ACENTO};
                    border-radius: 6px;
                }}
            """)
        elif habilitado:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {COLOR_SUPERFICIE};
                    border: 1px solid {COLOR_BORDE};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: {COLOR_INPUT_BG_HOVER};
                    border: 1px solid {COLOR_BORDE_FUERTE};
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #171717;
                    border: 1px solid #262626;
                    border-radius: 6px;
                }}
            """)

    def _seleccionar_tipo(self, tipo: str) -> None:
        self._tipo_seleccionado = tipo
        for t, btn in self._botones_tipo.items():
            habilitado = btn.isEnabled()
            self._aplicar_estilo_boton_tipo(btn, activo=(t == tipo),
                                             habilitado=habilitado)

    # -----------------------------------------------------------------
    def capturar(self) -> dict:
        return {
            "tipo":   self._tipo_seleccionado,
            "region": self.combo_region.currentText(),
        }

    def validar(self) -> str | None:
        if not self._tipo_seleccionado:
            return "Selecciona una categoría de proyecto."
        return None


# ═════════════════════════════════════════════════════════════════════════
#  PASO 3: DETALLES ARQUITECTÓNICOS (CONDICIONAL SEGÚN TIPO)
#
#  Panel condicional al estilo del mockup aprobado:
#    - borde completo azul + border-left grueso
#    - header con ícono info + texto azul claro "Cuéntanos sobre X"
#    - grid 2x2 de campos con label pequeño encima
#    - checkboxes horizontales al pie
#
#  Los campos son los MÍNIMOS necesarios para arrancar el proyecto y
#  autogenerar los planos por nivel. Todo lo demás (subestación, cargas
#  especiales, distribución) se determina en el espacio de trabajo con
#  los planos cargados y las cargas colocadas.
# ═════════════════════════════════════════════════════════════════════════
class Paso3Detalles(QWidget):

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {COLOR_FONDO};")

        self._tipo_actual: str | None = None
        self._widgets: dict[str, QWidget] = {}

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(24, 20, 24, 20)
        self._lay.setSpacing(12)

        titulo = QLabel("Detalles del proyecto")
        titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO}; font-size: 15px; font-weight: 600;
            background: transparent;
        """)
        sub = QLabel(
            "Información arquitectónica mínima para autogenerar los planos "
            "por nivel. El detalle fino se define al cargar cada plano."
        )
        sub.setStyleSheet(f"""
            color: {COLOR_TEXTO_MUTED}; font-size: 11px;
            background: transparent;
        """)
        sub.setWordWrap(True)
        self._lay.addWidget(titulo)
        self._lay.addWidget(sub)
        self._lay.addSpacing(4)

        # Panel condicional — borde completo azul + border-left grueso.
        # Ojo: el selector DEBE llevar objectName. Si se usa "QFrame { ... }"
        # sin identificador, la regla cascadea a todos los QFrame descendientes;
        # como QLabel hereda de QFrame, cada label del panel termina con un
        # rectángulo azul alrededor. Con "QFrame#panelCondicional" la regla
        # se aplica únicamente a este panel y los labels quedan limpios.
        self._panel = QFrame()
        self._panel.setObjectName("panelCondicional")
        self._panel.setStyleSheet(f"""
            QFrame#panelCondicional {{
                background: {COLOR_FONDO_PANEL};
                border: 1px solid {COLOR_ACENTO};
                border-left: 3px solid {COLOR_ACENTO};
                border-radius: 5px;
            }}
        """)
        self._panel_lay = QVBoxLayout(self._panel)
        self._panel_lay.setContentsMargins(16, 14, 16, 14)
        self._panel_lay.setSpacing(12)
        self._lay.addWidget(self._panel)
        self._lay.addStretch()

    # -----------------------------------------------------------------
    def configurar_para_tipo(self, tipo: str | None) -> None:
        """Reconstruye los campos según el tipo elegido en paso 2."""
        if tipo == self._tipo_actual:
            return
        self._tipo_actual = tipo
        self._widgets.clear()
        _limpiar_layout_recursivo(self._panel_lay)

        if tipo == "edificio":
            self._construir_edificio()
        elif tipo == "comercial":
            self._construir_comercial()
        elif tipo == "vivienda":
            self._construir_vivienda()
        else:
            self._construir_placeholder()

    # -----------------------------------------------------------------
    def _header_panel(self, texto: str) -> None:
        """Header azul dentro del panel: [ícono info] [texto]."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.info-circle", color=COLOR_ACENTO_SUAVE).pixmap(12, 12))
        ico.setFixedSize(12, 12)

        lbl = QLabel(texto)
        lbl.setStyleSheet(f"""
            color: {COLOR_ACENTO_SUAVE}; font-size: 11px; font-weight: 600;
            background: transparent;
        """)

        h.addWidget(ico)
        h.addWidget(lbl)
        h.addStretch()
        self._panel_lay.addWidget(w)

    def _grid_2col(self, campos: list[tuple[str, QWidget]]) -> None:
        """Agrega los campos en grid 2 columnas dentro del panel."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setContentsMargins(0, 0, 0, 0)
        for i, (label_txt, widget) in enumerate(campos):
            grid.addWidget(_campo_col(label_txt, widget), i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._panel_lay.addLayout(grid)

    def _chks_horizontales(self, checks: list[QCheckBox]) -> None:
        """Agrega checkboxes horizontales al pie del panel."""
        h = QHBoxLayout()
        h.setContentsMargins(0, 4, 0, 0)
        h.setSpacing(18)
        for chk in checks:
            h.addWidget(chk)
        h.addStretch()
        self._panel_lay.addLayout(h)

    # -----------------------------------------------------------------
    def _construir_edificio(self) -> None:
        self._header_panel("Cuéntanos más sobre el edificio")

        # Combos y spinboxes
        uso = _NoWheelComboBox()
        uso.setCursor(Qt.CursorShape.PointingHandCursor)
        uso.addItems(["Oficinas", "Aulas y oficinas",
                      "Departamentos (habitacional)", "Mixto"])
        uso.setStyleSheet(_estilo_combo())
        self._widgets["uso"] = uso

        pisos = _NoWheelSpinBox()
        pisos.setRange(1, 100)
        pisos.setValue(4)
        pisos.setStyleSheet(_estilo_spinbox())
        self._widgets["pisos"] = pisos

        sotanos = _NoWheelSpinBox()
        sotanos.setRange(0, 10)
        sotanos.setValue(0)
        sotanos.setStyleSheet(_estilo_spinbox())
        self._widgets["sotanos"] = sotanos

        self._grid_2col([
            ("Uso principal",    uso),
            ("Pisos sobre nivel", pisos),
            ("Sótanos",           sotanos),
        ])

        # Checkbox
        azotea = QCheckBox("Azotea utilizable")
        azotea.setStyleSheet(_estilo_checkbox())
        azotea.setCursor(Qt.CursorShape.PointingHandCursor)
        self._widgets["azotea"] = azotea
        self._chks_horizontales([azotea])

    def _construir_comercial(self) -> None:
        self._header_panel("Cuéntanos más sobre el proyecto comercial")

        niveles = _NoWheelSpinBox()
        niveles.setRange(1, 20)
        niveles.setValue(1)
        niveles.setStyleSheet(_estilo_spinbox())
        self._widgets["niveles"] = niveles

        locales = _NoWheelSpinBox()
        locales.setRange(1, 500)
        locales.setValue(10)
        locales.setStyleSheet(_estilo_spinbox())
        self._widgets["locales"] = locales

        self._grid_2col([
            ("Niveles",                    niveles),
            ("Locales rentables (aprox.)", locales),
        ])

        clima = QCheckBox("Áreas comunes climatizadas centralmente")
        clima.setStyleSheet(_estilo_checkbox())
        clima.setCursor(Qt.CursorShape.PointingHandCursor)
        self._widgets["clima_central"] = clima

        estacionamiento = QCheckBox("Estacionamiento")
        estacionamiento.setStyleSheet(_estilo_checkbox())
        estacionamiento.setCursor(Qt.CursorShape.PointingHandCursor)
        self._widgets["estacionamiento"] = estacionamiento

        self._chks_horizontales([clima, estacionamiento])

    def _construir_vivienda(self) -> None:
        self._header_panel("Cuéntanos más sobre la vivienda")

        niveles = _NoWheelSpinBox()
        niveles.setRange(1, 6)
        niveles.setValue(2)
        niveles.setStyleSheet(_estilo_spinbox())
        self._widgets["niveles"] = niveles

        self._grid_2col([
            ("Niveles", niveles),
        ])

        azotea = QCheckBox("Azotea utilizable")
        azotea.setStyleSheet(_estilo_checkbox())
        azotea.setCursor(Qt.CursorShape.PointingHandCursor)
        self._widgets["azotea"] = azotea

        jardin = QCheckBox("Patio o jardín")
        jardin.setStyleSheet(_estilo_checkbox())
        jardin.setCursor(Qt.CursorShape.PointingHandCursor)
        self._widgets["jardin"] = jardin

        alberca = QCheckBox("Alberca")
        alberca.setStyleSheet(_estilo_checkbox())
        alberca.setCursor(Qt.CursorShape.PointingHandCursor)
        self._widgets["alberca"] = alberca

        self._chks_horizontales([azotea, jardin, alberca])

    def _construir_placeholder(self) -> None:
        lbl = QLabel("Selecciona un tipo de proyecto en el paso anterior.")
        lbl.setStyleSheet(f"""
            color: {COLOR_TEXTO_MUTED}; font-size: 12px;
            background: transparent;
        """)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._panel_lay.addWidget(lbl)

    # -----------------------------------------------------------------
    def capturar(self) -> dict:
        d: dict = {"tipo": self._tipo_actual}
        for key, w in self._widgets.items():
            if isinstance(w, QComboBox):
                d[key] = w.currentText()
            elif isinstance(w, QSpinBox):
                d[key] = w.value()
            elif isinstance(w, QCheckBox):
                d[key] = w.isChecked()
        return d

    def validar(self) -> str | None:
        # Todos los defaults son razonables; no hay campos estrictamente
        # obligatorios en este paso.
        return None


# ═════════════════════════════════════════════════════════════════════════
#  PASO 4: CONFIGURACIÓN ELÉCTRICA BASE
#
#  Cuatro secciones ordenadas por importancia para el motor de propuesta:
#
#  1. Sistema de suministro — un solo combo con configuraciones reales
#     de CFE. Cada opción encapsula tensión Y sistema de hilos, porque
#     en la práctica van juntos (un monofásico 3H entrega 127/220 V al
#     mismo tablero; no tiene sentido separarlos en dos preguntas).
#     Si después una carga necesita voltaje incompatible (elevador a
#     440 V en un sistema 127/220 V), el motor propone automáticamente
#     transformador seco elevador en su topología — el proyectista NO
#     decide eso aquí.
#
#  2. Criterios de agrupación — máx. salidas por circuito y caída de
#     tensión máx. Son TECHOS que respeta el motor. Si un circuito
#     con 10 salidas no cumple la caída al fondo de un pasillo largo,
#     el motor baja a 8 o 6 salidas automáticamente. Nunca al revés.
#
#  3. Materiales por default — un default para circuitos derivados y
#     otro para alimentadores. Reflejan la práctica real mexicana:
#     cobre en derivados por seguridad y manipulación; en alimentadores
#     grandes suele elegirse aluminio para reducir costos (~1/3 del
#     precio del cobre). Editable por circuito en el espacio de trabajo.
#
#  4. Reserva de crecimiento — espacios extra en tableros para futuras
#     cargas (default 25%, criterio de buena práctica).
# ═════════════════════════════════════════════════════════════════════════
class Paso4ConfigElectrica(QWidget):

    # Configuraciones reales de suministro CFE en México.
    SISTEMAS_SUMINISTRO = [
        "Monofásico 2H · 127 V",
        "Monofásico 3H · 127/220 V",
        "Trifásico 4H · 127/220 V",
        "Trifásico 4H · 220/440 V",
        "Trifásico 4H · 277/480 V",
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {COLOR_FONDO};")

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(14)

        titulo = QLabel("Configuración eléctrica base")
        titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO}; font-size: 15px; font-weight: 600;
            background: transparent;
        """)
        sub = QLabel(
            "Parámetros generales del proyecto. El motor los usa como base "
            "y son editables por circuito en el espacio de trabajo."
        )
        sub.setStyleSheet(f"""
            color: {COLOR_TEXTO_MUTED}; font-size: 11px;
            background: transparent;
        """)
        sub.setWordWrap(True)
        v.addWidget(titulo)
        v.addWidget(sub)
        v.addSpacing(6)

        # ── 1. Sistema de suministro ─────────────────────────────────
        self.combo_sistema = _NoWheelComboBox()
        self.combo_sistema.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_sistema.addItems(self.SISTEMAS_SUMINISTRO)
        self.combo_sistema.setCurrentText("Monofásico 3H · 127/220 V")
        self.combo_sistema.setStyleSheet(_estilo_combo())
        v.addWidget(_campo_col("Sistema de suministro", self.combo_sistema))

        # ── 2. Criterios de agrupación ───────────────────────────────
        v.addSpacing(4)
        v.addWidget(_seccion_label("Criterios de agrupación"))

        self.spin_max_salidas = _NoWheelSpinBox()
        self.spin_max_salidas.setRange(1, 20)
        self.spin_max_salidas.setValue(10)
        self.spin_max_salidas.setStyleSheet(_estilo_spinbox())

        self.spin_caida_max = _NoWheelSpinBox()
        self.spin_caida_max.setRange(1, 10)
        self.spin_caida_max.setValue(3)
        self.spin_caida_max.setSuffix(" %")
        self.spin_caida_max.setStyleSheet(_estilo_spinbox())

        fila_crit = QHBoxLayout()
        fila_crit.setSpacing(10)
        fila_crit.addWidget(_campo_col("Máx. salidas por circuito", self.spin_max_salidas), 1)
        fila_crit.addWidget(_campo_col("Caída máx. en derivados", self.spin_caida_max), 1)
        v.addLayout(fila_crit)

        # ── 3. Materiales por default ────────────────────────────────
        v.addSpacing(4)
        v.addWidget(_seccion_label("Materiales por default"))

        self.combo_mat_derivados = _NoWheelComboBox()
        self.combo_mat_derivados.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_mat_derivados.addItems(["Cobre", "Aluminio"])
        self.combo_mat_derivados.setStyleSheet(_estilo_combo())

        self.combo_mat_alimentadores = _NoWheelComboBox()
        self.combo_mat_alimentadores.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_mat_alimentadores.addItems(["Cobre", "Aluminio"])
        self.combo_mat_alimentadores.setStyleSheet(_estilo_combo())

        fila_mat = QHBoxLayout()
        fila_mat.setSpacing(10)
        fila_mat.addWidget(_campo_col("Circuitos derivados", self.combo_mat_derivados), 1)
        fila_mat.addWidget(_campo_col("Alimentadores", self.combo_mat_alimentadores), 1)
        v.addLayout(fila_mat)

        # ── 4. Reserva de crecimiento ────────────────────────────────
        v.addSpacing(4)
        self.spin_reserva = _NoWheelSpinBox()
        self.spin_reserva.setRange(0, 100)
        self.spin_reserva.setValue(25)
        self.spin_reserva.setSuffix(" %")
        self.spin_reserva.setStyleSheet(_estilo_spinbox())
        self.spin_reserva.setMaximumWidth(180)
        v.addWidget(_campo_col("Reserva de crecimiento", self.spin_reserva))

        v.addStretch()

    # -----------------------------------------------------------------
    def capturar(self) -> dict:
        return {
            "sistema_suministro": self.combo_sistema.currentText(),
            "max_salidas":        self.spin_max_salidas.value(),
            "caida_max":          self.spin_caida_max.value(),
            "material_derivados": self.combo_mat_derivados.currentText(),
            "material_alimentadores": self.combo_mat_alimentadores.currentText(),
            "reserva_pct":        self.spin_reserva.value(),
        }

    def validar(self) -> str | None:
        return None


# ═════════════════════════════════════════════════════════════════════════
#  DIÁLOGO PRINCIPAL DEL WIZARD
# ═════════════════════════════════════════════════════════════════════════
class WizardNuevoProyecto(QDialog):
    """
    Asistente de 4 pasos para crear un nuevo proyecto.
    Emite ``proyecto_creado(dict)`` al finalizar exitosamente.
    """

    proyecto_creado = pyqtSignal(dict)

    LABELS_PASOS = ["Datos", "Tipo", "Detalles", "Eléctrico"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Nuevo proyecto")
        self.setModal(True)
        self.setFixedSize(680, 700)
        self.setStyleSheet(f"""
            QDialog {{ background: {COLOR_FONDO}; }}
            QScrollArea QLabel {{ background: transparent; }}
            QPushButton {{ outline: none; }}
        """)

        self._paso_actual = 0

        self._pasos: list[QWidget] = [
            Paso1DatosGenerales(),
            Paso2TipoRegion(),
            Paso3Detalles(),
            Paso4ConfigElectrica(),
        ]

        self._build_ui()
        self._actualizar_estado()

    # ═══════════════════════════════════════════════════════════════════
    #  UI
    # ═══════════════════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        # ── Header (SIN border-bottom) ───────────────────────────────
        header = QFrame()
        header.setFixedHeight(58)
        header.setStyleSheet(f"QFrame {{ background: {COLOR_FONDO_PANEL}; }}")

        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 10, 12, 10)

        cont_txt = QVBoxLayout()
        cont_txt.setSpacing(2)
        titulo = QLabel("Nuevo proyecto")
        titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO}; font-size: 14px; font-weight: 600;
            background: transparent;
        """)
        self._sub_titulo = QLabel("")
        self._sub_titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO_MUTED}; font-size: 11px;
            background: transparent;
        """)
        cont_txt.addWidget(titulo)
        cont_txt.addWidget(self._sub_titulo)

        btn_cerrar = QPushButton()
        btn_cerrar.setFixedSize(28, 28)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setIcon(qta.icon("fa5s.times", color=COLOR_TEXTO_MUTED))
        btn_cerrar.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; }}
            QPushButton:hover {{ background: {COLOR_INPUT_BG}; border-radius: 4px; }}
        """)
        btn_cerrar.clicked.connect(self.reject)

        h_lay.addLayout(cont_txt, 1)
        h_lay.addWidget(btn_cerrar, 0, Qt.AlignmentFlag.AlignTop)
        raiz.addWidget(header)

        # ── Stepper (SIN separador debajo) ───────────────────────────
        self._stepper = Stepper(self.LABELS_PASOS)
        raiz.addWidget(self._stepper)

        # ── Body: scroll con stack de pasos ──────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {COLOR_FONDO}; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 10px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #444; border-radius: 4px;
                min-height: 30px; margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{ background: #555; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                background: none; height: 0; border: none;
            }}
        """)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {COLOR_FONDO};")
        for p in self._pasos:
            self._stack.addWidget(p)

        scroll.setWidget(self._stack)
        raiz.addWidget(scroll, 1)

        # ── Footer (SIN border-top) ──────────────────────────────────
        footer = QFrame()
        footer.setFixedHeight(56)
        footer.setStyleSheet(f"QFrame {{ background: {COLOR_FONDO_PANEL}; }}")

        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(20, 10, 20, 10)

        self._lbl_paso = QLabel("")
        self._lbl_paso.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO}; font-size: 11px;
            background: transparent;
        """)

        self.btn_anterior = QPushButton("Anterior")
        self.btn_anterior.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_anterior.setStyleSheet(_estilo_boton_secundario())
        self.btn_anterior.clicked.connect(self._anterior)

        self.btn_siguiente = QPushButton("Siguiente")
        self.btn_siguiente.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_siguiente.setStyleSheet(_estilo_boton_primario())
        self.btn_siguiente.clicked.connect(self._siguiente)

        f_lay.addWidget(self._lbl_paso, 1)
        f_lay.addWidget(self.btn_anterior)
        f_lay.addWidget(self.btn_siguiente)
        raiz.addWidget(footer)

    # ═══════════════════════════════════════════════════════════════════
    #  NAVEGACIÓN
    # ═══════════════════════════════════════════════════════════════════
    def _siguiente(self) -> None:
        # Validar paso actual
        error = self._pasos[self._paso_actual].validar()
        if error:
            QMessageBox.warning(self, "Falta información", error)
            return

        if self._paso_actual == len(self._pasos) - 1:
            self._finalizar()
            return

        self._paso_actual += 1

        # Si entramos al paso 3, reconfigurarlo con el tipo del paso 2.
        if self._paso_actual == 2:
            tipo = self._pasos[1].capturar().get("tipo")
            self._pasos[2].configurar_para_tipo(tipo)

        self._actualizar_estado()

    def _anterior(self) -> None:
        if self._paso_actual == 0:
            return
        self._paso_actual -= 1
        self._actualizar_estado()

    def _actualizar_estado(self) -> None:
        self._stack.setCurrentIndex(self._paso_actual)
        self._stepper.set_paso(self._paso_actual)

        total = len(self._pasos)
        self._sub_titulo.setText(
            f"Paso {self._paso_actual + 1} de {total} · "
            f"{self.LABELS_PASOS[self._paso_actual]}"
        )
        self._lbl_paso.setText(f"Paso {self._paso_actual + 1} de {total}")

        self.btn_anterior.setEnabled(self._paso_actual > 0)
        self.btn_siguiente.setText(
            "Finalizar" if self._paso_actual == total - 1 else "Siguiente"
        )

    # ═══════════════════════════════════════════════════════════════════
    #  FINALIZACIÓN
    # ═══════════════════════════════════════════════════════════════════
    def _finalizar(self) -> None:
        d_generales = self._pasos[0].capturar()
        d_tipo      = self._pasos[1].capturar()
        d_detalles  = self._pasos[2].capturar()
        d_electrico = self._pasos[3].capturar()

        proyecto = {
            "nombre":  d_generales["nombre"],
            "cliente": d_generales["cliente"],
            "tipo":    d_tipo["tipo"],
            "subtipo": self._construir_subtipo(d_tipo["tipo"], d_detalles),
            # Datos completos para el espacio de trabajo:
            "datos_generales":   d_generales,
            "tipo_proyecto":     d_tipo,
            "detalles":          d_detalles,
            "config_electrica":  d_electrico,
        }

        self.proyecto_creado.emit(proyecto)
        self.accept()

    def _construir_subtipo(self, tipo: str, detalles: dict) -> str:
        """Genera el subtitle visible en la card del listado."""
        if tipo == "edificio":
            uso = detalles.get("uso", "Edificio")
            pisos = detalles.get("pisos", 0)
            sotanos = detalles.get("sotanos", 0)
            partes = [uso, f"{pisos} pisos"]
            if sotanos > 0:
                partes.append(f"{sotanos} sótano{'s' if sotanos > 1 else ''}")
            return " · ".join(partes)

        if tipo == "comercial":
            niveles = detalles.get("niveles", 1)
            locales = detalles.get("locales", 0)
            return f"Comercial · {niveles} nivel{'es' if niveles != 1 else ''} · {locales} locales"

        if tipo == "vivienda":
            niveles = detalles.get("niveles", 1)
            return f"Vivienda · {niveles} nivel{'es' if niveles != 1 else ''}"

        return tipo.capitalize() if tipo else "Proyecto"


# ═════════════════════════════════════════════════════════════════════════
#  EJECUCIÓN INDEPENDIENTE (desarrollo / prueba aislada)
# ═════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    app = QApplication(sys.argv)

    wiz = WizardNuevoProyecto()

    def _mostrar(dato: dict):
        import json
        print("Proyecto creado:")
        print(json.dumps(dato, indent=2, ensure_ascii=False))

    wiz.proyecto_creado.connect(_mostrar)
    wiz.exec()
    sys.exit(0)
