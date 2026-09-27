# responsables_config.py
"""
Páginas internas para la sección "Responsables" de Configuración.

Tres widgets que ConfiguracionWindow apila en su QStackedWidget:

    ResponsablesSelectorPage  →  selector Personal | Proveedor
    ListaPersonalPage         →  lista de personal con CRUD
    ListaProveedoresPage      →  lista de proveedores con CRUD

NOTA SOBRE ESTILOS: NO usamos self.setStyleSheet(...) a nivel de las páginas.
Eso afecta el motor de renderizado de Qt para los QDialog descendientes
(AgregarResponsableDialog se abre con parent=esta_página) y los hace verse
"más planos / grises" en lugar de respetar el dark mode nativo de Windows 11.
En cambio, cada widget recibe su propio setStyleSheet específico.

Comportamiento de filas:
- El click en la fila NO hace nada (no abre edición). El usuario debe pulsar
  el icono de editar para editar. El bote de basura elimina con confirmación.
- Hover sí cambia el fondo de la fila como pista visual de unidad/agrupación.
"""

import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QSizePolicy, QLineEdit, QMessageBox, QStyleFactory
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
import qtawesome as qta

from db_manager import connect_db
from agregar_responsable import AgregarResponsableDialog


def _buscar_widget_compatible(widget_origen) -> QWidget | None:
    """
    Encuentra un widget en la app que sirva como "padre de respaldo"
    para que los diálogos hereden su contexto de estilo.

    EL PROBLEMA: el diálogo abierto desde programar_nuevo se ve nativo
    porque hereda el QStyleSheetStyle de ese widget (que envuelve el
    estilo windows11 original). El mismo diálogo abierto desde mis
    páginas de configuración se ve gris porque por algún detalle del
    polish/render de Qt no recibe el mismo wrapper.

    EL TRUCO: en vez de pelear contra Qt, simplemente usamos
    programar_nuevo como padre del diálogo cuando se abra desde
    configuración. Así el diálogo hereda el mismo contexto exacto.

    Si no encontramos programar_nuevo (por ejemplo si el usuario nunca
    entró a Mantenimientos y el widget no se creó), devolvemos None y
    el caller usará el comportamiento por defecto.
    """
    try:
        from programar_nuevo import ProgramarNuevoWidget
    except ImportError:
        return None

    if widget_origen is None:
        return None

    raiz = widget_origen.window()
    if raiz is None:
        return None

    # findChildren busca recursivamente en todos los descendientes
    candidatos = raiz.findChildren(ProgramarNuevoWidget)
    return candidatos[0] if candidatos else None


# ── Paleta de avatares ───────────────────────────────────────────────────────
AVATAR_PALETA = [
    ("#5cb1ff", "#1a2c3d"),  # azul
    ("#6fc28f", "#1f3a26"),  # verde
    ("#d4a04c", "#332a18"),  # ámbar
    ("#e67e22", "#3a2418"),  # naranja
    ("#b88cff", "#2a1f3a"),  # morado
    ("#f1c40f", "#3a3318"),  # amarillo
]


def _color_avatar(seed: str):
    if not seed:
        return AVATAR_PALETA[0]
    idx = sum(ord(c) for c in seed) % len(AVATAR_PALETA)
    return AVATAR_PALETA[idx]


def _iniciales(nombre: str, ap_paterno: str) -> str:
    n = (nombre or "").strip()
    p = (ap_paterno or "").strip()
    if n and p:
        return (n[0] + p[0]).upper()
    if n:
        return (n[:2]).upper()
    return "??"


# ── Acceso a BD ──────────────────────────────────────────────────────────────
def cargar_personal() -> list[dict]:
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return []
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, id_personal, nombre, ap_paterno, ap_materno,
                   telefono, correo, puesto
            FROM personal
            ORDER BY nombre COLLATE NOCASE, ap_paterno COLLATE NOCASE
        """)
        rows = cur.fetchall()
    except Exception as e:
        print(f"[responsables_config] cargar_personal falló: {e}")
        rows = []
    finally:
        conn.close()
    return [
        {
            "id": r[0], "id_personal": r[1], "nombre": r[2],
            "ap_paterno": r[3], "ap_materno": r[4],
            "telefono": r[5], "correo": r[6], "puesto": r[7],
        }
        for r in rows
    ]


def cargar_proveedores() -> list[dict]:
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return []
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, id_proveedor, empresa, telefono, correo, contactos_json
            FROM proveedores
            ORDER BY empresa COLLATE NOCASE
        """)
        rows = cur.fetchall()
    except Exception as e:
        print(f"[responsables_config] cargar_proveedores falló: {e}")
        rows = []
    finally:
        conn.close()

    out = []
    for r in rows:
        try:
            contactos = json.loads(r[5]) if r[5] else []
        except Exception:
            contactos = []
        out.append({
            "id": r[0], "id_proveedor": r[1], "empresa": r[2],
            "telefono": r[3], "correo": r[4], "contactos": contactos,
        })
    return out


def eliminar_personal(id_pk: int) -> bool:
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM personal WHERE id = ?", (id_pk,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[responsables_config] eliminar_personal falló: {e}")
        return False
    finally:
        conn.close()


def eliminar_proveedor(id_pk: int) -> bool:
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM proveedores WHERE id = ?", (id_pk,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[responsables_config] eliminar_proveedor falló: {e}")
        return False
    finally:
        conn.close()


# ── Estilo reutilizable para scrollbars ──────────────────────────────────────
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
"""


# ── Botón de acción inline con hover de color ───────────────────────────────
class IconActionButton(QPushButton):
    """
    Botón pequeño plano con icono qtawesome. El icono cambia de color al hover
    para indicar interactividad (azul para editar, rojo para eliminar).
    """
    def __init__(self, icon_name: str, base_color: str = "#aaa",
                 hover_color: str = "#5cb1ff", tooltip: str = "", parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._base_color = base_color
        self._hover_color = hover_color

        self.setFixedSize(28, 28)
        self.setIconSize(QSize(14, 14))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #3a3a3a;
            }
        """)
        self._set_icon(base_color)

    def _set_icon(self, color: str):
        self.setIcon(qta.icon(self._icon_name, color=color))

    def enterEvent(self, event):
        self._set_icon(self._hover_color)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_icon(self._base_color)
        super().leaveEvent(event)


# ── Helpers visuales para avatares ───────────────────────────────────────────
def _make_avatar_iniciales(nombre: str, ap_paterno: str) -> QLabel:
    fg, bg = _color_avatar((nombre or "") + (ap_paterno or ""))
    lbl = QLabel(_iniciales(nombre, ap_paterno))
    lbl.setFixedSize(36, 36)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    lbl.setStyleSheet(f"""
        background: {bg};
        color: {fg};
        border-radius: 18px;
        font-size: 12px;
        font-weight: 500;
    """)
    return lbl


def _make_avatar_icono(seed: str, icon_name: str = "fa5s.building") -> QFrame:
    fg, bg = _color_avatar(seed)
    frame = QFrame()
    frame.setFixedSize(36, 36)
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    frame.setStyleSheet(f"background: {bg}; border-radius: 8px;")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ico = QLabel()
    ico.setPixmap(qta.icon(icon_name, color=fg).pixmap(18, 18))
    ico.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(ico)
    return frame


# ── Fila de registro ─────────────────────────────────────────────────────────
class RegistroRow(QFrame):
    """
    [avatar] Título                                [edit] [trash]
             subtítulo

    El click en la fila NO emite editar (el usuario debe usar el ícono).
    Solo cambia el fondo en hover como pista visual.
    """
    editar = pyqtSignal()
    eliminar = pyqtSignal()

    def __init__(self, avatar_widget: QWidget, titulo: str, subtitulo: str,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("registro_row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Estilo SOLO en este widget — no contiene al diálogo, no propaga
        self.setStyleSheet("""
            QFrame#registro_row {
                background: #2b2b2b;
                border-radius: 8px;
                border: 1px solid transparent;
            }
            QFrame#registro_row:hover {
                background: #333;
                border: 1px solid #3a3a3a;
            }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        lay.addWidget(avatar_widget, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        lbl_t = QLabel(titulo)
        lbl_t.setStyleSheet(
            "color: white; font-size: 13px; font-weight: 500; background: transparent;"
        )
        text_box.addWidget(lbl_t)
        lbl_s = QLabel(subtitulo)
        lbl_s.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        text_box.addWidget(lbl_s)
        lay.addLayout(text_box, 1)

        # Botones de acción con hover de color
        btn_edit = IconActionButton(
            "fa5s.edit", base_color="#aaa", hover_color="#5cb1ff", tooltip="Editar"
        )
        btn_edit.clicked.connect(self.editar.emit)
        lay.addWidget(btn_edit, alignment=Qt.AlignmentFlag.AlignVCenter)

        btn_del = IconActionButton(
            "fa5s.trash", base_color="#aaa", hover_color="#e74c3c", tooltip="Eliminar"
        )
        btn_del.clicked.connect(self.eliminar.emit)
        lay.addWidget(btn_del, alignment=Qt.AlignmentFlag.AlignVCenter)

    # NOTA: NO sobreescribimos mousePressEvent — el click en la fila no hace nada.


# ── Estilos para inputs/botones (aplicados a widgets individuales) ───────────
_SEARCH_QSS = """
    QLineEdit {
        background: #2b2b2b;
        color: white;
        border: 1px solid #3a3a3a;
        border-radius: 6px;
        padding: 7px 12px;
        font-size: 13px;
    }
    QLineEdit:focus {
        border: 1px solid #0078d7;
    }
"""

_BTN_AGREGAR_QSS = """
    QPushButton {
        background: #0078d7;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 7px 14px;
        font-size: 13px;
        font-weight: 500;
    }
    QPushButton:hover { background: #0094ff; }
"""


# ── Página 1: Selector Personal | Proveedor ──────────────────────────────────
class ResponsablesSelectorPage(QWidget):
    solicitar_personal = pyqtSignal()
    solicitar_proveedor = pyqtSignal()

    def __init__(self):
        super().__init__()
        # SIN setStyleSheet en self — los estilos van en cada fila
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 8, 32, 24)
        outer.setSpacing(8)

        self._fila_personal, self._lbl_count_personal = self._build_fila(
            "fa5s.id-badge", "#6fc28f", "#1f3a26",
            "Personal", "Empleados internos"
        )
        self._fila_personal.mousePressEvent = lambda e: self._click_personal(e)
        outer.addWidget(self._fila_personal)

        self._fila_proveedor, self._lbl_count_proveedor = self._build_fila(
            "fa5s.store", "#d4a04c", "#332a18",
            "Proveedor", "Empresas externas"
        )
        self._fila_proveedor.mousePressEvent = lambda e: self._click_proveedor(e)
        outer.addWidget(self._fila_proveedor)

        outer.addStretch()

    def _build_fila(self, icon_name, color, chip_bg, titulo, descripcion_base):
        f = QFrame()
        f.setObjectName("selector_row")
        f.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        f.setFrameShape(QFrame.Shape.NoFrame)
        f.setCursor(Qt.CursorShape.PointingHandCursor)
        f.setMinimumHeight(76)
        # Estilo en la propia fila — no afecta al diálogo (no es ancestro)
        f.setStyleSheet("""
            QFrame#selector_row {
                background: #2b2b2b;
                border-radius: 8px;
                border: 1px solid transparent;
            }
            QFrame#selector_row:hover {
                background: #333;
                border: 1px solid #0078d7;
            }
        """)

        lay = QHBoxLayout(f)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(16)

        chip = QFrame()
        chip.setFixedSize(44, 44)
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setStyleSheet(f"background: {chip_bg}; border-radius: 8px;")
        chip_lay = QVBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico = QLabel()
        ico.setPixmap(qta.icon(icon_name, color=color).pixmap(22, 22))
        ico.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip_lay.addWidget(ico)
        lay.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        lbl_t = QLabel(titulo)
        lbl_t.setStyleSheet(
            "color: white; font-size: 15px; font-weight: 500; background: transparent;"
        )
        text_box.addWidget(lbl_t)
        lbl_s = QLabel(descripcion_base)
        lbl_s.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
        text_box.addWidget(lbl_s)
        lay.addLayout(text_box, 1)

        chev = QLabel()
        chev.setPixmap(qta.icon("fa5s.chevron-right", color="#666").pixmap(14, 14))
        chev.setFixedSize(14, 14)
        chev.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay.addWidget(chev, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Devolvemos también el label del subtítulo para actualizarlo dinámicamente
        return f, lbl_s

    def _click_personal(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.solicitar_personal.emit()

    def _click_proveedor(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.solicitar_proveedor.emit()

    def showEvent(self, event):
        super().showEvent(event)
        n_p = len(cargar_personal())
        n_v = len(cargar_proveedores())
        self._lbl_count_personal.setText(
            f"Empleados internos — {n_p} {'registrado' if n_p == 1 else 'registrados'}"
        )
        self._lbl_count_proveedor.setText(
            f"Empresas externas — {n_v} {'registrada' if n_v == 1 else 'registradas'}"
        )


# ── Página 2: Lista de Personal ──────────────────────────────────────────────
class ListaPersonalPage(QWidget):
    contador_cambio = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._registros: list[dict] = []
        self._rows: list[RegistroRow] = []
        # SIN setStyleSheet en self — los estilos van en cada widget interno
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 8, 32, 24)
        outer.setSpacing(12)

        # Barra superior: buscador + botón agregar
        top = QHBoxLayout()
        top.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar por nombre, ID, puesto o correo…")
        self._search.setStyleSheet(_SEARCH_QSS)
        self._search.addAction(
            qta.icon("fa5s.search", color="#777"),
            QLineEdit.ActionPosition.LeadingPosition
        )
        self._search.textChanged.connect(self._aplicar_filtro)
        top.addWidget(self._search, 1)

        btn_add = QPushButton("  Agregar")
        btn_add.setStyleSheet(_BTN_AGREGAR_QSS)
        btn_add.setIcon(qta.icon("fa5s.plus", color="white"))
        btn_add.setIconSize(QSize(12, 12))
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(self.abrir_agregar)
        top.addWidget(btn_add)

        outer.addLayout(top)

        # Scroll con la lista de filas
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(SCROLLBAR_QSS)

        contenido = QWidget()
        self._lista_layout = QVBoxLayout(contenido)
        self._lista_layout.setContentsMargins(0, 0, 0, 0)
        self._lista_layout.setSpacing(6)

        self._lbl_empty = QLabel("No hay personal registrado. Pulsa “Agregar” para empezar.")
        self._lbl_empty.setStyleSheet(
            "color: #777; font-size: 13px; background: transparent;"
        )
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setContentsMargins(0, 40, 0, 0)
        self._lista_layout.addWidget(self._lbl_empty)

        self._lista_layout.addStretch()
        scroll.setWidget(contenido)
        outer.addWidget(scroll, 1)

    # ── Datos ────────────────────────────────────────────────────────────
    def texto_contador(self) -> str:
        n = len(self._registros)
        return f"{n} {'persona registrada' if n == 1 else 'personas registradas'}"

    def recargar(self):
        for row in self._rows:
            self._lista_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []

        self._registros = cargar_personal()

        idx_insert = 0
        for r in self._registros:
            row = self._build_row(r)
            self._lista_layout.insertWidget(idx_insert, row)
            self._rows.append(row)
            idx_insert += 1

        self._lbl_empty.setVisible(len(self._registros) == 0)
        self._aplicar_filtro(self._search.text())
        self.contador_cambio.emit()

    def _build_row(self, r: dict) -> RegistroRow:
        avatar = _make_avatar_iniciales(r["nombre"], r["ap_paterno"])
        nombre_completo = " ".join(filter(None, [
            (r.get("nombre") or "").strip(),
            (r.get("ap_paterno") or "").strip(),
            (r.get("ap_materno") or "").strip(),
        ])) or "(sin nombre)"
        # Subtítulo: ID · puesto · teléfono · correo (el correo es lo nuevo)
        subt = " · ".join(filter(None, [
            r.get("id_personal") or "",
            r.get("puesto") or "",
            r.get("telefono") or "",
            r.get("correo") or "",
        ]))
        row = RegistroRow(avatar, nombre_completo, subt)
        row.editar.connect(lambda datos=r: self.abrir_editar(datos))
        row.eliminar.connect(lambda datos=r: self.eliminar_registro(datos))
        return row

    def _aplicar_filtro(self, texto: str):
        texto = (texto or "").strip().lower()
        for row, r in zip(self._rows, self._registros):
            if not texto:
                row.setVisible(True)
                continue
            haystack = " ".join([
                (r.get("nombre") or ""),
                (r.get("ap_paterno") or ""),
                (r.get("ap_materno") or ""),
                (r.get("id_personal") or ""),
                (r.get("puesto") or ""),
                (r.get("telefono") or ""),
                (r.get("correo") or ""),
            ]).lower()
            row.setVisible(texto in haystack)

    # ── CRUD ─────────────────────────────────────────────────────────────
    def _abrir_dialogo_responsable(self, modo_edicion: bool, datos: dict | None):
        # Truco: usar el widget de programar_nuevo como padre del diálogo
        # para heredar su contexto de estilo (QStyleSheetStyle que envuelve
        # windows11). Es el mismo contexto que ya hace que el diálogo se
        # vea bien cuando se abre desde programar_nuevo, así nos aseguramos
        # que aquí se vea idéntico. Si no está disponible (raro), usamos
        # parent=None y el diálogo abre con el estilo por defecto de la app.
        parent_dialogo = _buscar_widget_compatible(self) or None

        dialogo = AgregarResponsableDialog(
            personal_registrado=self._registros,
            proveedores_registrados=[],
            parent=parent_dialogo,
            modo_edicion=modo_edicion,
            tipo="personal",
            datos=datos,
            # on_guardado: callback que el diálogo llama después de cada
            # save exitoso. Refresca la lista detrás del diálogo en vivo.
            on_guardado=self.recargar,
        )
        dialogo.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialogo.exec()
        self.recargar()

    def abrir_agregar(self):
        self._abrir_dialogo_responsable(modo_edicion=False, datos=None)

    def abrir_editar(self, datos: dict):
        self._abrir_dialogo_responsable(modo_edicion=True, datos=datos)

    def eliminar_registro(self, datos: dict):
        nombre = " ".join(filter(None, [
            (datos.get("nombre") or "").strip(),
            (datos.get("ap_paterno") or "").strip(),
        ])) or "este personal"

        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar personal")
        msg.setText(f"¿Eliminar a {nombre}?\n\nEsta acción no se puede deshacer.")
        btn_si = msg.addButton("Eliminar", QMessageBox.ButtonRole.YesRole)
        btn_no = msg.addButton("Cancelar", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_no)
        msg.exec()

        if msg.clickedButton() != btn_si:
            return

        if eliminar_personal(datos["id"]):
            self.recargar()
        else:
            QMessageBox.warning(self, "Error", "No se pudo eliminar el registro.")

    def showEvent(self, event):
        super().showEvent(event)
        self.recargar()


# ── Página 3: Lista de Proveedores ───────────────────────────────────────────
class ListaProveedoresPage(QWidget):
    contador_cambio = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._registros: list[dict] = []
        self._rows: list[RegistroRow] = []
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 8, 32, 24)
        outer.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar por empresa, ID, teléfono o correo…")
        self._search.setStyleSheet(_SEARCH_QSS)
        self._search.addAction(
            qta.icon("fa5s.search", color="#777"),
            QLineEdit.ActionPosition.LeadingPosition
        )
        self._search.textChanged.connect(self._aplicar_filtro)
        top.addWidget(self._search, 1)

        btn_add = QPushButton("  Agregar")
        btn_add.setStyleSheet(_BTN_AGREGAR_QSS)
        btn_add.setIcon(qta.icon("fa5s.plus", color="white"))
        btn_add.setIconSize(QSize(12, 12))
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(self.abrir_agregar)
        top.addWidget(btn_add)

        outer.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(SCROLLBAR_QSS)

        contenido = QWidget()
        self._lista_layout = QVBoxLayout(contenido)
        self._lista_layout.setContentsMargins(0, 0, 0, 0)
        self._lista_layout.setSpacing(6)

        self._lbl_empty = QLabel("No hay proveedores registrados. Pulsa “Agregar” para empezar.")
        self._lbl_empty.setStyleSheet(
            "color: #777; font-size: 13px; background: transparent;"
        )
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setContentsMargins(0, 40, 0, 0)
        self._lista_layout.addWidget(self._lbl_empty)

        self._lista_layout.addStretch()
        scroll.setWidget(contenido)
        outer.addWidget(scroll, 1)

    # ── Datos ────────────────────────────────────────────────────────────
    def texto_contador(self) -> str:
        n = len(self._registros)
        return f"{n} {'proveedor registrado' if n == 1 else 'proveedores registrados'}"

    def recargar(self):
        for row in self._rows:
            self._lista_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []

        self._registros = cargar_proveedores()

        idx_insert = 0
        for r in self._registros:
            row = self._build_row(r)
            self._lista_layout.insertWidget(idx_insert, row)
            self._rows.append(row)
            idx_insert += 1

        self._lbl_empty.setVisible(len(self._registros) == 0)
        self._aplicar_filtro(self._search.text())
        self.contador_cambio.emit()

    def _build_row(self, r: dict) -> RegistroRow:
        avatar = _make_avatar_icono(r.get("empresa") or "", "fa5s.building")
        empresa = (r.get("empresa") or "").strip() or "(sin empresa)"
        n_contactos = len(r.get("contactos") or [])
        # Subtítulo: ID · teléfono · correo · contactos (el correo es lo nuevo)
        partes_sub = [
            r.get("id_proveedor") or "",
            r.get("telefono") or "",
            r.get("correo") or "",
        ]
        if n_contactos:
            partes_sub.append(
                f"{n_contactos} {'contacto' if n_contactos == 1 else 'contactos'}"
            )
        subt = " · ".join(filter(None, partes_sub))
        row = RegistroRow(avatar, empresa, subt)
        row.editar.connect(lambda datos=r: self.abrir_editar(datos))
        row.eliminar.connect(lambda datos=r: self.eliminar_registro(datos))
        return row

    def _aplicar_filtro(self, texto: str):
        texto = (texto or "").strip().lower()
        for row, r in zip(self._rows, self._registros):
            if not texto:
                row.setVisible(True)
                continue
            haystack = " ".join([
                (r.get("empresa") or ""),
                (r.get("id_proveedor") or ""),
                (r.get("telefono") or ""),
                (r.get("correo") or ""),
            ]).lower()
            row.setVisible(texto in haystack)

    # ── CRUD ─────────────────────────────────────────────────────────────
    def _abrir_dialogo_responsable(self, modo_edicion: bool, datos: dict | None):
        parent_dialogo = _buscar_widget_compatible(self) or None

        dialogo = AgregarResponsableDialog(
            personal_registrado=[],
            proveedores_registrados=self._registros,
            parent=parent_dialogo,
            modo_edicion=modo_edicion,
            tipo="proveedor",
            datos=datos,
            on_guardado=self.recargar,
        )
        dialogo.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialogo.exec()
        self.recargar()

    def abrir_agregar(self):
        self._abrir_dialogo_responsable(modo_edicion=False, datos=None)

    def abrir_editar(self, datos: dict):
        self._abrir_dialogo_responsable(modo_edicion=True, datos=datos)

    def eliminar_registro(self, datos: dict):
        empresa = (datos.get("empresa") or "").strip() or "este proveedor"

        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar proveedor")
        msg.setText(f"¿Eliminar a {empresa}?\n\nEsta acción no se puede deshacer.")
        btn_si = msg.addButton("Eliminar", QMessageBox.ButtonRole.YesRole)
        btn_no = msg.addButton("Cancelar", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_no)
        msg.exec()

        if msg.clickedButton() != btn_si:
            return

        if eliminar_proveedor(datos["id"]):
            self.recargar()
        else:
            QMessageBox.warning(self, "Error", "No se pudo eliminar el registro.")

    def showEvent(self, event):
        super().showEvent(event)
        self.recargar()
