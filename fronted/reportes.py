"""
reportes.py — Pestaña Reportes de CAMF
═══════════════════════════════════════

UI principal del módulo de reportes:
  - Título superior con contador de reportes emitidos
  - Tira horizontal de 6 categorías (botones tipo pill)
  - Grid de tarjetas para los reportes de la categoría activa
  - Panel lateral derecho con los últimos reportes emitidos

Cada tarjeta muestra ícono, nombre, descripción breve y un badge de estado:
  • DISPONIBLE     — implementado, click abre diálogo de parámetros
  • PRÓXIMAMENTE   — placeholder, click muestra mensaje informativo
  • REQ. PROYECTO  — necesita el módulo Proyecto (Entrega futura)

Flujo de generación:
  Click tarjeta DISPONIBLE
    → diálogo de parámetros (selector de equipo, fechas, etc.)
    → botón Generar → llama `emitir_reporte(...)` del motor
    → mensaje de éxito con opción "Abrir PDF"
    → refresca panel de Recientes

Integración con el resto de la app:
  Desde main_app.py basta con:
      from reportes import ReportesTab
      self.tabs.addTab(ReportesTab(self), "Reportes")
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, date
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import (
    Qt, pyqtSignal, QSize, QPoint, QRect, QDate, QTimer
)
from PyQt6.QtGui import QCursor, QColor, QDesktopServices, QPixmap
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QSizePolicy, QComboBox, QDateEdit, QCheckBox,
    QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QLayout,
    QApplication,
)
import qtawesome as qta

import db_manager as db


# ══════════════════════════════════════════════════════════════════════════
#  CATÁLOGO DE REPORTES
# ══════════════════════════════════════════════════════════════════════════

# Estados de cada reporte
ESTADO_DISPONIBLE   = "disponible"
ESTADO_PROXIMO      = "proximo"
ESTADO_REQ_PROYECTO = "req_proyecto"

# Definición de las 6 categorías
CATEGORIAS = [
    {
        "key":   "operativos",
        "nombre": "Operativos",
        "icono": "fa5s.tools",
        "color": "#0078d7",
        "desc":  "Reportes de operación diaria y mantenimientos",
    },
    {
        "key":   "tecnicos",
        "nombre": "Técnicos",
        "icono": "fa5s.bolt",
        "color": "#e67e22",
        "desc":  "Pruebas, mediciones y documentación técnica",
    },
    {
        "key":   "ingenieria",
        "nombre": "Ingeniería",
        "icono": "fa5s.drafting-compass",
        "color": "#1d9e75",
        "desc":  "Cálculos eléctricos y diseños conforme a NOM-001",
    },
    {
        "key":   "uvie",
        "nombre": "UVIE",
        "icono": "fa5s.shield-alt",
        "color": "#c0392b",
        "desc":  "Verificación de instalaciones eléctricas (NOM-029)",
    },
    {
        "key":   "gestion",
        "nombre": "Gestión",
        "icono": "fa5s.chart-line",
        "color": "#9b59b6",
        "desc":  "Indicadores, costos y KPIs operativos",
    },
    {
        "key":   "inventario",
        "nombre": "Inventario",
        "icono": "fa5s.boxes",
        "color": "#34495e",
        "desc":  "Catálogos, etiquetas y fichas técnicas",
    },
]


# Cada reporte: (tipo, nombre, descripción, icono, estado)
# El "tipo" debe coincidir con la entrada del dispatcher en reportes_render.py
# para reportes implementados.
CATALOGO_REPORTES: Dict[str, List[Dict[str, Any]]] = {
    # ─── 1. OPERATIVOS ──────────────────────────────────────────────────
    "operativos": [
        {"tipo": "historial_equipo",
         "nombre": "Historial de mantenimiento",
         "desc":  "Todos los mantenimientos de un equipo en un periodo",
         "icono": "fa5s.history",
         "estado": ESTADO_DISPONIBLE},
        {"tipo": "programa_anual",
         "nombre": "Programa anual",
         "desc":  "Calendario anual de mantenimientos programados",
         "icono": "fa5s.calendar-alt",
         "estado": ESTADO_PROXIMO},
        {"tipo": "proximos_vencer",
         "nombre": "Próximos a vencer",
         "desc":  "Mantenimientos por vencer en los próximos N días",
         "icono": "fa5s.hourglass-half",
         "estado": ESTADO_PROXIMO},
        {"tipo": "equipos_fuera_servicio",
         "nombre": "Equipos fuera de servicio",
         "desc":  "Equipos con falla activa o mantenimiento abierto",
         "icono": "fa5s.power-off",
         "estado": ESTADO_PROXIMO},
        {"tipo": "orden_trabajo",
         "nombre": "Orden de trabajo",
         "desc":  "OT por mantenimiento específico",
         "icono": "fa5s.clipboard-list",
         "estado": ESTADO_PROXIMO},
        {"tipo": "bitacora",
         "nombre": "Bitácora",
         "desc":  "Registro cronológico de eventos en un periodo",
         "icono": "fa5s.book",
         "estado": ESTADO_PROXIMO},
    ],

    # ─── 2. TÉCNICOS ────────────────────────────────────────────────────
    "tecnicos": [
        {"tipo": "megger",
         "nombre": "Megger",
         "desc":  "Pruebas de resistencia de aislamiento",
         "icono": "fa5s.wave-square",
         "estado": ESTADO_PROXIMO},
        {"tipo": "ttr",
         "nombre": "TTR",
         "desc":  "Relación de transformación de transformadores",
         "icono": "fa5s.cog",
         "estado": ESTADO_PROXIMO},
        {"tipo": "termografia",
         "nombre": "Termografía",
         "desc":  "Inspección termográfica con imágenes infrarrojas",
         "icono": "fa5s.thermometer-half",
         "estado": ESTADO_PROXIMO},
        {"tipo": "tierras",
         "nombre": "Sistema de tierras",
         "desc":  "Medición de resistencia de puesta a tierra",
         "icono": "fa5s.broadcast-tower",
         "estado": ESTADO_PROXIMO},
        {"tipo": "calidad_energia",
         "nombre": "Calidad de energía",
         "desc":  "Análisis de armónicos, flicker y desbalance",
         "icono": "fa5s.signal",
         "estado": ESTADO_PROXIMO},
        {"tipo": "inspeccion_checklist",
         "nombre": "Inspección checklist",
         "desc":  "Lista de verificación visual con fotografías",
         "icono": "fa5s.tasks",
         "estado": ESTADO_PROXIMO},
        {"tipo": "memoria_tecnica",
         "nombre": "Memoria técnica",
         "desc":  "Descripción técnica completa de la instalación",
         "icono": "fa5s.file-alt",
         "estado": ESTADO_PROXIMO},
    ],

    # ─── 3. INGENIERÍA ──────────────────────────────────────────────────
    "ingenieria": [
        {"tipo": "cuadro_cargas",
         "nombre": "Cuadro de cargas",
         "desc":  "Cuadro de cargas por tablero según NOM-001",
         "icono": "fa5s.table",
         "estado": ESTADO_PROXIMO},
        {"tipo": "diagrama_unifilar",
         "nombre": "Diagrama unifilar",
         "desc":  "Representación esquemática unifilar de la instalación",
         "icono": "fa5s.project-diagram",
         "estado": ESTADO_PROXIMO},
        {"tipo": "memoria_calculo",
         "nombre": "Memoria de cálculo",
         "desc":  "Cálculos eléctricos con criterios y resultados",
         "icono": "fa5s.calculator",
         "estado": ESTADO_PROXIMO},
        {"tipo": "balanceo_fases",
         "nombre": "Balanceo de fases",
         "desc":  "Análisis de desbalance entre fases",
         "icono": "fa5s.balance-scale",
         "estado": ESTADO_PROXIMO},
        {"tipo": "caida_tension",
         "nombre": "Caída de tensión",
         "desc":  "Cálculo de caídas de tensión por circuito",
         "icono": "fa5s.long-arrow-alt-down",
         "estado": ESTADO_PROXIMO},
        {"tipo": "carga_instalada",
         "nombre": "Carga instalada",
         "desc":  "Demanda, diversidad y carga conectada total",
         "icono": "fa5s.plug",
         "estado": ESTADO_PROXIMO},
        {"tipo": "malla_tierras",
         "nombre": "Malla de tierras",
         "desc":  "Diseño y cálculo de malla de puesta a tierra",
         "icono": "fa5s.network-wired",
         "estado": ESTADO_REQ_PROYECTO},
        {"tipo": "pararrayos",
         "nombre": "Sistema de pararrayos",
         "desc":  "Cálculo de protección contra descargas atmosféricas",
         "icono": "fa5s.cloud-rain",
         "estado": ESTADO_REQ_PROYECTO},
        {"tipo": "cortocircuito",
         "nombre": "Estudio de cortocircuito",
         "desc":  "Cálculo de niveles de falla en puntos críticos",
         "icono": "fa5s.fire-alt",
         "estado": ESTADO_PROXIMO},
        {"tipo": "coordinacion_protecciones",
         "nombre": "Coordinación de protecciones",
         "desc":  "Curvas tiempo–corriente coordinadas",
         "icono": "fa5s.shield-alt",
         "estado": ESTADO_PROXIMO},
    ],

    # ─── 4. UVIE ────────────────────────────────────────────────────────
    "uvie": [
        {"tipo": "acta_evaluacion",
         "nombre": "Acta de evaluación",
         "desc":  "Acta firmada del proceso de verificación",
         "icono": "fa5s.file-signature",
         "estado": ESTADO_PROXIMO},
        {"tipo": "lista_verificacion_nom",
         "nombre": "Lista de verificación NOM-001",
         "desc":  "Checklist completo conforme a NOM-001-SEDE-2012",
         "icono": "fa5s.list-ol",
         "estado": ESTADO_PROXIMO},
        {"tipo": "expediente_tecnico",
         "nombre": "Expediente técnico",
         "desc":  "Compilación de documentos técnicos requeridos",
         "icono": "fa5s.folder-open",
         "estado": ESTADO_PROXIMO},
        {"tipo": "carpeta_uvie_completa",
         "nombre": "Carpeta UVIE completa",
         "desc":  "Paquete completo para entrega a verificador",
         "icono": "fa5s.folder",
         "estado": ESTADO_PROXIMO},
        {"tipo": "informe_trimestral_sener",
         "nombre": "Informe trimestral SENER",
         "desc":  "Reporte trimestral de actividades a SENER",
         "icono": "fa5s.chart-bar",
         "estado": ESTADO_PROXIMO},
    ],

    # ─── 5. GESTIÓN ─────────────────────────────────────────────────────
    "gestion": [
        {"tipo": "costos",
         "nombre": "Costos",
         "desc":  "Análisis de costos por equipo, periodo o categoría",
         "icono": "fa5s.dollar-sign",
         "estado": ESTADO_PROXIMO},
        {"tipo": "horas_hombre",
         "nombre": "Horas hombre",
         "desc":  "Acumulado de horas trabajadas por personal",
         "icono": "fa5s.user-clock",
         "estado": ESTADO_PROXIMO},
        {"tipo": "kpis",
         "nombre": "KPIs (MTBF / MTTR)",
         "desc":  "Indicadores de confiabilidad y tiempo medio de reparación",
         "icono": "fa5s.tachometer-alt",
         "estado": ESTADO_PROXIMO},
        {"tipo": "dashboard",
         "nombre": "Dashboard ejecutivo",
         "desc":  "Resumen visual de indicadores clave",
         "icono": "fa5s.chart-pie",
         "estado": ESTADO_PROXIMO},
    ],

    # ─── 6. INVENTARIO ──────────────────────────────────────────────────
    "inventario": [
        {"tipo": "catalogo",
         "nombre": "Catálogo de equipos",
         "desc":  "Listado completo de tableros y transformadores",
         "icono": "fa5s.list",
         "estado": ESTADO_PROXIMO},
        {"tipo": "listado_filtrado",
         "nombre": "Listado filtrado",
         "desc":  "Inventario por marca, ubicación, tipo, etc.",
         "icono": "fa5s.filter",
         "estado": ESTADO_PROXIMO},
        {"tipo": "etiquetas_qr",
         "nombre": "Etiquetas QR",
         "desc":  "Hoja de etiquetas QR para imprimir",
         "icono": "fa5s.qrcode",
         "estado": ESTADO_PROXIMO},
        {"tipo": "ficha_tecnica",
         "nombre": "Ficha técnica",
         "desc":  "Ficha individual de un equipo",
         "icono": "fa5s.id-card",
         "estado": ESTADO_PROXIMO},
    ],
}


def _total_reportes() -> int:
    return sum(len(r) for r in CATALOGO_REPORTES.values())


def _reportes_disponibles() -> int:
    n = 0
    for cat in CATALOGO_REPORTES.values():
        for r in cat:
            if r["estado"] == ESTADO_DISPONIBLE:
                n += 1
    return n


# ══════════════════════════════════════════════════════════════════════════
#  PALETA / QSS
# ══════════════════════════════════════════════════════════════════════════

BG_PRINCIPAL  = "#1a1a1a"
BG_PANEL      = "#222222"
BG_TARJETA    = "#262626"
BG_TARJETA_H  = "#2e2e2e"
BORDE         = "#333333"
TEXTO         = "#ffffff"
TEXTO_TENUE   = "#9a9a9a"
AZUL          = "#0078d7"

SCROLLBAR_QSS = """
    QScrollBar:vertical {
        background: transparent;
        width: 8px;
        margin: 0;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 8px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #404040;
        border-radius: 4px;
        min-height: 20px;
    }
    QScrollBar::handle:horizontal {
        background: #404040;
        border-radius: 4px;
        min-width: 20px;
    }
    QScrollBar::handle:vertical:hover,
    QScrollBar::handle:horizontal:hover {
        background: #555555;
    }
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {
        height: 0;
        width: 0;
        background: transparent;
    }
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {
        background: transparent;
    }
"""

DATE_QSS = """
    QDateEdit {
        background: #1e1e1e;
        border: 1px solid #3a3a3a;
        border-radius: 6px;
        padding: 6px 10px;
        color: white;
        font-size: 13px;
        min-height: 22px;
    }
    QDateEdit:focus {
        border: 1px solid #0078d7;
    }
    QDateEdit::drop-down {
        border: none;
        width: 22px;
    }
    QDateEdit:disabled {
        background: #1a1a1a;
        color: #555;
    }
"""

COMBO_QSS = """
    QComboBox {
        background: #1e1e1e;
        border: 1px solid #3a3a3a;
        border-radius: 6px;
        padding: 6px 10px;
        color: white;
        font-size: 13px;
        min-height: 22px;
    }
    QComboBox:focus {
        border: 1px solid #0078d7;
    }
    QComboBox::drop-down {
        border: none;
        width: 22px;
    }
    QComboBox QAbstractItemView {
        background: #1e1e1e;
        color: white;
        border: 1px solid #3a3a3a;
        selection-background-color: #0078d7;
        outline: 0;
        padding: 2px;
    }
"""

CHECK_QSS = """
    QCheckBox {
        color: #ddd;
        spacing: 8px;
        font-size: 13px;
        background: transparent;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border-radius: 3px;
        border: 1px solid #555;
        background-color: #1e1e1e;
    }
    QCheckBox::indicator:checked {
        background-color: #0078d7;
        border: 1px solid #0078d7;
    }
    QCheckBox::indicator:hover {
        border: 1px solid #888;
    }
"""

BTN_PRIMARY = """
    QPushButton {
        background: #0078d7;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 8px 18px;
        font-size: 13px;
        font-weight: bold;
        min-height: 22px;
    }
    QPushButton:hover { background: #0a8ae8; }
    QPushButton:pressed { background: #0066b8; }
    QPushButton:disabled { background: #2a3a4a; color: #777; }
"""

BTN_SECONDARY = """
    QPushButton {
        background: #2a2a2a;
        color: white;
        border: 1px solid #3a3a3a;
        border-radius: 6px;
        padding: 8px 18px;
        font-size: 13px;
        min-height: 22px;
    }
    QPushButton:hover { background: #333333; border: 1px solid #555; }
    QPushButton:pressed { background: #1e1e1e; }
"""


# ══════════════════════════════════════════════════════════════════════════
#  FLOW LAYOUT — para que las tarjetas se reorganicen al cambiar el ancho
# ══════════════════════════════════════════════════════════════════════════

class FlowLayout(QLayout):
    """
    Layout que acomoda widgets de izquierda a derecha y baja a la siguiente
    línea cuando se agota el espacio horizontal. Patrón estándar de Qt.
    """
    def __init__(self, parent=None, margin=0, h_spacing=14, v_spacing=14):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        for item in self._items:
            sz = item.sizeHint()
            next_x = x + sz.width() + self._h_spacing
            if next_x - self._h_spacing > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + self._v_spacing
                next_x = x + sz.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sz))
            x = next_x
            line_height = max(line_height, sz.height())
        return y + line_height - rect.y()


# ══════════════════════════════════════════════════════════════════════════
#  PILL DE CATEGORÍA — botón con icono + nombre + contador
# ══════════════════════════════════════════════════════════════════════════

class _CategoryPill(QFrame):
    clicked = pyqtSignal(str)  # emite la key de la categoría

    def __init__(self, cat: dict, n_reportes: int, parent=None):
        super().__init__(parent)
        self.cat_key = cat["key"]
        self.color   = cat["color"]
        self._activo = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        # Fixed en horizontal: la pill nunca encoge ni crece más allá de su
        # sizeHint, así nunca se corta el texto. Si todas juntas no caben en
        # la viewport, el QScrollArea horizontal entra en juego.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 16, 0)
        lay.setSpacing(9)

        self._icon = QLabel()
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFixedSize(16, 16)
        self._icono_name = cat["icono"]
        lay.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._lbl = QLabel(cat["nombre"])
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Badge de cantidad
        self._badge = QLabel(str(n_reportes))
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedHeight(18)
        self._badge.setMinimumWidth(22)
        lay.addWidget(self._badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._aplicar_estilo()

    def set_activo(self, activo: bool):
        if self._activo != activo:
            self._activo = activo
            self._aplicar_estilo()

    def _aplicar_estilo(self):
        if self._activo:
            bg          = self.color
            color_texto = "white"
            badge_bg    = "rgba(0,0,0,0.30)"
            badge_color = "white"
            borde       = self.color
            icon_color  = "white"
        else:
            bg          = BG_TARJETA
            color_texto = "#ddd"
            badge_bg    = "#1a1a1a"
            badge_color = TEXTO_TENUE
            borde       = BORDE
            icon_color  = self.color

        self.setStyleSheet(f"""
            _CategoryPill {{
                background: {bg};
                border: 1px solid {borde};
                border-radius: 20px;
            }}
            _CategoryPill:hover {{
                border: 1px solid {self.color};
            }}
        """)
        self._lbl.setStyleSheet(
            f"color: {color_texto}; font-size: 13px; font-weight: bold; background: transparent;"
        )
        self._badge.setStyleSheet(f"""
            background: {badge_bg};
            color: {badge_color};
            border-radius: 9px;
            font-size: 11px;
            font-weight: bold;
            padding: 0 6px;
        """)
        self._icon.setPixmap(qta.icon(self._icono_name, color=icon_color).pixmap(16, 16))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.cat_key)
        super().mousePressEvent(event)


# ══════════════════════════════════════════════════════════════════════════
#  TARJETA DE REPORTE
# ══════════════════════════════════════════════════════════════════════════

class _ReportCard(QFrame):
    clicked = pyqtSignal(dict)  # emite la definición completa del reporte

    ANCHO  = 240
    ALTURA = 158

    def __init__(self, reporte: dict, color_categoria: str, parent=None):
        super().__init__(parent)
        self.reporte = reporte
        self.color_categoria = color_categoria
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.ANCHO, self.ALTURA)

        # Layout vertical
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        # Fila superior: icono + badge alineado a la derecha
        top = QHBoxLayout()
        top.setSpacing(8)

        self._icon = QLabel()
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFixedSize(22, 22)
        self._icon.setPixmap(qta.icon(reporte["icono"], color=color_categoria).pixmap(22, 22))
        top.addWidget(self._icon)

        top.addStretch()

        self._badge = QLabel()
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedHeight(18)
        self._aplicar_badge()
        top.addWidget(self._badge)

        lay.addLayout(top)

        # Nombre
        self._nombre = QLabel(reporte["nombre"])
        self._nombre.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._nombre.setStyleSheet(
            f"color: {TEXTO}; font-size: 13px; font-weight: bold; background: transparent;"
        )
        self._nombre.setWordWrap(True)
        lay.addWidget(self._nombre)

        # Descripción
        self._desc = QLabel(reporte["desc"])
        self._desc.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._desc.setStyleSheet(
            f"color: {TEXTO_TENUE}; font-size: 11px; background: transparent;"
        )
        self._desc.setWordWrap(True)
        lay.addWidget(self._desc)

        lay.addStretch()

        self._aplicar_estilo()

    def _aplicar_badge(self):
        est = self.reporte["estado"]
        if est == ESTADO_DISPONIBLE:
            self._badge.setText("DISPONIBLE")
            self._badge.setStyleSheet(
                "background: #1d9e75; color: white; "
                "border-radius: 9px; font-size: 9px; font-weight: bold; "
                "padding: 0 8px;"
            )
        elif est == ESTADO_REQ_PROYECTO:
            self._badge.setText("REQ. PROYECTO")
            self._badge.setStyleSheet(
                "background: #b87a2a; color: white; "
                "border-radius: 9px; font-size: 9px; font-weight: bold; "
                "padding: 0 8px;"
            )
        else:  # PRÓXIMO
            self._badge.setText("PRÓXIMAMENTE")
            self._badge.setStyleSheet(
                "background: #3a3a3a; color: #aaa; "
                "border-radius: 9px; font-size: 9px; font-weight: bold; "
                "padding: 0 8px;"
            )

    def _aplicar_estilo(self):
        bg = BG_TARJETA_H if self._hover else BG_TARJETA
        borde = self.color_categoria if self._hover else BORDE
        self.setStyleSheet(f"""
            _ReportCard {{
                background: {bg};
                border: 1px solid {borde};
                border-radius: 10px;
            }}
        """)

    def enterEvent(self, event):
        self._hover = True
        self._aplicar_estilo()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._aplicar_estilo()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.reporte)
        super().mousePressEvent(event)


# ══════════════════════════════════════════════════════════════════════════
#  PANEL DE RECIENTES — última columna a la derecha
# ══════════════════════════════════════════════════════════════════════════

# Para mostrar nombres legibles en lugar de claves tipo "historial_equipo"
def _nombre_de_tipo(tipo_reporte: str) -> str:
    for cat in CATALOGO_REPORTES.values():
        for r in cat:
            if r["tipo"] == tipo_reporte:
                return r["nombre"]
    return tipo_reporte


class _RecienteItem(QFrame):
    """Una fila clickable del panel de Recientes."""
    abrir_pdf = pyqtSignal(str)  # ruta del archivo

    def __init__(self, folio: str, tipo: str, fecha_iso: str,
                 parametros_str: str, ruta: str, parent=None):
        super().__init__(parent)
        self.ruta = ruta
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(64)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(1)

        # Folio (clave) + fecha formateada compacta
        try:
            dt = datetime.fromisoformat(fecha_iso)
            fecha_fmt = dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            fecha_fmt = fecha_iso or ""

        lbl_folio = QLabel(folio or "—")
        lbl_folio.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl_folio.setStyleSheet(
            f"color: {TEXTO}; font-size: 11px; font-weight: bold; background: transparent;"
        )
        lay.addWidget(lbl_folio)

        # Tipo de reporte + parámetros breves
        sub = _nombre_de_tipo(tipo)
        if parametros_str:
            sub = f"{sub} · {parametros_str}"
        lbl_sub = QLabel(sub)
        lbl_sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl_sub.setStyleSheet(
            f"color: {TEXTO_TENUE}; font-size: 10px; background: transparent;"
        )
        lbl_sub.setWordWrap(False)
        lay.addWidget(lbl_sub)

        lbl_fecha = QLabel(fecha_fmt)
        lbl_fecha.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl_fecha.setStyleSheet(
            "color: #707070; font-size: 10px; background: transparent;"
        )
        lay.addWidget(lbl_fecha)

        self._aplicar_estilo()

    def _aplicar_estilo(self):
        bg = BG_TARJETA_H if self._hover else "transparent"
        borde = AZUL if self._hover else "transparent"
        self.setStyleSheet(f"""
            _RecienteItem {{
                background: {bg};
                border-left: 2px solid {borde};
                border-radius: 0;
            }}
        """)

    def enterEvent(self, event):
        self._hover = True
        self._aplicar_estilo()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._aplicar_estilo()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.ruta:
            self.abrir_pdf.emit(self.ruta)
        super().mousePressEvent(event)


class _PanelRecientes(QFrame):
    """Panel lateral derecho con los últimos N reportes emitidos."""
    LIMITE = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(280)
        self.setStyleSheet(f"_PanelRecientes {{ background: {BG_PANEL}; border-radius: 10px; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header del panel
        hdr = QFrame()
        hdr.setFixedHeight(48)
        hdr.setStyleSheet(f"background: transparent; border-bottom: 1px solid {BORDE};")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(16, 0, 12, 0)

        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.history", color=TEXTO_TENUE).pixmap(14, 14))
        hdr_lay.addWidget(ico, alignment=Qt.AlignmentFlag.AlignVCenter)

        ttl = QLabel("  Recientes")
        ttl.setStyleSheet(f"color: {TEXTO}; font-size: 13px; font-weight: bold; background: transparent;")
        hdr_lay.addWidget(ttl, alignment=Qt.AlignmentFlag.AlignVCenter)

        hdr_lay.addStretch()

        self._btn_refresh = QPushButton()
        self._btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh.setFixedSize(28, 28)
        self._btn_refresh.setIcon(qta.icon("fa5s.sync-alt", color=TEXTO_TENUE))
        self._btn_refresh.setIconSize(QSize(11, 11))
        self._btn_refresh.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 14px; }"
            "QPushButton:hover { background: #333; }"
        )
        self._btn_refresh.clicked.connect(self.recargar)
        hdr_lay.addWidget(self._btn_refresh)

        lay.addWidget(hdr)

        # Scroll de items
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(SCROLLBAR_QSS)

        self._cont = QWidget()
        self._cont_lay = QVBoxLayout(self._cont)
        self._cont_lay.setContentsMargins(0, 6, 0, 6)
        self._cont_lay.setSpacing(2)
        self._cont_lay.addStretch()

        self._scroll.setWidget(self._cont)
        lay.addWidget(self._scroll, 1)

        self.recargar()

    def recargar(self):
        # Vaciar items previos — usar setParent(None) para detacharlo de la
        # jerarquía visual inmediatamente; deleteLater() es diferido y deja
        # al widget colgando hasta el siguiente tick.
        while self._cont_lay.count() > 1:
            it = self._cont_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        filas = self._consultar()
        if not filas:
            vacio = QLabel("\n  No hay reportes emitidos aún.\n")
            vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vacio.setStyleSheet(
                f"color: {TEXTO_TENUE}; font-size: 11px; background: transparent; padding: 20px;"
            )
            vacio.setWordWrap(True)
            self._cont_lay.insertWidget(0, vacio)
            return

        for f in filas:
            params_short = self._formatear_parametros(f.get("parametros_json"))
            item = _RecienteItem(
                folio = f.get("folio") or "",
                tipo  = f.get("tipo_reporte") or "",
                fecha_iso = f.get("fecha") or "",
                parametros_str = params_short,
                ruta = f.get("archivo_ruta") or "",
            )
            item.abrir_pdf.connect(self._abrir_pdf)
            self._cont_lay.insertWidget(self._cont_lay.count() - 1, item)

    def _consultar(self) -> List[Dict[str, Any]]:
        conn = db.connect_db()
        if conn is None:
            return []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT folio, tipo_reporte, fecha, parametros_json, archivo_ruta
                FROM reportes
                ORDER BY fecha DESC
                LIMIT ?
            """, (self.LIMITE,))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception:
            return []
        finally:
            conn.close()

    @staticmethod
    def _formatear_parametros(params_json: Optional[str]) -> str:
        if not params_json:
            return ""
        try:
            p = json.loads(params_json)
        except Exception:
            return ""
        # Compactar lo que más signifique según los parámetros del reporte
        if isinstance(p, dict):
            if "equipo_id" in p and p["equipo_id"]:
                return str(p["equipo_id"])
        return ""

    @staticmethod
    def _abrir_pdf(ruta: str):
        if not ruta:
            return
        if os.path.exists(ruta):
            QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))
        else:
            QMessageBox.warning(
                None, "Archivo no encontrado",
                f"El archivo del reporte no se encuentra en su ubicación original:\n{ruta}"
            )


# ══════════════════════════════════════════════════════════════════════════
#  DIÁLOGO: Éxito (reemplaza QMessageBox nativo)
# ══════════════════════════════════════════════════════════════════════════

class _DialogoExito(QDialog):
    """
    Diálogo de éxito tras generar un reporte. Reemplaza QMessageBox.question
    porque el nativo de Windows aplica un sombreado oscuro detrás del texto
    que no respeta el QSS del tema.
    """
    def __init__(self, archivo_ruta: str, folio: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reporte generado")
        self.setMinimumWidth(480)
        self.setStyleSheet(f"QDialog {{ background: {BG_PANEL}; }}")
        self._abrir = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(14)

        # Header: ícono check + título
        top = QHBoxLayout()
        top.setSpacing(14)

        ico = QLabel()
        ico.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        ico.setPixmap(qta.icon("fa5s.check-circle", color="#1d9e75").pixmap(34, 34))
        top.addWidget(ico, alignment=Qt.AlignmentFlag.AlignVCenter)

        ttl = QLabel("Reporte generado")
        ttl.setStyleSheet(
            f"color: {TEXTO}; font-size: 16px; font-weight: bold; "
            f"background: transparent;"
        )
        top.addWidget(ttl, alignment=Qt.AlignmentFlag.AlignVCenter)
        top.addStretch()
        lay.addLayout(top)

        # Folio destacado (si se proporcionó)
        if folio:
            lbl_folio = QLabel(f"Folio: <b>{folio}</b>")
            lbl_folio.setStyleSheet(
                f"color: {TEXTO}; font-size: 13px; background: transparent;"
            )
            lay.addWidget(lbl_folio)

        # Ruta del archivo
        lbl_ruta_t = QLabel("Archivo:")
        lbl_ruta_t.setStyleSheet(
            f"color: {TEXTO_TENUE}; font-size: 11px; background: transparent;"
        )
        lay.addWidget(lbl_ruta_t)

        lbl_ruta = QLabel(archivo_ruta)
        lbl_ruta.setStyleSheet(
            f"color: {TEXTO}; font-size: 12px; background: transparent;"
            f"padding: 4px 0;"
        )
        lbl_ruta.setWordWrap(True)
        lbl_ruta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(lbl_ruta)

        lay.addSpacing(4)

        # Pregunta
        lbl_q = QLabel("¿Abrir ahora?")
        lbl_q.setStyleSheet(
            f"color: {TEXTO}; font-size: 13px; background: transparent;"
        )
        lay.addWidget(lbl_q)

        # Botones
        botones = QHBoxLayout()
        botones.addStretch()

        b_no = QPushButton("Más tarde")
        b_no.setStyleSheet(BTN_SECONDARY)
        b_no.setCursor(Qt.CursorShape.PointingHandCursor)
        b_no.clicked.connect(self.reject)
        botones.addWidget(b_no)

        b_si = QPushButton("  Abrir PDF")
        b_si.setIcon(qta.icon("fa5s.external-link-alt", color="white"))
        b_si.setIconSize(QSize(12, 12))
        b_si.setStyleSheet(BTN_PRIMARY)
        b_si.setCursor(Qt.CursorShape.PointingHandCursor)
        b_si.setDefault(True)
        b_si.clicked.connect(self._on_abrir)
        botones.addWidget(b_si)

        lay.addLayout(botones)

    def _on_abrir(self):
        self._abrir = True
        self.accept()

    def abrir_solicitado(self) -> bool:
        return self._abrir


# ══════════════════════════════════════════════════════════════════════════
#  VENTANA: Vista previa del reporte (con pymupdf)
# ══════════════════════════════════════════════════════════════════════════

class VentanaPreviewPDF(QDialog):
    """
    Ventana modal de vista previa de un PDF generado en modo preview.

    Renderea las páginas con pymupdf (fitz) y las muestra en un scroll.
    Sidebar izquierdo con thumbnails clickables para saltar a una página.

    Botones inferiores:
      - Cerrar: descarta el preview, no consume folio.
      - Imprimir: abre el diálogo nativo de impresión.
      - Generar PDF oficial: consume folio, registra en BD, emite la señal
        `pdf_oficial_generado(str)` con la ruta del PDF definitivo.
    """
    pdf_oficial_generado = pyqtSignal(str)

    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self._preview = preview  # PreviewReporte
        self._page_widgets: List[QWidget] = []

        titulo_doc = preview.datos.get('titulo', 'Reporte')
        self.setWindowTitle(f"Vista previa — {titulo_doc}")

        # Tamaño adaptado al área disponible de la pantalla. La altura tope
        # se calcula como 85% del área disponible (que ya excluye taskbar),
        # con un cap de 700 px en pantallas grandes y mínimo de 480.
        # Esto garantiza que en laptops 1366×768 los botones inferiores
        # quedan siempre visibles.
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            target_w = min(1100, max(700, avail.width()  - 80))
            target_h = min(700,  max(480, int(avail.height() * 0.85)))
        else:
            target_w, target_h = 1000, 640
        self.resize(target_w, target_h)
        self.setMinimumSize(700, 460)

        self.setStyleSheet(
            f"QDialog {{ background: {BG_PRINCIPAL}; }}"
            f"QLabel {{ background: transparent; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        root.addWidget(self._construir_header())

        # Body: sidebar de thumbnails + área de páginas
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self._construir_sidebar(), 0)
        body.addWidget(self._construir_main(), 1)
        cuerpo_wrap = QWidget()
        cuerpo_wrap.setLayout(body)
        root.addWidget(cuerpo_wrap, 1)

        # Footer
        root.addWidget(self._construir_footer())

        # Render
        QTimer.singleShot(0, self._renderear_pdf)

    # ──────────────────────────────────────────────────────────────────
    #  Construcción visual
    # ──────────────────────────────────────────────────────────────────

    def _construir_header(self) -> QWidget:
        hdr = QFrame()
        hdr.setFixedHeight(56)
        hdr.setStyleSheet(f"background: {BG_PANEL}; border-bottom: 1px solid {BORDE};")
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(12)

        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.eye", color=AZUL).pixmap(20, 20))
        lay.addWidget(ico, alignment=Qt.AlignmentFlag.AlignVCenter)

        titulo_doc = self._preview.datos.get('titulo', 'Reporte')
        subt = self._preview.datos.get('subtitulo', '')
        texto = titulo_doc + (f"  ·  {subt}" if subt else "")
        ttl = QLabel(texto)
        ttl.setStyleSheet(f"color: {TEXTO}; font-size: 14px; font-weight: bold;")
        lay.addWidget(ttl, alignment=Qt.AlignmentFlag.AlignVCenter)

        lay.addStretch()

        # Badge "PREVIEW" para que sea obvio que no es el documento oficial
        badge = QLabel("VISTA PREVIA")
        badge.setStyleSheet(
            "background: #b87a2a; color: white; "
            "border-radius: 9px; font-size: 10px; font-weight: bold; "
            "padding: 3px 10px;"
        )
        lay.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        return hdr

    def _construir_sidebar(self) -> QWidget:
        side = QFrame()
        side.setFixedWidth(146)
        side.setStyleSheet(f"background: {BG_PANEL}; border-right: 1px solid {BORDE};")

        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        lbl = QLabel("Páginas")
        lbl.setStyleSheet(
            f"color: {TEXTO_TENUE}; font-size: 11px; font-weight: bold; "
            f"padding: 14px 16px 8px 16px; background: transparent;"
        )
        outer.addWidget(lbl)

        self._side_scroll = QScrollArea()
        self._side_scroll.setWidgetResizable(True)
        self._side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._side_scroll.setStyleSheet(SCROLLBAR_QSS)

        self._side_cont = QWidget()
        self._side_lay = QVBoxLayout(self._side_cont)
        self._side_lay.setContentsMargins(12, 4, 12, 12)
        self._side_lay.setSpacing(8)
        self._side_lay.addStretch()

        self._side_scroll.setWidget(self._side_cont)
        outer.addWidget(self._side_scroll, 1)

        return side

    def _construir_main(self) -> QWidget:
        self._main_scroll = QScrollArea()
        self._main_scroll.setWidgetResizable(True)
        self._main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._main_scroll.setStyleSheet(
            f"QScrollArea {{ background: #1a1a1a; }}" + SCROLLBAR_QSS
        )
        self._main_cont = QWidget()
        self._main_cont.setStyleSheet("background: #1a1a1a;")
        self._main_lay = QVBoxLayout(self._main_cont)
        self._main_lay.setContentsMargins(24, 24, 24, 24)
        self._main_lay.setSpacing(16)
        # Placeholder de carga (se quita al renderear)
        self._lbl_cargando = QLabel("Cargando vista previa…")
        self._lbl_cargando.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_cargando.setStyleSheet(
            f"color: {TEXTO_TENUE}; font-size: 12px; padding: 60px;"
        )
        self._main_lay.addWidget(self._lbl_cargando)
        self._main_lay.addStretch()
        self._main_scroll.setWidget(self._main_cont)
        return self._main_scroll

    def _construir_footer(self) -> QWidget:
        ftr = QFrame()
        ftr.setFixedHeight(64)
        ftr.setStyleSheet(f"background: {BG_PANEL}; border-top: 1px solid {BORDE};")
        lay = QHBoxLayout(ftr)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(14)

        info_v = QVBoxLayout()
        info_v.setSpacing(0)
        lbl1 = QLabel("Folio que se asignará")
        lbl1.setStyleSheet(f"color: {TEXTO_TENUE}; font-size: 10px;")
        info_v.addWidget(lbl1)
        lbl2 = QLabel(self._preview.folio_preview)
        lbl2.setStyleSheet(f"color: {TEXTO}; font-size: 14px; font-weight: bold;")
        info_v.addWidget(lbl2)
        lay.addLayout(info_v)

        lay.addStretch()

        b_cerrar = QPushButton("Cerrar")
        b_cerrar.setStyleSheet(BTN_SECONDARY)
        b_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        b_cerrar.clicked.connect(self.reject)
        lay.addWidget(b_cerrar)

        b_imp = QPushButton("  Imprimir")
        b_imp.setIcon(qta.icon("fa5s.print", color="white"))
        b_imp.setIconSize(QSize(13, 13))
        b_imp.setStyleSheet(BTN_SECONDARY)
        b_imp.setCursor(Qt.CursorShape.PointingHandCursor)
        b_imp.clicked.connect(self._imprimir)
        lay.addWidget(b_imp)

        self._b_oficial = QPushButton("  Generar PDF")
        self._b_oficial.setIcon(qta.icon("fa5s.file-pdf", color="white"))
        self._b_oficial.setIconSize(QSize(13, 13))
        self._b_oficial.setStyleSheet(BTN_PRIMARY)
        self._b_oficial.setCursor(Qt.CursorShape.PointingHandCursor)
        self._b_oficial.setDefault(True)
        self._b_oficial.clicked.connect(self._generar_oficial)
        lay.addWidget(self._b_oficial)

        return ftr

    # ──────────────────────────────────────────────────────────────────
    #  Renderizado con pymupdf
    # ──────────────────────────────────────────────────────────────────

    def _renderear_pdf(self):
        """
        Lee el PDF temporal con pymupdf y arma:
          - Una QLabel grande por cada página (área principal)
          - Una mini-tarjeta thumbnail por cada página (sidebar)
        El renderizado se hace una sola vez al abrir la ventana.
        """
        try:
            import fitz  # pymupdf
        except ImportError:
            self._lbl_cargando.setText(
                "pymupdf no está instalado. Ejecuta:\npip install pymupdf"
            )
            return

        from PyQt6.QtGui import QImage
        try:
            doc = fitz.open(self._preview.ruta_temp)
        except Exception as e:
            self._lbl_cargando.setText(f"No se pudo abrir el PDF:\n{e}")
            return

        # Quitar el placeholder de carga
        self._main_lay.removeWidget(self._lbl_cargando)
        self._lbl_cargando.deleteLater()

        # Limpiar el stretch del final del side_lay (se vuelve a poner al final)
        while self._side_lay.count():
            it = self._side_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        # Vamos a quitar el stretch del main también, agregamos páginas, y
        # volvemos a poner el stretch al final
        n_main_items = self._main_lay.count()
        last_item = self._main_lay.itemAt(n_main_items - 1) if n_main_items else None
        if last_item and last_item.spacerItem():
            self._main_lay.removeItem(last_item)

        for i, page in enumerate(doc):
            # ── Página grande (110 DPI ≈ tamaño cómodo en pantalla) ────
            pix = page.get_pixmap(dpi=110, alpha=False)
            img = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format.Format_RGB888,
            ).copy()  # copy() libera del buffer de pymupdf
            pixmap = QPixmap.fromImage(img)

            lbl = QLabel()
            lbl.setPixmap(pixmap)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "background: white; border: 1px solid #2a2a2a;"
            )
            self._main_lay.addWidget(lbl, 0, Qt.AlignmentFlag.AlignHCenter)
            self._page_widgets.append(lbl)

            # ── Thumbnail en sidebar ───────────────────────────────────
            # Renderea a 50 DPI para tener resolución suficiente, luego
            # se escala a 96px de ancho. Eso da una mini-página de
            # aproximadamente 96×136 px (aspecto A4), compacta para el
            # sidebar sin perder legibilidad.
            pix_t = page.get_pixmap(dpi=50, alpha=False)
            img_t = QImage(
                pix_t.samples, pix_t.width, pix_t.height, pix_t.stride,
                QImage.Format.Format_RGB888,
            ).copy()
            pixmap_t = QPixmap.fromImage(img_t).scaledToWidth(
                96, Qt.TransformationMode.SmoothTransformation
            )
            thumb = self._construir_thumb(i + 1, pixmap_t)
            self._side_lay.addWidget(thumb)

        doc.close()

        # Restaurar stretches al final
        self._main_lay.addStretch()
        self._side_lay.addStretch()

    def _construir_thumb(self, num_pagina: int, pixmap: QPixmap) -> QWidget:
        """Mini-tarjeta clickable: thumbnail + número de página."""
        card = QFrame()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(
            f"QFrame {{ background: {BG_TARJETA}; border: 1px solid {BORDE}; "
            f"border-radius: 6px; }}"
            f"QFrame:hover {{ border: 1px solid {AZUL}; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        lbl_img = QLabel()
        lbl_img.setPixmap(pixmap)
        lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_img.setStyleSheet("background: white; border: 1px solid #555;")
        lay.addWidget(lbl_img, alignment=Qt.AlignmentFlag.AlignCenter)

        lbl_num = QLabel(f"Página {num_pagina}")
        lbl_num.setStyleSheet(f"color: {TEXTO_TENUE}; font-size: 9px;")
        lbl_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl_num)

        # Click → scroll a la página correspondiente
        idx_pagina = num_pagina - 1
        def _go(_event):
            self._ir_a_pagina(idx_pagina)
        card.mousePressEvent = _go
        return card

    def _ir_a_pagina(self, idx: int):
        if 0 <= idx < len(self._page_widgets):
            lbl = self._page_widgets[idx]
            self._main_scroll.ensureWidgetVisible(lbl, 50, 50)

    # ──────────────────────────────────────────────────────────────────
    #  Acciones de los botones
    # ──────────────────────────────────────────────────────────────────

    def _imprimir(self):
        """Abre el diálogo nativo de impresión y manda el PDF temporal."""
        try:
            from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
            from PyQt6.QtGui import QPainter, QImage
            import fitz
        except ImportError as e:
            QMessageBox.critical(self, "Falta módulo",
                                 f"No se puede imprimir: {e}")
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "Impresión",
                                "No se pudo iniciar la impresión.")
            return

        try:
            doc = fitz.open(self._preview.ruta_temp)
            zoom = printer.resolution() / 72.0  # PDF default DPI = 72
            matrix = fitz.Matrix(zoom, zoom)

            # Rectángulo de impresión en píxeles del printer
            page_rect = printer.pageLayout().paintRectPixels(printer.resolution())

            for i, page in enumerate(doc):
                if i > 0:
                    printer.newPage()
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img = QImage(
                    pix.samples, pix.width, pix.height, pix.stride,
                    QImage.Format.Format_RGB888,
                ).copy()
                # Fit dentro del page_rect preservando aspecto
                scaled = img.scaled(
                    page_rect.width(), page_rect.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                # Centrar horizontalmente
                x = page_rect.x() + (page_rect.width() - scaled.width()) // 2
                y = page_rect.y() + (page_rect.height() - scaled.height()) // 2
                painter.drawImage(x, y, scaled)
            doc.close()
        except Exception as e:
            QMessageBox.critical(self, "Error al imprimir",
                                 f"{type(e).__name__}: {e}")
        finally:
            painter.end()

    def _generar_oficial(self):
        """Confirma el preview → consume folio, registra, devuelve ruta."""
        self._b_oficial.setEnabled(False)
        self._b_oficial.setText("  Generando…")
        try:
            from reportes_render import confirmar_pdf_oficial
            ruta = confirmar_pdf_oficial(self._preview)
        except Exception as e:
            QMessageBox.critical(
                self, "Error al generar",
                f"No se pudo generar el reporte oficial:\n\n{type(e).__name__}: {e}"
            )
            self._b_oficial.setEnabled(True)
            self._b_oficial.setText("  Generar PDF")
            return

        self.pdf_oficial_generado.emit(ruta)

        # Mostrar diálogo de éxito (con la opción de abrir)
        folio = os.path.splitext(os.path.basename(ruta))[0]
        dlg_ok = _DialogoExito(ruta, folio=folio, parent=self)
        dlg_ok.exec()
        if dlg_ok.abrir_solicitado():
            QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))

        self.accept()

    # ──────────────────────────────────────────────────────────────────
    #  Limpieza
    # ──────────────────────────────────────────────────────────────────

    def done(self, result):
        """
        Limpieza al cerrar por CUALQUIER camino (accept, reject o close).
        Qt no dispara closeEvent en accept()/reject() — solo en close()
        explícito o cuando el OS cierra la ventana. done() sí cubre los
        tres casos.
        """
        try:
            from reportes_render import eliminar_temp
            eliminar_temp(self._preview)
        except Exception:
            pass
        super().done(result)


# ══════════════════════════════════════════════════════════════════════════
#  DIÁLOGO: Próximamente
# ══════════════════════════════════════════════════════════════════════════

class _DialogoProximamente(QDialog):
    def __init__(self, reporte: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(reporte["nombre"])
        self.setMinimumWidth(420)
        self.setStyleSheet(f"QDialog {{ background: {BG_PANEL}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 18)
        lay.setSpacing(14)

        # Icono grande + título
        top = QHBoxLayout()
        ico = QLabel()
        es_proyecto = reporte["estado"] == ESTADO_REQ_PROYECTO
        ico.setPixmap(qta.icon(
            "fa5s.cube" if es_proyecto else "fa5s.tools",
            color="#b87a2a" if es_proyecto else "#666"
        ).pixmap(36, 36))
        top.addWidget(ico)
        top.addSpacing(12)

        tit = QLabel(reporte["nombre"])
        tit.setStyleSheet(f"color: {TEXTO}; font-size: 16px; font-weight: bold; background: transparent;")
        top.addWidget(tit, alignment=Qt.AlignmentFlag.AlignVCenter)
        top.addStretch()
        lay.addLayout(top)

        # Mensaje
        if es_proyecto:
            msg = (
                "Este reporte requiere el módulo <b>Proyecto</b>, que estará disponible en "
                "una versión futura de CAMF.<br><br>"
                "<i>" + reporte["desc"] + "</i>"
            )
        else:
            msg = (
                "Este reporte estará disponible en una próxima entrega del módulo.<br><br>"
                "<i>" + reporte["desc"] + "</i>"
            )
        lbl = QLabel(msg)
        lbl.setStyleSheet(f"color: {TEXTO_TENUE}; font-size: 13px; background: transparent;")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        lay.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()
        cerrar = QPushButton("Cerrar")
        cerrar.setStyleSheet(BTN_SECONDARY)
        cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        cerrar.clicked.connect(self.accept)
        btns.addWidget(cerrar)
        lay.addLayout(btns)


# ══════════════════════════════════════════════════════════════════════════
#  DIÁLOGO: Historial de mantenimiento
# ══════════════════════════════════════════════════════════════════════════


# Estilos del botón "Elegir equipos" (3 estados, igual a programar_nuevo).
def _btn_elegir_qss_activo() -> str:
    return """
        QPushButton {
            background: #1e1e1e;
            border: 1px solid #3a3a3a;
            border-radius: 6px;
            padding: 6px 14px;
            color: white;
            font-size: 13px;
            text-align: left;
        }
        QPushButton:hover { border: 1px solid #0078d7; }
    """

def _btn_elegir_qss_deshab() -> str:
    return """
        QPushButton {
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 6px;
            padding: 6px 14px;
            color: #555;
            font-size: 13px;
            text-align: left;
        }
    """

def _btn_elegir_qss_con_seleccion() -> str:
    return """
        QPushButton {
            background: #143b5e;
            border: 1px solid #0078d7;
            border-radius: 6px;
            padding: 6px 14px;
            color: white;
            font-size: 13px;
            font-weight: bold;
            text-align: left;
        }
        QPushButton:hover { background: #1a4a73; }
    """


class _DialogoHistorialEquipo(QDialog):
    """
    Diálogo de filtros para 'Historial de mantenimiento'.

    Reutiliza el SelectorEquipoDialog existente para permitir selección
    múltiple por grupo (edificio, empresa, etc). Igual flujo que en
    programar_nuevo.py: combo de tipo → botón Elegir equipos → diálogo
    de selector.
    """

    pdf_generado = pyqtSignal(str)  # ruta del archivo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generar reporte — Historial de mantenimiento")
        self.setMinimumWidth(560)
        self.setStyleSheet(f"QDialog {{ background: {BG_PANEL}; }}")

        # Estado de la selección
        self.equipos_seleccionados: List[Dict[str, Any]] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(16)

        # Header
        top = QHBoxLayout()
        top.setSpacing(12)
        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.history", color=AZUL).pixmap(28, 28))
        top.addWidget(ico)
        ttl = QLabel("Historial de mantenimiento")
        ttl.setStyleSheet(f"color: {TEXTO}; font-size: 15px; font-weight: bold; background: transparent;")
        top.addWidget(ttl, alignment=Qt.AlignmentFlag.AlignVCenter)
        top.addStretch()
        lay.addLayout(top)

        descr = QLabel(
            "Genera un reporte cronológico de los mantenimientos realizados a uno o varios "
            "equipos. Puedes elegir equipos individuales o un grupo completo (edificio, "
            "ubicación, etc). Si seleccionas varios, el PDF contendrá una sección por equipo."
        )
        descr.setStyleSheet(f"color: {TEXTO_TENUE}; font-size: 12px; background: transparent;")
        descr.setWordWrap(True)
        lay.addWidget(descr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {BORDE}; max-height: 1px; border: none;")
        lay.addWidget(sep)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(12)
        form.setContentsMargins(0, 0, 0, 0)

        # --- Tipo de equipo (combo) + Botón Elegir equipos ---
        # Mismo patrón que programar_nuevo.py: el selector de equipos
        # solo soporta una tabla a la vez, así que primero se elige
        # tableros o transformadores, después se abre el árbol de grupos.
        fila_eq = QHBoxLayout()
        fila_eq.setSpacing(8)

        self._combo_tipo = QComboBox()
        self._combo_tipo.setFixedHeight(34)
        self._combo_tipo.setStyleSheet(COMBO_QSS)
        self._combo_tipo.addItem("Seleccionar tipo…", userData=None)
        self._combo_tipo.addItem("Tableros",        userData="tableros")
        self._combo_tipo.addItem("Transformadores", userData="transformadores")
        self._combo_tipo.currentIndexChanged.connect(self._on_tipo_cambiado)
        fila_eq.addWidget(self._combo_tipo, 1)

        self._btn_equipos = QPushButton("Elegir equipos")
        self._btn_equipos.setFixedHeight(34)
        self._btn_equipos.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_equipos.setEnabled(False)
        self._btn_equipos.setStyleSheet(_btn_elegir_qss_deshab())
        self._btn_equipos.clicked.connect(self._abrir_selector)
        fila_eq.addWidget(self._btn_equipos, 1)

        lbl_eq = QLabel("Equipos:")
        lbl_eq.setStyleSheet(f"color: {TEXTO}; font-size: 13px; background: transparent;")
        form.addRow(lbl_eq, fila_eq)

        # --- Fechas opcionales ---
        fila_fi = QHBoxLayout()
        self._chk_fi = QCheckBox()
        self._chk_fi.setStyleSheet(CHECK_QSS)
        self._chk_fi.stateChanged.connect(self._toggle_fechas)
        self._dt_fi = QDateEdit()
        self._dt_fi.setStyleSheet(DATE_QSS)
        self._dt_fi.setCalendarPopup(True)
        self._dt_fi.setDate(QDate.currentDate().addYears(-1))
        self._dt_fi.setEnabled(False)
        fila_fi.addWidget(self._chk_fi)
        fila_fi.addWidget(self._dt_fi, 1)
        lbl_fi = QLabel("Fecha inicio:")
        lbl_fi.setStyleSheet(f"color: {TEXTO}; font-size: 13px; background: transparent;")
        form.addRow(lbl_fi, fila_fi)

        fila_ff = QHBoxLayout()
        self._chk_ff = QCheckBox()
        self._chk_ff.setStyleSheet(CHECK_QSS)
        self._chk_ff.stateChanged.connect(self._toggle_fechas)
        self._dt_ff = QDateEdit()
        self._dt_ff.setStyleSheet(DATE_QSS)
        self._dt_ff.setCalendarPopup(True)
        self._dt_ff.setDate(QDate.currentDate())
        self._dt_ff.setEnabled(False)
        fila_ff.addWidget(self._chk_ff)
        fila_ff.addWidget(self._dt_ff, 1)
        lbl_ff = QLabel("Fecha fin:")
        lbl_ff.setStyleSheet(f"color: {TEXTO}; font-size: 13px; background: transparent;")
        form.addRow(lbl_ff, fila_ff)

        hint = QLabel("    Si no marcas las casillas, se incluye todo el historial.")
        hint.setStyleSheet(f"color: #707070; font-size: 10px; background: transparent;")
        form.addRow("", hint)

        lay.addLayout(form)

        lay.addStretch()

        # Folio preview
        from reportes_folios import previsualizar_proximo_folio
        try:
            folio_preview = previsualizar_proximo_folio("operativos")
        except Exception:
            folio_preview = ""
        if folio_preview:
            lbl_folio = QLabel(f"Folio asignado: <b>{folio_preview}</b>")
            lbl_folio.setStyleSheet(f"color: {TEXTO_TENUE}; font-size: 11px; background: transparent;")
            lay.addWidget(lbl_folio)

        # Botones
        botones = QHBoxLayout()
        botones.addStretch()

        b_cancelar = QPushButton("Cancelar")
        b_cancelar.setStyleSheet(BTN_SECONDARY)
        b_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        b_cancelar.clicked.connect(self.reject)
        botones.addWidget(b_cancelar)

        self._b_generar = QPushButton("  Vista previa")
        self._b_generar.setIcon(qta.icon("fa5s.eye", color="white"))
        self._b_generar.setIconSize(QSize(13, 13))
        self._b_generar.setStyleSheet(BTN_PRIMARY)
        self._b_generar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._b_generar.setEnabled(False)  # se habilita cuando hay selección
        self._b_generar.clicked.connect(self._generar)
        botones.addWidget(self._b_generar)

        lay.addLayout(botones)

    # ──────────────────────────────────────────────────────────────────
    #  Manejo del combo + selector
    # ──────────────────────────────────────────────────────────────────

    def _on_tipo_cambiado(self, _idx: int):
        """Habilita el botón Elegir equipos solo si hay un tipo elegido.
        Si el usuario cambia de tipo, descartamos la selección previa
        (las dos tablas tienen IDs distintos)."""
        tipo = self._combo_tipo.currentData()
        if tipo is None:
            self._btn_equipos.setEnabled(False)
            self._btn_equipos.setStyleSheet(_btn_elegir_qss_deshab())
            self._btn_equipos.setText("Elegir equipos")
        else:
            self._btn_equipos.setEnabled(True)
            self._btn_equipos.setStyleSheet(_btn_elegir_qss_activo())
            self._btn_equipos.setText("Elegir equipos")
        # Reset de selección al cambiar de tipo
        self.equipos_seleccionados = []
        self._actualizar_estado_generar()

    def _abrir_selector(self):
        tipo = self._combo_tipo.currentData()
        if not tipo:
            return
        try:
            from selector_equipo_dialog import SelectorEquipoDialog
        except ImportError:
            QMessageBox.critical(
                self, "Error",
                "No se pudo cargar el selector de equipos. "
                "Verifica que selector_equipo_dialog.py esté en el directorio del proyecto."
            )
            return

        preseleccion = [e for e in self.equipos_seleccionados if e.get("tipo") == tipo]
        dlg = SelectorEquipoDialog(
            tipo, parent=self,
            equipos_preseleccionados=preseleccion,
        )
        if dlg.exec():
            self.equipos_seleccionados = dlg.equipos_seleccionados
            self._actualizar_label_boton()
            self._actualizar_estado_generar()

    def _actualizar_label_boton(self):
        n = len(self.equipos_seleccionados)
        if n == 0:
            self._btn_equipos.setText("Elegir equipos")
            self._btn_equipos.setStyleSheet(_btn_elegir_qss_activo())
        elif n == 1:
            self._btn_equipos.setText(f"1 equipo: {self.equipos_seleccionados[0]['id']}")
            self._btn_equipos.setStyleSheet(_btn_elegir_qss_con_seleccion())
        else:
            self._btn_equipos.setText(f"{n} equipos seleccionados")
            self._btn_equipos.setStyleSheet(_btn_elegir_qss_con_seleccion())

    def _actualizar_estado_generar(self):
        self._b_generar.setEnabled(len(self.equipos_seleccionados) > 0)

    def _toggle_fechas(self):
        self._dt_fi.setEnabled(self._chk_fi.isChecked())
        self._dt_ff.setEnabled(self._chk_ff.isChecked())

    # ──────────────────────────────────────────────────────────────────
    #  Generación
    # ──────────────────────────────────────────────────────────────────

    def _generar(self):
        """
        Construye el PDF de preview (sin consumir folio) y abre la
        ventana de vista previa. El usuario decide allí si confirma
        o descarta.
        """
        if not self.equipos_seleccionados:
            QMessageBox.warning(self, "Faltan equipos",
                                "Selecciona al menos un equipo antes de continuar.")
            return

        # Lista normalizada de equipos para el motor: solo id y tipo,
        # el resto de datos se recargan desde BD al armar el reporte.
        equipos_param = [
            {"id": e["id"], "tipo": e["tipo"]}
            for e in self.equipos_seleccionados
        ]

        params: Dict[str, Any] = {
            "equipos":     equipos_param,
            "fecha_inicio": self._dt_fi.date().toString("yyyy-MM-dd") if self._chk_fi.isChecked() else None,
            "fecha_fin":    self._dt_ff.date().toString("yyyy-MM-dd") if self._chk_ff.isChecked() else None,
        }

        # Estado visual mientras se renderea el preview
        self._b_generar.setEnabled(False)
        self._b_generar.setText("  Renderizando…")
        QApplication.processEvents()

        try:
            from reportes_render import construir_pdf_preview
            preview = construir_pdf_preview(
                categoria    = "operativos",
                tipo_reporte = "historial_equipo",
                parametros   = params,
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Error al construir vista previa",
                f"Ocurrió un error al armar el preview:\n\n{type(e).__name__}: {e}"
            )
            self._b_generar.setEnabled(True)
            self._b_generar.setText("  Vista previa")
            return

        # Devolver el botón a su estado normal antes de abrir el modal,
        # para que si el usuario cierra el preview sin confirmar pueda
        # cambiar filtros y volver a previsualizar.
        self._b_generar.setEnabled(True)
        self._b_generar.setText("  Vista previa")

        # Abrir la ventana de preview (modal)
        win = VentanaPreviewPDF(preview, parent=self)
        win.pdf_oficial_generado.connect(self.pdf_generado.emit)
        resultado = win.exec()

        # Si el usuario generó el oficial, cerramos el diálogo de filtros.
        # Si solo consultó y cerró, mantenemos el diálogo abierto para que
        # pueda ajustar filtros y volver a previsualizar.
        if resultado == QDialog.DialogCode.Accepted:
            self.accept()


# ══════════════════════════════════════════════════════════════════════════
#  PESTAÑA PRINCIPAL — ReportesTab
# ══════════════════════════════════════════════════════════════════════════

class ReportesTab(QWidget):
    """
    Pestaña principal de Reportes. Para integrar en main_app.py:
        from reportes import ReportesTab
        tab = ReportesTab(self)
        self.tabs.addTab(tab, "Reportes")

        # Conectar el botón "Configuración de reportes" para que cambie a
        # la pestaña Configuración y navegue a la página Reportes:
        tab.abrir_configuracion_solicitada.connect(self._ir_a_config_reportes)
    """

    # Señal que main_app debe conectar para llevar al usuario a
    # Configuración → Reportes. Si nadie la conecta no pasa nada.
    abrir_configuracion_solicitada = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._categoria_activa = CATEGORIAS[0]["key"]
        self._pills: List[_CategoryPill] = []
        self.setStyleSheet(f"QWidget {{ background: {BG_PRINCIPAL}; color: {TEXTO}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── Header ─────────────────────────────────────────────────────
        root.addLayout(self._construir_header())

        # ── Tira de categorías (scroll horizontal) ─────────────────────
        root.addWidget(self._construir_pills())

        # ── Área principal: cards (izquierda) + recientes (derecha) ────
        contenido = QHBoxLayout()
        contenido.setSpacing(14)

        # ── Tarjetas ──
        self._scroll_cards = QScrollArea()
        self._scroll_cards.setWidgetResizable(True)
        self._scroll_cards.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_cards.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_cards.setStyleSheet(SCROLLBAR_QSS)

        self._cont_cards = QWidget()
        self._flow = FlowLayout(self._cont_cards, margin=4, h_spacing=14, v_spacing=14)
        self._scroll_cards.setWidget(self._cont_cards)
        contenido.addWidget(self._scroll_cards, 1)

        # ── Panel de recientes ──
        self._panel_recientes = _PanelRecientes()
        contenido.addWidget(self._panel_recientes)

        root.addLayout(contenido, 1)

        # Pintar la primera categoría
        self._set_categoria_activa(self._categoria_activa)

    # ──────────────────────────────────────────────────────────────────
    #  Header y pills
    # ──────────────────────────────────────────────────────────────────

    def _construir_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(14)

        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.file-pdf", color=AZUL).pixmap(26, 26))
        h.addWidget(ico, alignment=Qt.AlignmentFlag.AlignVCenter)

        tit = QLabel("Reportes")
        tit.setStyleSheet(f"color: {TEXTO}; font-size: 22px; font-weight: bold; background: transparent;")
        h.addWidget(tit, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Mini-stats
        h.addSpacing(20)
        n_disp = _reportes_disponibles()
        n_tot  = _total_reportes()
        stat = QLabel(
            f"<span style='color:{TEXTO_TENUE};'>{n_disp} de {n_tot} reportes disponibles</span>"
        )
        stat.setStyleSheet("font-size: 12px; background: transparent;")
        h.addWidget(stat, alignment=Qt.AlignmentFlag.AlignVCenter)

        h.addStretch()

        # Botón configurar
        b_cfg = QPushButton("  Configuración de reportes")
        b_cfg.setIcon(qta.icon("fa5s.cog", color="white"))
        b_cfg.setIconSize(QSize(13, 13))
        b_cfg.setStyleSheet(BTN_SECONDARY)
        b_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        b_cfg.clicked.connect(self._abrir_configuracion)
        h.addWidget(b_cfg)

        return h

    def _construir_pills(self) -> QWidget:
        contenedor = QFrame()
        contenedor.setFixedHeight(60)
        contenedor.setStyleSheet("background: transparent;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(SCROLLBAR_QSS)

        # Widget interno: pills con Fixed sizePolicy y SIN stretch para que
        # su ancho natural sea exactamente la suma de los pills + spacing.
        # Cuando ese ancho excede la viewport del scroll, la barra horizontal
        # aparece sola y los pills no se cortan.
        cont = QWidget()
        cont_lay = QHBoxLayout(cont)
        cont_lay.setContentsMargins(2, 10, 2, 10)
        cont_lay.setSpacing(10)

        for cat in CATEGORIAS:
            n = len(CATALOGO_REPORTES.get(cat["key"], []))
            pill = _CategoryPill(cat, n)
            pill.clicked.connect(self._set_categoria_activa)
            self._pills.append(pill)
            cont_lay.addWidget(pill, 0, Qt.AlignmentFlag.AlignLeft)

        # IMPORTANTE: no addStretch al final — Fixed + sin stretch hace que el
        # widget tenga el ancho natural y el scroll horizontal arranque cuando
        # toca, sin que las pills se estiren ni encojan.

        scroll.setWidget(cont)

        contenedor_lay = QVBoxLayout(contenedor)
        contenedor_lay.setContentsMargins(0, 0, 0, 0)
        contenedor_lay.addWidget(scroll)

        return contenedor

    # ──────────────────────────────────────────────────────────────────
    #  Navegación de categorías
    # ──────────────────────────────────────────────────────────────────

    def _set_categoria_activa(self, key: str):
        self._categoria_activa = key
        for p in self._pills:
            p.set_activo(p.cat_key == key)
        self._repintar_cards()

    def _repintar_cards(self):
        # Vaciar cards previas
        while self._flow.count():
            item = self._flow.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        cat = next(c for c in CATEGORIAS if c["key"] == self._categoria_activa)
        for r in CATALOGO_REPORTES.get(cat["key"], []):
            card = _ReportCard(r, cat["color"])
            card.clicked.connect(self._on_card_clicked)
            self._flow.addWidget(card)

    # ──────────────────────────────────────────────────────────────────
    #  Click en una tarjeta
    # ──────────────────────────────────────────────────────────────────

    def _on_card_clicked(self, reporte: dict):
        if reporte["estado"] != ESTADO_DISPONIBLE:
            dlg = _DialogoProximamente(reporte, self)
            dlg.exec()
            return

        # Despachar al diálogo correspondiente según el tipo
        if reporte["tipo"] == "historial_equipo":
            dlg = _DialogoHistorialEquipo(self)
            dlg.pdf_generado.connect(lambda _r: self._panel_recientes.recargar())
            dlg.exec()
            return

        # Cualquier otro implementado a futuro: aquí agregamos su diálogo.
        QMessageBox.information(
            self, reporte["nombre"],
            "Este reporte está marcado como disponible pero aún no tiene un diálogo registrado."
        )

    def _abrir_configuracion(self):
        """
        Emite la señal `abrir_configuracion_solicitada`. main_app.py debe
        conectarla a la lógica que cambia a la pestaña Configuración y
        navega al stack page de Reportes. Si nadie la conecta, no pasa
        nada (no muestra error).
        """
        self.abrir_configuracion_solicitada.emit()

    # API pública opcional para integración con main_app.py:
    def refresh_recientes(self):
        """Llámalo desde el main_app si quieres forzar la recarga del panel."""
        self._panel_recientes.recargar()


# ══════════════════════════════════════════════════════════════════════════
#  Modo standalone (para pruebas)
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    db.create_database()
    w = ReportesTab()
    w.setWindowTitle("CAMF · Reportes (preview)")
    w.resize(1280, 720)
    w.show()
    sys.exit(app.exec())
