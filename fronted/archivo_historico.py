"""
archivo_historico.py — Consulta del archivo histórico (Fase 4)

Contiene dos ventanas:

  DialogSeleccionArchivo:
    Diálogo chico que se abre al hacer clic en el botón "Archivo
    histórico" de Finalizados. El usuario elige año y mes (con la
    opción "Todo el año"), presiona Aceptar, y solo entonces se
    consultan los datos. Esto evita cargar todo el archivo a memoria
    cuando puede tener miles de registros.

  VentanaArchivoHistorico:
    Vista de consulta con listado tipo tabla ultra-compacta (una línea
    por evento) del contenido filtrado. Doble click abre la ficha del
    mantenimiento. Diseño de solo lectura — los mantenimientos
    archivados son inmutables por definición.

Uso desde finalizados.py:
    from archivo_historico import DialogSeleccionArchivo, VentanaArchivoHistorico
    dlg = DialogSeleccionArchivo(self)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        ventana = VentanaArchivoHistorico(dlg.anio_elegido, dlg.mes_elegido, self)
        ventana.exec()

Los datos vienen de db_manager.obtener_mantenimientos_archivados(anio, mes)
que ya filtra en SQL — nada se filtra en Python.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QWidget, QScrollArea, QFrame, QLineEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QFont
import qtawesome as qta

from db_manager import (
    obtener_conteos_por_anio_en_archivo,
    obtener_conteos_por_mes_en_archivo,
    obtener_mantenimientos_archivados,
)

# Reutilizamos helpers de programados.py (donde viven originalmente)
# para no duplicar lógica:
# - _formato_equipos_dos_lineas: convierte "eq:tabla|eq:tabla" a texto legible
# - calcular_estado: mismo cálculo de estado que usa toda la app
from programados import _formato_equipos_dos_lineas, calcular_estado


# ══════════════════════════════════════════════════════════════════════
#  Paleta de colores (consistente con el resto de la app)
# ══════════════════════════════════════════════════════════════════════
COLOR_BG         = "#1e1e1e"
COLOR_CARD       = "#2b2b2b"
COLOR_BORDER     = "#3a3a3a"
COLOR_TEXT       = "#e0e0e0"
COLOR_TEXT_DIM   = "#888888"
COLOR_TEXT_FAINT = "#666666"
COLOR_ACCENT     = "#0078d7"
COLOR_DANGER     = "#d9534f"
COLOR_SUCCESS    = "#5cb85c"

# Nombres de meses en español (índice 0 sin usar para que mes 1 = enero).
_MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]


# ══════════════════════════════════════════════════════════════════════
#  DIÁLOGO DE SELECCIÓN DE PARÁMETROS
# ══════════════════════════════════════════════════════════════════════

class DialogSeleccionArchivo(QDialog):
    """
    Ventana chica que le pide al usuario año y mes antes de cargar los
    datos. Al presionar Aceptar, self.anio_elegido y self.mes_elegido
    quedan con la selección (mes_elegido=None significa "todo el año").

    Si el archivo está vacío (caso edge que no debería llegar acá porque
    el botón que abre este diálogo está deshabilitado en ese caso),
    muestra un mensaje y no permite continuar.

    Al abrir por defecto:
      - Año: el más reciente disponible en el archivo.
      - Mes: "Todo el año".

    Cambio de año re-puebla el dropdown de meses con SOLO los meses de
    ese año que tengan contenido (los vacíos no aparecen). El mes vuelve
    a "Todo el año" cuando se cambia de año — así se evita mostrar
    "septiembre 2019" cuando el usuario acaba de elegir 2020.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Consultar archivo histórico")
        self.setModal(True)
        self.setFixedWidth(440)

        # Resultado de la selección (queda accesible tras Aceptar).
        self.anio_elegido: Optional[int] = None
        self.mes_elegido: Optional[int] = None   # None = todo el año

        # Datos para poblar los dropdowns.
        self._conteos_anio = obtener_conteos_por_anio_en_archivo()

        self.setStyleSheet(self._estilo())
        self._build_ui()
        self._poblar_anios()
        # Selección inicial: año más reciente (primero del dropdown).
        if self.combo_anio.count() > 0:
            self.combo_anio.setCurrentIndex(0)
            self._on_anio_changed()

    # ---------- Estilo (reusa el sistema de accion= como ficha_mantenimiento) ----------
    def _estilo(self) -> str:
        return f"""
            QDialog {{
                background-color: {COLOR_CARD};
                color: {COLOR_TEXT};
            }}
            QLabel {{
                color: {COLOR_TEXT};
                background: transparent;
            }}
            QComboBox {{
                background: {COLOR_BG};
                color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
                min-height: 22px;
            }}
            QComboBox:hover {{
                border: 1px solid {COLOR_ACCENT};
            }}
            /* No estilizamos QComboBox::drop-down ni QComboBox::down-arrow
               a propósito: PyQt6 6.9.1 no siempre renderiza el SVG
               data-URI inline en el down-arrow. Al no tocar esos
               selectores, Qt usa el chevron nativo de Windows 11 —
               mismo que los combos de circuito.py, tablero.py, etc. */
            QComboBox QAbstractItemView {{
                background: {COLOR_BG};
                color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER};
                selection-background-color: {COLOR_ACCENT};
                selection-color: white;
            }}
            QPushButton {{
                background: #2a2a2a;
                color: #fff;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background: #353535; }}
            QPushButton:disabled {{
                background: #1a1a1a;
                color: #555;
                border-color: #2a2a2a;
            }}
            QPushButton[accion="primario"] {{
                background: #2a4055; border: 1px solid #2a5085;
            }}
            QPushButton[accion="primario"]:hover {{ background: #355275; }}
            QPushButton[accion="primario"]:disabled {{
                background: #1a2530; border-color: #223045; color: #556;
            }}
            QPushButton[accion="cerrar_dialog"] {{
                background: transparent; color: #aaa; border: 1px solid #444;
            }}
            QPushButton[accion="cerrar_dialog"]:hover {{
                background: #2a2a2a; color: #ddd;
            }}
        """

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(14)

        # Encabezado
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.archive", color=COLOR_ACCENT).pixmap(QSize(22, 22)))
        ico.setStyleSheet("background: transparent;")
        header.addWidget(ico)
        titulo = QLabel("Consultar archivo histórico")
        titulo.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        header.addWidget(titulo, stretch=1)
        v.addLayout(header)

        # Descripción
        desc = QLabel(
            "Elige el año y mes que quieres consultar. "
            "Solo se cargarán los registros del filtro seleccionado."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        v.addWidget(desc)

        v.addSpacing(4)

        # Selector de Año
        lbl_anio = QLabel("Año")
        lbl_anio.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        v.addWidget(lbl_anio)
        self.combo_anio = QComboBox()
        self.combo_anio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_anio.currentIndexChanged.connect(self._on_anio_changed)
        v.addWidget(self.combo_anio)

        # Selector de Mes
        lbl_mes = QLabel("Mes")
        lbl_mes.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        v.addWidget(lbl_mes)
        self.combo_mes = QComboBox()
        self.combo_mes.setCursor(Qt.CursorShape.PointingHandCursor)
        v.addWidget(self.combo_mes)

        v.addSpacing(6)

        # Botones
        botones_h = QHBoxLayout()
        botones_h.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.setProperty("accion", "cerrar_dialog")
        btn_cancelar.clicked.connect(self.reject)
        botones_h.addWidget(btn_cancelar)

        self.btn_aceptar = QPushButton("Aceptar")
        self.btn_aceptar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_aceptar.setProperty("accion", "primario")
        self.btn_aceptar.clicked.connect(self._on_aceptar)
        botones_h.addWidget(self.btn_aceptar)

        v.addLayout(botones_h)

    # ---------- Poblar dropdowns ----------
    def _poblar_anios(self):
        """Llena el combo de años con las opciones disponibles, cada una
        con su conteo total del año. Si no hay años, deshabilita Aceptar."""
        self.combo_anio.clear()
        if not self._conteos_anio:
            self.combo_anio.addItem("Sin datos en el archivo")
            self.combo_anio.setEnabled(False)
            self.btn_aceptar.setEnabled(False)
            return

        # Ordenar años desc (más reciente primero) — el dict ya viene así
        # de la query SQL, pero iterar sobre .items() no preserva orden
        # garantizado en versiones viejas de Python, así que ordenamos.
        for anio in sorted(self._conteos_anio.keys(), reverse=True):
            cantidad = self._conteos_anio[anio]
            etiqueta = f"{anio} ({cantidad} {'registro' if cantidad == 1 else 'registros'})"
            self.combo_anio.addItem(etiqueta, userData=anio)

    def _on_anio_changed(self):
        """Cuando cambia el año, re-poblar el dropdown de meses con solo
        los meses que tienen contenido en ese año."""
        anio = self.combo_anio.currentData()
        self.combo_mes.clear()

        if anio is None:
            return

        # Total del año → primera opción "Todo el año (N registros)"
        total_anio = self._conteos_anio.get(anio, 0)
        etiqueta_total = f"Todo el año ({total_anio} {'registro' if total_anio == 1 else 'registros'})"
        self.combo_mes.addItem(etiqueta_total, userData=None)

        # Meses con contenido
        conteos_mes = obtener_conteos_por_mes_en_archivo(anio)
        for mes in sorted(conteos_mes.keys()):
            cantidad = conteos_mes[mes]
            nombre = _MESES_ES[mes]
            etiqueta = f"{nombre} ({cantidad} {'registro' if cantidad == 1 else 'registros'})"
            self.combo_mes.addItem(etiqueta, userData=mes)

        # Default: "Todo el año" (índice 0). Es lo que Cesar pidió al
        # abrir por primera vez y también al cambiar de año.
        self.combo_mes.setCurrentIndex(0)

    def _on_aceptar(self):
        """Guarda la selección y cierra con Accepted."""
        self.anio_elegido = self.combo_anio.currentData()
        self.mes_elegido  = self.combo_mes.currentData()
        if self.anio_elegido is None:
            # No debería pasar (Aceptar está deshabilitado si no hay años),
            # pero por defensa.
            self.reject()
            return
        self.accept()


# ══════════════════════════════════════════════════════════════════════
#  FILA DE ARCHIVO (una línea por evento)
# ══════════════════════════════════════════════════════════════════════

class FilaArchivo(QFrame):
    """
    Widget compacto para una fila del listado — Variante A del mockup:
    franja lateral por estado + columnas con datos clave.

    Layout de columnas:
      - Fecha:       ancho fijo (formato compacto YYYY-MM-DD).
      - Tipo:        ancho fijo (preventivo, correctivo, predictivo).
      - Equipos:     ancho fijo — se dimensiona a un tamaño razonable
                     para textos típicos ("TAB002, TAB003 · UPAEP >
                     Edificio K") y trunca los más largos con "...".
      - Responsable: stretch=1 con sizePolicy Ignored horizontal —
                     absorbe todo el ancho sobrante y por eso su texto
                     arranca inmediatamente después del final de la
                     columna Equipos, sin hueco visible.
      - Estado:      ancho fijo, alineado a la derecha.

    La decisión de anchos fijos para Equipos (en vez de stretch)
    responde al problema visual reportado: con stretch, el label
    absorbía todo el sobrante y quedaba un hueco enorme entre el texto
    real y el inicio de Responsable. Con ancho fijo, el hueco desaparece.

    Doble click emite double_clicked con el mant_id para que la ventana
    padre abra la ficha.
    """
    double_clicked = pyqtSignal(int)

    # Anchos fijos de columnas no elásticas (px).
    ANCHO_FECHA   = 100
    ANCHO_TIPO    = 100
    ANCHO_EQUIPOS = 260
    ANCHO_ESTADO  = 110

    def __init__(self, datos, equipos_lineas, parent=None):
        super().__init__(parent)
        self.mant_id = datos[0]
        # Normalizamos a lowercase para comparación robusta — la BD guarda
        # 'finalizado' / 'cancelado' en minúscula, pero calcular_estado()
        # en otros módulos usa 'Finalizado' / 'Cancelado' capitalizados.
        # No queremos depender de qué caso llegue acá.
        self.estado_raw = str(datos[8] or "").strip()
        self.estado_key = self.estado_raw.lower()  # 'finalizado' | 'cancelado'
        self.estado_display = self.estado_raw.capitalize()  # 'Finalizado'

        # Cache para texto buscable (se calcula una vez, se reusa por
        # cada tecla en el buscador).
        equipos_str = " ".join(str(x or "") for x in equipos_lineas)
        self._texto_busq = " ".join([
            equipos_str,
            str(datos[7] or ""),        # responsable
            str(datos[1] or ""),        # tipo
        ]).lower()

        # Color según estado. Verde para Finalizado, rojo para Cancelado.
        # Cualquier otro estado queda en gris tenue (defensivo).
        if self.estado_key == "finalizado":
            color_estado = COLOR_SUCCESS
        elif self.estado_key == "cancelado":
            color_estado = COLOR_DANGER
        else:
            color_estado = COLOR_TEXT_DIM

        self.setStyleSheet(f"""
            FilaArchivo {{
                background: {COLOR_CARD};
                border-left: 3px solid {color_estado};
                border-radius: 0;
            }}
            FilaArchivo:hover {{
                background: #333333;
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 8, 12, 8)
        h.setSpacing(12)

        # Columna 1: Fecha de cierre
        fecha_cierre = datos[10]
        fecha_str = self._fmt_fecha_corta(fecha_cierre)
        lbl_fecha = self._label(fecha_str, COLOR_TEXT, 12)
        lbl_fecha.setFixedWidth(self.ANCHO_FECHA)
        h.addWidget(lbl_fecha)

        # Columna 2: Tipo
        tipo = (datos[1] or "").capitalize()
        lbl_tipo = self._label(tipo, COLOR_TEXT_DIM, 12)
        lbl_tipo.setFixedWidth(self.ANCHO_TIPO)
        h.addWidget(lbl_tipo)

        # Columna 3: Equipos con ancho FIJO (260 px). Balance entre
        # "cabe casi todo" y "no queda hueco enorme" con Responsable.
        # Los textos más largos ("TAB002, TAB003 · UPAEP > Edificio K")
        # truncan con elipsis; los cortos ("TAB007 · ...") tienen un
        # pequeño espacio a la derecha antes de Responsable, aceptable
        # y consistente entre filas (todas las columnas Equipos tienen
        # el mismo ancho independientemente del contenido).
        equipos_texto = self._resumir_equipos(equipos_lineas)
        lbl_equipos = self._label(equipos_texto, COLOR_TEXT, 12)
        lbl_equipos.setWordWrap(False)
        lbl_equipos.setFixedWidth(self.ANCHO_EQUIPOS)
        h.addWidget(lbl_equipos)

        # Columna 4: Responsable absorbe TODO el ancho sobrante entre
        # Equipos y Estado. Con sizePolicy Ignored, trunca con elipsis
        # si el nombre no cabe.
        responsable = str(datos[7] or "").strip() or "—"
        lbl_resp = self._label(responsable, COLOR_TEXT_DIM, 12)
        lbl_resp.setWordWrap(False)
        lbl_resp.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        h.addWidget(lbl_resp, stretch=1)

        # Columna 5: Estado (color por tipo, alineado a la derecha)
        lbl_estado = self._label(self.estado_display, color_estado, 11)
        lbl_estado.setFixedWidth(self.ANCHO_ESTADO)
        lbl_estado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(lbl_estado)

    def _label(self, texto: str, color: str, tamano: int) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet(
            f"color: {color}; font-size: {tamano}px; background: transparent; border: none;"
        )
        return lbl

    @staticmethod
    def _fmt_fecha_corta(fecha_str) -> str:
        """'2022-08-15 10:30' → '15/08/2022'. Tolerante a valores raros."""
        if not fecha_str:
            return "—"
        try:
            dt = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return str(fecha_str)[:10] if fecha_str else "—"

    @staticmethod
    def _resumir_equipos(equipos_lineas) -> str:
        """Combina las dos líneas en una sola línea compacta para tabla."""
        if not equipos_lineas:
            return "—"
        linea1 = str(equipos_lineas[0] or "").strip() if len(equipos_lineas) > 0 else ""
        linea2 = str(equipos_lineas[1] or "").strip() if len(equipos_lineas) > 1 else ""
        if linea1 and linea2:
            return f"{linea1} · {linea2}"
        return linea1 or linea2 or "—"

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.mant_id)


# ══════════════════════════════════════════════════════════════════════
#  VENTANA DE ARCHIVO HISTÓRICO
# ══════════════════════════════════════════════════════════════════════

class VentanaArchivoHistorico(QDialog):
    """
    Vista grande de consulta del archivo, filtrada por año + mes según
    lo que el usuario eligió en DialogSeleccionArchivo.

    Diseño:
      - Header con el filtro activo + botón para reabrir el selector.
      - Buscador con debounce 150 ms.
      - Header de columnas.
      - Listado de filas (FilaArchivo) con Fase 2 (recycling) desde el
        diseño inicial: las filas se crean una vez, se filtran con
        show()/hide() según el texto del buscador.
      - Doble click en una fila abre FichaMantenimientoDialog (que es
        solo lectura para mantenimientos cerrados, por diseño de la ficha).
    """

    def __init__(self, anio: int, mes: Optional[int], parent=None):
        super().__init__(parent)
        self.anio = anio
        self.mes = mes  # None = todo el año

        self.setWindowTitle(self._titulo())
        self.setModal(True)
        self.resize(900, 640)

        # Estado interno del pool de filas (Fase 2 desde el inicio).
        self._filas_por_id = {}      # dict[int mant_id, FilaArchivo]
        self._texto_busqueda = ""

        # Debounce del buscador (misma técnica que Finalizados).
        self._debounce_busqueda = QTimer(self)
        self._debounce_busqueda.setSingleShot(True)
        self._debounce_busqueda.setInterval(150)
        self._debounce_busqueda.timeout.connect(self._aplicar_filtro_visual)

        self.setStyleSheet(self._estilo())
        self._build_ui()
        self._cargar_datos()

    def _titulo(self) -> str:
        if self.mes is None:
            return f"Archivo histórico — {self.anio}"
        return f"Archivo histórico — {_MESES_ES[self.mes]} {self.anio}"

    def _estilo(self) -> str:
        return f"""
            QDialog {{
                background-color: {COLOR_BG};
                color: {COLOR_TEXT};
            }}
            QLabel {{
                color: {COLOR_TEXT};
                background: transparent;
            }}
            QLineEdit {{
                background: {COLOR_CARD};
                color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {COLOR_ACCENT};
            }}
            QScrollArea {{
                background: {COLOR_BG};
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background: {COLOR_BG};
            }}
            QScrollBar:vertical {{
                background: {COLOR_BG};
                width: 10px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #3a3a3a;
                min-height: 20px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #4a4a4a;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: transparent;
                border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: {COLOR_BG};
            }}
            QPushButton {{
                background: #2a2a2a;
                color: #fff;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: #353535; }}
        """

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        # ---------- Header con filtro activo + botón cambiar filtro ----------
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.archive", color=COLOR_ACCENT).pixmap(QSize(20, 20)))
        header.addWidget(ico)

        self.lbl_titulo = QLabel(self._titulo())
        self.lbl_titulo.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        header.addWidget(self.lbl_titulo)

        self.lbl_conteo = QLabel("")
        self.lbl_conteo.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 12px;")
        header.addWidget(self.lbl_conteo)

        header.addStretch()

        btn_cambiar = QPushButton("  Cambiar filtro")
        btn_cambiar.setIcon(qta.icon("fa5s.filter", color=COLOR_TEXT_DIM))
        btn_cambiar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cambiar.clicked.connect(self._reabrir_selector)
        header.addWidget(btn_cambiar)

        v.addLayout(header)

        # ---------- Buscador ----------
        self.input_busqueda = QLineEdit()
        self.input_busqueda.setPlaceholderText("Buscar por equipo, responsable o tipo...")
        self.input_busqueda.textChanged.connect(self._on_busqueda_changed)
        v.addWidget(self.input_busqueda)

        # ---------- Header de columnas ----------
        header_cols = QFrame()
        header_cols.setStyleSheet(f"background: transparent; border: none;")
        h_cols = QHBoxLayout(header_cols)
        h_cols.setContentsMargins(16, 4, 12, 4)
        h_cols.setSpacing(12)

        def _lbl_col(texto, ancho=None, alineacion=Qt.AlignmentFlag.AlignLeft, stretch=False):
            lbl = QLabel(texto)
            lbl.setStyleSheet(
                f"color: {COLOR_TEXT_FAINT}; font-size: 10px; "
                f"font-weight: 600; letter-spacing: 0.5px; background: transparent;"
            )
            lbl.setAlignment(alineacion | Qt.AlignmentFlag.AlignVCenter)
            if ancho:
                lbl.setFixedWidth(ancho)
            return lbl

        h_cols.addWidget(_lbl_col("CERRADO", FilaArchivo.ANCHO_FECHA))
        h_cols.addWidget(_lbl_col("TIPO", FilaArchivo.ANCHO_TIPO))
        # EQUIPOS con ancho fijo igual al de las filas.
        # RESPONSABLE absorbe el resto vía stretch=1.
        h_cols.addWidget(_lbl_col("EQUIPOS", FilaArchivo.ANCHO_EQUIPOS))
        lbl_resp = _lbl_col("RESPONSABLE")
        lbl_resp.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        h_cols.addWidget(lbl_resp, stretch=1)
        h_cols.addWidget(_lbl_col(
            "ESTADO", FilaArchivo.ANCHO_ESTADO,
            alineacion=Qt.AlignmentFlag.AlignRight,
        ))
        v.addWidget(header_cols)

        # ---------- Scroll area con las filas ----------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._contenido = QWidget()
        self._contenido_lay = QVBoxLayout(self._contenido)
        self._contenido_lay.setContentsMargins(0, 0, 8, 0)
        self._contenido_lay.setSpacing(2)
        self._contenido_lay.addStretch()  # push filas hacia arriba

        self.scroll.setWidget(self._contenido)
        v.addWidget(self.scroll, stretch=1)

        # ---------- Mensaje de estado vacío (persistente, se muestra u oculta) ----------
        self._msg_vacio = QLabel("")
        self._msg_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_vacio.setStyleSheet(
            f"color: {COLOR_TEXT_FAINT}; font-size: 12px; font-style: italic;"
            f" background: transparent; padding: 30px 0;"
        )
        self._msg_vacio.hide()
        # Insertar antes del stretch.
        self._contenido_lay.insertWidget(0, self._msg_vacio)

    # ---------- Carga de datos ----------
    def _cargar_datos(self):
        """Trae los datos filtrados desde SQL y construye el pool de filas.
        Se llama una sola vez, al abrir la ventana. Cambiar el filtro
        (año/mes) cierra esta ventana y abre una nueva — la vieja se
        destruye entera junto con su pool."""
        datos = obtener_mantenimientos_archivados(anio=self.anio, mes=self.mes)

        self.lbl_conteo.setText(
            f"({len(datos)} {'registro' if len(datos) == 1 else 'registros'})"
        )

        if not datos:
            self._msg_vacio.setText("Sin registros para este filtro.")
            self._msg_vacio.show()
            return

        # Necesitamos jerarquia + grupo_por_equipo para el formato de equipos.
        # Los cargamos una vez desde db_manager en vez de por cada fila.
        jerarquia, grupo_por_equipo = self._cargar_contexto_equipos()

        # Construir todas las filas y agregarlas al layout.
        idx_stretch = self._contenido_lay.count() - 1  # el stretch está al final
        for m in datos:
            equipos_raw = m[9] if len(m) > 9 else None
            equipos_lineas = _formato_equipos_dos_lineas(
                equipos_raw, grupo_por_equipo, jerarquia
            )
            fila = FilaArchivo(m, equipos_lineas)
            fila.double_clicked.connect(self._abrir_ficha)
            self._filas_por_id[m[0]] = fila
            # Insertar antes del stretch para que se apilen desde arriba.
            self._contenido_lay.insertWidget(idx_stretch, fila)
            idx_stretch += 1

    def _cargar_contexto_equipos(self):
        """Carga jerarquía de grupos + mapa de equipo→grupo. Necesario
        para que _formato_equipos_dos_lineas resuelva nombres de tableros
        y transformadores en ubicaciones legibles."""
        from db_manager import connect_db
        conn = connect_db(create_if_missing=False)
        jerarquia = {}
        grupo_por_equipo = {}
        if conn is None:
            return jerarquia, grupo_por_equipo
        try:
            cur = conn.cursor()
            # Jerarquía de grupos: {id: (nombre, padre_id)}
            try:
                for gid, nombre, padre in cur.execute(
                    "SELECT id, nombre, padre_id FROM grupos"
                ).fetchall():
                    jerarquia[gid] = (nombre, padre)
            except Exception:
                pass
            # Mapa equipo→grupo (tableros + transformadores)
            for tabla in ("tableros", "transformadores"):
                try:
                    for eid, grp in cur.execute(
                        f"SELECT id, grupo_id FROM {tabla}"
                    ).fetchall():
                        grupo_por_equipo[(eid, tabla)] = grp
                except Exception:
                    continue
        finally:
            conn.close()
        return jerarquia, grupo_por_equipo

    # ---------- Buscador con debounce ----------
    def _on_busqueda_changed(self, texto: str):
        self._texto_busqueda = texto.strip().lower()
        self._debounce_busqueda.start()

    def _aplicar_filtro_visual(self):
        """Fase 2: show()/hide() sobre el pool. Cero destrucción/creación."""
        visibles = 0
        for mant_id, fila in self._filas_por_id.items():
            if not self._texto_busqueda or self._texto_busqueda in fila._texto_busq:
                fila.show()
                visibles += 1
            else:
                fila.hide()

        # Manejar mensaje de estado vacío según haya resultados o no.
        if visibles == 0 and self._filas_por_id:
            self._msg_vacio.setText("Sin resultados para la búsqueda actual.")
            self._msg_vacio.show()
        else:
            self._msg_vacio.hide()

    # ---------- Acciones ----------
    def _abrir_ficha(self, mant_id: int):
        """Doble click en una fila → abre la ficha. Por diseño de la ficha,
        los mantenimientos cerrados son de solo lectura (return [] en la
        lista de botones cuando fecha_cierre no es NULL)."""
        try:
            from ficha_mantenimiento import FichaMantenimientoDialog
            FichaMantenimientoDialog(mant_id, self).exec()
        except Exception as e:
            print(f"[ArchivoHistorico] no se pudo abrir la ficha del mantto {mant_id}: {e}")

    def _reabrir_selector(self):
        """Cierra esta ventana y reabre el diálogo de selección. Finalizados
        se encarga de encadenar la apertura de la nueva ventana con el
        nuevo filtro."""
        self.done(RESULTADO_CAMBIAR_FILTRO)


# ══════════════════════════════════════════════════════════════════════
#  Códigos de resultado personalizados para VentanaArchivoHistorico.exec()
#
#  QDialog.DialogCode define solo Accepted (1) y Rejected (0). Usamos un
#  valor > 1 para "el usuario pidió cambiar de filtro" y así el caller
#  puede diferenciar "cerrar" de "reabrir selector". Es una convención
#  estándar de Qt (los códigos de resultado son int arbitrarios).
# ══════════════════════════════════════════════════════════════════════
RESULTADO_CAMBIAR_FILTRO = 100
