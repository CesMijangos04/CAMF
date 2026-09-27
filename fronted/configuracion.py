# configuracion.py
"""
Ventana de Configuración estilo Windows 11 Settings.

NOTA SOBRE ESTILOS: No usamos self.setStyleSheet() a nivel de ConfiguracionWindow.
Eso cambia el motor de renderizado de Qt para TODOS los descendientes (incluyendo
los QDialog abiertos con parent=alguna_subpagina), haciendo que pierdan la
apariencia nativa de Windows 11 y se vean "más planos". En su lugar, cada widget
estilizado (botones, filas, scroll areas) recibe su propio setStyleSheet.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
import qtawesome as qta

from responsables_config import (
    ResponsablesSelectorPage,
    ListaPersonalPage,
    ListaProveedoresPage,
)
from base_datos_config import BaseDatosPage
from acerca_de_config import AcercaDePage
from reportes_config import (
    ReportesSelectorPage,
    ReportesPlantillasPage,
    ReportesFirmasPage,
    ReportesFoliosPage,
    ReportesAlmacenamientoPage,
    ReportesFormatoPage,
)


# ── IDs de página ────────────────────────────────────────────────────────────
PAGE_HOME         = 0
PAGE_RESPONSABLES = 1
PAGE_PERSONAL     = 2
PAGE_PROVEEDORES  = 3
PAGE_BASEDATOS    = 4
PAGE_ACERCADE     = 5

# Reportes (selector + 5 sub-páginas)
PAGE_REPORTES_HOME           = 6
PAGE_REPORTES_PLANTILLAS     = 7
PAGE_REPORTES_FIRMAS         = 8
PAGE_REPORTES_FOLIOS         = 9
PAGE_REPORTES_ALMACENAMIENTO = 10
PAGE_REPORTES_FORMATO        = 11


# ── Catálogo de opciones de la home ──────────────────────────────────────────
OPCIONES = [
    ("GENERAL", "Responsables",   "Administrar personal y proveedores",
        "fa5s.users",        "#6fc28f", "#1f3a26", "responsables"),
    ("GENERAL", "Calendario",     "Google Calendar y notificaciones",
        "fa5s.calendar-alt", "#5cb1ff", "#1a2c3d", "calendario"),
    ("GENERAL", "Reportes",       "Plantillas y formatos PDF",
        "fa5s.file-pdf",     "#e67e22", "#3a2418", "reportes"),
    ("GENERAL", "Alertas",        "Recordatorios y vencimientos",
        "fa5s.bell",         "#f1c40f", "#3a3318", "alertas"),

    ("SISTEMA", "Base de datos",  "Respaldos y sincronización",
        "fa5s.database",     "#6fc28f", "#1f3a2e", "basedatos"),
    ("SISTEMA", "Usuarios",       "Permisos y accesos",
        "fa5s.user-shield",  "#d4a04c", "#332a18", "usuarios"),
    ("SISTEMA", "Acerca de",      "Información del sistema",
        "fa5s.info-circle",  "#5cb1ff", "#1a2c3d", "acercade"),
]


# ── Estilos reutilizables (aplicados a widgets individuales) ────────────────
SCROLLBAR_QSS = """
    QScrollArea { background: transparent; border: none; }
    QScrollBar:vertical { background: #1a1a1a; width: 10px; margin: 0; }
    QScrollBar::handle:vertical {
        background: #444; border-radius: 4px;
        min-height: 30px; margin: 2px;
    }
    QScrollBar::handle:vertical:hover { background: #555; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        background: none; height: 0; border: none;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
"""


# ── Fila clickable de la home ────────────────────────────────────────────────
class SettingsRow(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, titulo, descripcion, icon_name, icon_color, chip_bg, key, parent=None):
        super().__init__(parent)
        self.key = key

        self.setObjectName("settings_row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Estilo SOLO en este widget — no se propaga al diálogo (no es ancestro)
        self.setStyleSheet("""
            QFrame#settings_row {
                background: #2b2b2b;
                border-radius: 8px;
                border: 1px solid transparent;
            }
            QFrame#settings_row:hover {
                background: #333333;
                border: 1px solid #0078d7;
            }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 16, 12)
        lay.setSpacing(14)

        chip = QFrame()
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedSize(36, 36)
        chip.setStyleSheet(f"background: {chip_bg}; border-radius: 8px;")
        chip_lay = QVBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono = QLabel()
        icono.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(18, 18))
        icono.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip_lay.addWidget(icono)
        lay.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(
            "color: white; font-size: 14px; font-weight: 500; background: transparent;"
        )
        text_box.addWidget(lbl_titulo)
        lbl_desc = QLabel(descripcion)
        lbl_desc.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
        text_box.addWidget(lbl_desc)
        lay.addLayout(text_box, 1)

        self._chevron = QLabel()
        self._chevron.setPixmap(qta.icon("fa5s.chevron-right", color="#666").pixmap(12, 12))
        self._chevron.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._chevron.setFixedSize(12, 12)
        lay.addWidget(self._chevron, alignment=Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._chevron.setPixmap(qta.icon("fa5s.chevron-right", color="#bbb").pixmap(12, 12))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._chevron.setPixmap(qta.icon("fa5s.chevron-right", color="#666").pixmap(12, 12))
        super().leaveEvent(event)


# ── Ventana principal ────────────────────────────────────────────────────────
class ConfiguracionWindow(QWidget):
    def __init__(self):
        super().__init__()
        # CLAVE: NO llamar self.setStyleSheet aquí. Romperia la apariencia
        # nativa de los QDialog que se abren con parent=alguna sub-página.
        self._nav_stack = [PAGE_HOME]
        self._construir_ui()

    def _construir_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        # Stack con las páginas
        self.stack = QStackedWidget()

        self._pagina_home = self._build_pagina_home()
        self.stack.addWidget(self._pagina_home)            # 0

        self._pagina_responsables = ResponsablesSelectorPage()
        self._pagina_responsables.solicitar_personal.connect(
            lambda: self.navegar_a(PAGE_PERSONAL)
        )
        self._pagina_responsables.solicitar_proveedor.connect(
            lambda: self.navegar_a(PAGE_PROVEEDORES)
        )
        self.stack.addWidget(self._pagina_responsables)    # 1

        self._pagina_personal = ListaPersonalPage()
        self._pagina_personal.contador_cambio.connect(self._actualizar_subtitulo_actual)
        self.stack.addWidget(self._pagina_personal)        # 2

        self._pagina_proveedores = ListaProveedoresPage()
        self._pagina_proveedores.contador_cambio.connect(self._actualizar_subtitulo_actual)
        self.stack.addWidget(self._pagina_proveedores)     # 3

        self._pagina_basedatos = BaseDatosPage()
        self.stack.addWidget(self._pagina_basedatos)       # 4

        self._pagina_acercade = AcercaDePage()
        self.stack.addWidget(self._pagina_acercade)        # 5

        # ── Reportes (selector + 5 sub-páginas) ──────────────────────
        self._pagina_reportes_home = ReportesSelectorPage()
        self._pagina_reportes_home.solicitar_plantillas.connect(
            lambda: self.navegar_a(PAGE_REPORTES_PLANTILLAS)
        )
        self._pagina_reportes_home.solicitar_firmas.connect(
            lambda: self.navegar_a(PAGE_REPORTES_FIRMAS)
        )
        self._pagina_reportes_home.solicitar_folios.connect(
            lambda: self.navegar_a(PAGE_REPORTES_FOLIOS)
        )
        self._pagina_reportes_home.solicitar_almacenamiento.connect(
            lambda: self.navegar_a(PAGE_REPORTES_ALMACENAMIENTO)
        )
        self._pagina_reportes_home.solicitar_formato.connect(
            lambda: self.navegar_a(PAGE_REPORTES_FORMATO)
        )
        self.stack.addWidget(self._pagina_reportes_home)   # 6

        self._pagina_reportes_plantillas = ReportesPlantillasPage()
        self.stack.addWidget(self._pagina_reportes_plantillas)      # 7

        self._pagina_reportes_firmas = ReportesFirmasPage()
        self.stack.addWidget(self._pagina_reportes_firmas)          # 8

        self._pagina_reportes_folios = ReportesFoliosPage()
        self.stack.addWidget(self._pagina_reportes_folios)          # 9

        self._pagina_reportes_almacenamiento = ReportesAlmacenamientoPage()
        self.stack.addWidget(self._pagina_reportes_almacenamiento)  # 10

        self._pagina_reportes_formato = ReportesFormatoPage()
        self.stack.addWidget(self._pagina_reportes_formato)         # 11

        outer.addWidget(self.stack, 1)

        self._actualizar_a_pagina(PAGE_HOME)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(32, 26, 32, 12)
        header_lay.setSpacing(4)

        titulo_row = QHBoxLayout()
        titulo_row.setSpacing(10)
        titulo_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Back button (oculto en home) — estilo aplicado a sí mismo
        self._btn_back = QPushButton()
        self._btn_back.setIcon(qta.icon("fa5s.arrow-left", color="#ddd"))
        self._btn_back.setIconSize(QSize(14, 14))
        self._btn_back.setFixedSize(30, 30)
        self._btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_back.setStyleSheet("""
            QPushButton {
                background: #2b2b2b;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0;
            }
            QPushButton:hover {
                background: #353535;
                border: 1px solid #0078d7;
            }
        """)
        self._btn_back.clicked.connect(self.navegar_atras)
        titulo_row.addWidget(self._btn_back, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Icono cog (solo en home)
        self._lbl_icono = QLabel()
        self._lbl_icono.setPixmap(qta.icon("fa5s.cog", color="#ddd").pixmap(22, 22))
        self._lbl_icono.setFixedSize(22, 22)
        titulo_row.addWidget(self._lbl_icono, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._lbl_titulo = QLabel("Configuración")
        self._lbl_titulo.setStyleSheet(
            "color: white; font-size: 22px; font-weight: 500; background: transparent;"
        )
        titulo_row.addWidget(self._lbl_titulo, alignment=Qt.AlignmentFlag.AlignVCenter)
        titulo_row.addStretch()

        header_lay.addLayout(titulo_row)

        self._lbl_subtitulo = QLabel("Sistema de Mantenimiento Eléctrico · v1.0")
        self._lbl_subtitulo.setStyleSheet(
            "color: #888; font-size: 12px; background: transparent;"
        )
        self._lbl_subtitulo.setContentsMargins(32, 0, 0, 0)
        header_lay.addWidget(self._lbl_subtitulo)

        return header

    def _build_pagina_home(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(SCROLLBAR_QSS)

        contenido = QWidget()
        lista_lay = QVBoxLayout(contenido)
        lista_lay.setContentsMargins(32, 8, 32, 24)
        lista_lay.setSpacing(6)

        seccion_actual = None
        for (seccion, titulo, desc, icon, color, chip_bg, key) in OPCIONES:
            if seccion != seccion_actual:
                if seccion_actual is not None:
                    lista_lay.addSpacing(10)
                cab = QLabel(seccion)
                cab.setStyleSheet(
                    "color: #666; font-size: 10px; font-weight: 500; "
                    "letter-spacing: 1px; background: transparent;"
                )
                cab.setContentsMargins(2, 0, 0, 4)
                lista_lay.addWidget(cab)
                seccion_actual = seccion
            fila = SettingsRow(titulo, desc, icon, color, chip_bg, key)
            fila.clicked.connect(self._on_home_opcion_clicked)
            lista_lay.addWidget(fila)

        lista_lay.addStretch()
        scroll.setWidget(contenido)
        return scroll

    # ── Navegación ───────────────────────────────────────────────────────
    def navegar_a(self, page_index: int):
        self._nav_stack.append(page_index)
        self._actualizar_a_pagina(page_index)

    def navegar_atras(self):
        if len(self._nav_stack) <= 1:
            return
        self._nav_stack.pop()
        self._actualizar_a_pagina(self._nav_stack[-1])

    def _actualizar_a_pagina(self, page_index: int):
        self.stack.setCurrentIndex(page_index)
        self._actualizar_header(page_index)

    def _actualizar_header(self, page_index: int):
        en_home = (page_index == PAGE_HOME)
        self._btn_back.setVisible(not en_home)
        self._lbl_icono.setVisible(en_home)

        if page_index == PAGE_HOME:
            self._lbl_titulo.setText("Configuración")
            self._lbl_subtitulo.setText("Sistema de Mantenimiento Eléctrico · v1.0")
        elif page_index == PAGE_RESPONSABLES:
            self._lbl_titulo.setText("Responsables")
            self._lbl_subtitulo.setText("Administrar personal y proveedores")
        elif page_index == PAGE_PERSONAL:
            self._lbl_titulo.setText("Personal")
            self._lbl_subtitulo.setText(self._pagina_personal.texto_contador())
        elif page_index == PAGE_PROVEEDORES:
            self._lbl_titulo.setText("Proveedor")
            self._lbl_subtitulo.setText(self._pagina_proveedores.texto_contador())
        elif page_index == PAGE_BASEDATOS:
            self._lbl_titulo.setText("Base de datos")
            self._lbl_subtitulo.setText("Respaldos y mantenimiento del archivo")
        elif page_index == PAGE_ACERCADE:
            self._lbl_titulo.setText("Acerca de")
            self._lbl_subtitulo.setText("Información del sistema y versión")
        elif page_index == PAGE_REPORTES_HOME:
            self._lbl_titulo.setText("Reportes")
            self._lbl_subtitulo.setText("Plantillas, firmas, folios y formatos")
        elif page_index == PAGE_REPORTES_PLANTILLAS:
            self._lbl_titulo.setText("Plantillas")
            self._lbl_subtitulo.setText("Empresa, logo y diseño de los reportes")
        elif page_index == PAGE_REPORTES_FIRMAS:
            self._lbl_titulo.setText("Firmas y responsables")
            self._lbl_subtitulo.setText("Catálogo de firmantes por rol")
        elif page_index == PAGE_REPORTES_FOLIOS:
            self._lbl_titulo.setText("Folios")
            self._lbl_subtitulo.setText("Numeración automática por categoría")
        elif page_index == PAGE_REPORTES_ALMACENAMIENTO:
            self._lbl_titulo.setText("Almacenamiento")
            self._lbl_subtitulo.setText("Carpeta local y respaldo en la nube")
        elif page_index == PAGE_REPORTES_FORMATO:
            self._lbl_titulo.setText("Formato de exportación")
            self._lbl_subtitulo.setText("PDF, Excel y Word")

    def _actualizar_subtitulo_actual(self):
        self._actualizar_header(self._nav_stack[-1])

    # ── Handlers ─────────────────────────────────────────────────────────
    def _on_home_opcion_clicked(self, key: str):
        if key == "responsables":
            self.navegar_a(PAGE_RESPONSABLES)
            return
        if key == "basedatos":
            self.navegar_a(PAGE_BASEDATOS)
            return
        if key == "acercade":
            self.navegar_a(PAGE_ACERCADE)
            return
        if key == "reportes":
            self.navegar_a(PAGE_REPORTES_HOME)
            return
        nombres = {
            "calendario":  "Calendario",
            "alertas":     "Alertas",
            "usuarios":    "Usuarios",
        }
        QMessageBox.information(
            self,
            "Próximamente",
            f"La sección '{nombres.get(key, key)}' se implementará en la siguiente fase."
        )
