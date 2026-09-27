# base_datos_config.py
"""
Página "Base de datos" — información y mantenimiento del archivo SQLite.

Estructura:
  Tarjeta superior   — icono + título + ruta completa al archivo
  ARCHIVO            — abrir ubicación, tamaño, última modificación
  REGISTROS          — conteo por tabla (personal, proveedores, equipos, mantenimientos)
  ACCIONES           — crear respaldo, restaurar respaldo, compactar BD

Es un "panel de control" — una sola página vertical, sin sub-páginas en el stack.
Las acciones se ejecutan inline con confirmaciones cuando son destructivas.
"""

import os
import shutil
import subprocess
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
import qtawesome as qta

from db_manager import connect_db


# ── Acceso a la base ─────────────────────────────────────────────────────────
def _obtener_path_bd() -> str | None:
    """Devuelve la ruta del archivo de la base de datos (vía PRAGMA database_list)."""
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA database_list")
        row = cur.fetchone()
        return row[2] if row else None
    except Exception as e:
        print(f"[base_datos_config] no pude obtener el path: {e}")
        return None
    finally:
        conn.close()


def _contar_registros() -> dict[str, int]:
    """Cuenta filas en cada tabla relevante. Si la tabla no existe, devuelve 0."""
    counts = {"personal": 0, "proveedores": 0, "equipos": 0, "mantenimientos": 0}
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return counts
    try:
        cur = conn.cursor()
        for tabla in list(counts.keys()):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tabla}")
                counts[tabla] = cur.fetchone()[0]
            except Exception:
                counts[tabla] = 0
    finally:
        conn.close()
    return counts


# ── Helpers de formato ───────────────────────────────────────────────────────
def _formatear_tamano(bytes_count: int) -> str:
    if bytes_count < 1024:
        return f"{bytes_count} bytes"
    if bytes_count < 1024 ** 2:
        return f"{bytes_count / 1024:.1f} KB"
    if bytes_count < 1024 ** 3:
        return f"{bytes_count / 1024 ** 2:.1f} MB"
    return f"{bytes_count / 1024 ** 3:.2f} GB"


def _formatear_fecha(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


# ── Widgets de presentación ──────────────────────────────────────────────────
def _make_db_icon(size: int = 64) -> QFrame:
    """Icono cuadrado con gradiente azul y disco de base de datos al centro."""
    frame = QFrame()
    frame.setFixedSize(size, size)
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    frame.setStyleSheet(f"""
        QFrame {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #1a3c5a, stop:1 #0a1c3a);
            border-radius: {size // 6}px;
        }}
    """)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ico = QLabel()
    ico.setPixmap(qta.icon("fa5s.database", color="#6cb4e8").pixmap(
        int(size * 0.5), int(size * 0.5)
    ))
    ico.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    lay.addWidget(ico)
    return frame


def _make_info_row(label: str, value: str) -> QFrame:
    """Fila informativa estática: label izquierda, valor derecha."""
    row = QFrame()
    row.setObjectName("info_row")
    row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    row.setMinimumHeight(50)
    row.setStyleSheet("""
        QFrame#info_row {
            background: #2b2b2b;
            border-radius: 8px;
        }
        QLabel#info_label {
            color: white; font-size: 14px; background: transparent;
        }
        QLabel#info_value {
            color: #aaa; font-size: 14px; background: transparent;
        }
    """)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(12)

    lbl_l = QLabel(label)
    lbl_l.setObjectName("info_label")
    lay.addWidget(lbl_l)
    lay.addStretch()
    lbl_r = QLabel(value)
    lbl_r.setObjectName("info_value")
    lbl_r.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(lbl_r)
    return row


class ActionRow(QFrame):
    """Fila clickable con icono + título + descripción + chevron."""
    clicked = pyqtSignal()

    def __init__(self, icon_name: str, icon_color: str, chip_bg: str,
                 titulo: str, descripcion: str, parent=None):
        super().__init__(parent)
        self.setObjectName("action_row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)
        self.setStyleSheet("""
            QFrame#action_row {
                background: #2b2b2b;
                border-radius: 8px;
                border: 1px solid transparent;
            }
            QFrame#action_row:hover {
                background: #333;
                border: 1px solid #0078d7;
            }
            QLabel#action_titulo {
                color: white; font-size: 14px; font-weight: 500;
                background: transparent;
            }
            QLabel#action_desc {
                color: #888; font-size: 12px; background: transparent;
            }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 16, 12)
        lay.setSpacing(14)

        # Chip con icono
        chip = QFrame()
        chip.setObjectName("icon_chip")
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedSize(36, 36)
        chip.setStyleSheet(f"QFrame#icon_chip {{ background: {chip_bg}; border-radius: 8px; }}")
        chip_lay = QVBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono = QLabel()
        icono.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(18, 18))
        icono.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        chip_lay.addWidget(icono)
        lay.addWidget(chip)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        lbl_t = QLabel(titulo)
        lbl_t.setObjectName("action_titulo")
        text_box.addWidget(lbl_t)
        lbl_d = QLabel(descripcion)
        lbl_d.setObjectName("action_desc")
        lbl_d.setWordWrap(True)
        text_box.addWidget(lbl_d)
        lay.addLayout(text_box, 1)

        self._chevron = QLabel()
        self._chevron.setPixmap(qta.icon("fa5s.chevron-right", color="#666").pixmap(12, 12))
        self._chevron.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay.addWidget(self._chevron)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._chevron.setPixmap(qta.icon("fa5s.chevron-right", color="#bbb").pixmap(12, 12))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._chevron.setPixmap(qta.icon("fa5s.chevron-right", color="#666").pixmap(12, 12))
        super().leaveEvent(event)


# ── Página principal ─────────────────────────────────────────────────────────
class BaseDatosPage(QWidget):
    def __init__(self):
        super().__init__()
        self._info_rows: dict[str, QFrame] = {}
        self._init_ui()

    # ── UI ───────────────────────────────────────────────────────────────
    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(_SCROLLBAR_QSS)
        outer.addWidget(scroll, 1)

        contenido = QWidget()
        contenido.setStyleSheet(_PAGE_QSS)
        scroll.setWidget(contenido)

        self._main_layout = QVBoxLayout(contenido)
        self._main_layout.setContentsMargins(32, 8, 32, 24)
        self._main_layout.setSpacing(18)

        self._construir_tarjeta_superior()
        self._construir_seccion_archivo()
        self._construir_seccion_registros()
        self._construir_seccion_acciones()

        self._main_layout.addStretch()

    def _construir_tarjeta_superior(self):
        card = QHBoxLayout()
        card.setSpacing(16)
        card.addWidget(_make_db_icon(64), alignment=Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        text_box.setContentsMargins(0, 2, 0, 0)

        lbl_t = QLabel("Base de datos")
        lbl_t.setObjectName("app_nombre")
        text_box.addWidget(lbl_t)

        self._lbl_path = QLabel("Cargando…")
        self._lbl_path.setObjectName("app_version")
        self._lbl_path.setWordWrap(True)
        text_box.addWidget(self._lbl_path)

        lbl_tag = QLabel("Información y respaldo del archivo de datos")
        lbl_tag.setObjectName("app_tagline")
        text_box.addWidget(lbl_tag)

        card.addLayout(text_box, 1)
        self._main_layout.addLayout(card)

    def _construir_seccion_archivo(self):
        self._main_layout.addSpacing(4)
        cab = QLabel("ARCHIVO")
        cab.setObjectName("section_header")
        self._main_layout.addWidget(cab)

        row_abrir = ActionRow(
            "fa5s.folder-open", "#d4a04c", "#332a18",
            "Abrir ubicación",
            "Muestra el archivo de la base de datos en el Explorador de Windows"
        )
        row_abrir.clicked.connect(self._abrir_carpeta)
        self._main_layout.addWidget(row_abrir)

        self._info_rows["tamano"] = _make_info_row("Tamaño", "—")
        self._main_layout.addWidget(self._info_rows["tamano"])

        self._info_rows["modif"] = _make_info_row("Última modificación", "—")
        self._main_layout.addWidget(self._info_rows["modif"])

    def _construir_seccion_registros(self):
        self._main_layout.addSpacing(4)
        cab = QLabel("REGISTROS")
        cab.setObjectName("section_header")
        self._main_layout.addWidget(cab)

        for key, label in [
            ("personal",       "Personal"),
            ("proveedores",    "Proveedores"),
            ("equipos",        "Equipos"),
            ("mantenimientos", "Mantenimientos"),
        ]:
            self._info_rows[key] = _make_info_row(label, "—")
            self._main_layout.addWidget(self._info_rows[key])

    def _construir_seccion_acciones(self):
        self._main_layout.addSpacing(4)
        cab = QLabel("ACCIONES")
        cab.setObjectName("section_header")
        self._main_layout.addWidget(cab)

        row_resp = ActionRow(
            "fa5s.save", "#6fc28f", "#1f3a26",
            "Crear respaldo",
            "Guarda una copia del archivo en otra ubicación"
        )
        row_resp.clicked.connect(self._crear_respaldo)
        self._main_layout.addWidget(row_resp)

        row_rest = ActionRow(
            "fa5s.history", "#d4a04c", "#332a18",
            "Restaurar respaldo",
            "Reemplaza la base actual con un archivo de respaldo guardado"
        )
        row_rest.clicked.connect(self._restaurar_respaldo)
        self._main_layout.addWidget(row_rest)

        row_vac = ActionRow(
            "fa5s.compress-arrows-alt", "#5cb1ff", "#1a2c3d",
            "Compactar base de datos",
            "Reduce el tamaño del archivo recuperando espacio de registros eliminados"
        )
        row_vac.clicked.connect(self._compactar)
        self._main_layout.addWidget(row_vac)

    # ── Datos ────────────────────────────────────────────────────────────
    def recargar(self):
        """Refresca los valores de tamaño, fecha, conteos y ruta."""
        path = _obtener_path_bd()
        self._lbl_path.setText(path or "No se pudo determinar la ruta")

        if path and os.path.exists(path):
            stat = os.stat(path)
            self._set_info("tamano", _formatear_tamano(stat.st_size))
            self._set_info("modif", _formatear_fecha(stat.st_mtime))
        else:
            self._set_info("tamano", "—")
            self._set_info("modif", "—")

        for key, count in _contar_registros().items():
            self._set_info(key, f"{count:,}")

    def _set_info(self, key: str, value: str):
        row = self._info_rows.get(key)
        if row is None:
            return
        lbl = row.findChild(QLabel, "info_value")
        if lbl is not None:
            lbl.setText(value)

    # ── Acciones ─────────────────────────────────────────────────────────
    def _abrir_carpeta(self):
        path = _obtener_path_bd()
        if not path:
            QMessageBox.warning(self, "Error", "No se pudo determinar la ruta de la base de datos.")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "Error", f"El archivo no existe:\n{path}")
            return
        try:
            # /select hace que Explorer abra la carpeta con el archivo seleccionado
            subprocess.Popen(f'explorer /select,"{path}"')
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo abrir el Explorador:\n{e}")

    def _crear_respaldo(self):
        path = _obtener_path_bd()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Error", "No se encontró el archivo de la base de datos.")
            return

        nombre_default = f"memoria_{datetime.now().strftime('%Y-%m-%d')}.db"
        destino, _ = QFileDialog.getSaveFileName(
            self, "Guardar respaldo", nombre_default,
            "Base de datos SQLite (*.db)"
        )
        if not destino:
            return

        try:
            shutil.copy2(path, destino)
            QMessageBox.information(
                self, "Respaldo creado",
                f"El respaldo se guardó correctamente en:\n\n{destino}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo crear el respaldo:\n{e}")

    def _restaurar_respaldo(self):
        # Confirmación previa con advertencia clara — esto es destructivo
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Restaurar respaldo")
        msg.setText(
            "Restaurar un respaldo REEMPLAZA la base de datos actual.\n\n"
            "Todos los registros agregados después de ese respaldo se perderán "
            "permanentemente. Esta acción no se puede deshacer."
        )
        btn_si = msg.addButton("Continuar y elegir respaldo", QMessageBox.ButtonRole.YesRole)
        btn_no = msg.addButton("Cancelar", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_no)
        msg.exec()
        if msg.clickedButton() != btn_si:
            return

        respaldo, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo de respaldo", "",
            "Base de datos SQLite (*.db)"
        )
        if not respaldo:
            return

        path_actual = _obtener_path_bd()
        if not path_actual:
            QMessageBox.warning(self, "Error", "No se pudo determinar la ruta de la base actual.")
            return

        try:
            # Por seguridad creamos un .before_restore antes de sobrescribir
            backup_seguridad = path_actual + ".before_restore"
            shutil.copy2(path_actual, backup_seguridad)
            shutil.copy2(respaldo, path_actual)
            QMessageBox.information(
                self, "Restaurado",
                "La base de datos se restauró correctamente.\n\n"
                f"Por seguridad guardé un respaldo de la versión anterior en:\n"
                f"{backup_seguridad}\n\n"
                "Reinicia la aplicación para que todos los datos se carguen desde "
                "el nuevo archivo."
            )
            self.recargar()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo restaurar:\n{e}")

    def _compactar(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Compactar base de datos")
        msg.setText(
            "Compactar reconstruye el archivo para reducir su tamaño tras "
            "eliminaciones masivas.\n\nEs una operación segura pero puede "
            "tardar unos segundos si la base es grande. ¿Continuar?"
        )
        btn_si = msg.addButton("Compactar", QMessageBox.ButtonRole.YesRole)
        btn_no = msg.addButton("Cancelar", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_si)
        msg.exec()
        if msg.clickedButton() != btn_si:
            return

        conn = connect_db(create_if_missing=False)
        if conn is None:
            QMessageBox.warning(self, "Error", "No se pudo abrir la base de datos.")
            return
        try:
            cur = conn.cursor()
            cur.execute("VACUUM")
            conn.commit()
            QMessageBox.information(self, "Listo", "La base de datos se compactó correctamente.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo compactar:\n{e}")
        finally:
            conn.close()

        self.recargar()

    # ── Lifecycle ────────────────────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        self.recargar()


# ── Estilos ──────────────────────────────────────────────────────────────────
_PAGE_QSS = """
    QLabel#app_nombre {
        color: white; font-size: 18px; font-weight: 500; background: transparent;
    }
    QLabel#app_version {
        color: #888; font-size: 12px; background: transparent;
    }
    QLabel#app_tagline {
        color: #999; font-size: 12px; background: transparent;
    }
    QLabel#section_header {
        color: #666; font-size: 10px; font-weight: 500;
        letter-spacing: 1px; background: transparent;
    }
"""

_SCROLLBAR_QSS = """
    QScrollArea, QScrollArea > QWidget > QWidget {
        background: transparent; border: none;
    }
    QScrollBar:vertical {
        background: #1a1a1a; width: 10px; margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #444; border-radius: 4px;
        min-height: 30px; margin: 2px;
    }
    QScrollBar::handle:vertical:hover { background: #555; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        background: none; height: 0; border: none;
    }
"""
