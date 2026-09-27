"""
espacio_trabajo.py
==================

Ventana del espacio de trabajo de un proyecto. Se abre al hacer doble
clic sobre una card del listado. Contiene:

  * Header superior con: botón toggle del sidebar, botón Volver,
    nombre del proyecto + subtítulo, badge de estado.
  * Sidebar izquierdo colapsable con las 7 etapas del proyecto
    (patrón visual idéntico al sidebar de main.py de CAMF).
  * Área de contenido con placeholder informativo por etapa.

Cada etapa es hoy un placeholder que describe qué hará. Se irán
implementando una por una:

  1. Planos         — cargar PDF/imagen por nivel + calibrar escala.
  2. Delimitación   — trazar muros y polígonos de habitaciones.
  3. Elementos      — colocar simbología eléctrica sobre el plano.
  4. Tableros       — indicar ubicación de tableros.
  5. Agrupación    — motor propone circuitos, fases y trayectorias.
  6. Cálculos       — cuadros de carga, balance por fase.
  7. Documentación — unifilar, memoria técnica, planos finales.

Se instancia como QMainWindow independiente sin parent, para permitir
tener varios proyectos abiertos al mismo tiempo. VentanaProyectos
guarda una referencia interna para evitar garbage collection.

Ejecución independiente:
    python proyectos/espacio_trabajo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

import qtawesome as qta

# Sesión C — modelo de proyecto abierto + UI real de la etapa "Planos".
# Import lazy dentro de _construir_body para que esta ventana pueda
# probarse sin las dependencias de canvas cuando aún no hay planos.


# ═════════════════════════════════════════════════════════════════════════
#  PALETA CAMF (replicada localmente para autonomía)
# ═════════════════════════════════════════════════════════════════════════
COLOR_FONDO           = "#121212"
COLOR_HEADER          = "#141414"
COLOR_SIDEBAR         = "#1a1a1a"
COLOR_SIDEBAR_ITEM    = "#1e1e1e"   # fondo del item activo
COLOR_SIDEBAR_HOVER   = "#242424"
COLOR_SUPERFICIE      = "#1e1e1e"
COLOR_BORDE           = "#333333"
COLOR_BORDE_SUAVE     = "#2a2a2a"
COLOR_ACENTO          = "#0078d7"
COLOR_ACENTO_SUAVE    = "#85B7EB"
COLOR_ACENTO_HOVER    = "#005a9e"
COLOR_TEXTO           = "#ffffff"
COLOR_TEXTO_SUAVE     = "#dddddd"
COLOR_TEXTO_MUTED     = "#aaaaaa"
COLOR_TEXTO_APAGADO   = "#666666"
COLOR_INPUT_BG        = "#2b2b2b"
COLOR_INPUT_BG_HOVER  = "#353535"

# Estilo de los badges de estado (idéntico a ventana_proyectos.py).
ESTADO_COLORES = {
    "borrador":    {"bg": "#888888", "fg": "#1a1a1a", "label": "Borrador"},
    "en_revision": {"bg": "#FAC775", "fg": "#412402", "label": "En revisión"},
    "aprobado":    {"bg": "#97C459", "fg": "#173404", "label": "Aprobado"},
    "entregado":   {"bg": "#0078d7", "fg": "#ffffff", "label": "Entregado"},
}


# ═════════════════════════════════════════════════════════════════════════
#  DEFINICIÓN DE LAS 7 ETAPAS
#  Cada etapa es un diccionario que define su icono, título, descripción
#  y opcionalmente un "info_banner" con una pista contextual. El diseño
#  del placeholder se genera automáticamente desde estos datos, así que
#  añadir/quitar/reordenar etapas es cambio de un solo lugar.
# ═════════════════════════════════════════════════════════════════════════
ETAPAS = [
    {
        "key": "planos",
        "label": "Planos",
        "icono": "fa5s.map",
        "titulo": "Planos por nivel",
        "descripcion": (
            "Carga el plano arquitectónico de cada nivel del edificio en "
            "PDF o imagen. Calibra la escala con dos puntos y una "
            "distancia conocida para que las mediciones sean reales."
        ),
        "info_banner": "Nombra cada plano según el nivel al que corresponde.",
    },
    {
        "key": "delimitacion",
        "label": "Delimitación",
        "icono": "fa5s.draw-polygon",
        "titulo": "Delimitación de espacios",
        "descripcion": (
            "Sobre cada plano cargado traza los muros, marca las puertas "
            "y cierra los polígonos que definen cada habitación."
        ),
        "info_banner": None,
    },
    {
        "key": "elementos",
        "label": "Elementos",
        "icono": "fa5s.bolt",
        "titulo": "Elementos eléctricos",
        "descripcion": (
            "Coloca luminarias, contactos, apagadores y cargas especiales "
            "con la paleta de simbología. Doble clic sobre cada elemento "
            "configura sus parámetros (potencia, voltaje, tipo)."
        ),
        "info_banner": None,
    },
    {
        "key": "tableros",
        "label": "Tableros",
        "icono": "fa5s.microchip",
        "titulo": "Ubicación de tableros",
        "descripcion": (
            "Indica dónde se instalarán los tableros generales y "
            "derivados sobre cada plano. El motor los usará como puntos "
            "de origen para calcular trayectorias y caídas de tensión."
        ),
        "info_banner": None,
    },
    {
        "key": "agrupacion",
        "label": "Agrupación",
        "icono": "fa5s.project-diagram",
        "titulo": "Agrupación automática",
        "descripcion": (
            "El motor propone circuitos derivados, balance de fases y "
            "trayectorias de canalización respetando NOM-001-SEDE. "
            "Revisa la propuesta y edita antes de aprobar."
        ),
        "info_banner": None,
    },
    {
        "key": "calculos",
        "label": "Cálculos",
        "icono": "fa5s.calculator",
        "titulo": "Cuadros de carga",
        "descripcion": (
            "Cuadro de cargas por tablero, balance por fase y verificación "
            "de capacidad. Se actualiza automáticamente con cada cambio "
            "en el diseño."
        ),
        "info_banner": None,
    },
    {
        "key": "documentacion",
        "label": "Documentación",
        "icono": "fa5s.file-alt",
        "titulo": "Documentación técnica",
        "descripcion": (
            "Diagrama unifilar, memoria técnica, listado de materiales y "
            "planos finales listos para entrega al cliente o UVIE."
        ),
        "info_banner": None,
    },
]


# ═════════════════════════════════════════════════════════════════════════
#  ITEM DEL SIDEBAR
#  QPushButton custom que representa una etapa. Cambia de estilo según
#  esté activo o no, y según el sidebar esté expandido o colapsado.
# ═════════════════════════════════════════════════════════════════════════
class ItemSidebar(QPushButton):

    clicked_key = pyqtSignal(str)   # emite la key de la etapa

    def __init__(self, etapa_data: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._data = etapa_data
        self._activo = False
        self._colapsado = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self.clicked.connect(lambda: self.clicked_key.emit(self._data["key"]))
        self._render()

    def set_activo(self, activo: bool) -> None:
        if activo == self._activo:
            return
        self._activo = activo
        self._render()

    def set_colapsado(self, colapsado: bool) -> None:
        if colapsado == self._colapsado:
            return
        self._colapsado = colapsado
        self._render()

    def _render(self) -> None:
        # Ícono con color según estado activo/inactivo.
        color_ico = COLOR_ACENTO_SUAVE if self._activo else COLOR_TEXTO_APAGADO
        self.setIcon(qta.icon(self._data["icono"], color=color_ico))
        self.setIconSize(QSize(16, 16))

        # Texto y tooltip según modo colapsado.
        if self._colapsado:
            self.setText("")
            self.setToolTip(self._data["label"])
        else:
            # Doble espacio inicial: separación visual entre ícono y texto
            # (QPushButton nativo pone el ícono justo antes del texto).
            self.setText("  " + self._data["label"])
            self.setToolTip("")

        # QSS: barra azul lateral cuando activo, fondo cambiante en hover.
        if self._activo:
            border_left = f"3px solid {COLOR_ACENTO}"
            bg = COLOR_SIDEBAR_ITEM
            color_txt = COLOR_TEXTO
            weight = "500"
        else:
            border_left = "3px solid transparent"
            bg = "transparent"
            color_txt = COLOR_TEXTO_MUTED
            weight = "400"

        if self._colapsado:
            # Centrar el ícono en un sidebar de 52 px.
            padding = "0"
            text_align = "center"
        else:
            padding = "0 14px 0 11px"  # 11 izq porque los 3 px del border-left cuentan
            text_align = "left"

        # Hover: para el item activo dejamos su mismo fondo (no se aclara);
        # para el inactivo un ligero highlight.
        hover_bg = COLOR_SIDEBAR_ITEM if self._activo else COLOR_SIDEBAR_HOVER
        hover_color = COLOR_TEXTO if self._activo else COLOR_TEXTO_SUAVE

        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border: none;
                border-left: {border_left};
                color: {color_txt};
                font-size: 12px;
                font-weight: {weight};
                padding: {padding};
                text-align: {text_align};
                border-radius: 0;
                outline: none;
            }}
            QPushButton:hover {{
                background: {hover_bg};
                color: {hover_color};
            }}
        """)


# ═════════════════════════════════════════════════════════════════════════
#  SIDEBAR DE ETAPAS
#  Contenedor vertical de los 7 items. Colapsable con setFixedWidth.
# ═════════════════════════════════════════════════════════════════════════
class SidebarEtapas(QWidget):

    etapa_cambiada = pyqtSignal(str)

    ANCHO_EXPANDIDO = 190
    ANCHO_COLAPSADO = 52

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._colapsado = False
        self._etapa_actual = ETAPAS[0]["key"]
        self._items: dict[str, ItemSidebar] = {}

        self.setFixedWidth(self.ANCHO_EXPANDIDO)
        self.setStyleSheet(f"background: {COLOR_SIDEBAR};")

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 8)
        v.setSpacing(2)

        for etapa_data in ETAPAS:
            item = ItemSidebar(etapa_data)
            item.clicked_key.connect(self._on_item_click)
            self._items[etapa_data["key"]] = item
            v.addWidget(item)

        v.addStretch()

        # Marcar la primera etapa como activa por default.
        self._items[self._etapa_actual].set_activo(True)

    # -----------------------------------------------------------------
    def _on_item_click(self, key: str) -> None:
        if key == self._etapa_actual:
            return
        self._items[self._etapa_actual].set_activo(False)
        self._items[key].set_activo(True)
        self._etapa_actual = key
        self.etapa_cambiada.emit(key)

    def toggle_colapsado(self) -> None:
        self._colapsado = not self._colapsado
        nuevo_ancho = self.ANCHO_COLAPSADO if self._colapsado else self.ANCHO_EXPANDIDO
        self.setFixedWidth(nuevo_ancho)
        for item in self._items.values():
            item.set_colapsado(self._colapsado)

    def esta_colapsado(self) -> bool:
        return self._colapsado


# ═════════════════════════════════════════════════════════════════════════
#  PÁGINA DE ETAPA (placeholder de contenido)
#  Se construye automáticamente desde el dict de la etapa (icono, título,
#  descripción, info_banner opcional). Cuando una etapa se implemente
#  de verdad, su placeholder se reemplaza por el widget funcional.
# ═════════════════════════════════════════════════════════════════════════
class PaginaEtapa(QWidget):

    def __init__(self, etapa_data: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._data = etapa_data
        self.setStyleSheet(f"background: {COLOR_FONDO};")

        v = QVBoxLayout(self)
        v.setContentsMargins(32, 40, 32, 40)
        v.setSpacing(0)
        v.addStretch()

        # ── Ícono grande en cuadro ──────────────────────────────────
        cuadro_ico = QLabel()
        cuadro_ico.setFixedSize(64, 64)
        cuadro_ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cuadro_ico.setPixmap(qta.icon(etapa_data["icono"], color=COLOR_ACENTO).pixmap(34, 34))
        cuadro_ico.setStyleSheet(f"""
            background: {COLOR_SUPERFICIE};
            border-radius: 12px;
        """)
        v.addWidget(cuadro_ico, 0, Qt.AlignmentFlag.AlignCenter)
        v.addSpacing(18)

        # ── Título ──────────────────────────────────────────────────
        titulo = QLabel(etapa_data["titulo"])
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO}; font-size: 18px; font-weight: 500;
            background: transparent;
        """)
        v.addWidget(titulo)
        v.addSpacing(8)

        # ── Descripción ─────────────────────────────────────────────
        # Se envuelve en un container horizontal con stretch a los lados
        # y setFixedWidth (no setMaximumWidth). Con wordWrap + AlignCenter
        # + maxWidth, Qt no siempre calcula bien la altura del label y
        # termina solapando la descripción con los widgets siguientes.
        desc = QLabel(etapa_data["descripcion"])
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setFixedWidth(440)
        desc.setStyleSheet(f"""
            color: {COLOR_TEXTO_MUTED}; font-size: 12px;
            background: transparent;
        """)

        desc_wrap = QWidget()
        desc_wrap.setStyleSheet("background: transparent;")
        desc_h = QHBoxLayout(desc_wrap)
        desc_h.setContentsMargins(0, 0, 0, 0)
        desc_h.addStretch()
        desc_h.addWidget(desc)
        desc_h.addStretch()
        v.addWidget(desc_wrap)
        v.addSpacing(22)

        # ── Info-banner opcional ────────────────────────────────────
        if etapa_data.get("info_banner"):
            banner = self._construir_info_banner(etapa_data["info_banner"])
            v.addWidget(banner, 0, Qt.AlignmentFlag.AlignCenter)
            v.addSpacing(22)

        # ── Badge "No iniciado" + leyenda "Próximamente" ────────────
        fila_estado = QWidget()
        fila_estado.setStyleSheet("background: transparent;")
        h_est = QHBoxLayout(fila_estado)
        h_est.setContentsMargins(0, 0, 0, 0)
        h_est.setSpacing(10)

        badge = QLabel("No iniciado")
        badge.setStyleSheet(f"""
            background: {COLOR_INPUT_BG};
            color: {COLOR_TEXTO_APAGADO};
            padding: 4px 10px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 500;
        """)
        prox = QLabel("Próximamente")
        prox.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO}; font-size: 11px;
            background: transparent;
        """)
        h_est.addWidget(badge)
        h_est.addWidget(prox)

        v.addWidget(fila_estado, 0, Qt.AlignmentFlag.AlignCenter)
        v.addStretch()

    # -----------------------------------------------------------------
    def _construir_info_banner(self, texto: str) -> QFrame:
        """Banner sutil con ícono info + texto, para pistas contextuales."""
        banner = QFrame()
        banner.setObjectName("infoBanner")
        # Ojo: uso objectName para que el borde no cascadee a los QLabel
        # hijos (mismo bug que arreglamos en el wizard).
        banner.setStyleSheet(f"""
            QFrame#infoBanner {{
                background: {COLOR_HEADER};
                border: 1px solid {COLOR_BORDE_SUAVE};
                border-radius: 6px;
            }}
        """)
        h = QHBoxLayout(banner)
        h.setContentsMargins(14, 10, 16, 10)
        h.setSpacing(10)

        ico = QLabel()
        ico.setFixedSize(14, 14)
        ico.setPixmap(qta.icon("fa5s.info-circle", color=COLOR_ACENTO_SUAVE).pixmap(14, 14))
        ico.setStyleSheet("background: transparent;")

        txt = QLabel(texto)
        txt.setStyleSheet(f"""
            color: {COLOR_TEXTO_SUAVE}; font-size: 12px; background: transparent;
        """)

        h.addWidget(ico)
        h.addWidget(txt)
        return banner


# ═════════════════════════════════════════════════════════════════════════
#  VENTANA PRINCIPAL DEL ESPACIO DE TRABAJO
# ═════════════════════════════════════════════════════════════════════════
class EspacioTrabajoProyecto(QMainWindow):
    """
    Ventana independiente que muestra un proyecto abierto con su
    sidebar de etapas y el área de contenido de la etapa activa.

    Se abre desde ``VentanaProyectos._abrir_proyecto`` al hacer doble
    clic en una card. Se instancia sin parent para que sea una
    top-level window que puede coexistir con el listado y con otros
    espacios de trabajo abiertos simultáneamente.
    """

    def __init__(self, proyecto: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._proyecto = proyecto

        # Sesión C: modelo de proyecto abierto (RAM). Encapsula la lista
        # de planos, la escala calibrada por plano, y los signals que
        # las páginas de etapa escuchan para reaccionar a cambios. El
        # dict `proyecto` se conserva como fuente de metadata; el modelo
        # gestiona el estado mutable de la sesión de trabajo.
        # Import lazy para no romper la ejecución independiente cuando
        # aún no existan estos módulos junto al espacio_trabajo.py.
        try:
            from proyectos.datos_proyecto import ProyectoAbierto
        except ImportError:
            from datos_proyecto import ProyectoAbierto  # type: ignore
        self._proyecto_abierto = ProyectoAbierto(proyecto, parent=self)

        self.setWindowTitle(f"CAMF · {proyecto.get('nombre', 'Proyecto')}")
        self.resize(1200, 760)
        self.setMinimumSize(880, 560)
        self.setStyleSheet(f"""
            QMainWindow {{ background: {COLOR_FONDO}; }}
            QPushButton {{ outline: none; }}
        """)

        self._build_ui()

    # ═══════════════════════════════════════════════════════════════════
    #  CONSTRUCCIÓN DE UI
    # ═══════════════════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        central = QWidget()
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        raiz.addWidget(self._construir_header())
        raiz.addWidget(self._construir_body(), 1)

        self.setCentralWidget(central)

    # -----------------------------------------------------------------
    def _construir_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"QFrame {{ background: {COLOR_HEADER}; }}")

        h = QHBoxLayout(header)
        h.setContentsMargins(10, 10, 20, 10)
        h.setSpacing(10)

        # Botón toggle sidebar (hamburguesa)
        self.btn_toggle = QPushButton()
        self.btn_toggle.setFixedSize(34, 34)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setIcon(qta.icon("fa5s.bars", color=COLOR_TEXTO_MUTED))
        self.btn_toggle.setIconSize(QSize(15, 15))
        self.btn_toggle.setToolTip("Contraer/expandir menú")
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                border-radius: 4px; outline: none;
            }}
            QPushButton:hover {{ background: {COLOR_INPUT_BG}; }}
        """)
        self.btn_toggle.clicked.connect(self._toggle_sidebar)
        h.addWidget(self.btn_toggle)

        # Botón Volver
        self.btn_volver = QPushButton("  Volver")
        self.btn_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_volver.setIcon(qta.icon("fa5s.arrow-left", color=COLOR_TEXTO_SUAVE))
        self.btn_volver.setIconSize(QSize(12, 12))
        self.btn_volver.setStyleSheet(f"""
            QPushButton {{
                background: {COLOR_INPUT_BG};
                color: {COLOR_TEXTO_SUAVE};
                border: none; outline: none;
                padding: 6px 12px 6px 10px;
                border-radius: 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {COLOR_INPUT_BG_HOVER};
            }}
        """)
        self.btn_volver.clicked.connect(self.close)
        h.addWidget(self.btn_volver)

        h.addSpacing(6)

        # Bloque de texto (nombre + subtitle)
        cont_txt = QVBoxLayout()
        cont_txt.setSpacing(2)
        cont_txt.setContentsMargins(0, 0, 0, 0)

        nombre = QLabel(self._proyecto.get("nombre", "Proyecto"))
        nombre.setStyleSheet(f"""
            color: {COLOR_TEXTO}; font-size: 14px; font-weight: 500;
            background: transparent;
        """)

        cliente = self._proyecto.get("cliente", "")
        subtipo = self._proyecto.get("subtipo", "")
        partes = [p for p in [cliente, subtipo] if p]
        sub_txt = " · ".join(partes)

        subtitle = QLabel(sub_txt)
        subtitle.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO}; font-size: 11px;
            background: transparent;
        """)

        cont_txt.addWidget(nombre)
        cont_txt.addWidget(subtitle)
        h.addLayout(cont_txt, 1)

        # Badge de estado
        estado = self._proyecto.get("estado", "borrador")
        est_info = ESTADO_COLORES.get(estado, ESTADO_COLORES["borrador"])
        badge = QLabel(est_info["label"])
        badge.setFixedHeight(22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"""
            background: {est_info['bg']};
            color: {est_info['fg']};
            padding: 3px 10px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 600;
        """)
        h.addWidget(badge)

        return header

    # -----------------------------------------------------------------
    def _construir_body(self) -> QWidget:
        body = QWidget()
        body.setStyleSheet(f"background: {COLOR_FONDO};")
        h = QHBoxLayout(body)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # Sidebar
        self._sidebar = SidebarEtapas()
        self._sidebar.etapa_cambiada.connect(self._cambiar_etapa)
        h.addWidget(self._sidebar)

        # Stack de páginas por etapa.
        # La etapa "planos" usa la UI funcional PaginaPlanos (Sesión C).
        # Las demás siguen con el placeholder PaginaEtapa hasta que se
        # implementen en sus propias sesiones.
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {COLOR_FONDO};")
        self._paginas: dict[str, QWidget] = {}

        # Import lazy de las páginas funcionales. Si algún módulo no
        # existe todavía en disco, la etapa vuelve al placeholder.
        try:
            from proyectos.pagina_planos import PaginaPlanos
        except ImportError:
            try:
                from pagina_planos import PaginaPlanos  # type: ignore
            except ImportError:
                PaginaPlanos = None  # type: ignore

        try:
            from proyectos.pagina_delimitacion import PaginaDelimitacion
        except ImportError:
            try:
                from pagina_delimitacion import PaginaDelimitacion  # type: ignore
            except ImportError:
                PaginaDelimitacion = None  # type: ignore

        for etapa_data in ETAPAS:
            key = etapa_data["key"]
            if key == "planos" and PaginaPlanos is not None:
                pag = PaginaPlanos(self._proyecto_abierto)
            elif key == "delimitacion" and PaginaDelimitacion is not None:
                pag = PaginaDelimitacion(self._proyecto_abierto)
            else:
                pag = PaginaEtapa(etapa_data)
            self._paginas[key] = pag
            self._stack.addWidget(pag)
        h.addWidget(self._stack, 1)

        return body

    # ═══════════════════════════════════════════════════════════════════
    #  EVENTOS
    # ═══════════════════════════════════════════════════════════════════
    def _toggle_sidebar(self) -> None:
        self._sidebar.toggle_colapsado()

    def _cambiar_etapa(self, key: str) -> None:
        pag = self._paginas.get(key)
        if pag is not None:
            self._stack.setCurrentWidget(pag)


# ═════════════════════════════════════════════════════════════════════════
#  EJECUCIÓN INDEPENDIENTE (desarrollo)
# ═════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    app = QApplication(sys.argv)

    proyecto_ejemplo = {
        "id": "PRJ-001",
        "nombre": "Edificio aulas UAM",
        "cliente": "UAM Iztapalapa",
        "tipo": "edificio",
        "subtipo": "Aulas y oficinas · 4 pisos · 1 sótano",
        "estado": "en_revision",
        "fecha_modificacion": "5 sept 2026",
    }

    # Ícono de la ventana si existe fronted/icons/logo.png
    logo_path = Path(__file__).resolve().parent.parent / "icons" / "logo.png"
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    ventana = EspacioTrabajoProyecto(proyecto_ejemplo)
    ventana.show()
    sys.exit(app.exec())
