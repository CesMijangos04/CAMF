from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox, QLineEdit, QSizePolicy,
    QTextEdit, QPushButton, QDateEdit, QMessageBox, QTimeEdit, QGridLayout, QGraphicsOpacityEffect,
    QToolBar, QDialog
)
from PyQt6.QtCore import Qt, QDate, QSize, QTime, QLocale, pyqtSignal
from PyQt6.QtGui import QIcon, QIntValidator, QAction, QTextCursor, QTextListFormat, QTextBlockFormat
from datetime import datetime, timedelta, time as dtime
from db_manager import obtener_datos, ejecutar_query, insertar_datos, connect_db
from selector_equipo_dialog import SelectorEquipoDialog
from lista_responsables import ListaResponsablesDialog
from signals import app_signals
import qtawesome as qta
import re

# ── Mapeo amigable ←→ valor interno para el tipo de equipo ──────────────────
# El combo muestra "Tableros" / "Transformadores"; internamente trabajamos
# con el nombre de la tabla en la BD ('tableros' / 'transformadores'), que
# es lo que esperan SelectorEquipoDialog y la tabla puente mantenimientos_equipos.
TIPO_EQUIPO_OPCIONES = [
    ("Tableros",        "tableros"),
    ("Transformadores", "transformadores"),
]

class ProgramarNuevoWidget(QWidget):
    # ── Signals usados por el modo edición ────────────────────────────────
    # Emitidos para que el QDialog que envuelve el widget en modo edición
    # sepa cuándo cerrarse (accept tras UPDATE exitoso / reject tras cancelar).
    # En modo creación normal (la pestaña Nuevo) no se usan.
    mantenimiento_actualizado = pyqtSignal()
    edicion_cancelada         = pyqtSignal()

    def __init__(self, modo_edicion=False, mantenimiento_id=None, parent=None):
        super().__init__(parent)
        # ── Modo edición ──
        # Si modo_edicion=True, el widget se comporta como editor de un
        # mantenimiento existente: precarga datos, deshabilita campos no
        # editables (equipos, fechas, horario) y el botón guardar cambia a
        # 'Actualizar'. Se invoca típicamente vía editar_modal(...).
        self.modo_edicion = modo_edicion
        self.mantenimiento_id_edicion = mantenimiento_id

        self.personal_registrado = []
        self.equipos_registrados = []
        self.proveedores_registrados = []
        self.responsable_actual = None

        # Lista de equipos seleccionados en el diálogo de selección múltiple.
        self.equipos_seleccionados = []

        self.init_ui()

        # Si entramos en modo edición, precargar datos del mantenimiento y
        # bloquear los campos no editables. Esto va DESPUÉS de init_ui para
        # que todos los widgets ya existan.
        if self.modo_edicion and self.mantenimiento_id_edicion is not None:
            self._cargar_para_edicion()

        self._actualizar_estado_boton_guardar()

    #------------------------- UI Programar nuevo ----------------------------
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(20)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(16)

        # ─── Header (mismo patrón que Programados / Finalizados) ────
        # Ícono qtawesome a la izquierda + título grande + subtítulo
        # tenue debajo. Las 3 piezas se guardan como atributos de
        # instancia para que _cargar_para_edicion pueda cambiarlas
        # cuando se entre en modo edición.
        header_container = QWidget()
        header_v = QVBoxLayout(header_container)
        header_v.setContentsMargins(0, 0, 0, 0)
        header_v.setSpacing(4)

        titulo_row = QHBoxLayout()
        titulo_row.setSpacing(10)
        titulo_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._icono_header_label = QLabel()
        self._icono_header_label.setPixmap(
            qta.icon("fa5s.plus-circle", color="#ddd").pixmap(22, 22)
        )
        self._icono_header_label.setFixedSize(22, 22)
        titulo_row.addWidget(
            self._icono_header_label, alignment=Qt.AlignmentFlag.AlignVCenter
        )

        self._titulo_label = QLabel("Programar nuevo mantenimiento")
        self._titulo_label.setStyleSheet(
            "color: white; font-size: 22px; font-weight: 500;"
            " background: transparent;"
        )
        titulo_row.addWidget(
            self._titulo_label, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        titulo_row.addStretch()
        header_v.addLayout(titulo_row)

        self._subtitulo_label = QLabel(
            "Captura los datos del evento a programar"
        )
        self._subtitulo_label.setStyleSheet(
            "color: #888; font-size: 12px; background: transparent;"
        )
        self._subtitulo_label.setContentsMargins(32, 0, 0, 0)
        header_v.addWidget(self._subtitulo_label)

        form_layout.addWidget(header_container)

         # ─── Selección de equipo (combo + botón) ─────────────────
        equipo_layout = QHBoxLayout()
 
        self.combo_equipo = QComboBox()
        self.combo_equipo.setFixedHeight(32)
        self.combo_equipo.addItem("Seleccionar equipo o tablero", userData=None)
        self.combo_equipo.setStyleSheet("""
            QComboBox {
                background-color: #1e1e1e; color: white;
                border: 1px solid #444; border-radius: 5px;
                padding: 6px;
            }
        """)
 
        self.btn_elegir_equipo = QPushButton("Elegir equipo")
        self.btn_elegir_equipo.setFixedHeight(32)
        self._aplicar_estilo_btn_elegir(activo=False)  # inicia deshabilitado
        self.btn_elegir_equipo.setEnabled(False)
        self.btn_elegir_equipo.clicked.connect(self.abrir_selector_equipo)
 
        self.combo_equipo.currentIndexChanged.connect(self.on_tipo_equipo_changed)
 
        equipo_layout.addWidget(self.combo_equipo)
        equipo_layout.addWidget(self.btn_elegir_equipo)
        form_layout.addLayout(equipo_layout)

        # ─── Tipo de mantenimiento + Urgente ─────────────────────
        self.combo_tipo = QComboBox()
        self.combo_tipo.setFixedHeight(32)
        self.combo_tipo.setStyleSheet("""
            QComboBox {
                background-color: #1e1e1e; color: white;
                border: 1px solid #444; border-radius: 5px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e1e1e; color: white;
                selection-background-color: #0078d7;
                border: 1px solid #444;
            }
        """)
        self.combo_tipo.addItems(["Preventivo", "Correctivo", "Predictivo"])

        CHECKBOX_STYLE = """
            QCheckBox { color: white; spacing: 8px; }
            QCheckBox::indicator {
                width: 16px; height: 16px; border-radius: 3px;
                border: 1px solid #555; background-color: #1e1e1e;
            }
            QCheckBox::indicator:checked {
                background-color: #0078d7; border: 1px solid #0078d7;
            }
            QCheckBox::indicator:checked:hover { background-color: #0094ff; }
            QCheckBox::indicator:disabled {
                background-color: #2a2a2a; border: 1px solid #444;
            }
        """

        # ── Slot extra del tipo: "Urgente" (correctivo) o "Recurrente cada [...]" (preventivo) ──
        # Comparten la misma fila vertical para no desalinear la columna de fechas.
        # Solo uno de los dos sets de controles es visible a la vez según el tipo.
        self.chk_urgente = QCheckBox("Urgente")
        self.chk_urgente.setStyleSheet(CHECKBOX_STYLE)

        self.chk_recurrente = QCheckBox("Recurrente")
        self.chk_recurrente.setStyleSheet(CHECKBOX_STYLE)

        self.lbl_cada = QLabel("cada")
        self.lbl_cada.setStyleSheet("color: #aaa; font-size: 12px; background: transparent;")

        self.combo_periodicidad = QComboBox()
        self.combo_periodicidad.setFixedHeight(28)
        # (etiqueta_visible, meses_internos) — para no perder el valor numérico al guardar
        for etiqueta, meses in [("1 mes", 1), ("3 meses", 3), ("6 meses", 6),
                                ("12 meses", 12), ("24 meses", 24)]:
            self.combo_periodicidad.addItem(etiqueta, userData=meses)
        # ──── TEMPORAL · PRUEBAS QA ─────────────────────────────────────────
        # Opción que dispara la generación del siguiente evento +1 día en vez
        # de +N meses, para validar el ciclo recurrente en una semana de prueba
        # en lugar de varios meses. db_manager.generar_siguiente_recurrencia()
        # interpreta userData=0 como sentinela "+1 día". Quitar esta línea y el
        # bloque marcado en db_manager.py antes de salir a producción.
        self.combo_periodicidad.addItem("1 día (prueba)", userData=0)
        # ────────────────────────────────────────────────────────────────────
        self.combo_periodicidad.setCurrentText("6 meses")
        self.combo_periodicidad.setStyleSheet("""
            QComboBox {
                background-color: #1e1e1e; color: white;
                border: 1px solid #444; border-radius: 5px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e1e1e; color: white;
                selection-background-color: #0078d7;
                border: 1px solid #444;
            }
        """)

        # Habilitar el combo solo cuando "Recurrente" está marcado
        def on_recurrente_changed(checked):
            self.combo_periodicidad.setEnabled(bool(checked))
        self.chk_recurrente.stateChanged.connect(on_recurrente_changed)
        self.combo_periodicidad.setEnabled(False)

        # Contenedor que reserva siempre la misma altura (evita que la columna
        # derecha "fechas" se desalinee al cambiar de tipo).
        self._slot_tipo_extra = QWidget()
        self._slot_tipo_extra.setFixedHeight(32)
        slot_layout = QHBoxLayout(self._slot_tipo_extra)
        slot_layout.setContentsMargins(0, 0, 0, 0)
        slot_layout.setSpacing(8)
        slot_layout.addWidget(self.chk_urgente)
        slot_layout.addWidget(self.chk_recurrente)
        slot_layout.addWidget(self.lbl_cada)
        slot_layout.addWidget(self.combo_periodicidad)
        slot_layout.addStretch()

        # Arrancan ocultos; on_tipo_changed los acomoda según el tipo seleccionado
        self.chk_urgente.setVisible(False)
        self.chk_recurrente.setVisible(False)
        self.lbl_cada.setVisible(False)
        self.combo_periodicidad.setVisible(False)

        def on_tipo_changed(text):
            es_correctivo = (text == "Correctivo")
            es_preventivo = (text == "Preventivo")

            # --- Correctivo: solo "Urgente" ---
            self.chk_urgente.setVisible(es_correctivo)
            if not es_correctivo:
                self.chk_urgente.setChecked(False)

            # --- Preventivo: "Recurrente cada [combo]" ---
            self.chk_recurrente.setVisible(es_preventivo)
            self.lbl_cada.setVisible(es_preventivo)
            self.combo_periodicidad.setVisible(es_preventivo)
            if not es_preventivo:
                self.chk_recurrente.setChecked(False)
        self.combo_tipo.currentTextChanged.connect(on_tipo_changed)
        # Inicializar slot según el tipo actual (por defecto "Preventivo")
        on_tipo_changed(self.combo_tipo.currentText())

        # ─── Fechas ──────────────────────────────────────────────
        self.date_inicio = QDateEdit()
        self.date_inicio.setFixedHeight(32)
        self.date_inicio.setCalendarPopup(True)
        self.date_inicio.setDate(QDate.currentDate())
 
        self.date_fin = QDateEdit()
        self.date_fin.setFixedHeight(32)
        self.date_fin.setCalendarPopup(True)
        self.date_fin.setDate(QDate.currentDate())
 
        self.chk_un_dia = QCheckBox("Un solo día")
        self.chk_un_dia.setChecked(True)
        self.date_fin.setVisible(False)
        self.chk_un_dia.setStyleSheet(CHECKBOX_STYLE)
 
        def on_un_dia_changed(checked):
            self.date_fin.setVisible(not checked)
            self._actualizar_duracion()
            self._actualizar_estado_boton_guardar()
        self.chk_un_dia.stateChanged.connect(on_un_dia_changed)
        self.date_inicio.dateChanged.connect(self._on_fecha_hora_changed)
        self.date_fin.dateChanged.connect(self._on_fecha_hora_changed)
 
        layout_tipo_fecha = QHBoxLayout()

        # ---- Columna izquierda (tipo + slot urgente/recurrente) ----
        col_tipo = QVBoxLayout()
        col_tipo.addWidget(QLabel("Tipo de mantenimiento:"))
        col_tipo.addWidget(self.combo_tipo)
        col_tipo.addWidget(self._slot_tipo_extra)

        # ---- Columna derecha (fechas) ----
        col_fecha = QVBoxLayout()
        col_fecha.addWidget(QLabel("Fecha:"))
        fila_fechas = QHBoxLayout()
        fila_fechas.addWidget(self.date_inicio)
        fila_fechas.addWidget(self.date_fin)
        col_fecha.addLayout(fila_fechas)
        col_fecha.addWidget(self.chk_un_dia)

        layout_tipo_fecha.addLayout(col_tipo, 1)
        layout_tipo_fecha.addSpacing(30)
        layout_tipo_fecha.addLayout(col_fecha, 1)
        form_layout.addLayout(layout_tipo_fecha)

        # ─── Horario + Costo (QGridLayout) ───────────────────────
        horario_costo_layout = QGridLayout()
        horario_costo_layout.setColumnStretch(0, 0)
        horario_costo_layout.setContentsMargins(0, 0, 0, 0)
        horario_costo_layout.setHorizontalSpacing(20)
        horario_costo_layout.setVerticalSpacing(6)

        # ── Horario: dos QComboBox con horas precargadas cada 30 min ──
        lbl_horario = QLabel("Horario:")
        horario_costo_layout.addWidget(lbl_horario, 0, 0, Qt.AlignmentFlag.AlignLeft)
 
        self.combo_hora_inicio = QComboBox()
        self.combo_hora_fin = QComboBox()
        for h in range(24):
            for m in (0, 30):
                etiqueta = f"{h:02d}:{m:02d}"
                self.combo_hora_inicio.addItem(etiqueta)
                self.combo_hora_fin.addItem(etiqueta)
        self.combo_hora_inicio.setCurrentText("08:00")
        self.combo_hora_fin.setCurrentText("16:00")
        # Estilo + ancho fijo
        for cb in (self.combo_hora_inicio, self.combo_hora_fin):
            cb.setFixedWidth(110)
            cb.setFixedHeight(32)
            cb.setStyleSheet("""
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
            """)
            cb.currentTextChanged.connect(self._on_fecha_hora_changed)
 
        horario_widget = QWidget()
        hw_layout = QHBoxLayout(horario_widget)
        hw_layout.setContentsMargins(0, 0, 0, 0)
        hw_layout.setSpacing(6)
        hw_layout.addWidget(self.combo_hora_inicio)
        hw_layout.addWidget(QLabel("→"))
        hw_layout.addWidget(self.combo_hora_fin)
        horario_costo_layout.addWidget(horario_widget, 1, 0, Qt.AlignmentFlag.AlignLeft)
 
        # Label de duración (debajo del horario, span 2 columnas)
        self.lbl_duracion = QLabel("")
        self.lbl_duracion.setStyleSheet("color: #aaa; font-size: 11px; font-style: italic;")
        horario_costo_layout.addWidget(self.lbl_duracion, 2, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)

        # ── Costo + Moneda ──
        lbl_costo = QLabel("Costo:")
        horario_costo_layout.addWidget(lbl_costo, 0, 1, Qt.AlignmentFlag.AlignLeft)
 
        costo_widget = QWidget()
        cw_layout = QHBoxLayout(costo_widget)
        cw_layout.setContentsMargins(0, 0, 0, 0)
        cw_layout.setSpacing(6)
 
        self.costo_input = QLineEdit()
        self.costo_input.setFixedHeight(32)
        self.costo_input.setPlaceholderText("$0")
        self.costo_input.setMaximumWidth(200)
        self.costo_input.setValidator(QIntValidator(0, 100000000))
        self.costo_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e1e; color: white;
                border: 1px solid #444; border-radius: 5px;
                padding: 4px 8px;
            }
        """)

        def formatear_costo():
            texto = self.costo_input.text().replace("$", "").replace(",", "")
            if texto:
                try:
                    valor = int(texto)
                except ValueError:
                    return
                locale = QLocale(QLocale.Language.Spanish, QLocale.Country.Mexico)
                self.costo_input.blockSignals(True)
                self.costo_input.setText(f"${locale.toString(valor)}")
                self.costo_input.blockSignals(False)
        self.costo_input.textChanged.connect(formatear_costo)
 
        self.combo_moneda = QComboBox()
        self.combo_moneda.addItems(["MXN", "USD"])
        self.combo_moneda.setFixedWidth(75)
        self.combo_moneda.setFixedHeight(32)
        self.combo_moneda.setStyleSheet("""
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
        """)
 
        cw_layout.addWidget(self.costo_input)
        cw_layout.addWidget(self.combo_moneda)
        cw_layout.addStretch()
        horario_costo_layout.addWidget(costo_widget, 1, 1, Qt.AlignmentFlag.AlignLeft)
 
        form_layout.addLayout(horario_costo_layout)

        # ─── Descripción ─────────────────────────────────────────
        form_layout.addWidget(QLabel("Descripción:"))

        # ── Barra de herramientas tipo "mini-Word" ──
        self.toolbar_descripcion = QToolBar()
        self.toolbar_descripcion.setIconSize(QSize(16, 16))
        self.toolbar_descripcion.setStyleSheet("""
            QToolBar {
                background-color: #1e1e1e;
                border: 1px solid #444;
                border-bottom: none;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                padding: 2px;
                spacing: 2px;
            }
            QToolButton {
                color: white;
                background: transparent;
                padding: 4px 8px;
                border-radius: 3px;
                font-weight: bold;
                min-width: 22px;
            }
            QToolButton:hover { background-color: #2e2e2e; }
            QToolButton:checked { background-color: #0078d7; }
        """)

        self._accion_negrita = QAction("B", self)
        self._accion_negrita.setCheckable(True)
        self._accion_negrita.setShortcut("Ctrl+B")
        self._accion_negrita.setToolTip("Negrita (Ctrl+B)")
        # Usamos lambda para encapsular el estado del check
        self._accion_negrita.triggered.connect(
            lambda checked: self.text_descripcion.setFontWeight(700 if checked else 400)
        )
        self.toolbar_descripcion.addAction(self._accion_negrita)

        self._accion_cursiva = QAction("I", self)
        self._accion_cursiva.setCheckable(True)
        self._accion_cursiva.setShortcut("Ctrl+I")
        self._accion_cursiva.setToolTip("Cursiva (Ctrl+I)")
        # Hint: tooltip italic visual
        f_it = self._accion_cursiva.font(); f_it.setItalic(True); self._accion_cursiva.setFont(f_it)
        self._accion_cursiva.triggered.connect(
            lambda checked: self.text_descripcion.setFontItalic(checked)
        )
        self.toolbar_descripcion.addAction(self._accion_cursiva)

        self._accion_subrayado = QAction("U", self)
        self._accion_subrayado.setCheckable(True)
        self._accion_subrayado.setShortcut("Ctrl+U")
        self._accion_subrayado.setToolTip("Subrayado (Ctrl+U)")
        f_un = self._accion_subrayado.font(); f_un.setUnderline(True); self._accion_subrayado.setFont(f_un)
        self._accion_subrayado.triggered.connect(
            lambda checked: self.text_descripcion.setFontUnderline(checked)
        )
        self.toolbar_descripcion.addAction(self._accion_subrayado)

        self.toolbar_descripcion.addSeparator()

        accion_viñetas = QAction("•", self)
        accion_viñetas.setToolTip("Lista con viñetas")
        accion_viñetas.triggered.connect(lambda: self._insertar_lista(QTextListFormat.Style.ListDisc))
        self.toolbar_descripcion.addAction(accion_viñetas)

        accion_numerada = QAction("1.", self)
        accion_numerada.setToolTip("Lista numerada")
        accion_numerada.triggered.connect(lambda: self._insertar_lista(QTextListFormat.Style.ListDecimal))
        self.toolbar_descripcion.addAction(accion_numerada)

        self.toolbar_descripcion.addSeparator()

        # Combo de interlineado: 100 / 150 / 200 son porcentajes Qt
        self._combo_interlineado = QComboBox()
        self._combo_interlineado.setFixedHeight(24)
        self._combo_interlineado.setToolTip("Interlineado")
        self._combo_interlineado.addItem("Interlineado 1.0", 100)
        self._combo_interlineado.addItem("Interlineado 1.5", 150)
        self._combo_interlineado.addItem("Interlineado 2.0", 200)
        self._combo_interlineado.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a; color: white;
                border: 1px solid #555; border-radius: 3px;
                padding: 2px 6px; font-size: 11px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e1e1e; color: white;
                selection-background-color: #0078d7;
                border: 1px solid #444;
            }
        """)
        self._combo_interlineado.currentIndexChanged.connect(self._aplicar_interlineado)
        self.toolbar_descripcion.addWidget(self._combo_interlineado)

        form_layout.addWidget(self.toolbar_descripcion)

        self.text_descripcion = QTextEdit()
        self.text_descripcion.setPlaceholderText("Descripción del mantenimiento...")
        self.text_descripcion.setFixedHeight(150)
        self.text_descripcion.setAcceptRichText(True)
        # Refresca el estado de los botones según la posición del cursor
        self.text_descripcion.cursorPositionChanged.connect(self._sincronizar_botones_formato)
        self.text_descripcion.currentCharFormatChanged.connect(self._sincronizar_botones_formato)
        self.text_descripcion.textChanged.connect(self._actualizar_estado_boton_guardar)
        # Estilo: el QTextEdit pega arriba con la toolbar (sin gap)
        self.text_descripcion.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e; color: white;
                border: 1px solid #444; border-top: none;
                border-bottom-left-radius: 5px;
                border-bottom-right-radius: 5px;
                padding: 8px 10px;
            }
        """)
        form_layout.addWidget(self.text_descripcion)
        
        main_layout.addLayout(form_layout)
        main_layout.addStretch()

        # ─── Footer: responsable + botón Guardar ─────────────────
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        # --- Sección de personal ---
        self.btn_lista_personal = QPushButton()
        try:
            icono = QIcon("icons/person.png")
            self.btn_lista_personal.setIcon(icono)
        except Exception:
            pass
        self.btn_lista_personal.setIconSize(QSize(22, 22))
        self.btn_lista_personal.setFixedSize(40, 40)
        self.btn_lista_personal.setEnabled(False)
        self.btn_lista_personal.setStyleSheet("""
            QPushButton {
                background-color: #0078d7;
                border-radius: 20px;
            }
            QPushButton:disabled { background-color: #444; }
            QPushButton:enabled:hover { background-color: #0094ff; }
        """)
        self.btn_lista_personal.clicked.connect(self.mostrar_lista_personal)

        # Label de responsable
        self.lbl_responsable = QLabel("")
        self.lbl_responsable.setFixedHeight(40)
        self.lbl_responsable.setMinimumWidth(260)
        self.lbl_responsable.setEnabled(False)
        self._style_responsable_off = """
            QLabel {
                background-color: #2a2a2a;
                border-radius: 6px;
                border: 1px dashed #555;
            }
        """
        self._style_responsable_on = """
            QLabel {
                background-color: #606060;
                border-radius: 6px;
                border: 1px solid #4fa3ff;
                padding-left: 10px; padding-right: 10px;
                color: white; font-weight: bold;
            }
        """
        self.lbl_responsable.setStyleSheet(self._style_responsable_off)

        footer_layout.addWidget(self.btn_lista_personal)
        footer_layout.addWidget(self.lbl_responsable)
        footer_layout.addStretch()

        # Botón Cancelar (solo visible en modo edición). Va a la izquierda
        # del botón principal. En modo creación queda oculto.
        self.btn_cancelar_edicion = QPushButton("Cancelar")
        self.btn_cancelar_edicion.setFixedHeight(40)
        self.btn_cancelar_edicion.setVisible(False)
        self.btn_cancelar_edicion.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a; color: white;
                border-radius: 8px;
                padding: 0 24px;
            }
            QPushButton:hover { background-color: #505050; }
        """)
        self.btn_cancelar_edicion.clicked.connect(self._on_cancelar_edicion)
        footer_layout.addWidget(self.btn_cancelar_edicion)

        # Botón Guardar (deshabilitado por defecto)
        self.btn_guardar = QPushButton("Guardar")
        self.btn_guardar.setFixedHeight(40)
        self.btn_guardar.setEnabled(False)
        self.btn_guardar.setStyleSheet("""
            QPushButton {
                background-color: #0078d7; color: white;
                border-radius: 8px; font-weight: bold;
                padding: 0 24px;
            }
            QPushButton:hover { background-color: #0094ff; }
            QPushButton:disabled {
                background-color: #2a4055; color: #777;
            }
        """)
        self.btn_guardar.clicked.connect(self.guardar_mantenimiento)
        footer_layout.addWidget(self.btn_guardar)

        main_layout.addLayout(footer_layout)

        # Estado inicial
        self.cargar_tipos_equipos()
        self.actualizar_estado_boton_lista_personal()
        self._actualizar_duracion()
        self.setLayout(main_layout)

    def _aplicar_estilo_btn_elegir(self, activo: bool):
        """Estilo del botón Elegir equipo según esté habilitado o no."""
        if activo:
            self.btn_elegir_equipo.setStyleSheet("""
                QPushButton {
                    background-color: #0078d7; color: white;
                    border-radius: 6px; font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover { background-color: #0094ff; }
            """)
        else:
            self.btn_elegir_equipo.setStyleSheet("""
                QPushButton {
                    background-color: #2a4055; color: #777;
                    border-radius: 6px; font-weight: bold;
                    padding: 6px 12px;
                }
            """)
 
    def _aplicar_estilo_btn_elegir_con_seleccion(self):
        """Verde una vez que ya hay equipos seleccionados."""
        self.btn_elegir_equipo.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32; color: white;
                font-weight: bold; border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #388e3c; }
        """)

    # ============================================================
    #  Recarga al entrar a la pestaña
    # ============================================================
    def showEvent(self, event):
        super().showEvent(event)
        self.cargar_tipos_equipos()
        self.actualizar_estado_boton_lista_personal()

    # ============================================================
    #  Combo de tipo de equipo
    # ============================================================
    def cargar_tipos_equipos(self):
        """Llena el combo solo con los tipos que tienen al menos un equipo en BD."""
        self.combo_equipo.blockSignals(True)  # ⛔ Bloquea señales
        self.combo_equipo.clear()
        self.combo_equipo.addItem("Seleccionar equipo o tablero", userData=None)

        tableros = obtener_datos("tableros")
        transformadores = obtener_datos("transformadores")

        if tableros:
            self.combo_equipo.addItem("Tableros", userData="tableros")
        if transformadores:
            self.combo_equipo.addItem("Transformadores", userData="transformadores")

        self.combo_equipo.blockSignals(False)  # ✅ Reactiva señales
        # Forzar re-evaluación del estado del botón
        self.on_tipo_equipo_changed(self.combo_equipo.currentIndex())

    def on_tipo_equipo_changed(self, _index):
        """Habilita/deshabilita el botón Elegir equipo según el combo, y resetea selección."""
        tipo_db = self.combo_equipo.currentData()
        if tipo_db is None:
            # Placeholder seleccionado
            self.btn_elegir_equipo.setEnabled(False)
            self._aplicar_estilo_btn_elegir(activo=False)
            self.btn_elegir_equipo.setText("Elegir equipo")
        else:
            self.btn_elegir_equipo.setEnabled(True)
            # Si veníamos de otro tipo y había equipos seleccionados, los reseteamos
            self._resetear_equipos_seleccionados(actualizar_estilo=True)
        self._actualizar_estado_boton_guardar()
 
    def _resetear_equipos_seleccionados(self, actualizar_estilo: bool = True):
        self.equipos_seleccionados = []
        if actualizar_estilo:
            self.btn_elegir_equipo.setText("Elegir equipo")
            if self.btn_elegir_equipo.isEnabled():
                self._aplicar_estilo_btn_elegir(activo=True)
            else:
                self._aplicar_estilo_btn_elegir(activo=False)
        self._actualizar_estado_boton_guardar()

    # ============================================================
    #  Botón Elegir equipo (abre selector múltiple)
    # ============================================================
    def abrir_selector_equipo(self):
        tipo_db = self.combo_equipo.currentData()
        if not tipo_db:
            return

        # Recuperar estado guardado en disco (ui_state.json) y los equipos
        # ya seleccionados, para que el diálogo arranque tal cual quedó la
        # última vez aunque el programa se haya cerrado y vuelto a abrir.
        from ui_state import obtener_valor, guardar_valor
        clave_contraidos = f"selector_grupos_contraidos_{tipo_db}"
        grupos_contraidos = set(obtener_valor(clave_contraidos, []))
        preseleccion = [e for e in self.equipos_seleccionados if e.get("tipo") == tipo_db]

        dialog = SelectorEquipoDialog(
            tipo_db, parent=self,
            grupos_contraidos=grupos_contraidos,
            equipos_preseleccionados=preseleccion,
        )
        resultado = dialog.exec()

        # Guardar el estado de colapso siempre (acepte o cancele): así si el
        # usuario contrae grupos y cancela, esa preferencia visual se conserva.
        guardar_valor(clave_contraidos, sorted(list(dialog.obtener_grupos_contraidos())))

        if resultado:
            self.equipos_seleccionados = dialog.equipos_seleccionados
            n = len(self.equipos_seleccionados)
            if n == 0:
                self.btn_elegir_equipo.setText("Elegir equipo")
                self._aplicar_estilo_btn_elegir(activo=True)
            elif n == 1:
                self.btn_elegir_equipo.setText(f"1 equipo: {self.equipos_seleccionados[0]['id']}")
                self._aplicar_estilo_btn_elegir_con_seleccion()
            else:
                self.btn_elegir_equipo.setText(f"{n} equipos seleccionados")
                self._aplicar_estilo_btn_elegir_con_seleccion()
            self._actualizar_estado_boton_guardar()

    # ============================================================
    #  Personal / Proveedor
    # ============================================================
    def actualizar_estado_boton_lista_personal(self):
        """Habilita el botón de lista de personal si hay datos en BD."""
        hay_personal = ejecutar_query("SELECT 1 FROM personal LIMIT 1")
        hay_proveedores = ejecutar_query("SELECT 1 FROM proveedores LIMIT 1")
        hay_datos = bool(hay_personal) or bool(hay_proveedores)
        self.btn_lista_personal.setEnabled(hay_datos)

    def mostrar_lista_personal(self):
        self.dialogo_responsables = ListaResponsablesDialog(self)
        self.dialogo_responsables.responsable_asignado.connect(self.mostrar_responsable_asignado)
        self.dialogo_responsables.exec()

        self.actualizar_estado_boton_lista_personal()

    def mostrar_responsable_asignado(self, data):
        self.responsable_actual = data
        # Caso: se quitó el responsable
        if not data.get("tipo"):
            self.lbl_responsable.setText("")
            self.lbl_responsable.setEnabled(False)
            self.lbl_responsable.setStyleSheet(self._style_responsable_off)
            self._actualizar_estado_boton_guardar()
            return

        emojis = {
            "personal": "👤",
            "proveedor": "🏢",
            # más tipos futuros aquí
        }

        # Obtener emoji según tipo, si no existe usar vacío
        icono = emojis.get(data['tipo'].lower(), "")
        self.lbl_responsable.setText(f"{data['nombre']} {icono}")
        self.lbl_responsable.setEnabled(True)
        self.lbl_responsable.setStyleSheet(self._style_responsable_on)
        self._actualizar_estado_boton_guardar()

    # ============================================================
    #  Cálculo de dt_inicio / dt_fin y duración
    # ============================================================
    def _calcular_datetimes(self):
        """
        Devuelve (dt_inicio, dt_fin, error_str_o_None).
        error_str es no-vacío si la combinación es inválida.
        """
        try:
            fecha_inicio = self.date_inicio.date().toPyDate()
            h_ini_txt = self.combo_hora_inicio.currentText()
            h_fin_txt = self.combo_hora_fin.currentText()
            h, m = map(int, h_ini_txt.split(":"))
            hora_inicio = dtime(h, m)
            h, m = map(int, h_fin_txt.split(":"))
            hora_fin = dtime(h, m)
 
            dt_inicio = datetime.combine(fecha_inicio, hora_inicio)
 
            if self.chk_un_dia.isChecked():
                dt_fin = datetime.combine(fecha_inicio, hora_fin)
                # Si fin <= inicio, cruza al día siguiente
                if dt_fin <= dt_inicio:
                    dt_fin += timedelta(days=1)
            else:
                fecha_fin = self.date_fin.date().toPyDate()
                dt_fin = datetime.combine(fecha_fin, hora_fin)
 
            if dt_fin <= dt_inicio:
                return dt_inicio, dt_fin, "La fecha/hora de fin debe ser posterior a la de inicio."
 
            return dt_inicio, dt_fin, None
        except Exception as e:
            return None, None, f"Error al calcular fechas: {e}"
        
    def _formato_duracion(self, dt_inicio, dt_fin):
        """'1 día 4 h 30 min', '8 h', '45 min', etc."""
        delta = dt_fin - dt_inicio
        total_min = int(delta.total_seconds() // 60)
        if total_min <= 0:
            return ""
        dias, resto = divmod(total_min, 24 * 60)
        horas, minutos = divmod(resto, 60)
        partes = []
        if dias:    partes.append(f"{dias} día{'s' if dias != 1 else ''}")
        if horas:   partes.append(f"{horas} h")
        if minutos: partes.append(f"{minutos} min")
        return " ".join(partes) if partes else "0 min"
 
    def _on_fecha_hora_changed(self, *_):
        self._actualizar_duracion()
        self._actualizar_estado_boton_guardar()
 
    def _actualizar_duracion(self):
        dt_inicio, dt_fin, error = self._calcular_datetimes()
        if error:
            self.lbl_duracion.setText(f"⚠ {error}")
            self.lbl_duracion.setStyleSheet("color: #e84747; font-size: 11px; font-style: italic;")
            return
        # Aviso especial cuando el "mismo día" cruzó medianoche
        cruzo_medianoche = (self.chk_un_dia.isChecked()
                            and dt_inicio.date() != dt_fin.date())
        texto = f"Duración: {self._formato_duracion(dt_inicio, dt_fin)}"
        if cruzo_medianoche:
            texto += "  (cruza al día siguiente)"
        self.lbl_duracion.setText(texto)
        self.lbl_duracion.setStyleSheet("color: #aaa; font-size: 11px; font-style: italic;")

    # ============================================================
    #  Estado del botón Guardar (validación en vivo)
    # ============================================================
    def _actualizar_estado_boton_guardar(self):
        """Habilita Guardar sólo cuando todos los campos requeridos son válidos."""
        if not hasattr(self, "btn_guardar"):
            return  # llamada anticipada antes de construir el footer
 
        # 1) Equipos
        if not self.equipos_seleccionados:
            self.btn_guardar.setEnabled(False)
            return
 
        # 2) Responsable
        if not self.responsable_actual or not self.responsable_actual.get("tipo"):
            self.btn_guardar.setEnabled(False)
            return
 
        # 3) Descripción
        if not self.text_descripcion.toPlainText().strip():
            self.btn_guardar.setEnabled(False)
            return
 
        # 4) Fechas válidas
        _, _, error = self._calcular_datetimes()
        if error:
            self.btn_guardar.setEnabled(False)
            return
 
        self.btn_guardar.setEnabled(True)
    
    # ============================================================
    #  Guardar mantenimiento
    # ============================================================
    # ============================================================
    #  Modo edición (cargar + actualizar + cancelar + modal helper)
    # ============================================================
    def _cargar_para_edicion(self):
        """
        Llena el formulario con los datos del mantenimiento existente y
        deja la UI en modo edición: cambia el título y el botón, muestra
        Cancelar, y deshabilita los campos no editables (equipos, fechas,
        horarios). Para cambiar esos campos el usuario debe usar
        Reprogramar (fechas/horario) o Cancelar + crear uno nuevo (equipos).
        """
        # 1) SELECT del mantenimiento
        filas = ejecutar_query("""
            SELECT tipo_mantenimiento, urgente, fecha_inicio, fecha_fin,
                   costo, costo_moneda, descripcion,
                   responsable_tipo, responsable_id, responsable_nombre,
                   responsable_correo, responsable_telefono,
                   es_recurrente, recurrencia_meses
            FROM mantenimientos
            WHERE id = ?
        """, (self.mantenimiento_id_edicion,))
        if not filas:
            QMessageBox.critical(self, "Error",
                f"No se pudo cargar el mantenimiento #{self.mantenimiento_id_edicion}")
            return
        (tipo, urgente, fi_str, ff_str, costo, costo_moneda, descripcion,
         resp_tipo, resp_id, resp_nombre, resp_correo, resp_tel,
         es_recurrente, recurrencia_meses) = filas[0]

        # 2) SELECT de equipos relacionados (informativo, no editables)
        equipos_rows = ejecutar_query("""
            SELECT equipo_id, equipo_tipo
            FROM mantenimientos_equipos
            WHERE mantenimiento_id = ?
        """, (self.mantenimiento_id_edicion,))
        self.equipos_seleccionados = [
            {"id": eid, "tipo": etipo} for (eid, etipo) in equipos_rows
        ]

        # 3) Precargar widgets editables
        # Tipo (primero, porque on_tipo_changed maneja la visibilidad del
        # slot extra: chk_urgente para Correctivo, chk_recurrente+combo para
        # Preventivo, nada para Predictivo).
        idx = self.combo_tipo.findText(tipo or "Preventivo")
        if idx >= 0:
            self.combo_tipo.setCurrentIndex(idx)
        # Urgente (solo aplica visualmente si es Correctivo, pero el valor
        # se preserva en BD aunque el tipo sea otro).
        self.chk_urgente.setChecked(bool(urgente))
        # Recurrencia (solo aplica visualmente si es Preventivo).
        self.chk_recurrente.setChecked(bool(es_recurrente))
        if recurrencia_meses:
            idx_per = self.combo_periodicidad.findData(int(recurrencia_meses))
            if idx_per >= 0:
                self.combo_periodicidad.setCurrentIndex(idx_per)
        # Costo + moneda
        self.costo_input.setText(str(costo) if costo else "")
        idx = self.combo_moneda.findText(costo_moneda or "MXN")
        if idx >= 0:
            self.combo_moneda.setCurrentIndex(idx)
        # Descripción: HTML auto-detectado (mismo criterio que la ficha)
        if descripcion:
            if "<" in descripcion and ">" in descripcion:
                self.text_descripcion.setHtml(descripcion)
            else:
                self.text_descripcion.setPlainText(descripcion)
        # Responsable (snapshot plano)
        self.responsable_actual = {
            "tipo":     resp_tipo,
            "id":       resp_id,
            "nombre":   resp_nombre,
            "correo":   resp_correo or "",
            "telefono": resp_tel or "",
        }
        if resp_nombre:
            emojis = {"personal": "👤", "proveedor": "🏢"}
            icono = emojis.get((resp_tipo or "").lower(), "")
            self.lbl_responsable.setText(f"{resp_nombre} {icono}".strip())
            self.lbl_responsable.setEnabled(True)
            self.lbl_responsable.setStyleSheet(self._style_responsable_on)

        # 4) Precargar fechas y horarios (informativo, se deshabilitan)
        try:
            dt_ini = datetime.strptime(fi_str, "%Y-%m-%d %H:%M")
            dt_fin = datetime.strptime(ff_str, "%Y-%m-%d %H:%M")
            self.date_inicio.setDate(QDate(dt_ini.year, dt_ini.month, dt_ini.day))
            self.date_fin.setDate(QDate(dt_fin.year, dt_fin.month, dt_fin.day))
            # Snap a 30 min
            m_ini = 30 if dt_ini.minute >= 30 else 0
            m_fin = 30 if dt_fin.minute >= 30 else 0
            self.combo_hora_inicio.setCurrentText(f"{dt_ini.hour:02d}:{m_ini:02d}")
            self.combo_hora_fin.setCurrentText(f"{dt_fin.hour:02d}:{m_fin:02d}")
            es_un_dia = (dt_ini.date() == dt_fin.date())
            self.chk_un_dia.setChecked(es_un_dia)
            self.date_fin.setVisible(not es_un_dia)
        except Exception as e:
            print(f"[Editar] Error precargando fechas: {e}")

        # 5) Resumen de equipos en btn_elegir_equipo
        n = len(self.equipos_seleccionados)
        if n == 1:
            self.btn_elegir_equipo.setText(
                f"1 equipo: {self.equipos_seleccionados[0]['id']}"
            )
        elif n > 1:
            self.btn_elegir_equipo.setText(f"{n} equipos seleccionados")

        # 6) Cosmética del modo edición — actualizamos las 3 piezas del
        #    header (ícono, título, subtítulo) para que el usuario sepa
        #    de un vistazo que está modificando, no creando.
        self._icono_header_label.setPixmap(
            qta.icon("fa5s.edit", color="#ddd").pixmap(22, 22)
        )
        self._titulo_label.setText(
            f"Editar mantenimiento #{self.mantenimiento_id_edicion}"
        )
        self._subtitulo_label.setText(
            "Modifica los datos. Los cambios reemplazarán los existentes."
        )
        self.btn_guardar.setText("Actualizar")
        self.btn_cancelar_edicion.setVisible(True)

        # 7) Deshabilitar + atenuar visualmente los campos no editables
        self._deshabilitar_no_editables()

    def _deshabilitar_no_editables(self):
        """
        Bloquea los campos que no se pueden tocar desde Editar.

        IMPORTANTE: aquí NO usamos QGraphicsOpacityEffect aunque sería
        la forma más obvia de atenuar visualmente. Ese effect cambia el
        modo de compositing del widget (lo renderiza vía QGraphicsScene
        con alpha layer) y en PyQt6 ese compositing se propaga a los
        QDialogs hijos que se renderizan sobre el form (p. ej.
        ListaResponsablesDialog cuando abrís 'Lista de personal' desde
        modo edición). El resultado es que TODA la ventana hija se ve
        atenuada/grisácea, como si tuviera un hover permanente. Por eso
        nos quedamos solo con setEnabled(False); Qt aplica su look
        :disabled propio sin tocar el compositing.
        """
        no_editables = [
            self.combo_equipo,
            self.btn_elegir_equipo,
            self.date_inicio,
            self.date_fin,
            self.chk_un_dia,
            self.combo_hora_inicio,
            self.combo_hora_fin,
        ]
        for w in no_editables:
            w.setEnabled(False)

        # Reemplazar el label de duración por aviso sobre cómo cambiar
        # fechas/equipos en modo edición.
        self.lbl_duracion.setText(
            "ℹ Para cambiar fechas u horario usa Reprogramar · "
            "Para cambiar equipos cancela el mantenimiento"
        )
        self.lbl_duracion.setStyleSheet(
            "color: #888; font-size: 11px; font-style: italic;"
        )

    def _actualizar_mantenimiento_editable(self):
        """
        UPDATE de los campos editables: tipo, urgente, costo + moneda,
        descripción y responsable. NO toca fechas, equipos, estado,
        creado_en, ni sincronización con Google Calendar.
        """
        # Validaciones (las de equipos/fechas no aplican: están precargadas)
        if not self.responsable_actual or not self.responsable_actual.get("tipo"):
            QMessageBox.warning(self, "Falta responsable", "Debes asignar un responsable.")
            return
        descripcion = self.text_descripcion.toPlainText().strip()
        if not descripcion:
            QMessageBox.warning(self, "Falta descripción", "Agrega una descripción.")
            return

        # Costo
        texto_costo = self.costo_input.text()
        costo = int(re.sub(r"[^\d]", "", texto_costo)) if texto_costo else 0
        moneda = self.combo_moneda.currentText()

        responsable = self.responsable_actual

        # UPDATE directo. Mismo estilo que el INSERT de la tabla puente del
        # flujo normal: SQL específico vive aquí, donde está el formulario.
        try:
            conn = connect_db()
            if conn is None:
                QMessageBox.critical(self, "Error", "No se pudo conectar a la BD.")
                return
            # Recurrencia: misma lógica que en INSERT — solo se persiste si el
            # tipo es Preventivo y el usuario marcó "Recurrente". Cualquier
            # otro caso deja es_recurrente=0 / recurrencia_meses=NULL, lo cual
            # detiene el ciclo (si lo había) sin destruir el historial.
            tipo_seleccionado = self.combo_tipo.currentText()
            es_recurrente = 1 if (tipo_seleccionado == "Preventivo"
                                  and self.chk_recurrente.isChecked()) else 0
            recurrencia_meses = (self.combo_periodicidad.currentData()
                                 if es_recurrente else None)

            conn.execute("""
                UPDATE mantenimientos SET
                    tipo_mantenimiento   = ?,
                    urgente              = ?,
                    costo                = ?,
                    costo_moneda         = ?,
                    descripcion          = ?,
                    responsable_tipo     = ?,
                    responsable_id       = ?,
                    responsable_nombre   = ?,
                    responsable_correo   = ?,
                    responsable_telefono = ?,
                    es_recurrente        = ?,
                    recurrencia_meses    = ?
                WHERE id = ?
            """, (
                tipo_seleccionado,
                int(self.chk_urgente.isChecked()),
                costo,
                moneda,
                descripcion,
                responsable["tipo"],
                responsable["id"],
                responsable["nombre"],
                responsable.get("correo") or "",
                responsable.get("telefono") or "",
                es_recurrente,
                recurrencia_meses,
                self.mantenimiento_id_edicion,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            QMessageBox.critical(self, "Error al actualizar",
                f"No se pudo actualizar el mantenimiento:\n{e}")
            return

        # Notificar a la app: refresca pestañas + cierra el modal padre
        app_signals.mantenimiento_guardado.emit()
        QMessageBox.information(self, "Actualizado",
            "✅ Mantenimiento actualizado correctamente.")
        self.mantenimiento_actualizado.emit()

    def _on_cancelar_edicion(self):
        """Cierra el modal sin guardar cambios."""
        self.edicion_cancelada.emit()

    @staticmethod
    def editar_modal(parent, mantenimiento_id):
        """
        Abre el formulario en modo edición como diálogo modal sobre `parent`.
        Devuelve True si el usuario guardó cambios, False si canceló o
        cerró el modal con la X de la ventana.

        Sin styleSheet propio: hereda el estilo global de MantenimientosWindow,
        que ya define los colores oscuros para todos los QWidget descendientes.
        """
        dlg = QDialog(parent)
        dlg.setWindowTitle(f"Editar mantenimiento #{mantenimiento_id}")
        dlg.setModal(True)
        dlg.resize(900, 720)

        form = ProgramarNuevoWidget(
            modo_edicion=True,
            mantenimiento_id=mantenimiento_id,
            parent=dlg,
        )
        form.mantenimiento_actualizado.connect(dlg.accept)
        form.edicion_cancelada.connect(dlg.reject)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(form)

        return dlg.exec() == QDialog.DialogCode.Accepted

    def guardar_mantenimiento(self):
        # En modo edición, redirigir al flujo UPDATE y salir
        if self.modo_edicion:
            self._actualizar_mantenimiento_editable()
            return

        # ---------------- VALIDACIONES ----------------
        if not self.equipos_seleccionados:
            QMessageBox.warning(self, "Falta equipo", "Debes seleccionar al menos un equipo.")
            return

        if not self.responsable_actual or not self.responsable_actual.get("tipo"):
            QMessageBox.warning(self, "Falta responsable", "Debes asignar un responsable.")
            return

        descripcion = self.text_descripcion.toPlainText().strip()
        if not descripcion:
            QMessageBox.warning(self, "Falta descripción", "Agrega una descripción.")
            return

        # ---------------- FECHAS Y HORAS ----------------
        dt_inicio, dt_fin, error = self._calcular_datetimes()
        if error:
            QMessageBox.warning(self, "Fechas inválidas", error)
            return
 
        fecha_inicio_iso = dt_inicio.strftime("%Y-%m-%d %H:%M")
        fecha_fin_iso = dt_fin.strftime("%Y-%m-%d %H:%M")

        # ---------------- COSTO ----------------
        texto_costo = self.costo_input.text()
        costo = int(re.sub(r"[^\d]", "", texto_costo)) if texto_costo else 0
        moneda = self.combo_moneda.currentText()

        # ---------------- RESPONSABLE ----------------
        responsable = self.responsable_actual  # debe venir del diálogo

        # ---------------- RECURRENCIA (solo aplica a Preventivos) ----------------
        # Si el usuario marcó "Recurrente" y el tipo es Preventivo, guardamos el
        # período en meses. db_manager.cerrar_mantenimiento_pendiente() detecta
        # es_recurrente=1 al cerrar y genera la siguiente instancia. El campo
        # dias_aviso_responsable queda fijo en 7 por ahora; se expondrá en
        # Configuración → Alertas en la fase 2 (Notificaciones).
        tipo_seleccionado = self.combo_tipo.currentText()
        es_recurrente = 1 if (tipo_seleccionado == "Preventivo"
                              and self.chk_recurrente.isChecked()) else 0
        recurrencia_meses = (self.combo_periodicidad.currentData()
                             if es_recurrente else None)

        # ---------------- DICCIONARIO FINAL ----------------
        datos_mantenimiento = {
            "tipo_mantenimiento":     tipo_seleccionado,
            "urgente":                int(self.chk_urgente.isChecked()),
            "fecha_inicio":           fecha_inicio_iso,
            "fecha_fin":              fecha_fin_iso,
            "costo":                  costo,
            "costo_moneda":           moneda,
            "descripcion":            descripcion,
            "responsable_tipo":       responsable["tipo"],
            "responsable_id":         responsable["id"],
            "responsable_nombre":     responsable["nombre"],
            "responsable_correo":     responsable.get("correo") or "",
            "responsable_telefono":   responsable.get("telefono") or "",
            "estado":                 "programado",
            "es_recurrente":          es_recurrente,
            "recurrencia_meses":      recurrencia_meses,
            "dias_aviso_responsable": 7,
            "creado_en":              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # ---------------- INSERT REAL A BD ----------------
        try:
            mantenimiento_id = insertar_datos("mantenimientos", datos_mantenimiento)
 
            # Inserción atómica de la tabla puente
            conn = connect_db(create_if_missing=True)
            cur = conn.cursor()
            for eq in self.equipos_seleccionados:
                cur.execute("""
                    INSERT INTO mantenimientos_equipos (mantenimiento_id, equipo_id, equipo_tipo)
                    VALUES (?, ?, ?)
                """, (mantenimiento_id, eq["id"], eq["tipo"]))
            conn.commit()
            conn.close()
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar el mantenimiento:\n{e}")
            return

        # ---------------- GOOGLE CALENDAR (INTENTO) ----------------
        try:
            from services.google_calendar_service import GoogleCalendarService
            calendar = GoogleCalendarService()
            # Pasamos también la lista de equipos para que aparezca en el evento
            datos_para_calendar = dict(datos_mantenimiento)
            datos_para_calendar["equipos"] = self.equipos_seleccionados
            resultado = calendar.crear_evento(datos_para_calendar)
 
            if resultado.get("ok"):
                ejecutar_query("""
                    UPDATE mantenimientos
                    SET google_event_id = ?,
                        calendar_sync = 1,
                        calendar_last_sync = ?
                    WHERE id = ?
                """, (resultado["event_id"],
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      mantenimiento_id))
            else:
                ejecutar_query("""
                    UPDATE mantenimientos
                    SET calendar_sync = 0,
                        calendar_last_error = ?,
                        calendar_last_sync = ?
                    WHERE id = ?
                """, (resultado.get("error", "Error desconocido"),
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      mantenimiento_id))
                QMessageBox.warning(
                    self, "Sincronización incompleta",
                    "⚠️ El mantenimiento se guardó correctamente, pero no se pudo "
                    "sincronizar con Google Calendar."
                )
        except ImportError:
            pass  # Servicio no disponible en este entorno
        except Exception as e:
            print(f"[Google Calendar] Error no fatal: {e}")

        # ────────────────── SEÑAL + UI ─────────────────────
        app_signals.mantenimiento_guardado.emit()
        QMessageBox.information(self, "Guardado", f"✅ Mantenimiento programado correctamente.")
        self.limpiar_formulario()

    # ============================================================
    #  Limpiar formulario
    # ============================================================
    # ============================================================
    #  Helpers de la toolbar de descripción
    # ============================================================
    def _insertar_lista(self, estilo):
        """Crea (o cambia) la lista del bloque actual con el estilo dado."""
        cursor = self.text_descripcion.textCursor()
        fmt = QTextListFormat()
        fmt.setStyle(estilo)
        cursor.createList(fmt)
        self.text_descripcion.setFocus()
 
    def _aplicar_interlineado(self, _index):
        """Aplica el interlineado seleccionado al bloque actual / selección."""
        porcentaje = self._combo_interlineado.currentData()
        if porcentaje is None:
            return
        cursor = self.text_descripcion.textCursor()
        block_fmt = QTextBlockFormat()
        # ProportionalHeight = porcentaje (100 = simple, 150 = 1.5, 200 = doble)
        block_fmt.setLineHeight(porcentaje, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_fmt)
        self.text_descripcion.setFocus()
 
    def _sincronizar_botones_formato(self, *_):
        """Mantiene marcados los botones B/I/U según el formato bajo el cursor."""
        if not hasattr(self, "_accion_negrita"):
            return
        fmt = self.text_descripcion.currentCharFormat()
        for accion, getter in (
            (self._accion_negrita,   lambda: fmt.fontWeight() >= 700),
            (self._accion_cursiva,   lambda: fmt.fontItalic()),
            (self._accion_subrayado, lambda: fmt.fontUnderline()),
        ):
            accion.blockSignals(True)
            accion.setChecked(getter())
            accion.blockSignals(False)
 
    def limpiar_formulario(self):
        # -------- Equipo y tipo --------
        self.combo_equipo.setCurrentIndex(0)
        self.combo_tipo.setCurrentIndex(0)

        # -------- Descripción --------
        self.text_descripcion.clear()

        # -------- Fechas --------
        hoy = QDate.currentDate()
        self.date_inicio.setDate(hoy)
        self.date_fin.setDate(hoy)

        # -------- Horarios --------
        self.combo_hora_inicio.setCurrentText("08:00")
        self.combo_hora_fin.setCurrentText("16:00")

        # -------- Checkboxes --------
        self.chk_un_dia.setChecked(True)
        self.chk_urgente.setChecked(False)
        self.chk_recurrente.setChecked(False)
        self.combo_periodicidad.setCurrentText("6 meses")

        # -------- Costo --------
        self.costo_input.clear()
        self.combo_moneda.setCurrentIndex(0)

        # -------- Responsable --------
        self.responsable_actual = None
        self.lbl_responsable.setText("")
        self.lbl_responsable.setEnabled(False)
        self.lbl_responsable.setStyleSheet(self._style_responsable_off)
 
        self._resetear_equipos_seleccionados(actualizar_estilo=True)
        self._actualizar_duracion()
        self._actualizar_estado_boton_guardar()