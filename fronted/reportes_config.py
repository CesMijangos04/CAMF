# reportes_config.py
"""
Configuración → Reportes
========================
Páginas que viven dentro de ConfiguracionWindow. Mismo estilo Windows 11
que base_datos_config / acerca_de_config / responsables_config.

Estructura:
  ReportesSelectorPage       — landing con 5 filas
    ├── ReportesPlantillasPage      — empresa, logo, diseño
    ├── ReportesFirmasPage          — catálogo de firmantes por rol
    ├── ReportesFoliosPage          — patrón de folio por categoría
    ├── ReportesAlmacenamientoPage  — dónde se guardan los archivos generados
    └── ReportesFormatoPage         — PDF / Excel / Word

NOTA SOBRE ESTILOS: Igual que en configuracion.py, no usamos setStyleSheet
en widgets contenedores (la ventana, los QScrollArea). Cada widget estilizado
recibe su propio setStyleSheet para que los QDialog que abrimos con parent=self
mantengan apariencia nativa de Windows 11.
"""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QSizePolicy, QLineEdit, QSpinBox, QComboBox, QCheckBox,
    QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QColorDialog,
    QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPixmap
import qtawesome as qta

from db_manager import connect_db


# ══════════════════════════════════════════════════════════════════════════
#  HELPERS DE BD (lectura/escritura de las tablas reportes_*)
# ══════════════════════════════════════════════════════════════════════════

def _rows_to_dicts(rows, keys):
    return [dict(zip(keys, r)) for r in rows]


# ── Plantillas ─────────────────────────────────────────────────────────────
_PLANTILLA_KEYS = [
    'id', 'nombre', 'es_predeterminada', 'logo_path',
    'empresa_nombre', 'empresa_subtitulo', 'empresa_direccion',
    'empresa_telefono', 'empresa_correo', 'empresa_rfc',
    'pie_texto', 'mostrar_paginacion',
    'color_principal', 'color_secundario', 'tamano_letra',
    'orientacion', 'tamano_pagina',
]


def obtener_plantilla_predeterminada() -> Optional[Dict[str, Any]]:
    """Devuelve la plantilla marcada como predeterminada, o None si no hay."""
    conn = connect_db()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT {', '.join(_PLANTILLA_KEYS)}
            FROM reportes_plantillas
            WHERE es_predeterminada = 1
            LIMIT 1
        """)
        row = cur.fetchone()
    finally:
        conn.close()
    return dict(zip(_PLANTILLA_KEYS, row)) if row else None


def actualizar_plantilla(plantilla_id: int, **campos) -> None:
    """Actualiza campos arbitrarios de una plantilla."""
    if not campos:
        return
    conn = connect_db()
    if conn is None:
        return
    try:
        sets = ', '.join(f"{k} = ?" for k in campos.keys())
        vals = list(campos.values()) + [plantilla_id]
        conn.execute(f"UPDATE reportes_plantillas SET {sets} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


# ── Folios ─────────────────────────────────────────────────────────────────
_FOLIO_KEYS = ['id', 'categoria', 'patron', 'siguiente_numero', 'anio_actual', 'reset_anual']


def obtener_folios() -> List[Dict[str, Any]]:
    """Lista todos los patrones de folio, ordenados por categoría."""
    conn = connect_db()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT {', '.join(_FOLIO_KEYS)}
            FROM reportes_folios_config
            ORDER BY categoria
        """)
        rows = cur.fetchall()
    finally:
        conn.close()
    return _rows_to_dicts(rows, _FOLIO_KEYS)


def actualizar_folio(folio_id: int, **campos) -> None:
    """Actualiza patron / siguiente_numero / reset_anual."""
    permitidos = {'patron', 'siguiente_numero', 'reset_anual'}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if not campos:
        return
    conn = connect_db()
    if conn is None:
        return
    try:
        sets = ', '.join(f"{k} = ?" for k in campos.keys())
        vals = list(campos.values()) + [folio_id]
        conn.execute(f"UPDATE reportes_folios_config SET {sets} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


# ── Firmas ─────────────────────────────────────────────────────────────────
_FIRMA_KEYS = [
    'id', 'rol', 'persona_nombre', 'persona_puesto',
    'persona_cedula', 'firma_imagen_path', 'es_predeterminada',
]


def obtener_firmas() -> List[Dict[str, Any]]:
    conn = connect_db()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT {', '.join(_FIRMA_KEYS)}
            FROM reportes_firmas
            ORDER BY rol, persona_nombre
        """)
        rows = cur.fetchall()
    finally:
        conn.close()
    return _rows_to_dicts(rows, _FIRMA_KEYS)


def insertar_firma(rol: str, nombre: str, puesto: str = "",
                   cedula: str = "", firma_imagen_path: str = "") -> Optional[int]:
    conn = connect_db()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reportes_firmas
                (rol, persona_nombre, persona_puesto, persona_cedula,
                 firma_imagen_path, es_predeterminada)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (rol, nombre, puesto, cedula, firma_imagen_path or None))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def actualizar_firma(firma_id: int, **campos) -> None:
    """Actualiza campos arbitrarios de una firma (rol, nombre, imagen…)."""
    if not campos:
        return
    conn = connect_db()
    if conn is None:
        return
    try:
        sets = ', '.join(f"{k} = ?" for k in campos.keys())
        vals = list(campos.values()) + [firma_id]
        conn.execute(f"UPDATE reportes_firmas SET {sets} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


def eliminar_firma(firma_id: int) -> None:
    conn = connect_db()
    if conn is None:
        return
    try:
        conn.execute("DELETE FROM reportes_firmas WHERE id = ?", (firma_id,))
        conn.commit()
    finally:
        conn.close()


# ── Carpeta de reportes (storage local) ────────────────────────────────────
def carpeta_reportes() -> str:
    """%LOCALAPPDATA%/CAMF/reportes/ — destino por defecto de PDFs/Excel."""
    base_dir = os.path.join(os.getenv('LOCALAPPDATA', os.getcwd()), "CAMF")
    return os.path.join(base_dir, "reportes")


# ── Carpeta de recursos (logos, firmas, etc.) ──────────────────────────────
def carpeta_recursos(subcarpeta: str) -> str:
    """
    %LOCALAPPDATA%/CAMF/recursos/<subcarpeta>/  — destino para imágenes
    que vive el ciclo de vida de las plantillas/firmas (logos, firmas
    escaneadas, sellos). La carpeta se crea si no existe.
    """
    base_dir = os.path.join(os.getenv('LOCALAPPDATA', os.getcwd()), "CAMF")
    ruta = os.path.join(base_dir, "recursos", subcarpeta)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def copiar_recurso(origen: str, subcarpeta: str, prefijo: str = "img") -> str:
    """
    Copia `origen` a la carpeta de recursos con un nombre único. Devuelve
    la ruta destino. Si el archivo origen no existe lanza FileNotFoundError.

    El nombre destino lleva timestamp + extensión original para evitar
    colisiones cuando el usuario sube varias veces el mismo nombre.
    """
    import shutil
    if not os.path.isfile(origen):
        raise FileNotFoundError(f"No se encontró el archivo: {origen}")
    ext = os.path.splitext(origen)[1].lower() or '.png'
    nombre = f"{prefijo}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
    destino = os.path.join(carpeta_recursos(subcarpeta), nombre)
    shutil.copy2(origen, destino)
    return destino


# ══════════════════════════════════════════════════════════════════════════
#  CATÁLOGOS (etiquetas, iconos y colores por rol/categoría)
# ══════════════════════════════════════════════════════════════════════════

# (etiqueta, icono qta, color_icono, color_chip_bg)
ROLES_FIRMA = {
    'responsable_tecnico': ('Responsable técnico', 'fa5s.user-tie',    '#5cb1ff', '#1a2c3d'),
    'supervisor':          ('Supervisor',          'fa5s.user-shield', '#d4a04c', '#332a18'),
    'cliente':             ('Cliente',             'fa5s.user',        '#6fc28f', '#1f3a26'),
    'uvie':                ('UVIE',                'fa5s.shield-alt',  '#e67e22', '#3a2418'),
    'perito':              ('Perito',              'fa5s.gavel',       '#c45a4a', '#2a1818'),
}

CATEGORIAS_FOLIO = {
    'operativos': ('Operativos', 'fa5s.history',     '#6fc28f', '#1f3a26'),
    'tecnicos':   ('Técnicos',   'fa5s.bolt',        '#f1c40f', '#3a3318'),
    'ingenieria': ('Ingeniería', 'fa5s.calculator',  '#5cb1ff', '#1a2c3d'),
    'uvie':       ('UVIE',       'fa5s.shield-alt',  '#e67e22', '#3a2418'),
    'gestion':    ('Gestión',    'fa5s.chart-line',  '#d4a04c', '#332a18'),
    'inventario': ('Inventario', 'fa5s.boxes',       '#6fc28f', '#1f3a2e'),
}


# ══════════════════════════════════════════════════════════════════════════
#  ESTILOS REUTILIZABLES (aplicados a widgets individuales)
# ══════════════════════════════════════════════════════════════════════════

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

ROW_QSS = """
    QFrame#settings_row {
        background: #2b2b2b;
        border-radius: 8px;
        border: 1px solid transparent;
    }
    QFrame#settings_row:hover {
        background: #333333;
        border: 1px solid #0078d7;
    }
"""

CARD_QSS = """
    QFrame#card {
        background: #2b2b2b;
        border-radius: 8px;
        border: 1px solid #2f2f2f;
    }
"""

INPUT_QSS = """
    QLineEdit, QSpinBox, QComboBox {
        background: #232323;
        color: white;
        border: 1px solid #3a3a3a;
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 13px;
        min-height: 22px;
    }
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
        border: 1px solid #0078d7;
    }
    QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
        color: #666;
        background: #1f1f1f;
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
    QCheckBox::indicator:indeterminate {
        background-color: #4a8acf;
        border: 1px solid #0078d7;
    }
    QCheckBox::indicator:hover {
        border: 1px solid #888;
    }
    QCheckBox::indicator:disabled {
        background-color: #1a1a1a;
        border: 1px solid #333;
    }
"""

BTN_PRIMARY_QSS = """
    QPushButton {
        background: #0078d7;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 8px 18px;
        font-size: 13px;
        min-height: 22px;
    }
    QPushButton:hover  { background: #1a8ae0; }
    QPushButton:pressed{ background: #006bbf; }
    QPushButton:disabled { background: #2b2b2b; color: #666; }
"""

BTN_SECONDARY_QSS = """
    QPushButton {
        background: #2b2b2b;
        color: white;
        border: 1px solid #3a3a3a;
        border-radius: 6px;
        padding: 8px 14px;
        font-size: 13px;
        min-height: 22px;
    }
    QPushButton:hover {
        background: #353535;
        border: 1px solid #0078d7;
    }
    QPushButton:disabled { color: #666; }
"""

BTN_DANGER_QSS = """
    QPushButton {
        background: #2a1818;
        color: #e07a6a;
        border: 1px solid #3a2020;
        border-radius: 6px;
        padding: 6px 12px;
        font-size: 12px;
    }
    QPushButton:hover {
        background: #3a1f1f;
        border: 1px solid #e07a6a;
    }
"""

LBL_TITULO   = "color: white; font-size: 14px; font-weight: 500; background: transparent;"
LBL_DESC     = "color: #888; font-size: 12px; background: transparent;"
LBL_SECCION  = ("color: #666; font-size: 10px; font-weight: 500; "
                "letter-spacing: 1px; background: transparent;")
LBL_CAMPO    = "color: #bbb; font-size: 12px; background: transparent;"
LBL_VALOR    = "color: white; font-size: 13px; background: transparent;"
LBL_HINT     = "color: #888; font-size: 11px; background: transparent;"


# ══════════════════════════════════════════════════════════════════════════
#  WIDGET REUTILIZABLE — Fila clickable (idéntica a SettingsRow)
# ══════════════════════════════════════════════════════════════════════════

class _SettingsRow(QFrame):
    """Fila clickable estilo Windows 11. Idéntica a la de configuracion.py."""
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
        self.setStyleSheet(ROW_QSS)

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
        lbl_titulo.setStyleSheet(LBL_TITULO)
        text_box.addWidget(lbl_titulo)
        lbl_desc = QLabel(descripcion)
        lbl_desc.setStyleSheet(LBL_DESC)
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


def _scroll_envoltura(contenido: QWidget) -> QScrollArea:
    """Envuelve un QWidget en un QScrollArea estilizado consistente."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet(SCROLLBAR_QSS)
    scroll.setWidget(contenido)
    return scroll


# ══════════════════════════════════════════════════════════════════════════
#  WIDGET REUTILIZABLE — Selector visual de color
# ══════════════════════════════════════════════════════════════════════════

# Paleta de presets — colores típicos para reportes corporativos.
# Si el color guardado coincide con uno de estos, mostramos su nombre legible
# en lugar del hex.
COLORES_PRESET = [
    ("Azul corporativo",  "#0078d7"),
    ("Azul marino",       "#1f3a68"),
    ("Verde institucional", "#1d9e75"),
    ("Naranja",           "#e67e22"),
    ("Rojo",              "#c0392b"),
    ("Gris oscuro",       "#3a3a3a"),
    ("Gris medio",        "#666666"),
    ("Negro",             "#000000"),
]


def _nombre_color(hex_color: str) -> str:
    """Devuelve el nombre legible si es preset, o el hex si es custom."""
    hex_norm = (hex_color or "").lower()
    for nombre, hex_preset in COLORES_PRESET:
        if hex_preset.lower() == hex_norm:
            return nombre
    return hex_color or "—"


class _SelectorColor(QPushButton):
    """
    Botón que muestra una muestra cuadrada del color + su nombre legible
    (o hex si es custom). Al hacer click abre QColorDialog y emite la
    señal `color_cambiado` con el hex en mayúsculas (#RRGGBB).
    """
    color_cambiado = pyqtSignal(str)

    def __init__(self, hex_inicial: str = "#0078d7", parent=None):
        super().__init__(parent)
        self._hex = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Estilo base — el botón es como un campo de input
        self.setStyleSheet("""
            QPushButton {
                background: #232323;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px 10px;
                text-align: left;
                color: white;
                font-size: 13px;
            }
            QPushButton:hover {
                border: 1px solid #0078d7;
            }
        """)
        self.clicked.connect(self._abrir_picker)
        self.set_hex(hex_inicial)

    def hex(self) -> str:
        return self._hex

    def set_hex(self, hex_color: str):
        # Normalizar
        if not hex_color or not hex_color.startswith("#") or len(hex_color) not in (4, 7):
            hex_color = "#0078d7"
        self._hex = hex_color.upper()
        self._render_etiqueta()

    def _render_etiqueta(self):
        """Construye visualmente el botón: muestra (cuadro de color) + texto."""
        # Como QPushButton es text-only por defecto, usamos un layout interno
        # con un QFrame para la muestra y un QLabel para el texto.
        # Como no podemos meter widgets dentro de QPushButton de manera limpia,
        # usamos un padding-based hack via setText con HTML enriquecido NO.
        # En su lugar, dibujamos via paintEvent. Pero el camino simple:
        # contenedores anidados sí funcionan en PyQt si usamos un layout
        # propio en el botón.
        # Truco: limpiar layout previo si existe y volver a crearlo.
        old = self.layout()
        if old is not None:
            while old.count():
                item = old.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            QWidget().setLayout(old)  # reasignar para liberar

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 10, 4)
        lay.setSpacing(10)

        muestra = QFrame()
        muestra.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        muestra.setFixedSize(20, 20)
        muestra.setStyleSheet(
            f"background: {self._hex}; border: 1px solid #555; border-radius: 3px;"
        )
        lay.addWidget(muestra, alignment=Qt.AlignmentFlag.AlignVCenter)

        etiqueta = QLabel(_nombre_color(self._hex))
        etiqueta.setStyleSheet("color: white; font-size: 13px; background: transparent;")
        etiqueta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(etiqueta, alignment=Qt.AlignmentFlag.AlignVCenter)

        lay.addStretch()

        chev = QLabel()
        chev.setPixmap(qta.icon("fa5s.chevron-down", color="#888").pixmap(10, 10))
        chev.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        chev.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(chev, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _abrir_picker(self):
        dlg = _DialogoSelectorColor(self._hex, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            nuevo = dlg.color_seleccionado()
            if nuevo and nuevo.upper() != self._hex:
                self.set_hex(nuevo)
                self.color_cambiado.emit(self._hex)


class _DialogoSelectorColor(QDialog):
    """
    Diálogo de selección de color con dos vías:
      1) Paleta de 8 presets corporativos (un solo click)
      2) Botón "Color personalizado…" que abre QColorDialog
    """
    def __init__(self, hex_actual: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elegir color")
        self.setMinimumWidth(360)
        self._seleccionado = hex_actual.upper() if hex_actual else "#0078D7"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)

        instr = QLabel("Elige un color o ábrelo en personalizado.")
        instr.setStyleSheet("color: #ccc; font-size: 12px; background: transparent;")
        lay.addWidget(instr)

        # Grid de presets (4 columnas)
        grid = QHBoxLayout()
        grid.setSpacing(8)
        col_actual = QVBoxLayout()
        col_actual.setSpacing(8)
        contador = 0
        cols = [QVBoxLayout() for _ in range(4)]
        for c in cols:
            c.setSpacing(6)
        for nombre, hex_color in COLORES_PRESET:
            btn = self._btn_preset(nombre, hex_color)
            cols[contador % 4].addWidget(btn)
            contador += 1
        for c in cols:
            c.addStretch()
            grid.addLayout(c, 1)
        lay.addLayout(grid)

        # Separador visual
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #333; max-height: 1px; border: none;")
        lay.addWidget(sep)

        # Botón color personalizado
        btn_custom = QPushButton("  Color personalizado…")
        btn_custom.setIcon(qta.icon("fa5s.palette", color="white"))
        btn_custom.setIconSize(QSize(13, 13))
        btn_custom.setStyleSheet(BTN_SECONDARY_QSS)
        btn_custom.clicked.connect(self._abrir_picker_custom)
        lay.addWidget(btn_custom)

        # Botones inferiores
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def _btn_preset(self, nombre: str, hex_color: str) -> QPushButton:
        b = QPushButton(f"  {nombre}")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(32)
        # Icono "swatch" custom: usamos un pixmap pintado con qta
        b.setIcon(qta.icon("fa5s.square", color=hex_color))
        b.setIconSize(QSize(16, 16))
        es_actual = hex_color.upper() == self._seleccionado.upper()
        borde = "#0078d7" if es_actual else "#3a3a3a"
        b.setStyleSheet(f"""
            QPushButton {{
                background: #232323;
                border: 1px solid {borde};
                border-radius: 6px;
                padding: 4px 10px;
                text-align: left;
                color: white;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: #2a2a2a;
                border: 1px solid #0078d7;
            }}
        """)
        b.clicked.connect(lambda: self._elegir(hex_color))
        return b

    def _elegir(self, hex_color: str):
        self._seleccionado = hex_color.upper()
        self.accept()

    def _abrir_picker_custom(self):
        col_inicial = QColor(self._seleccionado) if QColor(self._seleccionado).isValid() else QColor("#0078d7")
        col = QColorDialog.getColor(col_inicial, self, "Color personalizado",
                                    QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if col.isValid():
            self._seleccionado = col.name().upper()  # devuelve "#rrggbb"
            self.accept()

    def color_seleccionado(self) -> str:
        return self._seleccionado


# ══════════════════════════════════════════════════════════════════════════
#  PÁGINA 1 — SELECTOR (landing)
# ══════════════════════════════════════════════════════════════════════════

class ReportesSelectorPage(QWidget):
    """
    Landing de Configuración → Reportes.
    5 filas clickables que disparan navegación al stack superior.
    """
    solicitar_plantillas     = pyqtSignal()
    solicitar_firmas         = pyqtSignal()
    solicitar_folios         = pyqtSignal()
    solicitar_almacenamiento = pyqtSignal()
    solicitar_formato        = pyqtSignal()

    OPCIONES = [
        ("Plantillas",
         "Logotipo, datos de empresa, colores y diseño",
         "fa5s.file-alt", "#5cb1ff", "#1a2c3d",
         "plantillas"),
        ("Firmas y responsables",
         "Catálogo de firmantes por rol",
         "fa5s.signature", "#6fc28f", "#1f3a26",
         "firmas"),
        ("Folios",
         "Numeración automática por categoría",
         "fa5s.hashtag", "#d4a04c", "#332a18",
         "folios"),
        ("Almacenamiento",
         "Carpeta local y respaldo en la nube",
         "fa5s.folder", "#e67e22", "#3a2418",
         "almacenamiento"),
        ("Formato de exportación",
         "PDF, Excel y Word",
         "fa5s.file-export", "#c45a4a", "#2a1818",
         "formato"),
    ]

    def __init__(self):
        super().__init__()
        self._construir_ui()

    def _construir_ui(self):
        contenido = QWidget()
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.setSpacing(6)

        cab = QLabel("PERSONALIZACIÓN")
        cab.setStyleSheet(LBL_SECCION)
        cab.setContentsMargins(2, 0, 0, 4)
        lay.addWidget(cab)

        for (titulo, desc, icon, color, chip_bg, key) in self.OPCIONES:
            fila = _SettingsRow(titulo, desc, icon, color, chip_bg, key)
            fila.clicked.connect(self._on_clicked)
            lay.addWidget(fila)

        lay.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_envoltura(contenido))

    def _on_clicked(self, key: str):
        if   key == "plantillas":     self.solicitar_plantillas.emit()
        elif key == "firmas":         self.solicitar_firmas.emit()
        elif key == "folios":         self.solicitar_folios.emit()
        elif key == "almacenamiento": self.solicitar_almacenamiento.emit()
        elif key == "formato":        self.solicitar_formato.emit()


# ══════════════════════════════════════════════════════════════════════════
#  PÁGINA 2 — PLANTILLAS (editor del perfil predeterminado)
# ══════════════════════════════════════════════════════════════════════════

class ReportesPlantillasPage(QWidget):
    """
    Editor de la plantilla predeterminada. Por ahora se trabaja sobre la
    'Plantilla predeterminada' (id=1, sembrada al crear la BD). En el
    futuro podrá listar/seleccionar entre varias plantillas.

    El logo (subir/limpiar archivo) se deja como "Próximamente" porque
    requiere armar la carpeta gestionada %LOCALAPPDATA%/CAMF/plantillas/
    y la lógica de copia, que va en una entrega siguiente.
    """
    cambios_guardados = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._plantilla: Dict[str, Any] = {}
        self._construir_ui()
        self.recargar()

    # ── UI ───────────────────────────────────────────────────────────────
    def _construir_ui(self):
        contenido = QWidget()
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.setSpacing(14)

        # Nombre de la plantilla activa
        cab_plantilla = QLabel("PLANTILLA ACTIVA")
        cab_plantilla.setStyleSheet(LBL_SECCION)
        lay.addWidget(cab_plantilla)

        tarjeta_nombre = QFrame()
        tarjeta_nombre.setObjectName("card")
        tarjeta_nombre.setStyleSheet(CARD_QSS)
        tn_lay = QHBoxLayout(tarjeta_nombre)
        tn_lay.setContentsMargins(16, 12, 16, 12)
        tn_lay.setSpacing(12)

        chip = QFrame()
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedSize(36, 36)
        chip.setStyleSheet("background: #1a2c3d; border-radius: 8px;")
        chip_lay = QVBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(qta.icon("fa5s.file-alt", color="#5cb1ff").pixmap(18, 18))
        ic.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        chip_lay.addWidget(ic)
        tn_lay.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)

        tn_text = QVBoxLayout()
        tn_text.setContentsMargins(0, 0, 0, 0)
        tn_text.setSpacing(2)
        self._lbl_plantilla_nombre = QLabel("—")
        self._lbl_plantilla_nombre.setStyleSheet(LBL_TITULO)
        tn_text.addWidget(self._lbl_plantilla_nombre)
        sub = QLabel("Es la plantilla que se usa por defecto al generar reportes.")
        sub.setStyleSheet(LBL_DESC)
        tn_text.addWidget(sub)
        tn_lay.addLayout(tn_text, 1)

        lay.addWidget(tarjeta_nombre)

        # ── Empresa ──────────────────────────────────────────────────────
        cab = QLabel("EMPRESA")
        cab.setStyleSheet(LBL_SECCION)
        cab.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(cab)

        empresa_card = QFrame()
        empresa_card.setObjectName("card")
        empresa_card.setStyleSheet(CARD_QSS)
        emp_lay = QVBoxLayout(empresa_card)
        emp_lay.setContentsMargins(16, 14, 16, 14)
        emp_lay.setSpacing(10)

        self._inp_empresa_nombre    = self._mk_input("Nombre de la empresa")
        self._inp_empresa_subtitulo = self._mk_input("Subtítulo / giro")
        self._inp_empresa_direccion = self._mk_input("Dirección")
        self._inp_empresa_telefono  = self._mk_input("Teléfono")
        self._inp_empresa_correo    = self._mk_input("Correo electrónico")
        self._inp_empresa_rfc       = self._mk_input("RFC")

        emp_lay.addLayout(self._mk_campo("Nombre",    self._inp_empresa_nombre))
        emp_lay.addLayout(self._mk_campo("Subtítulo", self._inp_empresa_subtitulo))
        emp_lay.addLayout(self._mk_campo("Dirección", self._inp_empresa_direccion))

        fila_contacto = QHBoxLayout()
        fila_contacto.setSpacing(10)
        fila_contacto.addLayout(self._mk_campo("Teléfono", self._inp_empresa_telefono), 1)
        fila_contacto.addLayout(self._mk_campo("Correo",   self._inp_empresa_correo),   1)
        fila_contacto.addLayout(self._mk_campo("RFC",      self._inp_empresa_rfc),      1)
        emp_lay.addLayout(fila_contacto)

        lay.addWidget(empresa_card)

        # ── Logo ─────────────────────────────────────────────────────────
        cab_logo = QLabel("LOGOTIPO")
        cab_logo.setStyleSheet(LBL_SECCION)
        cab_logo.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(cab_logo)

        logo_card = QFrame()
        logo_card.setObjectName("card")
        logo_card.setStyleSheet(CARD_QSS)
        logo_lay = QHBoxLayout(logo_card)
        logo_lay.setContentsMargins(16, 14, 16, 14)
        logo_lay.setSpacing(14)

        self._logo_preview = QLabel("Sin logo")
        self._logo_preview.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._logo_preview.setFixedSize(72, 72)
        self._logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_preview.setStyleSheet(
            "background: #1a1a1a; color: #666; font-size: 11px; border-radius: 6px;"
        )
        # Estado del logo cargado — se mantiene aquí entre recargas
        self._logo_path_actual: str = ""
        logo_lay.addWidget(self._logo_preview)

        logo_text = QVBoxLayout()
        logo_text.setSpacing(4)
        lbl_logo_nota = QLabel("Carga del logotipo")
        lbl_logo_nota.setStyleSheet(LBL_VALOR)
        logo_text.addWidget(lbl_logo_nota)
        hint = QLabel(
            "Formatos aceptados: PNG, JPG o SVG. Se copia a "
            "%LOCALAPPDATA%/CAMF/recursos/logos/ y se guarda la ruta en BD."
        )
        hint.setStyleSheet(LBL_HINT)
        hint.setWordWrap(True)
        logo_text.addWidget(hint)
        logo_lay.addLayout(logo_text, 1)

        # Botones a la derecha (cargar + quitar)
        col_btns = QVBoxLayout()
        col_btns.setSpacing(6)
        self._btn_logo_cargar = QPushButton("  Cargar imagen…")
        self._btn_logo_cargar.setIcon(qta.icon("fa5s.upload", color="white"))
        self._btn_logo_cargar.setIconSize(QSize(12, 12))
        self._btn_logo_cargar.setStyleSheet(BTN_SECONDARY_QSS)
        self._btn_logo_cargar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_logo_cargar.clicked.connect(self._cargar_logo)
        col_btns.addWidget(self._btn_logo_cargar)

        self._btn_logo_quitar = QPushButton("  Quitar")
        self._btn_logo_quitar.setIcon(qta.icon("fa5s.times", color="white"))
        self._btn_logo_quitar.setIconSize(QSize(11, 11))
        self._btn_logo_quitar.setStyleSheet(BTN_SECONDARY_QSS)
        self._btn_logo_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_logo_quitar.setEnabled(False)
        self._btn_logo_quitar.clicked.connect(self._quitar_logo)
        col_btns.addWidget(self._btn_logo_quitar)
        logo_lay.addLayout(col_btns)

        lay.addWidget(logo_card)

        # ── Pie de página ────────────────────────────────────────────────
        cab_pie = QLabel("PIE DE PÁGINA")
        cab_pie.setStyleSheet(LBL_SECCION)
        cab_pie.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(cab_pie)

        pie_card = QFrame()
        pie_card.setObjectName("card")
        pie_card.setStyleSheet(CARD_QSS)
        pie_lay = QVBoxLayout(pie_card)
        pie_lay.setContentsMargins(16, 14, 16, 14)
        pie_lay.setSpacing(10)

        self._inp_pie_texto = self._mk_input("Texto del pie de página")
        pie_lay.addLayout(self._mk_campo("Texto", self._inp_pie_texto))

        self._chk_paginacion = QCheckBox("Mostrar número de página (X de Y)")
        self._chk_paginacion.setStyleSheet(CHECK_QSS)
        pie_lay.addWidget(self._chk_paginacion)

        lay.addWidget(pie_card)

        # ── Diseño ───────────────────────────────────────────────────────
        cab_dis = QLabel("DISEÑO")
        cab_dis.setStyleSheet(LBL_SECCION)
        cab_dis.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(cab_dis)

        dis_card = QFrame()
        dis_card.setObjectName("card")
        dis_card.setStyleSheet(CARD_QSS)
        dis_lay = QVBoxLayout(dis_card)
        dis_lay.setContentsMargins(16, 14, 16, 14)
        dis_lay.setSpacing(10)

        # Colores — selectores visuales con paleta de presets + picker custom
        self._sel_color_principal  = _SelectorColor("#0078d7")
        self._sel_color_secundario = _SelectorColor("#666666")

        fila_colores = QHBoxLayout()
        fila_colores.setSpacing(10)
        fila_colores.addLayout(self._mk_campo("Color principal",  self._sel_color_principal), 1)
        fila_colores.addLayout(self._mk_campo("Color secundario", self._sel_color_secundario), 1)
        dis_lay.addLayout(fila_colores)

        # Tamaño de letra
        self._spn_letra = QSpinBox()
        self._spn_letra.setRange(8, 16)
        self._spn_letra.setSuffix(" pt")
        self._spn_letra.setStyleSheet(INPUT_QSS)
        self._spn_letra.setFixedWidth(110)

        # Orientación y tamaño de página
        self._cmb_orientacion = QComboBox()
        self._cmb_orientacion.addItems(["Vertical", "Horizontal"])
        self._cmb_orientacion.setStyleSheet(INPUT_QSS)
        self._cmb_orientacion.setFixedWidth(140)

        self._cmb_tamano = QComboBox()
        self._cmb_tamano.addItems(["A4", "Carta"])
        self._cmb_tamano.setStyleSheet(INPUT_QSS)
        self._cmb_tamano.setFixedWidth(110)

        fila_layout = QHBoxLayout()
        fila_layout.setSpacing(10)
        fila_layout.addLayout(self._mk_campo("Tamaño de letra", self._spn_letra))
        fila_layout.addLayout(self._mk_campo("Orientación", self._cmb_orientacion))
        fila_layout.addLayout(self._mk_campo("Tamaño de página", self._cmb_tamano))
        fila_layout.addStretch()
        dis_lay.addLayout(fila_layout)

        lay.addWidget(dis_card)

        # ── Footer con Guardar / Descartar ───────────────────────────────
        footer = QHBoxLayout()
        footer.addStretch()

        self._btn_descartar = QPushButton("Descartar cambios")
        self._btn_descartar.setStyleSheet(BTN_SECONDARY_QSS)
        self._btn_descartar.clicked.connect(self.recargar)
        footer.addWidget(self._btn_descartar)

        self._btn_guardar = QPushButton("Guardar")
        self._btn_guardar.setStyleSheet(BTN_PRIMARY_QSS)
        self._btn_guardar.clicked.connect(self._guardar)
        footer.addWidget(self._btn_guardar)

        lay.addLayout(footer)
        lay.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_envoltura(contenido))

    # ── Helpers UI ───────────────────────────────────────────────────────
    def _mk_input(self, placeholder: str = "") -> QLineEdit:
        e = QLineEdit()
        e.setPlaceholderText(placeholder)
        e.setStyleSheet(INPUT_QSS)
        return e

    def _mk_campo(self, etiqueta: str, widget: QWidget) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(4)
        v.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(etiqueta)
        lbl.setStyleSheet(LBL_CAMPO)
        v.addWidget(lbl)
        v.addWidget(widget)
        return v

    # ── Estado ───────────────────────────────────────────────────────────
    def recargar(self):
        """Lee la plantilla predeterminada de BD y la vuelca en los campos."""
        self._plantilla = obtener_plantilla_predeterminada() or {}
        p = self._plantilla

        self._lbl_plantilla_nombre.setText(p.get('nombre') or "—")

        self._inp_empresa_nombre.setText(   p.get('empresa_nombre')    or "")
        self._inp_empresa_subtitulo.setText(p.get('empresa_subtitulo') or "")
        self._inp_empresa_direccion.setText(p.get('empresa_direccion') or "")
        self._inp_empresa_telefono.setText( p.get('empresa_telefono')  or "")
        self._inp_empresa_correo.setText(   p.get('empresa_correo')    or "")
        self._inp_empresa_rfc.setText(      p.get('empresa_rfc')       or "")

        self._inp_pie_texto.setText(p.get('pie_texto') or "")
        self._chk_paginacion.setChecked(bool(p.get('mostrar_paginacion', 1)))

        self._sel_color_principal.set_hex( p.get('color_principal')  or "#0078d7")
        self._sel_color_secundario.set_hex(p.get('color_secundario') or "#666666")
        self._spn_letra.setValue(int(p.get('tamano_letra') or 10))

        orient = (p.get('orientacion') or 'vertical').lower()
        self._cmb_orientacion.setCurrentText("Vertical" if orient == 'vertical' else "Horizontal")

        tam = p.get('tamano_pagina') or 'A4'
        idx = self._cmb_tamano.findText(tam, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self._cmb_tamano.setCurrentIndex(idx)

        # Logo: cargar preview si el archivo existe
        self._logo_path_actual = p.get('logo_path') or ""
        self._render_logo_preview()

    def _guardar(self):
        if not self._plantilla.get('id'):
            QMessageBox.warning(self, "Sin plantilla",
                                "No se encontró la plantilla predeterminada en la base de datos.")
            return

        actualizar_plantilla(
            self._plantilla['id'],
            empresa_nombre    = self._inp_empresa_nombre.text().strip(),
            empresa_subtitulo = self._inp_empresa_subtitulo.text().strip(),
            empresa_direccion = self._inp_empresa_direccion.text().strip(),
            empresa_telefono  = self._inp_empresa_telefono.text().strip(),
            empresa_correo    = self._inp_empresa_correo.text().strip(),
            empresa_rfc       = self._inp_empresa_rfc.text().strip(),
            pie_texto         = self._inp_pie_texto.text().strip(),
            mostrar_paginacion= 1 if self._chk_paginacion.isChecked() else 0,
            color_principal   = self._sel_color_principal.hex() or "#0078d7",
            color_secundario  = self._sel_color_secundario.hex() or "#666666",
            tamano_letra      = int(self._spn_letra.value()),
            orientacion       = 'vertical' if self._cmb_orientacion.currentText() == "Vertical" else 'horizontal',
            tamano_pagina     = self._cmb_tamano.currentText(),
            logo_path         = self._logo_path_actual or None,
        )
        self.cambios_guardados.emit()
        self.recargar()
        QMessageBox.information(self, "Plantilla guardada",
                                "Los cambios se guardaron correctamente.")

    # ── Logo ─────────────────────────────────────────────────────────────
    def _cargar_logo(self):
        """
        Abre QFileDialog, valida el archivo seleccionado, lo copia a la
        carpeta de recursos y actualiza el preview. La ruta se persiste
        cuando el usuario presione "Guardar cambios".
        """
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir imagen del logotipo",
            "", "Imágenes (*.png *.jpg *.jpeg *.svg)"
        )
        if not ruta:
            return
        try:
            destino = copiar_recurso(ruta, subcarpeta="logos", prefijo="logo")
        except Exception as e:
            QMessageBox.critical(self, "Error al copiar",
                                 f"No se pudo copiar la imagen:\n{e}")
            return
        self._logo_path_actual = destino
        self._render_logo_preview()

    def _quitar_logo(self):
        """Desliga el logo de la plantilla. El archivo en disco se conserva."""
        self._logo_path_actual = ""
        self._render_logo_preview()

    def _render_logo_preview(self):
        """Pinta el preview cuadrado del logo (o el placeholder 'Sin logo')."""
        ruta = self._logo_path_actual
        if ruta and os.path.isfile(ruta):
            pix = QPixmap(ruta)
            if not pix.isNull():
                pix = pix.scaled(
                    72, 72,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._logo_preview.setPixmap(pix)
                self._logo_preview.setText("")
                self._logo_preview.setStyleSheet(
                    "background: #1a1a1a; border-radius: 6px;"
                )
                self._btn_logo_quitar.setEnabled(True)
                return
        # Sin logo
        self._logo_preview.clear()
        self._logo_preview.setText("Sin logo")
        self._logo_preview.setStyleSheet(
            "background: #1a1a1a; color: #666; font-size: 11px; border-radius: 6px;"
        )
        self._btn_logo_quitar.setEnabled(False)


# ══════════════════════════════════════════════════════════════════════════
#  PÁGINA 3 — FIRMAS
# ══════════════════════════════════════════════════════════════════════════

class _FirmaRow(QFrame):
    """Una fila de la lista de firmas: chip del rol + datos + botón borrar."""
    eliminada = pyqtSignal(int)

    def __init__(self, firma: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.firma = firma
        self.setObjectName("card")
        self.setStyleSheet(CARD_QSS)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        rol = firma.get('rol') or ''
        etiqueta_rol, icon_name, icon_color, chip_bg = ROLES_FIRMA.get(
            rol, (rol.title(), 'fa5s.user', '#888', '#2a2a2a')
        )

        chip = QFrame()
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedSize(32, 32)
        chip.setStyleSheet(f"background: {chip_bg}; border-radius: 7px;")
        chip_lay = QVBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(16, 16))
        ic.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        chip_lay.addWidget(ic)
        lay.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.setContentsMargins(0, 0, 0, 0)
        nombre = QLabel(firma.get('persona_nombre') or "—")
        nombre.setStyleSheet(LBL_TITULO)
        text.addWidget(nombre)
        puesto = firma.get('persona_puesto') or ''
        cedula = firma.get('persona_cedula') or ''
        sub_partes = [etiqueta_rol]
        if puesto:
            sub_partes.append(puesto)
        if cedula:
            sub_partes.append(f"Céd. {cedula}")
        sub = QLabel(" · ".join(sub_partes))
        sub.setStyleSheet(LBL_DESC)
        text.addWidget(sub)
        lay.addLayout(text, 1)

        btn_borrar = QPushButton("Eliminar")
        btn_borrar.setStyleSheet(BTN_DANGER_QSS)
        btn_borrar.clicked.connect(self._confirmar_borrado)
        lay.addWidget(btn_borrar, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _confirmar_borrado(self):
        resp = QMessageBox.question(
            self, "Eliminar firma",
            f"¿Eliminar la firma de {self.firma.get('persona_nombre')}?",
        )
        if resp == QMessageBox.StandardButton.Yes:
            self.eliminada.emit(self.firma['id'])


class _DialogoNuevaFirma(QDialog):
    """Diálogo para agregar una firma. Incluye carga opcional de imagen
    (PNG transparente o JPG) que se renderea encima de la línea de firma
    en el reporte final."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva firma")
        self.setMinimumWidth(420)
        self._firma_imagen_path: str = ""

        form = QFormLayout(self)
        form.setSpacing(10)

        self.cmb_rol = QComboBox()
        self.cmb_rol.setStyleSheet(INPUT_QSS)
        for key, (etiq, *_rest) in ROLES_FIRMA.items():
            self.cmb_rol.addItem(etiq, userData=key)

        self.inp_nombre = QLineEdit()
        self.inp_nombre.setStyleSheet(INPUT_QSS)
        self.inp_nombre.setPlaceholderText("Nombre completo")

        self.inp_puesto = QLineEdit()
        self.inp_puesto.setStyleSheet(INPUT_QSS)
        self.inp_puesto.setPlaceholderText("Ej. Ingeniero electricista")

        self.inp_cedula = QLineEdit()
        self.inp_cedula.setStyleSheet(INPUT_QSS)
        self.inp_cedula.setPlaceholderText("Cédula profesional (opcional)")

        form.addRow("Rol:",    self.cmb_rol)
        form.addRow("Nombre:", self.inp_nombre)
        form.addRow("Puesto:", self.inp_puesto)
        form.addRow("Cédula:", self.inp_cedula)

        # ── Imagen de firma (opcional) ───────────────────────────────────
        fila_firma = QHBoxLayout()
        fila_firma.setSpacing(10)

        self._firma_preview = QLabel("Sin imagen")
        self._firma_preview.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._firma_preview.setFixedSize(120, 56)
        self._firma_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._firma_preview.setStyleSheet(
            "background: #1a1a1a; color: #666; font-size: 11px; border-radius: 4px;"
        )
        fila_firma.addWidget(self._firma_preview)

        col_btns = QVBoxLayout()
        col_btns.setSpacing(4)
        self._btn_firma_cargar = QPushButton("  Cargar…")
        self._btn_firma_cargar.setIcon(qta.icon("fa5s.upload", color="white"))
        self._btn_firma_cargar.setIconSize(QSize(11, 11))
        self._btn_firma_cargar.setStyleSheet(BTN_SECONDARY_QSS)
        self._btn_firma_cargar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_firma_cargar.clicked.connect(self._cargar_imagen)
        col_btns.addWidget(self._btn_firma_cargar)

        self._btn_firma_quitar = QPushButton("  Quitar")
        self._btn_firma_quitar.setIcon(qta.icon("fa5s.times", color="white"))
        self._btn_firma_quitar.setIconSize(QSize(10, 10))
        self._btn_firma_quitar.setStyleSheet(BTN_SECONDARY_QSS)
        self._btn_firma_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_firma_quitar.setEnabled(False)
        self._btn_firma_quitar.clicked.connect(self._quitar_imagen)
        col_btns.addWidget(self._btn_firma_quitar)
        fila_firma.addLayout(col_btns)
        fila_firma.addStretch()

        form.addRow("Imagen:", fila_firma)

        hint_firma = QLabel(
            "Recomendado: PNG transparente, fondo claro. "
            "Tamaño aprox 600×220 px."
        )
        hint_firma.setStyleSheet(LBL_HINT)
        hint_firma.setWordWrap(True)
        form.addRow("", hint_firma)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Agregar")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

    def _cargar_imagen(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir imagen de firma",
            "", "Imágenes (*.png *.jpg *.jpeg)"
        )
        if not ruta:
            return
        try:
            destino = copiar_recurso(ruta, subcarpeta="firmas", prefijo="firma")
        except Exception as e:
            QMessageBox.critical(self, "Error al copiar",
                                 f"No se pudo copiar la imagen:\n{e}")
            return
        self._firma_imagen_path = destino
        self._render_preview()

    def _quitar_imagen(self):
        self._firma_imagen_path = ""
        self._render_preview()

    def _render_preview(self):
        ruta = self._firma_imagen_path
        if ruta and os.path.isfile(ruta):
            pix = QPixmap(ruta)
            if not pix.isNull():
                pix = pix.scaled(
                    120, 56,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._firma_preview.setPixmap(pix)
                self._firma_preview.setText("")
                self._firma_preview.setStyleSheet(
                    "background: #f5f5f5; border-radius: 4px;"
                )
                self._btn_firma_quitar.setEnabled(True)
                return
        self._firma_preview.clear()
        self._firma_preview.setText("Sin imagen")
        self._firma_preview.setStyleSheet(
            "background: #1a1a1a; color: #666; font-size: 11px; border-radius: 4px;"
        )
        self._btn_firma_quitar.setEnabled(False)

    def _aceptar(self):
        if not self.inp_nombre.text().strip():
            QMessageBox.warning(self, "Falta el nombre",
                                "El nombre de la persona es obligatorio.")
            return
        self.accept()

    def datos(self) -> Dict[str, str]:
        return {
            'rol':                self.cmb_rol.currentData(),
            'nombre':             self.inp_nombre.text().strip(),
            'puesto':             self.inp_puesto.text().strip(),
            'cedula':             self.inp_cedula.text().strip(),
            'firma_imagen_path':  self._firma_imagen_path,
        }


class ReportesFirmasPage(QWidget):
    """
    Catálogo de firmas. Listado + botón Agregar.
    La imagen de firma (PNG transparente) queda para una entrega
    posterior; aquí solo capturamos los datos textuales.
    """
    def __init__(self):
        super().__init__()
        self._construir_ui()
        self.recargar()

    def _construir_ui(self):
        contenido = QWidget()
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.setSpacing(10)

        # Cabecera + botón Agregar
        cabecera = QHBoxLayout()
        cabecera.setSpacing(10)
        lbl = QLabel("FIRMAS REGISTRADAS")
        lbl.setStyleSheet(LBL_SECCION)
        cabecera.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        cabecera.addStretch()

        btn = QPushButton("  Agregar firma")
        btn.setIcon(qta.icon("fa5s.plus", color="white"))
        btn.setIconSize(QSize(12, 12))
        btn.setStyleSheet(BTN_PRIMARY_QSS)
        btn.clicked.connect(self._agregar)
        cabecera.addWidget(btn)
        lay.addLayout(cabecera)

        # Contenedor de la lista
        self._lista_layout = QVBoxLayout()
        self._lista_layout.setSpacing(6)
        lay.addLayout(self._lista_layout)

        # Estado vacío
        self._lbl_vacio = QLabel(
            "Aún no has registrado firmas. Agrega responsables que firmen los reportes."
        )
        self._lbl_vacio.setStyleSheet(LBL_HINT)
        self._lbl_vacio.setWordWrap(True)
        self._lbl_vacio.setContentsMargins(4, 12, 4, 12)
        lay.addWidget(self._lbl_vacio)

        lay.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_envoltura(contenido))

    def recargar(self):
        # Limpiar layout
        while self._lista_layout.count():
            item = self._lista_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        firmas = obtener_firmas()
        self._lbl_vacio.setVisible(len(firmas) == 0)

        for f in firmas:
            fila = _FirmaRow(f)
            fila.eliminada.connect(self._eliminar)
            self._lista_layout.addWidget(fila)

    def _agregar(self):
        dlg = _DialogoNuevaFirma(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.datos()
            insertar_firma(rol=d['rol'], nombre=d['nombre'],
                           puesto=d['puesto'], cedula=d['cedula'],
                           firma_imagen_path=d['firma_imagen_path'])
            self.recargar()

    def _eliminar(self, firma_id: int):
        eliminar_firma(firma_id)
        self.recargar()


# ══════════════════════════════════════════════════════════════════════════
#  PÁGINA 4 — FOLIOS
# ══════════════════════════════════════════════════════════════════════════

class _FolioRow(QFrame):
    """Una fila de la lista de folios: categoría + patrón editable + contador."""
    guardada = pyqtSignal()
    reset_solicitado = pyqtSignal(int)

    def __init__(self, folio: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.folio = folio
        self.setObjectName("card")
        self.setStyleSheet(CARD_QSS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        # Cabecera: chip + nombre de categoría + contador actual
        cab = QHBoxLayout()
        cab.setSpacing(12)

        cat = folio.get('categoria') or ''
        etiqueta, icon_name, icon_color, chip_bg = CATEGORIAS_FOLIO.get(
            cat, (cat.title(), 'fa5s.tag', '#888', '#2a2a2a')
        )

        chip = QFrame()
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedSize(32, 32)
        chip.setStyleSheet(f"background: {chip_bg}; border-radius: 7px;")
        chip_lay = QVBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(16, 16))
        ic.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        chip_lay.addWidget(ic)
        cab.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)

        nombre = QLabel(etiqueta)
        nombre.setStyleSheet(LBL_TITULO)
        cab.addWidget(nombre, alignment=Qt.AlignmentFlag.AlignVCenter)
        cab.addStretch()

        contador = QLabel(f"Próximo número: {folio.get('siguiente_numero')}")
        contador.setStyleSheet(LBL_DESC)
        cab.addWidget(contador, alignment=Qt.AlignmentFlag.AlignVCenter)

        lay.addLayout(cab)

        # Patrón + ejemplo + acciones
        fila = QHBoxLayout()
        fila.setSpacing(10)

        self._inp_patron = QLineEdit(folio.get('patron') or '')
        self._inp_patron.setStyleSheet(INPUT_QSS)
        self._inp_patron.setPlaceholderText("Ej. CAMF-MTTO-{YYYY}-{####}")
        self._inp_patron.textChanged.connect(self._actualizar_ejemplo)
        fila.addWidget(self._inp_patron, 2)

        self._lbl_ejemplo = QLabel("")
        self._lbl_ejemplo.setStyleSheet(LBL_HINT)
        fila.addWidget(self._lbl_ejemplo, 1)

        btn_guardar = QPushButton("Guardar")
        btn_guardar.setStyleSheet(BTN_SECONDARY_QSS)
        btn_guardar.clicked.connect(self._guardar)
        fila.addWidget(btn_guardar)

        btn_reset = QPushButton("Reiniciar")
        btn_reset.setStyleSheet(BTN_SECONDARY_QSS)
        btn_reset.setToolTip("Vuelve el contador a 1 (no cambia el patrón).")
        btn_reset.clicked.connect(self._reset)
        fila.addWidget(btn_reset)

        lay.addLayout(fila)
        self._actualizar_ejemplo()

    def _actualizar_ejemplo(self):
        patron = self._inp_patron.text().strip()
        if not patron:
            self._lbl_ejemplo.setText("")
            return
        from datetime import datetime as _dt
        anio = _dt.now().year
        mes = f"{_dt.now().month:02d}"
        num = int(self.folio.get('siguiente_numero') or 1)
        ejemplo = (patron
                   .replace('{YYYY}', str(anio))
                   .replace('{MM}', mes)
                   .replace('{####}', f"{num:04d}"))
        self._lbl_ejemplo.setText(f"→  {ejemplo}")

    def _guardar(self):
        patron = self._inp_patron.text().strip()
        if not patron:
            QMessageBox.warning(self, "Patrón vacío", "El patrón no puede estar vacío.")
            return
        if '{####}' not in patron:
            resp = QMessageBox.question(
                self, "Patrón sin contador",
                "El patrón no incluye '{####}'. Sin esto, todos los folios serán iguales.\n\n"
                "¿Guardar de todas formas?",
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
        actualizar_folio(self.folio['id'], patron=patron)
        self.folio['patron'] = patron
        self.guardada.emit()

    def _reset(self):
        resp = QMessageBox.question(
            self, "Reiniciar contador",
            f"¿Reiniciar el contador de '{self.folio['categoria']}' a 1?\n\n"
            "Los folios viejos siguen siendo válidos; solo afecta el próximo número emitido.",
        )
        if resp == QMessageBox.StandardButton.Yes:
            self.reset_solicitado.emit(self.folio['id'])


class ReportesFoliosPage(QWidget):
    """
    Configuración de patrones de folio por categoría.
    Muestra 6 filas (una por categoría) con patrón editable, contador
    actual, vista previa de ejemplo y botón de reset.
    """
    def __init__(self):
        super().__init__()
        self._construir_ui()
        self.recargar()

    def _construir_ui(self):
        contenido = QWidget()
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.setSpacing(10)

        cab = QLabel("PATRONES POR CATEGORÍA")
        cab.setStyleSheet(LBL_SECCION)
        lay.addWidget(cab)

        ayuda = QLabel(
            "Tokens disponibles: {YYYY} año, {MM} mes, {####} número (4 dígitos)."
        )
        ayuda.setStyleSheet(LBL_HINT)
        ayuda.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(ayuda)

        self._lista_layout = QVBoxLayout()
        self._lista_layout.setSpacing(8)
        lay.addLayout(self._lista_layout)

        lay.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_envoltura(contenido))

    def recargar(self):
        while self._lista_layout.count():
            item = self._lista_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for f in obtener_folios():
            fila = _FolioRow(f)
            fila.guardada.connect(self.recargar)
            fila.reset_solicitado.connect(self._resetear_contador)
            self._lista_layout.addWidget(fila)

    def showEvent(self, event):
        # Cada vez que la página se hace visible (entrar desde el selector
        # superior o regresar a Configuración después de emitir un reporte),
        # refrescamos los contadores para que la vista previa del próximo
        # folio refleje el estado real de la BD.
        super().showEvent(event)
        self.recargar()

    def _resetear_contador(self, folio_id: int):
        actualizar_folio(folio_id, siguiente_numero=1)
        self.recargar()


# ══════════════════════════════════════════════════════════════════════════
#  PÁGINA 5 — ALMACENAMIENTO
# ══════════════════════════════════════════════════════════════════════════

class ReportesAlmacenamientoPage(QWidget):
    """
    Configuración de almacenamiento de reportes generados.
    Por ahora muestra (solo lectura) la carpeta local destino.
    Firebase queda como "Próximamente".
    """
    def __init__(self):
        super().__init__()
        self._construir_ui()

    def _construir_ui(self):
        contenido = QWidget()
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.setSpacing(14)

        # ── Carpeta local ───────────────────────────────────────────────
        cab1 = QLabel("CARPETA LOCAL")
        cab1.setStyleSheet(LBL_SECCION)
        lay.addWidget(cab1)

        local_card = QFrame()
        local_card.setObjectName("card")
        local_card.setStyleSheet(CARD_QSS)
        l1 = QVBoxLayout(local_card)
        l1.setContentsMargins(16, 14, 16, 14)
        l1.setSpacing(10)

        ruta = carpeta_reportes()
        lbl_etiqueta = QLabel("Destino actual")
        lbl_etiqueta.setStyleSheet(LBL_CAMPO)
        l1.addWidget(lbl_etiqueta)

        self._inp_ruta = QLineEdit(ruta)
        self._inp_ruta.setReadOnly(True)
        self._inp_ruta.setStyleSheet(INPUT_QSS)
        l1.addWidget(self._inp_ruta)

        acciones = QHBoxLayout()
        acciones.addStretch()

        btn_abrir = QPushButton("  Abrir carpeta")
        btn_abrir.setIcon(qta.icon("fa5s.folder-open", color="white"))
        btn_abrir.setIconSize(QSize(12, 12))
        btn_abrir.setStyleSheet(BTN_SECONDARY_QSS)
        btn_abrir.clicked.connect(self._abrir_carpeta)
        acciones.addWidget(btn_abrir)

        btn_cambiar = QPushButton("Cambiar ubicación…")
        btn_cambiar.setStyleSheet(BTN_SECONDARY_QSS)
        btn_cambiar.setEnabled(False)
        btn_cambiar.setToolTip("Próximamente — por ahora se usa la ruta por defecto.")
        acciones.addWidget(btn_cambiar)

        l1.addLayout(acciones)
        lay.addWidget(local_card)

        # ── Respaldo en la nube ─────────────────────────────────────────
        cab2 = QLabel("RESPALDO EN LA NUBE")
        cab2.setStyleSheet(LBL_SECCION)
        cab2.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(cab2)

        cloud_card = QFrame()
        cloud_card.setObjectName("card")
        cloud_card.setStyleSheet(CARD_QSS)
        l2 = QHBoxLayout(cloud_card)
        l2.setContentsMargins(16, 14, 16, 14)
        l2.setSpacing(12)

        chip = QFrame()
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedSize(36, 36)
        chip.setStyleSheet("background: #2a1f15; border-radius: 8px;")
        chip_lay = QVBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(qta.icon("fa5s.cloud", color="#e67e22").pixmap(18, 18))
        ic.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        chip_lay.addWidget(ic)
        l2.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(2)
        titulo = QLabel("Firebase Storage")
        titulo.setStyleSheet(LBL_TITULO)
        text.addWidget(titulo)
        desc = QLabel("Sincronización automática de reportes generados.")
        desc.setStyleSheet(LBL_DESC)
        text.addWidget(desc)
        l2.addLayout(text, 1)

        badge = QLabel("Próximamente")
        badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        badge.setStyleSheet(
            "background: #2a1f15; color: #e67e22; "
            "font-size: 11px; font-weight: 500; padding: 4px 10px; border-radius: 4px;"
        )
        l2.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(cloud_card)
        lay.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_envoltura(contenido))

    def _abrir_carpeta(self):
        ruta = self._inp_ruta.text().strip()
        try:
            os.makedirs(ruta, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "No se pudo abrir",
                                f"No se pudo crear/abrir la carpeta:\n{e}")
            return
        # Multiplataforma básico — en Windows usa explorer
        try:
            if os.name == 'nt':
                os.startfile(ruta)  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(['xdg-open', ruta])  # noqa: S607
        except Exception as e:
            QMessageBox.warning(self, "No se pudo abrir",
                                f"No se pudo abrir el explorador de archivos:\n{e}")


# ══════════════════════════════════════════════════════════════════════════
#  PÁGINA 6 — FORMATO DE EXPORTACIÓN
# ══════════════════════════════════════════════════════════════════════════

class ReportesFormatoPage(QWidget):
    """
    Toggles de formato de exportación.

    NOTA: Por ahora los toggles son visuales. La persistencia se conecta
    cuando esté funcional el motor de generación de reportes (Entrega 1.3+).
    """
    def __init__(self):
        super().__init__()
        self._construir_ui()

    def _construir_ui(self):
        contenido = QWidget()
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.setSpacing(10)

        cab = QLabel("FORMATOS DISPONIBLES PARA EXPORTAR")
        cab.setStyleSheet(LBL_SECCION)
        lay.addWidget(cab)

        ayuda = QLabel(
            "Al generar un reporte podrás elegir el formato. Aquí defines cuáles aparecen activos."
        )
        ayuda.setStyleSheet(LBL_HINT)
        ayuda.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(ayuda)

        lay.addWidget(self._fila_formato(
            "PDF", "Documento portable, no editable",
            "fa5s.file-pdf", "#e74c3c", "#2a1818",
            activo=True, deshabilitado=False, badge=None,
        ))
        lay.addWidget(self._fila_formato(
            "Excel", "Datos tabulares editables",
            "fa5s.file-excel", "#6fc28f", "#1f3a26",
            activo=True, deshabilitado=False, badge=None,
        ))
        lay.addWidget(self._fila_formato(
            "Word", "Documento editable en Office",
            "fa5s.file-word", "#5cb1ff", "#1a2c3d",
            activo=False, deshabilitado=True, badge="Próximamente",
        ))

        nota = QLabel(
            "La persistencia de estas preferencias se activará cuando esté listo "
            "el motor de generación de reportes."
        )
        nota.setStyleSheet(LBL_HINT)
        nota.setWordWrap(True)
        nota.setContentsMargins(0, 16, 0, 0)
        lay.addWidget(nota)

        lay.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll_envoltura(contenido))

    def _fila_formato(self, nombre, desc, icon_name, icon_color, chip_bg,
                      activo: bool, deshabilitado: bool, badge: Optional[str]) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(CARD_QSS)
        l = QHBoxLayout(card)
        l.setContentsMargins(16, 12, 16, 12)
        l.setSpacing(12)

        chip = QFrame()
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedSize(36, 36)
        chip.setStyleSheet(f"background: {chip_bg}; border-radius: 8px;")
        chip_lay = QVBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(18, 18))
        ic.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        chip_lay.addWidget(ic)
        l.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.setContentsMargins(0, 0, 0, 0)
        tit = QLabel(nombre)
        tit.setStyleSheet(LBL_TITULO)
        text.addWidget(tit)
        sub = QLabel(desc)
        sub.setStyleSheet(LBL_DESC)
        text.addWidget(sub)
        l.addLayout(text, 1)

        if badge:
            b = QLabel(badge)
            b.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            b.setStyleSheet(
                "background: #2a1f15; color: #e67e22; "
                "font-size: 11px; font-weight: 500; padding: 4px 10px; border-radius: 4px;"
            )
            l.addWidget(b, alignment=Qt.AlignmentFlag.AlignVCenter)

        chk = QCheckBox()
        chk.setStyleSheet(CHECK_QSS)
        chk.setChecked(activo)
        chk.setEnabled(not deshabilitado)
        l.addWidget(chk, alignment=Qt.AlignmentFlag.AlignVCenter)

        return card
