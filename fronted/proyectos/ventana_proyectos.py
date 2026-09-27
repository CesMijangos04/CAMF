"""
ventana_proyectos.py
====================

Ventana principal del módulo Proyectos de CAMF.

Muestra el listado de proyectos existentes en formato de cards, con:
  * Botón "+" arriba a la derecha para crear un nuevo proyecto
    (abre el wizard de 4 pasos definido en wizard_nuevo_proyecto.py).
  * Buscador con píldoras de filtro de estado (Todos / Borrador /
    En revisión / Aprobado / Entregado), estilo idéntico al de
    programados.py para mantener coherencia visual.
  * Grid de 2 columnas con cards de proyectos.
  * Doble clic sobre una card abre el "espacio de trabajo" del
    proyecto (próxima fase).
  * Estado vacío con "+" grande centrado, mismo patrón que Inventario.

Ejecución independiente durante desarrollo:

    python proyectos/ventana_proyectos.py

Integración en CAMF (una vez añadida la entrada en el sidebar de
main.py):

    from proyectos.ventana_proyectos import VentanaProyectos

Fase actual: datos en RAM. Migración a SQLite pendiente hasta que
el flujo de UI esté validado.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

import qtawesome as qta


# ═════════════════════════════════════════════════════════════════════════
#  PALETA DE COLORES CAMF
#  Replicada localmente para autonomía del módulo (sin imports cruzados).
# ═════════════════════════════════════════════════════════════════════════
COLOR_FONDO            = "#121212"
COLOR_SUPERFICIE       = "#1e1e1e"
COLOR_SUPERFICIE_HOVER = "#242424"
COLOR_INPUT_BG         = "#2b2b2b"   # coincide con programados.py
COLOR_INPUT_BG_HOVER   = "#353535"
COLOR_BORDE            = "#333333"
COLOR_BORDE_FUERTE     = "#444444"
COLOR_ACENTO           = "#0078d7"
COLOR_ACENTO_BRILLANTE = "#0094ff"   # hover de píldoras activas (programados.py)
COLOR_ACENTO_HOVER     = "#005a9e"   # hover del botón +
COLOR_TEXTO            = "#ffffff"
COLOR_TEXTO_SUAVE      = "#dddddd"
COLOR_TEXTO_MUTED      = "#aaaaaa"
COLOR_TEXTO_APAGADO    = "#888888"

# Estilo de los badges de estado del proyecto.
ESTADO_COLORES = {
    "borrador":    {"bg": "#888888", "fg": "#1a1a1a", "label": "Borrador"},
    "en_revision": {"bg": "#FAC775", "fg": "#412402", "label": "En revisión"},
    "aprobado":    {"bg": "#97C459", "fg": "#173404", "label": "Aprobado"},
    "entregado":   {"bg": "#0078d7", "fg": "#ffffff", "label": "Entregado"},
}

# Íconos qtawesome por tipo de proyecto (categoría gruesa del paso 2 del wizard).
TIPO_ICONOS = {
    "edificio":     "fa5s.building",
    "vivienda":     "fa5s.home",
    "comercial":    "fa5s.store",
    "industrial":   "fa5s.industry",
    "hospitalario": "fa5s.hospital",
    "educativo":    "fa5s.school",
    "hotelero":     "fa5s.bed",
    "otro":         "fa5s.ellipsis-h",
}

# Etapas de progreso mostradas como chips al pie de cada card.
ETAPAS = ("planos", "calculo", "docs")
ETAPAS_LABEL = {"planos": "Planos", "calculo": "Cálculo", "docs": "Docs"}


# ═════════════════════════════════════════════════════════════════════════
#  DATOS DE EJEMPLO EN RAM
#  A eliminar cuando conectemos la BD. Ejemplos vivos para validar la UI.
# ═════════════════════════════════════════════════════════════════════════
PROYECTOS_EJEMPLO = [
    {
        "id": "PRJ-001",
        "nombre": "Edificio aulas UAM",
        "cliente": "UAM Iztapalapa",
        "tipo": "edificio",
        "subtipo": "Aulas y oficinas · 4 pisos + sótano",
        "estado": "en_revision",
        "fecha_modificacion": "5 sept 2026",
        "progreso": {"planos": True, "calculo": True, "docs": False},
    },
    {
        "id": "PRJ-002",
        "nombre": "Plaza Nápoles",
        "cliente": "Inmobiliaria RGV",
        "tipo": "comercial",
        "subtipo": "Centro comercial · 24 locales",
        "estado": "aprobado",
        "fecha_modificacion": "22 ago 2026",
        "progreso": {"planos": True, "calculo": True, "docs": True},
    },
    {
        "id": "PRJ-003",
        "nombre": "Casa Fracc. Los Encinos",
        "cliente": "Fam. Hernández",
        "tipo": "vivienda",
        "subtipo": "Vivienda unifamiliar · 2 niveles",
        "estado": "borrador",
        "fecha_modificacion": "hoy",
        "progreso": {"planos": True, "calculo": False, "docs": False},
    },
    {
        "id": "PRJ-004",
        "nombre": "Oficinas Corp. Reforma",
        "cliente": "Grupo Financiero MX",
        "tipo": "edificio",
        "subtipo": "Edificio corporativo · 8 pisos",
        "estado": "entregado",
        "fecha_modificacion": "12 jul 2026",
        "progreso": {"planos": True, "calculo": True, "docs": True},
    },
]


# ═════════════════════════════════════════════════════════════════════════
#  ESTILO DE PÍLDORA (idéntico a programados.py)
# ═════════════════════════════════════════════════════════════════════════
def _pill_style(activo: bool) -> str:
    """QSS de una píldora de filtro. Coincide con programados.py."""
    if activo:
        return f"""
            QPushButton {{
                background: {COLOR_ACENTO}; color: white; border: none;
                padding: 5px 12px; border-radius: 12px;
                font-size: 11px; font-weight: 500;
            }}
            QPushButton:hover {{ background: {COLOR_ACENTO_BRILLANTE}; }}
        """
    return f"""
        QPushButton {{
            background: {COLOR_INPUT_BG}; color: {COLOR_TEXTO_MUTED}; border: none;
            padding: 5px 12px; border-radius: 12px; font-size: 11px;
        }}
        QPushButton:hover {{ background: {COLOR_INPUT_BG_HOVER}; color: #ccc; }}
    """


# ═════════════════════════════════════════════════════════════════════════
#  CARD DE PROYECTO
# ═════════════════════════════════════════════════════════════════════════
class CardProyecto(QFrame):
    """
    Card individual de un proyecto en el listado.
    Emite ``abrir_solicitado(proyecto_id)`` al doble clic.
    """

    abrir_solicitado = pyqtSignal(str)

    def __init__(self, proyecto: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.proyecto_id: str = proyecto["id"]

        self.setObjectName("cardProyecto")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(170)
        self.setStyleSheet(f"""
            QFrame#cardProyecto {{
                background-color: {COLOR_SUPERFICIE};
                border: 1px solid {COLOR_BORDE};
                border-radius: 8px;
            }}
            QFrame#cardProyecto:hover {{
                background-color: {COLOR_SUPERFICIE_HOVER};
                border: 1px solid {COLOR_ACENTO};
            }}
            QFrame#cardProyecto QLabel {{
                background: transparent;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # ── Fila superior: [ícono + nombre] .............. [badge estado]
        fila_top = QHBoxLayout()
        fila_top.setSpacing(8)

        icono_tipo = QLabel()
        icono_tipo.setPixmap(
            qta.icon(
                TIPO_ICONOS.get(proyecto["tipo"], "fa5s.folder"),
                color=COLOR_ACENTO,
            ).pixmap(20, 20)
        )
        icono_tipo.setFixedSize(20, 20)

        nombre = QLabel(proyecto["nombre"])
        nombre.setStyleSheet(f"""
            color: {COLOR_TEXTO};
            font-size: 14px;
            font-weight: 600;
        """)
        nombre.setWordWrap(True)

        est = ESTADO_COLORES.get(proyecto["estado"], ESTADO_COLORES["borrador"])
        badge = QLabel(est["label"])
        badge.setStyleSheet(f"""
            background-color: {est['bg']};
            color: {est['fg']};
            font-size: 10px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 3px;
        """)
        badge.setFixedHeight(20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        fila_top.addWidget(icono_tipo, 0, Qt.AlignmentFlag.AlignTop)
        fila_top.addWidget(nombre, 1)
        fila_top.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(fila_top)

        # ── Filas de información: cliente, subtipo, fecha
        layout.addWidget(self._fila_info("fa5s.user", proyecto["cliente"]))
        layout.addWidget(self._fila_info("fa5s.info-circle", proyecto["subtipo"]))
        layout.addWidget(self._fila_info(
            "fa5s.clock", f"Modificado: {proyecto['fecha_modificacion']}"
        ))

        layout.addStretch()

        # ── Chips de progreso por etapa
        chips_row = QHBoxLayout()
        chips_row.setSpacing(4)
        for etapa in ETAPAS:
            activa = bool(proyecto.get("progreso", {}).get(etapa, False))
            chips_row.addWidget(self._chip(ETAPAS_LABEL[etapa], activa))
        chips_row.addStretch()
        layout.addLayout(chips_row)

    # -------------------------------------------------------------------
    def _fila_info(self, qta_icono: str, texto: str) -> QWidget:
        """Fila horizontal: [ícono pequeño] [texto muted]."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        icono = QLabel()
        icono.setPixmap(qta.icon(qta_icono, color=COLOR_TEXTO_APAGADO).pixmap(12, 12))
        icono.setFixedSize(12, 12)

        lbl = QLabel(texto)
        lbl.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO};
            font-size: 11px;
        """)
        lbl.setWordWrap(True)

        h.addWidget(icono, 0, Qt.AlignmentFlag.AlignTop)
        h.addWidget(lbl, 1)
        return w

    def _chip(self, texto: str, activo: bool) -> QLabel:
        """Chip de etapa: azul si completada, gris si no."""
        if activo:
            bg, fg = COLOR_ACENTO, COLOR_TEXTO
        else:
            bg, fg = COLOR_BORDE, COLOR_TEXTO_APAGADO
        chip = QLabel(texto)
        chip.setStyleSheet(f"""
            background-color: {bg};
            color: {fg};
            font-size: 10px;
            font-weight: 500;
            padding: 3px 8px;
            border-radius: 3px;
        """)
        chip.setFixedHeight(20)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return chip

    # -------------------------------------------------------------------
    def mouseDoubleClickEvent(self, event):
        self.abrir_solicitado.emit(self.proyecto_id)
        super().mouseDoubleClickEvent(event)


# ═════════════════════════════════════════════════════════════════════════
#  VENTANA PRINCIPAL DEL MÓDULO PROYECTOS
# ═════════════════════════════════════════════════════════════════════════
class VentanaProyectos(QWidget):
    """
    Ventana principal del módulo Proyectos.

    Puede vivir como pestaña dentro de CAMF (main.py la instancia como
    página del QStackedWidget del sidebar) o ejecutarse aislada durante
    desarrollo con ``python proyectos/ventana_proyectos.py``.
    """

    COLUMNAS_GRID = 2

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("CAMF · Proyectos")

        # Estado de la UI ------------------------------------------------
        self._filtro_estado: str = "todos"
        self._texto_busqueda: str = ""

        # Fuente de datos: por ahora una lista en RAM. Mañana será una
        # consulta a db_manager. La estructura de cada dict se mantendrá
        # equivalente (id, nombre, cliente, tipo, subtipo, estado,
        # fecha_modificacion, progreso) para que la migración sea de una
        # sola línea (cambiar el origen, no la UI).
        self._proyectos: list[dict] = list(PROYECTOS_EJEMPLO)

        # Contador para IDs de proyectos nuevos (temporal, en fase RAM).
        # En BD se reemplaza por AUTOINCREMENT de SQLite.
        self._contador_id: int = max(
            (int(p["id"].split("-")[1]) for p in self._proyectos), default=0
        )

        self._build_ui()
        self._render()

    # ═══════════════════════════════════════════════════════════════════
    #  CONSTRUCCIÓN DE UI
    # ═══════════════════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        # Estilo global de la ventana. La regla "QScrollArea QLabel" evita
        # el bug de "rectángulo negro" de PyQt6/Windows 11 en scrolls.
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_FONDO};
                color: {COLOR_TEXTO};
            }}
            QScrollArea QLabel {{
                background: transparent;
            }}
        """)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 18, 20, 18)
        raiz.setSpacing(14)

        raiz.addLayout(self._construir_cabecera())
        raiz.addLayout(self._construir_barra_filtros())
        raiz.addWidget(self._construir_stack(), 1)

    # -------------------------------------------------------------------
    def _construir_cabecera(self) -> QHBoxLayout:
        """Título del módulo + botón '+' circular arriba a la derecha."""
        cabecera = QHBoxLayout()
        cabecera.setSpacing(10)

        titulo_box = QVBoxLayout()
        titulo_box.setSpacing(2)
        titulo_box.setContentsMargins(0, 0, 0, 0)

        titulo = QLabel("Proyectos")
        titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO};
            font-size: 20px;
            font-weight: 600;
            background: transparent;
        """)
        subtitulo = QLabel("Diseño eléctrico asistido")
        subtitulo.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO};
            font-size: 12px;
            background: transparent;
        """)
        titulo_box.addWidget(titulo)
        titulo_box.addWidget(subtitulo)

        self.btn_nuevo = QPushButton("+")
        self.btn_nuevo.setFixedSize(45, 45)
        self.btn_nuevo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_nuevo.setToolTip("Nuevo proyecto")
        self.btn_nuevo.setStyleSheet(f"""
            QPushButton {{
                font-size: 22px;
                background-color: {COLOR_ACENTO};
                color: white;
                border: none;
                border-radius: 22px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_ACENTO_HOVER};
            }}
        """)
        self.btn_nuevo.clicked.connect(self._abrir_wizard)

        cabecera.addLayout(titulo_box, 1)
        cabecera.addWidget(self.btn_nuevo, 0, Qt.AlignmentFlag.AlignTop)
        return cabecera

    # -------------------------------------------------------------------
    def _construir_barra_filtros(self) -> QHBoxLayout:
        """Buscador + píldoras de filtro de estado (mismo estilo que programados.py)."""
        fila = QHBoxLayout()
        fila.setSpacing(8)

        # Buscador con debounce ligero (150 ms). Mismo estilo visual y
        # dimensiones que el buscador de programados.py.
        self.input_busqueda = QLineEdit()
        self.input_busqueda.setPlaceholderText(
            "Buscar proyecto por nombre, cliente o tipo…"
        )
        self.input_busqueda.setFixedHeight(30)
        self.input_busqueda.setMinimumWidth(260)
        self.input_busqueda.setMaximumWidth(360)
        self.input_busqueda.setStyleSheet(f"""
            QLineEdit {{
                background: {COLOR_INPUT_BG}; color: {COLOR_TEXTO_SUAVE};
                border: 1px solid {COLOR_BORDE};
                border-radius: 6px; padding: 4px 10px; font-size: 11px;
            }}
            QLineEdit:focus {{ border: 1px solid {COLOR_ACENTO}; }}
        """)
        self._timer_busqueda = QTimer(self)
        self._timer_busqueda.setSingleShot(True)
        self._timer_busqueda.setInterval(150)
        self._timer_busqueda.timeout.connect(self._render)
        self.input_busqueda.textChanged.connect(self._on_busqueda_cambio)

        # Píldoras de filtro. Patrón idéntico al de programados.py:
        # QPushButton sencillo cuyo QSS se reemplaza al cambiar el
        # filtro activo (no usa :checked porque el mismo método sirve
        # para el estado inicial y para el cambio dinámico).
        self._pills: dict[str, QPushButton] = {}
        estados_visibles = [
            ("todos",       "Todos"),
            ("borrador",    "Borrador"),
            ("en_revision", "En revisión"),
            ("aprobado",    "Aprobado"),
            ("entregado",   "Entregado"),
        ]

        fila.addWidget(self.input_busqueda)

        for key, label in estados_visibles:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_pill_style(activo=(key == "todos")))
            btn.clicked.connect(lambda _c=False, k=key: self._cambiar_filtro(k))
            self._pills[key] = btn
            fila.addWidget(btn)

        fila.addStretch()
        return fila

    # -------------------------------------------------------------------
    def _construir_stack(self) -> QStackedWidget:
        """
        Contenedor con dos páginas:
          0 = scroll con grid de cards (cuando hay resultados)
          1 = mensaje vacío (sin proyectos o filtro sin coincidencias)
        """
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        # ── Página 0: scroll con grid ─────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Estilo de scroll idéntico al de programados.py.
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
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
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)

        self._cont_grid = QWidget()
        self._cont_grid.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._cont_grid)
        self._grid.setContentsMargins(0, 0, 8, 0)  # margen para no tapar scrollbar
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)
        self._scroll.setWidget(self._cont_grid)

        # ── Página 1: mensaje vacío ───────────────────────────────────
        self._vacio = QWidget()
        self._vacio.setStyleSheet("background: transparent;")
        vlay = QVBoxLayout(self._vacio)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.addStretch()

        self._lbl_vacio = QLabel("No hay proyectos que coincidan con el filtro.")
        self._lbl_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_vacio.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO};
            font-size: 13px;
            background: transparent;
        """)
        vlay.addWidget(self._lbl_vacio, 0, Qt.AlignmentFlag.AlignCenter)

        # Botón "+" grande, sólo visible cuando la lista está totalmente
        # vacía (no cuando el filtro deja cero coincidencias).
        self._btn_vacio = QPushButton("+")
        self._btn_vacio.setFixedSize(55, 55)
        self._btn_vacio.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_vacio.setStyleSheet(f"""
            QPushButton {{
                font-size: 26px;
                background-color: {COLOR_ACENTO};
                color: white;
                border: none;
                border-radius: 27px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_ACENTO_HOVER};
            }}
        """)
        self._btn_vacio.clicked.connect(self._abrir_wizard)
        vlay.addSpacing(12)
        vlay.addWidget(self._btn_vacio, 0, Qt.AlignmentFlag.AlignCenter)
        vlay.addStretch()

        self._stack.addWidget(self._scroll)
        self._stack.addWidget(self._vacio)
        return self._stack

    # ═══════════════════════════════════════════════════════════════════
    #  EVENTOS DE UI
    # ═══════════════════════════════════════════════════════════════════
    def _on_busqueda_cambio(self, texto: str) -> None:
        self._texto_busqueda = texto.strip().lower()
        self._timer_busqueda.start()

    def _cambiar_filtro(self, key: str) -> None:
        """Reemplaza el QSS de todas las pills y re-renderiza."""
        if key == self._filtro_estado:
            return
        self._filtro_estado = key
        for k, btn in self._pills.items():
            btn.setStyleSheet(_pill_style(activo=(k == key)))
        self._render()

    # ═══════════════════════════════════════════════════════════════════
    #  RENDER
    # ═══════════════════════════════════════════════════════════════════
    def _proyectos_filtrados(self) -> list[dict]:
        resultado = []
        for p in self._proyectos:
            if self._filtro_estado != "todos" and p["estado"] != self._filtro_estado:
                continue
            if self._texto_busqueda:
                cadena = " ".join([
                    p["nombre"].lower(),
                    p["cliente"].lower(),
                    p["tipo"].lower(),
                    p["subtipo"].lower(),
                ])
                if self._texto_busqueda not in cadena:
                    continue
            resultado.append(p)
        return resultado

    def _render(self) -> None:
        """Reconstruye el grid a partir del filtro/búsqueda actuales."""
        # Limpiar grid. Siempre hide() antes de deleteLater() para evitar
        # flicker de ventanas con ícono de python.exe (ver notas del proyecto).
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

        filtrados = self._proyectos_filtrados()

        if not filtrados:
            if not self._proyectos:
                # Estado genuinamente vacío: invitación a crear el primero.
                self._lbl_vacio.setText(
                    "Aún no hay proyectos. Da clic en + para crear el primero."
                )
                self._btn_vacio.show()
            else:
                # Hay proyectos, solo que el filtro no matchea nada.
                self._lbl_vacio.setText(
                    "No hay proyectos que coincidan con el filtro."
                )
                self._btn_vacio.hide()
            self._stack.setCurrentWidget(self._vacio)
            return

        self._stack.setCurrentWidget(self._scroll)

        for idx, p in enumerate(filtrados):
            card = CardProyecto(p, parent=self._cont_grid)
            card.abrir_solicitado.connect(self._abrir_proyecto)
            self._grid.addWidget(
                card,
                idx // self.COLUMNAS_GRID,
                idx % self.COLUMNAS_GRID,
            )

        # Asegurar reparto uniforme de anchura entre columnas.
        for c in range(self.COLUMNAS_GRID):
            self._grid.setColumnStretch(c, 1)

    # ═══════════════════════════════════════════════════════════════════
    #  ACCIONES
    # ═══════════════════════════════════════════════════════════════════
    def _abrir_wizard(self) -> None:
        """Abre el wizard de nuevo proyecto y agrega el resultado al listado."""
        # Import lazy para evitar coste en el arranque de CAMF y para
        # facilitar que el módulo se pruebe pieza por pieza.
        try:
            from proyectos.wizard_nuevo_proyecto import WizardNuevoProyecto
        except ImportError:
            # Fallback: ejecución independiente desde la propia carpeta.
            from wizard_nuevo_proyecto import WizardNuevoProyecto  # type: ignore

        wiz = WizardNuevoProyecto(parent=self)
        wiz.proyecto_creado.connect(self._agregar_proyecto)
        wiz.exec()

    def _agregar_proyecto(self, datos: dict) -> None:
        """
        Recibe el dict de un proyecto recién creado por el wizard y lo
        inserta al principio del listado. En fase RAM asigna el id con
        un contador local; cuando entre BD, delegará el INSERT.
        """
        self._contador_id += 1
        datos["id"] = f"PRJ-{self._contador_id:03d}"
        datos.setdefault("estado", "borrador")
        datos.setdefault("fecha_modificacion", "hoy")
        datos.setdefault("progreso", {"planos": False, "calculo": False, "docs": False})

        # Al principio para que sea inmediatamente visible.
        self._proyectos.insert(0, datos)
        self._render()

    def _abrir_proyecto(self, proyecto_id: str) -> None:
        """Abre el espacio de trabajo del proyecto en una ventana independiente."""
        proy = next((p for p in self._proyectos if p["id"] == proyecto_id), None)
        if proy is None:
            return

        # Import lazy (mismo patrón que _abrir_wizard).
        try:
            from proyectos.espacio_trabajo import EspacioTrabajoProyecto
        except ImportError:
            from espacio_trabajo import EspacioTrabajoProyecto  # type: ignore

        # Guardar referencia: sin esto Python garbage-collectaría la
        # ventana casi de inmediato (no tiene parent Qt). El attr se
        # inicializa perezosamente para no ensuciar __init__.
        if not hasattr(self, "_ventanas_abiertas"):
            self._ventanas_abiertas: list = []

        ventana = EspacioTrabajoProyecto(proy)
        # WA_DeleteOnClose libera memoria cuando el usuario cierra la
        # ventana con la X, sin acumular ventanas viejas en RAM.
        ventana.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # Al cerrarse, quitar de la lista para permitir GC.
        def _limpiar_referencia(_obj=None, v=ventana):
            if v in self._ventanas_abiertas:
                self._ventanas_abiertas.remove(v)
        ventana.destroyed.connect(_limpiar_referencia)

        self._ventanas_abiertas.append(ventana)
        ventana.show()


# ═════════════════════════════════════════════════════════════════════════
#  EJECUCIÓN INDEPENDIENTE (desarrollo)
# ═════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Agregar fronted/ al sys.path para importar módulos del padre
    # (db_manager, calculos_electricos) cuando se necesiten.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    app = QApplication(sys.argv)

    main = QMainWindow()
    main.setWindowTitle("CAMF · Proyectos (desarrollo)")
    main.resize(1050, 720)
    main.setStyleSheet(f"QMainWindow {{ background-color: {COLOR_FONDO}; }}")

    logo_path = Path(__file__).resolve().parent.parent / "icons" / "logo.png"
    if logo_path.exists():
        main.setWindowIcon(QIcon(str(logo_path)))

    ventana = VentanaProyectos()
    main.setCentralWidget(ventana)
    main.show()

    sys.exit(app.exec())
