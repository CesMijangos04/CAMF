# dialogs_mantenimiento.py
"""
Sub-diálogos del módulo Mantenimientos.

Aquí viven los diálogos accesorios que emergen desde la ficha
(ficha_mantenimiento.py) para acciones puntuales del footer:

    - DialogReprogramar          (estados Programado / Pendiente cierre / Cancelado)
    - (futuro) DialogCerrarMantenimiento  (estado Pendiente cierre)
    - (futuro) DialogCerrarCancelado      (estado Cancelado, captura motivo)

Todos comparten el mismo lenguaje visual: frameless con titlebar custom
mini, fondo oscuro con border-radius 10px, footer con botón primario
azul + cancelar gris. Coherente con la ficha pero deliberadamente más
simple — no llevan header coloreado por estado, sidebar, etc.
"""
from datetime import datetime, timedelta, time as dtime
import os

from PyQt6.QtCore import Qt, QDate, QLocale, pyqtSignal
from PyQt6.QtGui import QIntValidator, QDoubleValidator
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QDateEdit, QComboBox, QCheckBox, QFrame, QWidget,
    QFileDialog, QLineEdit, QTextEdit, QScrollArea, QSizePolicy
)
import qtawesome as qta


# ── Widgets de captura (extraídos del refactor de organización) ─────────
# Las secciones "Cambios al equipo" (tableros) y "Pruebas del transformador"
# viven en módulos propios para mantener este archivo por debajo del umbral
# de legibilidad. La API pública que consume DialogCerrarMantenimiento es
# idéntica a antes; solo cambió la ubicación del código.
from widget_cambios_tablero import _SeccionCambiosTablero
from widget_pruebas_transformador import _SeccionPruebasTransformador


# ── Estilos compartidos (mismo lenguaje que programar_nuevo.py) ─────────
TITLEBAR_BG   = "#1f1f1f"
DIALOG_BG     = "#202020"
FOOTER_BG     = "#1a1a1a"
TEXT_SECONDARY = "#aaa"
DANGER        = "#e84747"

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
"""

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

# Estilo común para entradas de texto (QTextEdit + QLineEdit) en los diálogos.
# Aplicado explícitamente porque la cadena de padres puede contaminar la
# herencia de styleSheets desde el top-level MantenimientosWindow.
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

LABEL_FORM_STYLE = "color: #ccc; font-size: 13px;"

# Color de acento ámbar para "cambios pendientes" y avisos suaves.
WARNING       = "#EF9F27"

class _NoWheelComboBox(QComboBox):
    """
    QComboBox que ignora la rueda del mouse.

    Por defecto, cuando el usuario está scrolleando dentro de un QScrollArea
    y el cursor pasa por encima de un QComboBox, Qt cambia el valor del
    combo. Comportamiento peligroso en formularios largos: el usuario puede
    alterar valores sin querer al intentar simplemente bajar la vista.

    Con `event.ignore()` el wheel se propaga al padre (el QScrollArea),
    que sí procesa el scroll. El usuario sigue pudiendo cambiar el valor
    clickeando el combo normalmente.
    """

    def wheelEvent(self, event):
        event.ignore()


class DialogReprogramar(QDialog):
    """
    Sub-diálogo para cambiar las fechas y horarios de un mantenimiento.

    El estado destino es siempre 'programado' (lo maneja el helper
    db_manager.reprogramar_mantenimiento). La ficha se encarga de
    detectar el cambio de estado y disparar la animación de tinte
    (a azul si la nueva fecha es futura, a amarillo si ya empezó).

    Uso recomendado vía el helper estático `mostrar(...)`:

        resultado = DialogReprogramar.mostrar(parent, mant_id, dt_ini, dt_fin)
        if resultado:
            dt_nuevo_inicio, dt_nuevo_fin = resultado
            ...
    """

    def __init__(self, mantenimiento_id, dt_inicio_actual, dt_fin_actual, parent=None):
        super().__init__(parent)
        self.mantenimiento_id = mantenimiento_id
        self._drag_offset = None
        self._dt_inicio_resultado = None
        self._dt_fin_resultado = None

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.resize(500, 360)
        self.setMinimumSize(460, 340)

        self._build_ui(dt_inicio_actual, dt_fin_actual)
        # Aplicar styleSheet DESPUÉS de construir la UI — siguiendo el patrón
        # exacto que usa la ficha en _set_styles_aislados(). Si se aplica antes
        # de _build_ui, Qt re-pinta al crear los widgets internos y rompe la
        # transparencia, dejando que el fondo heredado de "QWidget {
        # background-color: #121212 }" se asome arriba del titlebar.
        self.setObjectName("DialogReprogramar")
        self.setStyleSheet("QDialog#DialogReprogramar { background: transparent; }")
        self._on_fecha_hora_changed()  # primer cálculo de duración

    # ── Construcción de UI ──────────────────────────────────────────────
    def _build_ui(self, dt_inicio_actual, dt_fin_actual):
        # Layout root sin márgenes: el contenedor interno se encarga del border-radius
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        main = QFrame()
        main.setObjectName("main_dialog")
        main.setStyleSheet(f"""
            #main_dialog {{
                background: {DIALOG_BG};
                border-radius: 10px;
                /* sin border explícito: la sombra del SO ya da separación.
                   Antes había aquí "border: 1px solid #333;" que combinado
                   con la sombra de Windows 11 generaba un halo oscuro visible
                   alrededor del titlebar — eliminarlo lo resuelve. */
            }}
        """)
        outer.addWidget(main, 1)

        lay = QVBoxLayout(main)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_titlebar())
        lay.addWidget(self._build_body(dt_inicio_actual, dt_fin_actual), 1)
        lay.addWidget(self._build_footer())

    def _build_titlebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(32)
        bar.setStyleSheet(f"""
            #titlebar {{
                background: {TITLEBAR_BG};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
        """)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(10, 0, 4, 0)
        bar_lay.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.calendar-day", color="#cccccc").pixmap(14, 14))
        bar_lay.addWidget(icon_lbl)

        title = QLabel(f"Reprogramar mantenimiento #{self.mantenimiento_id}")
        title.setStyleSheet("color: white; font-size: 12px; font-weight: 500;")
        bar_lay.addWidget(title)
        bar_lay.addStretch()

        btn_x = QPushButton()
        btn_x.setIcon(qta.icon("fa5s.times", color="#cccccc"))
        btn_x.setFixedSize(40, 28)
        btn_x.setStyleSheet("""
            QPushButton { background: transparent; border: none; }
            QPushButton:hover { background: #3a3a3a; }
        """)
        btn_x.clicked.connect(self.reject)
        bar_lay.addWidget(btn_x)

        # Drag manual (mismo patrón que la ficha)
        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        bar.mouseReleaseEvent = self._bar_release

        return bar

    def _build_body(self, dt_inicio_actual, dt_fin_actual) -> QWidget:
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(20, 16, 20, 12)
        body_lay.setSpacing(10)

        # ── Fechas ──
        lbl_fecha = QLabel("Fecha:")
        lbl_fecha.setStyleSheet(LABEL_FORM_STYLE)
        body_lay.addWidget(lbl_fecha)

        fila_fechas = QHBoxLayout()
        fila_fechas.setSpacing(8)

        self.date_inicio = QDateEdit()
        self.date_inicio.setFixedHeight(32)
        self.date_inicio.setCalendarPopup(True)
        self.date_inicio.setDate(QDate(dt_inicio_actual.year,
                                       dt_inicio_actual.month,
                                       dt_inicio_actual.day))

        self.date_fin = QDateEdit()
        self.date_fin.setFixedHeight(32)
        self.date_fin.setCalendarPopup(True)
        self.date_fin.setDate(QDate(dt_fin_actual.year,
                                    dt_fin_actual.month,
                                    dt_fin_actual.day))

        # Detectar si el mantenimiento actual es "un solo día"
        es_un_dia = (dt_inicio_actual.date() == dt_fin_actual.date())
        self.date_fin.setVisible(not es_un_dia)

        fila_fechas.addWidget(self.date_inicio)
        fila_fechas.addWidget(self.date_fin)
        body_lay.addLayout(fila_fechas)

        self.chk_un_dia = QCheckBox("Un solo día")
        self.chk_un_dia.setChecked(es_un_dia)
        self.chk_un_dia.setStyleSheet(CHECKBOX_STYLE)
        body_lay.addWidget(self.chk_un_dia)

        # ── Horario ──
        lbl_horario = QLabel("Horario:")
        lbl_horario.setStyleSheet(LABEL_FORM_STYLE)
        body_lay.addWidget(lbl_horario)

        fila_horas = QHBoxLayout()
        fila_horas.setSpacing(6)

        self.combo_hora_inicio = QComboBox()
        self.combo_hora_fin = QComboBox()
        for h in range(24):
            for m in (0, 30):
                etiqueta = f"{h:02d}:{m:02d}"
                self.combo_hora_inicio.addItem(etiqueta)
                self.combo_hora_fin.addItem(etiqueta)
        # Pre-cargar con las horas actuales (snap a 30 min)
        self.combo_hora_inicio.setCurrentText(self._snap_30(dt_inicio_actual))
        self.combo_hora_fin.setCurrentText(self._snap_30(dt_fin_actual))

        for cb in (self.combo_hora_inicio, self.combo_hora_fin):
            cb.setFixedWidth(110)
            cb.setFixedHeight(32)
            cb.setStyleSheet(COMBO_STYLE)

        fila_horas.addWidget(self.combo_hora_inicio)
        flecha = QLabel("→")
        flecha.setStyleSheet("color: #888; font-size: 16px;")
        fila_horas.addWidget(flecha)
        fila_horas.addWidget(self.combo_hora_fin)
        fila_horas.addStretch()
        body_lay.addLayout(fila_horas)

        # ── Label de duración (mismo patrón que programar_nuevo) ──
        self.lbl_duracion = QLabel("")
        self.lbl_duracion.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-style: italic;"
        )
        body_lay.addWidget(self.lbl_duracion)

        body_lay.addStretch()

        # ── Conexiones de validación viva ──
        self.date_inicio.dateChanged.connect(self._on_fecha_hora_changed)
        self.date_fin.dateChanged.connect(self._on_fecha_hora_changed)
        self.combo_hora_inicio.currentTextChanged.connect(self._on_fecha_hora_changed)
        self.combo_hora_fin.currentTextChanged.connect(self._on_fecha_hora_changed)
        self.chk_un_dia.stateChanged.connect(self._on_un_dia_changed)

        return body

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footer_dialog")
        footer.setStyleSheet(f"""
            #footer_dialog {{
                background: {FOOTER_BG};
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
            }}
        """)
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(20, 12, 20, 12)
        f_lay.setSpacing(8)
        f_lay.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFixedHeight(32)
        btn_cancelar.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: white; border: 1px solid #444;
                border-radius: 5px; padding: 4px 16px;
            }
            QPushButton:hover { background: #333; }
        """)
        btn_cancelar.clicked.connect(self.reject)
        f_lay.addWidget(btn_cancelar)

        self.btn_aceptar = QPushButton("  Aceptar")
        self.btn_aceptar.setFixedHeight(32)
        self.btn_aceptar.setIcon(qta.icon("fa5s.check", color="white"))
        self.btn_aceptar.setStyleSheet("""
            QPushButton {
                background: #0078d7; color: white; border: none;
                border-radius: 5px; padding: 4px 16px; font-weight: 500;
            }
            QPushButton:hover { background: #0094ff; }
            QPushButton:disabled { background: #335577; color: #999; }
        """)
        self.btn_aceptar.clicked.connect(self._on_aceptar)
        f_lay.addWidget(self.btn_aceptar)

        return footer

    # ── Drag manual de la ventana ───────────────────────────────────────
    def _bar_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _bar_move(self, event):
        if self._drag_offset and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _bar_release(self, event):
        self._drag_offset = None

    # ── Lógica de validación viva ───────────────────────────────────────
    @staticmethod
    def _snap_30(dt):
        """Redondea el minuto al múltiplo de 30 más cercano (00 o 30)."""
        m = 30 if dt.minute >= 30 else 0
        return f"{dt.hour:02d}:{m:02d}"

    def _on_un_dia_changed(self, _):
        self.date_fin.setVisible(not self.chk_un_dia.isChecked())
        self._on_fecha_hora_changed()

    def _on_fecha_hora_changed(self, *_):
        dt_inicio, dt_fin, error = self._calcular_datetimes()
        if error:
            self.lbl_duracion.setText(f"⚠ {error}")
            self.lbl_duracion.setStyleSheet(
                f"color: {DANGER}; font-size: 11px; font-style: italic;"
            )
            self.btn_aceptar.setEnabled(False)
            return
        cruzo_medianoche = (self.chk_un_dia.isChecked()
                            and dt_inicio.date() != dt_fin.date())
        texto = f"Duración: {self._formato_duracion(dt_inicio, dt_fin)}"
        if cruzo_medianoche:
            texto += "  (cruza al día siguiente)"
        self.lbl_duracion.setText(texto)
        self.lbl_duracion.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-style: italic;"
        )
        self.btn_aceptar.setEnabled(True)

    def _calcular_datetimes(self):
        """
        Mismo patrón que programar_nuevo._calcular_datetimes.
        Devuelve (dt_inicio, dt_fin, error_str_o_None).
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

    # ── Confirmación ────────────────────────────────────────────────────
    def _on_aceptar(self):
        dt_inicio, dt_fin, error = self._calcular_datetimes()
        if error:
            return  # botón debería estar deshabilitado, pero por seguridad
        self._dt_inicio_resultado = dt_inicio
        self._dt_fin_resultado = dt_fin
        self.accept()

    # ── Helper estático para invocación limpia desde la ficha ───────────
    @staticmethod
    def mostrar(parent, mantenimiento_id, dt_inicio_actual, dt_fin_actual):
        """
        Abre el diálogo modal y devuelve:
            - (dt_inicio_nuevo, dt_fin_nuevo) si el usuario aceptó
            - None si el usuario canceló o cerró el diálogo
        """
        dlg = DialogReprogramar(mantenimiento_id, dt_inicio_actual, dt_fin_actual, parent=parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return (dlg._dt_inicio_resultado, dlg._dt_fin_resultado)
        return None


class DialogCerrarCancelado(QDialog):
    """
    Sub-diálogo simple para cerrar un mantenimiento que está en estado
    Cancelado. Solo captura el motivo de la cancelación. Tras aceptar,
    el estado_db sigue 'cancelado' (no cambia) pero se llena fecha_cierre,
    y el mantenimiento pasa a la pestaña Finalizados (que filtra por
    fecha_cierre IS NOT NULL, no por estado).

    Uso recomendado vía helper estático:

        motivo = DialogCerrarCancelado.mostrar(parent, mant_id)
        if motivo is not None:
            db_manager.cerrar_mantenimiento_cancelado(mant_id, motivo)
    """

    def __init__(self, mantenimiento_id, parent=None):
        super().__init__(parent)
        self.mantenimiento_id = mantenimiento_id
        self._drag_offset = None
        self._motivo_resultado = None

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.resize(500, 320)
        self.setMinimumSize(460, 300)

        self._build_ui()
        # Aplicar styleSheet DESPUÉS de _build_ui (ver nota en DialogReprogramar)
        self.setObjectName("DialogCerrarCancelado")
        self.setStyleSheet("QDialog#DialogCerrarCancelado { background: transparent; }")
        self._actualizar_estado_aceptar()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        main = QFrame()
        main.setObjectName("main_dialog")
        main.setStyleSheet(f"""
            #main_dialog {{
                background: {DIALOG_BG};
                border-radius: 10px;
                /* sin border explícito: la sombra del SO ya da separación.
                   Antes había aquí "border: 1px solid #333;" que combinado
                   con la sombra de Windows 11 generaba un halo oscuro visible
                   alrededor del titlebar — eliminarlo lo resuelve. */
            }}
        """)
        outer.addWidget(main, 1)

        lay = QVBoxLayout(main)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_titlebar())
        lay.addWidget(self._build_body(), 1)
        lay.addWidget(self._build_footer())

    def _build_titlebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(32)
        bar.setStyleSheet(f"""
            #titlebar {{
                background: {TITLEBAR_BG};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
        """)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(10, 0, 4, 0)
        bar_lay.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.ban", color="#cccccc").pixmap(14, 14))
        bar_lay.addWidget(icon_lbl)

        title = QLabel(f"Cerrar mantenimiento cancelado #{self.mantenimiento_id}")
        title.setStyleSheet("color: white; font-size: 12px; font-weight: 500;")
        bar_lay.addWidget(title)
        bar_lay.addStretch()

        btn_x = QPushButton()
        btn_x.setIcon(qta.icon("fa5s.times", color="#cccccc"))
        btn_x.setFixedSize(40, 28)
        btn_x.setStyleSheet("""
            QPushButton { background: transparent; border: none; }
            QPushButton:hover { background: #3a3a3a; }
        """)
        btn_x.clicked.connect(self.reject)
        bar_lay.addWidget(btn_x)

        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        bar.mouseReleaseEvent = self._bar_release

        return bar

    def _build_body(self) -> QWidget:
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(20, 16, 20, 12)
        body_lay.setSpacing(8)

        lbl = QLabel("Motivo de la cancelación:")
        lbl.setStyleSheet(LABEL_FORM_STYLE)
        body_lay.addWidget(lbl)

        self.text_motivo = QTextEdit()
        self.text_motivo.setStyleSheet(INPUT_STYLE)
        self.text_motivo.setPlaceholderText(
            "Explica brevemente por qué se canceló el mantenimiento…"
        )
        self.text_motivo.textChanged.connect(self._actualizar_estado_aceptar)
        body_lay.addWidget(self.text_motivo, 1)

        return body

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footer_dialog")
        footer.setStyleSheet(f"""
            #footer_dialog {{
                background: {FOOTER_BG};
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
            }}
        """)
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(20, 12, 20, 12)
        f_lay.setSpacing(8)
        f_lay.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFixedHeight(32)
        btn_cancelar.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: white; border: 1px solid #444;
                border-radius: 5px; padding: 4px 16px;
            }
            QPushButton:hover { background: #333; }
        """)
        btn_cancelar.clicked.connect(self.reject)
        f_lay.addWidget(btn_cancelar)

        self.btn_aceptar = QPushButton("  Aceptar")
        self.btn_aceptar.setFixedHeight(32)
        self.btn_aceptar.setIcon(qta.icon("fa5s.check", color="white"))
        self.btn_aceptar.setStyleSheet("""
            QPushButton {
                background: #0078d7; color: white; border: none;
                border-radius: 5px; padding: 4px 16px; font-weight: 500;
            }
            QPushButton:hover { background: #0094ff; }
            QPushButton:disabled { background: #335577; color: #999; }
        """)
        self.btn_aceptar.clicked.connect(self._on_aceptar)
        f_lay.addWidget(self.btn_aceptar)

        return footer

    # ── Drag manual de la ventana ───────────────────────────────────────
    def _bar_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _bar_move(self, event):
        if self._drag_offset and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _bar_release(self, event):
        self._drag_offset = None

    # ── Validación ──────────────────────────────────────────────────────
    def _actualizar_estado_aceptar(self):
        """El botón Aceptar se habilita solo si el motivo tiene >=3 chars."""
        texto = self.text_motivo.toPlainText().strip()
        self.btn_aceptar.setEnabled(len(texto) >= 3)

    def _on_aceptar(self):
        motivo = self.text_motivo.toPlainText().strip()
        if len(motivo) < 3:
            return
        self._motivo_resultado = motivo
        self.accept()

    # ── Helper estático ─────────────────────────────────────────────────
    @staticmethod
    def mostrar(parent, mantenimiento_id):
        """
        Abre el diálogo modal y devuelve:
            - El motivo (str) si el usuario aceptó
            - None si canceló
        """
        dlg = DialogCerrarCancelado(mantenimiento_id, parent=parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._motivo_resultado
        return None


class DialogCerrarMantenimiento(QDialog):
    """
    Sub-diálogo para cerrar un mantenimiento en estado 'Pendiente cierre'
    (estado_db='programado' con fechas vencidas). Captura:
        - PDF del informe          (obligatorio)
        - Retroalimentación        (obligatorio, ≥3 caracteres)
        - Costo real               (opcional; si vacío, se asume igual al
                                    estimado)

    La moneda NO es editable: hereda del costo_moneda original (regla del
    producto: si se programó en MXN, se cierra en MXN).

    ── Sección "Cambios al equipo" (solo modo tableros) ────────────────
    Si el mantenimiento es sobre tableros (todos los equipos con
    equipo_tipo='tableros'), el diálogo agrega una sección donde el
    ingeniero puede editar los circuitos de esos tableros. El inventario
    se sobreescribe y el histórico queda en `cambios_equipo` — todo en la
    misma transacción atómica de `cerrar_mantenimiento_pendiente`.

    Uso recomendado vía helper estático:

        resultado = DialogCerrarMantenimiento.mostrar(
            parent, mant_id, costo_estimado=5000, moneda='MXN', equipos=lista)
        if resultado:
            pdf, retro, costo, upd_circ, cambios = resultado
    """

    def __init__(self, mantenimiento_id, costo_estimado, moneda,
                 equipos=None, parent=None):
        super().__init__(parent)
        self.mantenimiento_id = mantenimiento_id
        self._costo_estimado = costo_estimado
        self._moneda = moneda or 'MXN'
        self._drag_offset = None
        self._pdf_origen = None
        self._pdf_resultado = None
        self._retro_resultado = None
        self._costo_real_resultado = None

        # ── Detección de modo según los equipos del mantenimiento ─────
        # Regla: en programar_nuevo.py, cambiar de tipo de equipo resetea
        # la selección (línea 698). Un mantenimiento nunca mezcla tipos,
        # así que basta con mirar el primero.
        self._equipos = list(equipos) if equipos else []
        tipos = {(e.get("tipo") or "").lower() for e in self._equipos}
        if tipos == {"tableros"}:
            self._modo = "tableros"
        elif tipos == {"transformadores"}:
            self._modo = "transformadores"
        else:
            self._modo = "generico"

        # Payloads que se llenan en _on_aceptar (solo modo tableros por ahora)
        self._updates_resultado = None
        self._cambios_resultado = None

        # Payloads que se llenan cuando modo == 'transformadores'
        self._pruebas_resultado = None
        self._inspeccion_resultado = None
        self._tap_resultado = None

        # Referencia a la sección de cambios; se instancia en _build_body
        # solo en modo tableros.
        self._seccion_cambios = None

        # Referencia a la sección de pruebas; se instancia en _build_body
        # solo en modo transformadores.
        self._seccion_pruebas = None

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        # Tamaño más generoso cuando hay sección de cambios o pruebas: la
        # tabla de circuitos y el formulario de pruebas necesitan ancho para
        # los campos. La altura queda fija; el body es scrolleable como una
        # unidad (ver _build_ui), así que el contenido puede exceder la
        # altura visible y el usuario scrollea para verlo todo.
        if self._equipos and self._modo in ("tableros", "transformadores"):
            self.resize(880, 720)
            self.setMinimumSize(760, 620)
        else:
            self.resize(520, 560)
            self.setMinimumSize(480, 520)

        self._build_ui()
        # Aplicar styleSheet DESPUÉS de _build_ui (ver nota en DialogReprogramar)
        self.setObjectName("DialogCerrarMantenimiento")
        self.setStyleSheet("QDialog#DialogCerrarMantenimiento { background: transparent; }")
        self._actualizar_estado_aceptar()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        main = QFrame()
        main.setObjectName("main_dialog")
        main.setStyleSheet(f"""
            #main_dialog {{
                background: {DIALOG_BG};
                border: none;
                border-radius: 10px;
                /* sin border explícito: la sombra del SO ya da separación.
                   Antes había aquí "border: 1px solid #333;" que combinado
                   con la sombra de Windows 11 generaba un halo oscuro visible
                   alrededor del titlebar — eliminarlo lo resuelve. */
                /* margin/padding 0 explícito para blindar contra estilos
                   heredados de MantenimientosWindow (que puede aplicar
                   reglas genéricas a QWidget o QFrame). Sin este blindaje,
                   un padding-top heredado dejaba visible el fondo
                   transparente del QDialog arriba del titlebar (la
                   "franja negra" que se veía como sombra). */
                margin: 0;
                padding: 0;
            }}
        """)
        outer.addWidget(main, 1)

        lay = QVBoxLayout(main)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_titlebar())

        # Body envuelto en QScrollArea global. Titlebar y footer quedan
        # fijos (siempre visibles); solo el contenido del formulario
        # scrollea. Es el patrón estándar de diálogos de apps profesionales
        # (Outlook, VS Code settings, macOS System Preferences).
        #
        # Decisión de arquitectura: el body puede ser mucho más alto que
        # la ventana (formulario del transformador ~930 px, tablero de 42
        # circuitos ~1700 px) y este scroll global lo maneja. Los widgets
        # internos (SeccionPruebasTransformador, SeccionCambiosTablero) ya
        # NO envuelven su contenido en QScrollArea propio — crecen a su
        # tamaño natural y el scroll global se encarga.
        #
        # Estilo del scroll: sin borde (NoFrame), sin track visible, handle
        # delgado en gris oscuro, fondo transparente. Mantiene el look
        # limpio del diálogo sin agregar "caja adicional".
        body_widget = self._build_body()
        scroll_body = QScrollArea()
        scroll_body.setWidgetResizable(True)
        scroll_body.setFrameShape(QFrame.Shape.NoFrame)
        scroll_body.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll_body.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            /* body_widget (nieto directo del QScrollArea) recibe el
               color del diálogo explícitamente. Sin esta regla, en
               Windows 11 el body queda con el fondo default de la
               palette del sistema (negro puro), y los QLabels dentro
               heredan ese negro, causando "rectángulos oscuros" alrededor
               de los textos como "Reporte PDF:", "Retroalimentación:",
               etc. El selector `> QWidget > QWidget` apunta a body_widget
               sin afectar widgets más profundos como el QFrame
               `#cont_pruebas` (que tiene su propio background). */
            QScrollArea > QWidget > QWidget {{
                background: {DIALOG_BG};
            }}
            /* Blindaje global de QLabel dentro del scroll: garantiza
               transparencia para heredar el fondo del padre. Necesario
               porque LABEL_FORM_STYLE (usado por labels del body como
               "Reporte PDF:") no incluye background: transparent. */
            QScrollArea QLabel {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #3a3a3a;
                border-radius: 5px;
                min-height: 30px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{ background: #4a4a4a; }}
            QScrollBar::handle:vertical:pressed {{ background: #5a5a5a; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0; background: none; border: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{ background: none; }}
        """)
        scroll_body.setWidget(body_widget)
        lay.addWidget(scroll_body, 1)

        lay.addWidget(self._build_footer())

    def _build_titlebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(32)
        # border: none explícito para bloquear cualquier `border: ... solid`
        # que MantenimientosWindow aplique genéricamente a QFrame. Sin este
        # blindaje, el border heredado se pintaba arriba del titlebar como
        # una franja oscura de 1-2 px que aparentaba una "sombra".
        # margin/padding 0 explícito por la misma razón que #main_dialog.
        bar.setStyleSheet(f"""
            #titlebar {{
                background: {TITLEBAR_BG};
                border: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                margin: 0;
                padding: 0;
            }}
            #titlebar QLabel {{
                background: transparent;
                border: none;
            }}
        """)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(10, 0, 4, 0)
        bar_lay.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.flag-checkered", color="#cccccc").pixmap(14, 14))
        bar_lay.addWidget(icon_lbl)

        title = QLabel(f"Cerrar mantenimiento #{self.mantenimiento_id}")
        title.setStyleSheet("color: white; font-size: 12px; font-weight: 500;")
        bar_lay.addWidget(title)
        bar_lay.addStretch()

        btn_x = QPushButton()
        btn_x.setIcon(qta.icon("fa5s.times", color="#cccccc"))
        btn_x.setFixedSize(40, 28)
        btn_x.setStyleSheet("""
            QPushButton { background: transparent; border: none; }
            QPushButton:hover { background: #3a3a3a; }
        """)
        btn_x.clicked.connect(self.reject)
        bar_lay.addWidget(btn_x)

        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        bar.mouseReleaseEvent = self._bar_release

        return bar

    def _build_body(self) -> QWidget:
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(20, 16, 20, 12)
        body_lay.setSpacing(10)

        # ── Bloque PDF ──
        lbl_pdf = QLabel("Reporte PDF:")
        lbl_pdf.setStyleSheet(LABEL_FORM_STYLE)
        body_lay.addWidget(lbl_pdf)

        fila_pdf = QHBoxLayout()
        fila_pdf.setSpacing(8)

        self.btn_seleccionar_pdf = QPushButton("  Seleccionar archivo")
        self.btn_seleccionar_pdf.setIcon(qta.icon("fa5s.file-upload", color="white"))
        self.btn_seleccionar_pdf.setFixedHeight(32)
        self.btn_seleccionar_pdf.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: white; border: 1px solid #444;
                border-radius: 5px; padding: 4px 14px;
            }
            QPushButton:hover { background: #333; }
        """)
        self.btn_seleccionar_pdf.clicked.connect(self._on_seleccionar_pdf)
        fila_pdf.addWidget(self.btn_seleccionar_pdf)

        self.lbl_pdf_nombre = QLabel("Ningún archivo seleccionado")
        self.lbl_pdf_nombre.setStyleSheet(
            "color: #888; font-size: 12px; font-style: italic;"
        )
        fila_pdf.addWidget(self.lbl_pdf_nombre, 1)
        body_lay.addLayout(fila_pdf)

        # ── Bloque Retroalimentación ──
        lbl_retro = QLabel("Retroalimentación:")
        lbl_retro.setStyleSheet(LABEL_FORM_STYLE)
        body_lay.addWidget(lbl_retro)

        self.text_retro = QTextEdit()
        self.text_retro.setStyleSheet(INPUT_STYLE)
        self.text_retro.setPlaceholderText(
            "Comentarios sobre el trabajo realizado, observaciones, hallazgos…"
        )
        # Altura acotada a ~3 líneas visibles. Antes tenía stretch=1 en el
        # body_lay, lo que le hacía consumir bastante espacio vertical y
        # comprimir el scroll interno del widget de pruebas/cambios. Se
        # usa Maximum + Minimum + SizePolicy Fixed (en vez de FixedHeight
        # solo) para blindar contra HiDPI de Windows 11 (donde
        # setFixedHeight sin sizePolicy puede escalar con el DPR y
        # terminar el widget con altura mayor a la esperada).
        self.text_retro.setMinimumHeight(70)
        self.text_retro.setMaximumHeight(75)
        self.text_retro.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.text_retro.textChanged.connect(self._actualizar_estado_aceptar)
        body_lay.addWidget(self.text_retro)

        # ── Bloque Cambios al equipo (solo modo tableros) ──
        # Se inserta entre Retroalimentación y Costo real cuando el
        # mantenimiento es sobre tableros. Para transformadores o modo
        # genérico, se omite (comportamiento actual del diálogo).
        if self._modo == "tableros" and self._equipos:
            tableros = [
                {"id": e.get("id"), "nombre": e.get("nombre", ""),
                 "ubicacion": e.get("ubicacion", "")}
                for e in self._equipos if (e.get("tipo") or "").lower() == "tableros"
            ]
            self._seccion_cambios = _SeccionCambiosTablero(tableros, parent=body)
            self._seccion_cambios.cambios_cambiaron.connect(self._actualizar_estado_aceptar)
            body_lay.addWidget(self._seccion_cambios, 2)

        # ── Bloque Pruebas del transformador (solo modo transformadores) ──
        # Simétrico al bloque anterior: se monta cuando el mantenimiento es
        # sobre transformadores. Ambos modos son mutuamente excluyentes
        # (regla de negocio del programador de mantenimiento).
        elif self._modo == "transformadores" and self._equipos:
            transformadores = [
                {"id": e.get("id"), "nombre": e.get("nombre", ""),
                 "ubicacion": e.get("ubicacion", "")}
                for e in self._equipos
                if (e.get("tipo") or "").lower() == "transformadores"
            ]
            self._seccion_pruebas = _SeccionPruebasTransformador(
                transformadores, parent=body)
            self._seccion_pruebas.datos_cambiaron.connect(
                self._actualizar_estado_aceptar)
            body_lay.addWidget(self._seccion_pruebas, 2)

        # ── Bloque Costo real ──
        lbl_costo = QLabel("Costo real (opcional):")
        lbl_costo.setStyleSheet(LABEL_FORM_STYLE)
        body_lay.addWidget(lbl_costo)

        fila_costo = QHBoxLayout()
        fila_costo.setSpacing(8)

        self.input_costo_real = QLineEdit()
        self.input_costo_real.setFixedHeight(32)
        self.input_costo_real.setStyleSheet(INPUT_STYLE)
        self.input_costo_real.setPlaceholderText("$0")
        self.input_costo_real.setValidator(QIntValidator(0, 100000000))

        # Mismo formato que programar_nuevo.py: separador de miles con coma
        # vía QLocale español-México, prefijo "$". Se reformatea en cada
        # textChanged. blockSignals evita loop infinito al re-setear el text.
        def _formatear_costo_real():
            texto = self.input_costo_real.text().replace("$", "").replace(",", "")
            if texto:
                try:
                    valor = int(texto)
                except ValueError:
                    return
                locale = QLocale(QLocale.Language.Spanish, QLocale.Country.Mexico)
                self.input_costo_real.blockSignals(True)
                self.input_costo_real.setText(f"${locale.toString(valor)}")
                self.input_costo_real.blockSignals(False)
        self.input_costo_real.textChanged.connect(_formatear_costo_real)
        fila_costo.addWidget(self.input_costo_real, 1)

        lbl_moneda = QLabel(self._moneda)
        lbl_moneda.setStyleSheet(
            "color: #ccc; font-size: 13px; font-weight: 500; padding: 0 4px;"
        )
        fila_costo.addWidget(lbl_moneda)
        body_lay.addLayout(fila_costo)

        # Texto explicativo bajo el campo
        costo_est_fmt = f"${self._costo_estimado:,}" if self._costo_estimado else "$0"
        info = QLabel(
            f"Si dejas vacío, se asume igual al estimado "
            f"({costo_est_fmt} {self._moneda})."
        )
        info.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")
        body_lay.addWidget(info)

        return body

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footer_dialog")
        footer.setStyleSheet(f"""
            #footer_dialog {{
                background: {FOOTER_BG};
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
            }}
        """)
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(20, 12, 20, 12)
        f_lay.setSpacing(8)
        f_lay.addStretch()

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFixedHeight(32)
        btn_cancelar.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: white; border: 1px solid #444;
                border-radius: 5px; padding: 4px 16px;
            }
            QPushButton:hover { background: #333; }
        """)
        btn_cancelar.clicked.connect(self.reject)
        f_lay.addWidget(btn_cancelar)

        self.btn_aceptar = QPushButton("  Cerrar mantenimiento")
        self.btn_aceptar.setFixedHeight(32)
        self.btn_aceptar.setIcon(qta.icon("fa5s.check", color="white"))
        self.btn_aceptar.setStyleSheet("""
            QPushButton {
                background: #0078d7; color: white; border: none;
                border-radius: 5px; padding: 4px 16px; font-weight: 500;
            }
            QPushButton:hover { background: #0094ff; }
            QPushButton:disabled { background: #335577; color: #999; }
        """)
        self.btn_aceptar.clicked.connect(self._on_aceptar)
        f_lay.addWidget(self.btn_aceptar)

        return footer

    # ── Drag manual ─────────────────────────────────────────────────────
    def _bar_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _bar_move(self, event):
        if self._drag_offset and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _bar_release(self, event):
        self._drag_offset = None

    # ── Selector de PDF ─────────────────────────────────────────────────
    def _on_seleccionar_pdf(self):
        """
        Abre QFileDialog para elegir un PDF. NO copia el archivo: solo
        guarda la ruta de origen. La copia a la carpeta gestionada de la
        app se hace en el handler de la ficha (vía db_manager.copiar_informe_pdf)
        después de que el usuario haya aceptado el diálogo.
        """
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar reporte PDF",
            "",
            "Archivos PDF (*.pdf);;Todos los archivos (*)"
        )
        if not ruta:
            return
        # Validar extensión por si el usuario eligió "Todos los archivos"
        if not ruta.lower().endswith(".pdf"):
            self.lbl_pdf_nombre.setText("⚠ El archivo debe ser un PDF")
            self.lbl_pdf_nombre.setStyleSheet(
                f"color: {DANGER}; font-size: 12px; font-style: italic;"
            )
            return

        self._pdf_origen = ruta
        nombre = os.path.basename(ruta)
        self.lbl_pdf_nombre.setText(nombre)
        self.lbl_pdf_nombre.setStyleSheet(
            "color: #ccc; font-size: 12px;"
        )
        self._actualizar_estado_aceptar()

    # ── Validación viva ─────────────────────────────────────────────────
    def _actualizar_estado_aceptar(self):
        """
        Aceptar habilitado solo si:
            - Hay un PDF seleccionado
            - La retroalimentación tiene ≥3 caracteres no-whitespace
            - Si hay sección de cambios: no hay cambios sin justificar
            - Si hay sección de pruebas: no hay tap con posición cambiada
              sin justificar
        El costo real es opcional, no entra en la validación.
        """
        retro_ok = len(self.text_retro.toPlainText().strip()) >= 3
        pdf_ok = self._pdf_origen is not None
        cambios_ok = True
        tooltip = ""
        if self._seccion_cambios is not None:
            if self._seccion_cambios.hay_cambios_sin_justificar():
                cambios_ok = False
                tooltip = "Falta justificación en uno o más cambios al equipo."
        if self._seccion_pruebas is not None:
            if self._seccion_pruebas.hay_incompletos():
                cambios_ok = False
                tooltip = "Falta justificación del cambio de tap."
        self.btn_aceptar.setEnabled(retro_ok and pdf_ok and cambios_ok)
        self.btn_aceptar.setToolTip(tooltip)

    def _on_aceptar(self):
        retro = self.text_retro.toPlainText().strip()
        if not retro or not self._pdf_origen:
            return  # botón debería estar disabled, pero por seguridad

        # Costo real: limpiar de separadores y convertir a int. Si vacío → None
        # (la BD copiará el costo estimado al cerrar).
        texto_costo = self.input_costo_real.text().strip()
        if texto_costo:
            import re
            limpio = re.sub(r"[^\d]", "", texto_costo)
            costo_real = int(limpio) if limpio else None
        else:
            costo_real = None

        # Recolectar payloads de la sección de cambios (solo en modo tableros).
        # En modos sin sección, ambos quedan None → cerrar_mantenimiento_pendiente
        # ignora los parámetros opcionales y se comporta igual que antes.
        if self._seccion_cambios is not None and self._seccion_cambios.total_cambios() > 0:
            self._updates_resultado = self._seccion_cambios.obtener_payload_updates()
            # El nombre del responsable se resuelve en la ficha (que sí lo tiene
            # cargado); aquí lo dejamos como None y la ficha lo inyecta después.
            self._cambios_resultado = self._seccion_cambios.obtener_payload_cambios()
        else:
            self._updates_resultado = None
            self._cambios_resultado = None

        # Recolectar payloads de la sección de pruebas (solo en modo
        # transformadores). Los payloads son independientes entre sí; cada
        # uno se pasa a cerrar_mantenimiento_pendiente como parámetro
        # opcional. Vacíos (listas vacías) también pasan como None para no
        # ejecutar INSERTs innecesarios.
        if self._seccion_pruebas is not None:
            pruebas = self._seccion_pruebas.obtener_payload_pruebas()
            inspeccion = self._seccion_pruebas.obtener_payload_inspeccion()
            tap = self._seccion_pruebas.obtener_payload_tap()
            self._pruebas_resultado    = pruebas    if pruebas    else None
            self._inspeccion_resultado = inspeccion if inspeccion else None
            self._tap_resultado        = tap        if tap        else None
        else:
            self._pruebas_resultado = None
            self._inspeccion_resultado = None
            self._tap_resultado = None

        self._pdf_resultado = self._pdf_origen
        self._retro_resultado = retro
        self._costo_real_resultado = costo_real
        self.accept()

    # ── Helper estático ─────────────────────────────────────────────────
    @staticmethod
    def mostrar(parent, mantenimiento_id, costo_estimado, moneda, equipos=None):
        """
        Abre el diálogo modal y devuelve una tupla de 8 elementos:

            (pdf_ruta_origen, retroalimentacion, costo_real_o_None,
             updates_circuitos_o_None, cambios_equipo_o_None,
             pruebas_transformador_o_None, inspeccion_transformador_o_None,
             posicion_tap_o_None)

        Los últimos 5 son None si el modo no aplica o el ingeniero no capturó
        nada. En modo 'tableros' se llenan updates_circuitos y cambios_equipo;
        en modo 'transformadores' se llenan las 3 últimas. Los modos son
        mutuamente excluyentes, así que un cierre siempre tiene o los 2
        primeros pares None o los 3 últimos None.

        El caller (ficha) simplemente pasa a cerrar_mantenimiento_pendiente
        cualquiera de los payloads que no sea None — la función de BD ignora
        los parámetros opcionales cuando llegan como None.

        Devuelve None si el usuario canceló.
        """
        dlg = DialogCerrarMantenimiento(
            mantenimiento_id, costo_estimado, moneda,
            equipos=equipos, parent=parent
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return (dlg._pdf_resultado,
                    dlg._retro_resultado,
                    dlg._costo_real_resultado,
                    dlg._updates_resultado,
                    dlg._cambios_resultado,
                    dlg._pruebas_resultado,
                    dlg._inspeccion_resultado,
                    dlg._tap_resultado)
        return None
