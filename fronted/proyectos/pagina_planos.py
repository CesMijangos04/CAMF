"""
pagina_planos.py
================

UI real de la etapa "Planos" del espacio de trabajo. Reemplaza el
PaginaEtapa genérico (placeholder) por la interfaz funcional:

  * Panel izquierdo (240 px):
      - Botón "+ Cargar plano" al tope.
      - Lista scrolleable de cards de planos cargados, con:
          · Thumbnail
          · Título
          · Estado de calibración ("Calibrado ✓" / "Sin calibrar")
          · Card resaltada = plano actualmente abierto en el canvas.
      - Doble clic sobre una card → abre en el canvas.
      - Clic derecho → menú "Renombrar" / "Eliminar plano".

  * Panel derecho (resto del ancho): ribbon del canvas arriba, canvas
    ocupando el ancho, status bar delgado abajo. Reutiliza el motor
    CanvasPlano y las herramientas de la Sesión A/B.

  * Estado vacío: cuando no hay planos cargados, un placeholder amable
    con "+ Cargar tu primer plano" al centro del panel derecho.

Convenciones del módulo Proyectos:
  * Self-contained: paleta local, imports de proyectos/*.
  * QFrame con border SIEMPRE via objectName.
  * Rueda del mouse solo para zoom del canvas.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

try:
    import qtawesome as qta
    _QTA_OK = True
except Exception:  # noqa: BLE001
    _QTA_OK = False


# Módulos del propio paquete Proyectos
from canvas_plano import CanvasPlano, Herramienta
from datos_proyecto import PlanoDeProyecto, ProyectoAbierto
from escala_calibrador import EscalaCalibrada, MedicionCalibrada


# ---------------------------------------------------------------------------
# Paleta CAMF (replicada — misma convención que el resto del módulo)
# ---------------------------------------------------------------------------

COLOR_FONDO           = "#121212"
COLOR_HEADER          = "#141414"
COLOR_SIDEBAR         = "#1a1a1a"
COLOR_SUPERFICIE      = "#1e1e1e"
COLOR_SUPERFICIE_HOVER= "#242424"
COLOR_INPUT_BG        = "#2b2b2b"
COLOR_INPUT_BG_HOVER  = "#353535"
COLOR_BORDE           = "#333333"
COLOR_BORDE_FUERTE    = "#444444"
COLOR_ACENTO          = "#0078d7"
COLOR_ACENTO_BRILL    = "#0094ff"
COLOR_ACENTO_HOVER    = "#005a9e"
COLOR_ACENTO_SUAVE    = "#85B7EB"
COLOR_TEXTO           = "#ffffff"
COLOR_TEXTO_SUAVE     = "#dddddd"
COLOR_TEXTO_MUTED     = "#aaaaaa"
COLOR_TEXTO_APAGADO   = "#666666"

COLOR_OK              = "#97C459"    # calibrado ✓ (verde de estado "aprobado")
COLOR_WARN            = "#FAC775"    # sin calibrar ⚠ (naranja de "en_revision")


# Anchos del panel lateral izquierdo
_ANCHO_PANEL       = 260
_ALTO_CARD_PLANO   = 190
_ANCHO_TOOL_CHICO  = 66
_ANCHO_TOOL_GRANDE = 90
_SPACING_BOTONES   = 2


# ---------------------------------------------------------------------------
# DialogoCargarPlano — pide título + archivo antes de cargar
# ---------------------------------------------------------------------------

class DialogoCargarPlano(QDialog):
    """Diálogo modal para cargar un plano nuevo al proyecto.

    Campos:
      * Título del plano (texto libre, ej. "Primer nivel").
      * Archivo (botón que abre file dialog).

    Al aceptar, devuelve (titulo, path) via `datos()`. Valida que
    ambos estén presentes antes de habilitar el botón "Cargar".
    """

    FORMATOS_SOPORTADOS = "Planos (*.pdf *.png *.jpg *.jpeg *.bmp)"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cargar plano nuevo")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedSize(500, 300)
        self.setStyleSheet(self._stylesheet())

        self._path_seleccionado: Optional[Path] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)

        titulo = QLabel("Cargar plano nuevo")
        titulo.setObjectName("tituloDialogo")
        layout.addWidget(titulo)

        explicacion = QLabel(
            "Dale un título que identifique el nivel al que corresponde "
            "y elige el archivo PDF o de imagen del plano arquitectónico."
        )
        explicacion.setObjectName("descripcionDialogo")
        explicacion.setWordWrap(True)
        layout.addWidget(explicacion)

        # --- Fila título
        lbl_titulo = QLabel("Título del plano")
        lbl_titulo.setObjectName("etiquetaCampo")
        layout.addWidget(lbl_titulo)

        self._input_titulo = QLineEdit()
        self._input_titulo.setPlaceholderText(
            "Ej. Primer nivel, Sótano 1, Azotea…"
        )
        self._input_titulo.textChanged.connect(self._revalidar)
        layout.addWidget(self._input_titulo)

        # --- Fila archivo
        lbl_arch = QLabel("Archivo del plano")
        lbl_arch.setObjectName("etiquetaCampo")
        layout.addWidget(lbl_arch)

        fila_arch = QHBoxLayout()
        fila_arch.setSpacing(8)

        self._lbl_path = QLabel("Ningún archivo seleccionado")
        self._lbl_path.setObjectName("pathArchivo")
        self._lbl_path.setWordWrap(False)
        fila_arch.addWidget(self._lbl_path, 1)

        btn_examinar = QPushButton("Examinar…")
        btn_examinar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_examinar.setObjectName("secundario")
        btn_examinar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_examinar.clicked.connect(self._elegir_archivo)
        fila_arch.addWidget(btn_examinar)

        layout.addLayout(fila_arch)

        layout.addStretch(1)

        # --- Botones
        botones = QHBoxLayout()
        botones.setSpacing(8)
        botones.addStretch(1)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("secundario")
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_cancelar.clicked.connect(self.reject)
        botones.addWidget(btn_cancelar)

        self._btn_ok = QPushButton("Cargar")
        self._btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_ok.setDefault(True)
        self._btn_ok.clicked.connect(self.accept)
        botones.addWidget(self._btn_ok)

        layout.addLayout(botones)

        self._revalidar()
        self._input_titulo.setFocus()

    def _elegir_archivo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir plano", "",
            f"{self.FORMATOS_SOPORTADOS};;Todos los archivos (*.*)",
        )
        if not path:
            return
        p = Path(path)
        self._path_seleccionado = p
        # Mostrar solo el nombre, con tooltip del path completo
        self._lbl_path.setText(p.name)
        self._lbl_path.setToolTip(str(p))
        # Sugerir el nombre del archivo (sin extensión) como título si
        # el usuario aún no ha escrito nada.
        if not self._input_titulo.text().strip():
            self._input_titulo.setText(p.stem)
        self._revalidar()

    def _revalidar(self) -> None:
        listo = (
            bool(self._input_titulo.text().strip())
            and self._path_seleccionado is not None
        )
        self._btn_ok.setEnabled(listo)

    def datos(self) -> tuple[str, Path]:
        return (
            self._input_titulo.text().strip(),
            Path(self._path_seleccionado) if self._path_seleccionado else Path(),
        )

    def _stylesheet(self) -> str:
        return f"""
            QDialog {{
                background-color: {COLOR_FONDO};
                color: {COLOR_TEXTO_SUAVE};
            }}
            QLabel {{ color: {COLOR_TEXTO_SUAVE}; font-size: 12px; }}
            QLabel#tituloDialogo {{
                color: {COLOR_TEXTO};
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 4px;
            }}
            QLabel#descripcionDialogo {{
                color: {COLOR_TEXTO_MUTED};
                font-size: 12px;
                padding-bottom: 6px;
            }}
            QLabel#etiquetaCampo {{
                color: {COLOR_TEXTO_MUTED};
                font-size: 11px;
                padding-top: 4px;
            }}
            QLabel#pathArchivo {{
                color: {COLOR_TEXTO};
                background-color: {COLOR_INPUT_BG};
                border: 1px solid {COLOR_BORDE_FUERTE};
                border-radius: 4px;
                padding: 7px 10px;
                font-size: 12px;
            }}
            QLineEdit {{
                background-color: {COLOR_INPUT_BG};
                color: {COLOR_TEXTO};
                border: 1px solid {COLOR_BORDE_FUERTE};
                border-radius: 4px;
                padding: 7px 10px;
                font-size: 12px;
                selection-background-color: {COLOR_ACENTO};
            }}
            QLineEdit:focus {{ border-color: {COLOR_ACENTO}; }}
            QPushButton {{
                background-color: {COLOR_ACENTO};
                color: {COLOR_TEXTO};
                border: none;
                padding: 8px 18px;
                border-radius: 4px;
                font-size: 12px;
                min-width: 90px;
                outline: none;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACENTO_BRILL}; }}
            QPushButton:disabled {{
                background-color: {COLOR_BORDE_FUERTE};
                color: {COLOR_TEXTO_APAGADO};
            }}
            QPushButton#secundario {{
                background-color: {COLOR_INPUT_BG};
                color: {COLOR_TEXTO_SUAVE};
            }}
            QPushButton#secundario:hover {{
                background-color: {COLOR_BORDE_FUERTE};
                color: {COLOR_TEXTO};
            }}
        """


# ---------------------------------------------------------------------------
# CardPlano — card individual en el panel lateral
# ---------------------------------------------------------------------------

class CardPlano(QFrame):
    """Card visual de un plano en el panel lateral.

    Signals:
      * seleccionada(str) — emit(plano_id) al doble clic.
      * renombrar_solicitado(str) — clic derecho → "Renombrar".
      * eliminar_solicitado(str) — clic derecho → "Eliminar plano".
    """

    seleccionada         = pyqtSignal(str)
    renombrar_solicitado = pyqtSignal(str)
    eliminar_solicitado  = pyqtSignal(str)

    def __init__(
        self, plano: PlanoDeProyecto, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._plano = plano
        self._activa: bool = False

        self.setObjectName("cardPlano")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(_ALTO_CARD_PLANO)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._mostrar_menu_contexto)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # Thumbnail
        self._lbl_thumb = QLabel()
        self._lbl_thumb.setObjectName("thumbPlano")
        self._lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_thumb.setFixedHeight(110)
        if plano.thumbnail is not None and not plano.thumbnail.isNull():
            self._lbl_thumb.setPixmap(
                plano.thumbnail.scaledToHeight(
                    108, Qt.TransformationMode.SmoothTransformation
                )
            )
        else:
            self._lbl_thumb.setText("[sin miniatura]")
        v.addWidget(self._lbl_thumb)

        # Título
        self._lbl_titulo = QLabel(plano.titulo)
        self._lbl_titulo.setObjectName("tituloPlano")
        self._lbl_titulo.setWordWrap(True)
        v.addWidget(self._lbl_titulo)

        # Estado de calibración
        self._lbl_estado = QLabel()
        self._lbl_estado.setObjectName("estadoPlano")
        v.addWidget(self._lbl_estado)

        v.addStretch()
        self._aplicar_estilo()
        self._refrescar_estado_calibracion()

    def plano_id(self) -> str:
        return self._plano.id

    def actualizar_plano(self, plano: PlanoDeProyecto) -> None:
        """Refresca la card con datos actualizados del plano (título o
        escala cambiaron)."""
        self._plano = plano
        self._lbl_titulo.setText(plano.titulo)
        self._refrescar_estado_calibracion()

    def set_activa(self, activa: bool) -> None:
        if activa == self._activa:
            return
        self._activa = activa
        self._aplicar_estilo()

    def _refrescar_estado_calibracion(self) -> None:
        if self._plano.esta_calibrado():
            escala = self._plano.escala
            n = escala.cantidad_puntos() if escala is not None else 0
            texto = f"✓  Calibrado  ·  {n} pt" if n > 1 else "✓  Calibrado"
            self._lbl_estado.setText(texto)
            self._lbl_estado.setProperty("ok", True)
        else:
            self._lbl_estado.setText("⚠  Sin calibrar")
            self._lbl_estado.setProperty("ok", False)
        # Reaplicar estilo para que el color del label cambie
        self._lbl_estado.style().unpolish(self._lbl_estado)
        self._lbl_estado.style().polish(self._lbl_estado)

    def _aplicar_estilo(self) -> None:
        borde = COLOR_ACENTO if self._activa else COLOR_BORDE
        fondo = COLOR_SUPERFICIE_HOVER if self._activa else COLOR_SUPERFICIE
        self.setStyleSheet(f"""
            QFrame#cardPlano {{
                background-color: {fondo};
                border: 1px solid {borde};
                border-radius: 8px;
            }}
            QFrame#cardPlano:hover {{
                background-color: {COLOR_SUPERFICIE_HOVER};
                border: 1px solid {COLOR_ACENTO};
            }}
            QFrame#cardPlano QLabel {{
                background: transparent;
            }}
            QLabel#thumbPlano {{
                background-color: {COLOR_INPUT_BG};
                color: {COLOR_TEXTO_APAGADO};
                border-radius: 4px;
                font-size: 10px;
            }}
            QLabel#tituloPlano {{
                color: {COLOR_TEXTO};
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#estadoPlano {{
                color: {COLOR_WARN};
                font-size: 11px;
            }}
            QLabel#estadoPlano[ok="true"] {{
                color: {COLOR_OK};
            }}
        """)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.seleccionada.emit(self._plano.id)
        super().mouseDoubleClickEvent(event)

    def _mostrar_menu_contexto(self, pos) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_menu_stylesheet())
        act_rename = QAction("Renombrar…", menu)
        act_rename.triggered.connect(
            lambda: self.renombrar_solicitado.emit(self._plano.id)
        )
        act_delete = QAction("Eliminar plano", menu)
        act_delete.triggered.connect(
            lambda: self.eliminar_solicitado.emit(self._plano.id)
        )
        menu.addAction(act_rename)
        menu.addSeparator()
        menu.addAction(act_delete)
        menu.exec(self.mapToGlobal(pos))


def _menu_stylesheet() -> str:
    return f"""
        QMenu {{
            background-color: {COLOR_SUPERFICIE};
            color: {COLOR_TEXTO_SUAVE};
            border: 1px solid {COLOR_BORDE_FUERTE};
            padding: 4px 0px;
            font-size: 12px;
        }}
        QMenu::item {{ padding: 6px 20px; background-color: transparent; }}
        QMenu::item:selected {{
            background-color: {COLOR_ACENTO};
            color: {COLOR_TEXTO};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {COLOR_BORDE};
            margin: 4px 0px;
        }}
    """


# ---------------------------------------------------------------------------
# _RibbonCanvas — reutilizado (mismo look que la demo del canvas)
# ---------------------------------------------------------------------------

class _RibbonCanvas(QFrame):
    """Ribbon horizontal del canvas: Vista + Herramientas + Medición.

    Se instancia dentro de PaginaPlanos y opera sobre un CanvasPlano
    pasado por referencia. Reemplaza el ribbon standalone de la demo
    del canvas.
    """

    def __init__(
        self,
        canvas: CanvasPlano,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._modo_borrar_actual: str = "todas"
        self.setObjectName("ribbonCanvas")
        self.setFixedHeight(88)
        self.setStyleSheet(_ribbon_stylesheet())

        h = QHBoxLayout(self)
        h.setContentsMargins(10, 4, 10, 2)
        h.setSpacing(4)

        # VISTA
        grupo_vista = _crear_grupo("VISTA", [_ANCHO_TOOL_CHICO] * 3)
        self._btn_fit = _crear_boton(
            "fa5s.expand", "Encajar", _ANCHO_TOOL_CHICO,
            lambda: self._canvas.encajar_plano_en_vista(),
        )
        self._btn_zin = _crear_boton(
            "fa5s.search-plus", "Zoom +", _ANCHO_TOOL_CHICO,
            lambda: self._canvas.zoom_in(),
        )
        self._btn_zout = _crear_boton(
            "fa5s.search-minus", "Zoom −", _ANCHO_TOOL_CHICO,
            lambda: self._canvas.zoom_out(),
        )
        grupo_vista["contenido"].addWidget(self._btn_fit)
        grupo_vista["contenido"].addWidget(self._btn_zin)
        grupo_vista["contenido"].addWidget(self._btn_zout)
        h.addWidget(grupo_vista["widget"])

        h.addWidget(_sep())

        # HERRAMIENTAS
        grupo_tools = _crear_grupo(
            "HERRAMIENTAS", [_ANCHO_TOOL_GRANDE, _ANCHO_TOOL_CHICO]
        )
        self._btn_sel = _crear_boton(
            "fa5s.mouse-pointer", "Seleccionar", _ANCHO_TOOL_GRANDE,
            lambda: self._canvas.set_herramienta(Herramienta.SELECCIONAR),
        )
        self._btn_pan = _crear_boton(
            "fa5s.hand-paper", "Pan", _ANCHO_TOOL_CHICO,
            lambda: self._canvas.set_herramienta(Herramienta.PAN),
        )
        grupo_tools["contenido"].addWidget(self._btn_sel)
        grupo_tools["contenido"].addWidget(self._btn_pan)
        h.addWidget(grupo_tools["widget"])

        h.addWidget(_sep())

        # MEDICIÓN
        grupo_med = _crear_grupo(
            "MEDICIÓN", [_ANCHO_TOOL_GRANDE, _ANCHO_TOOL_CHICO, 82]
        )
        self._btn_cal = _crear_boton(
            "fa5s.ruler-combined", "Calibrar", _ANCHO_TOOL_GRANDE,
            self._iniciar_calibracion,
        )
        self._btn_med = _crear_boton(
            "fa5s.ruler", "Medir", _ANCHO_TOOL_CHICO,
            lambda: self._canvas.set_herramienta(Herramienta.MEDIR),
        )
        self._btn_med.setEnabled(False)
        self._btn_med.setToolTip(
            "Medir distancias en metros.\nRequiere calibrar el plano primero."
        )
        self._btn_borrar = _crear_boton(
            "fa5s.trash-alt", "Todas", 82,
            self._ejecutar_borrar_actual,
        )
        grupo_med["contenido"].addWidget(self._btn_cal)
        grupo_med["contenido"].addWidget(self._btn_med)
        grupo_med["contenido"].addWidget(self._btn_borrar)
        h.addWidget(grupo_med["widget"])

        h.addStretch(1)

        # Conexiones del canvas → visual del ribbon
        canvas.herramienta_cambiada.connect(self._on_herramienta_cambiada)
        canvas.escala_cambiada.connect(self._on_escala_cambiada)
        canvas.modo_borrar_individual_cambiado.connect(
            self._on_modo_borrar_cambiado
        )
        # Estado visual inicial
        self._marcar_herramienta(Herramienta.SELECCIONAR)

    # ---- Callbacks

    def _iniciar_calibracion(self) -> None:
        if not self._canvas.iniciar_calibracion():
            QMessageBox.information(
                self, "Calibrar escala",
                "Primero abre un plano para calibrar."
            )

    def _ejecutar_borrar_actual(self) -> None:
        if self._modo_borrar_actual == "una":
            self._canvas.iniciar_modo_borrar_individual()
        else:
            self._canvas.borrar_mediciones()

    def _on_herramienta_cambiada(self, herramienta: Herramienta) -> None:
        self._marcar_herramienta(herramienta)

    def _on_escala_cambiada(self, escala: Optional[EscalaCalibrada]) -> None:
        tiene = (escala is not None)
        self._btn_med.setEnabled(tiene)
        self._btn_med.setToolTip(
            "Medir distancias en metros usando la escala calibrada."
            if tiene else
            "Medir distancias en metros.\nRequiere calibrar el plano primero."
        )

    def _on_modo_borrar_cambiado(self, activo: bool) -> None:
        self._btn_borrar.setObjectName("toolActivo" if activo else "")
        self._reaplicar(self._btn_borrar)

    def _marcar_herramienta(self, h: Herramienta) -> None:
        mapping = {
            Herramienta.SELECCIONAR: self._btn_sel,
            Herramienta.PAN:         self._btn_pan,
            Herramienta.MEDIR:       self._btn_med,
        }
        for hi, btn in mapping.items():
            activo = (hi == h)
            btn.setObjectName("toolActivo" if activo else "")
            _aplicar_icono(btn, activo=activo)
            self._reaplicar(btn)

    @staticmethod
    def _reaplicar(w: QWidget) -> None:
        s = w.style()
        if s is not None:
            s.unpolish(w)
            s.polish(w)


# ---------------------------------------------------------------------------
# Helpers de ribbon (extraídos para reutilizar el look del canvas_plano.py)
# ---------------------------------------------------------------------------

def _crear_grupo(etiqueta: str, anchos_botones: list[int]) -> dict:
    ancho_total = sum(anchos_botones) + _SPACING_BOTONES * max(
        0, len(anchos_botones) - 1
    )
    wrap = QWidget()
    wrap.setFixedWidth(ancho_total)
    v = QVBoxLayout(wrap)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    contenido = QHBoxLayout()
    contenido.setContentsMargins(0, 0, 0, 0)
    contenido.setSpacing(_SPACING_BOTONES)
    v.addLayout(contenido)
    lbl = QLabel(etiqueta)
    lbl.setObjectName("grupoLabel")
    lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    lbl.setFixedWidth(ancho_total)
    v.addWidget(lbl)
    return {"widget": wrap, "contenido": contenido}


def _sep() -> QFrame:
    sep = QFrame()
    sep.setObjectName("ribbonSeparator")
    sep.setFrameShape(QFrame.Shape.NoFrame)
    return sep


def _crear_boton(icono_nombre: str, texto: str, ancho: int, on_click) -> QToolButton:
    btn = QToolButton()
    btn.setText(texto)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    btn.setIconSize(QSize(22, 22))
    btn.setFixedWidth(ancho)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setToolTip(texto)
    btn.setProperty("iconName", icono_nombre)
    _aplicar_icono(btn, activo=False)
    btn.clicked.connect(on_click)
    return btn


def _aplicar_icono(btn: QToolButton, activo: bool) -> None:
    nombre = btn.property("iconName")
    if not nombre or not _QTA_OK:
        return
    color = COLOR_TEXTO if activo else COLOR_TEXTO_SUAVE
    btn.setIcon(qta.icon(nombre, color=color))


def _ribbon_stylesheet() -> str:
    return f"""
        QFrame#ribbonCanvas {{
            background-color: {COLOR_HEADER};
            border-bottom: 1px solid {COLOR_BORDE};
        }}
        QFrame#ribbonSeparator {{
            background-color: {COLOR_BORDE};
            min-width: 1px; max-width: 1px;
            margin: 4px 6px 22px 6px;
        }}
        QLabel#grupoLabel {{
            color: {COLOR_TEXTO_APAGADO};
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 0.5px;
            padding: 2px 0px 0px 0px;
            background-color: transparent;
        }}
        QToolButton {{
            background-color: transparent;
            color: {COLOR_TEXTO_SUAVE};
            border: 1px solid transparent;
            border-radius: 4px;
            padding: 4px 6px;
            min-height: 54px;
            font-size: 11px;
            outline: none;
        }}
        QToolButton:hover {{
            background-color: {COLOR_INPUT_BG};
            border-color: {COLOR_BORDE_FUERTE};
            color: {COLOR_TEXTO};
        }}
        QToolButton:pressed {{ background-color: {COLOR_BORDE_FUERTE}; }}
        QToolButton:disabled {{
            background-color: transparent;
            color: {COLOR_TEXTO_APAGADO};
            border-color: transparent;
        }}
        QToolButton#toolActivo {{
            background-color: {COLOR_ACENTO};
            border-color: {COLOR_ACENTO_BRILL};
            color: {COLOR_TEXTO};
        }}
        QToolButton#toolActivo:hover {{
            background-color: {COLOR_ACENTO_BRILL};
            border-color: {COLOR_ACENTO_BRILL};
        }}
    """


# ---------------------------------------------------------------------------
# PaginaPlanos — la etapa "Planos" del espacio de trabajo
# ---------------------------------------------------------------------------

class PaginaPlanos(QWidget):
    """Widget que reemplaza el placeholder de la etapa "Planos" con la
    UI funcional: panel de planos a la izquierda, canvas + ribbon a la
    derecha.
    """

    def __init__(
        self,
        proyecto: ProyectoAbierto,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._proyecto = proyecto
        self._plano_activo_id: Optional[str] = None
        self._cards: dict[str, CardPlano] = {}

        self.setStyleSheet(f"background: {COLOR_FONDO};")

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        raiz.addWidget(self._construir_panel_lateral())
        raiz.addWidget(self._construir_panel_canvas(), 1)

        # Conexiones al modelo
        proyecto.plano_agregado.connect(self._on_plano_agregado)
        proyecto.plano_eliminado.connect(self._on_plano_eliminado)
        proyecto.plano_actualizado.connect(self._on_plano_actualizado)
        proyecto.escala_actualizada.connect(self._on_escala_actualizada_modelo)

        # Renderizar planos que ya vengan en el proyecto (por ejemplo,
        # cuando reabrimos un proyecto guardado en BD).
        for plano in proyecto.planos():
            self._on_plano_agregado(plano)

        self._actualizar_estado_vacio()

    # ------------------------------------------------------ Construcción UI

    def _construir_panel_lateral(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panelLateralPlanos")
        panel.setFixedWidth(_ANCHO_PANEL)
        panel.setStyleSheet(f"""
            QFrame#panelLateralPlanos {{
                background: {COLOR_SIDEBAR};
                border-right: 1px solid {COLOR_BORDE};
            }}
        """)

        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        # Botón "+ Cargar plano"
        self._btn_cargar = QPushButton()
        self._btn_cargar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cargar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if _QTA_OK:
            self._btn_cargar.setIcon(
                qta.icon("fa5s.plus", color=COLOR_TEXTO)
            )
            self._btn_cargar.setIconSize(QSize(12, 12))
        self._btn_cargar.setText("  Cargar plano")
        self._btn_cargar.setFixedHeight(38)
        self._btn_cargar.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACENTO};
                color: {COLOR_TEXTO};
                border: none;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 12px;
                font-weight: 500;
                text-align: left;
                outline: none;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACENTO_BRILL}; }}
        """)
        self._btn_cargar.clicked.connect(self._abrir_dialogo_cargar)
        v.addWidget(self._btn_cargar)

        # Título del listado
        lbl_titulo = QLabel("Planos del proyecto")
        lbl_titulo.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO};
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 0.5px;
            padding: 6px 0px 0px 2px;
            background: transparent;
        """)
        v.addWidget(lbl_titulo)

        # Scroll con lista de cards
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {COLOR_BORDE_FUERTE};
                border-radius: 3px;
                min-height: 30px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {COLOR_TEXTO_APAGADO};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                background: none; height: 0; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)

        self._cont_cards = QWidget()
        self._cont_cards.setStyleSheet("background: transparent;")
        self._layout_cards = QVBoxLayout(self._cont_cards)
        self._layout_cards.setContentsMargins(0, 0, 4, 0)
        self._layout_cards.setSpacing(8)
        self._layout_cards.addStretch(1)
        self._scroll.setWidget(self._cont_cards)
        v.addWidget(self._scroll, 1)

        # Mensaje de "aún no hay planos"
        self._lbl_vacio_panel = QLabel(
            "Aún no hay planos.\nDa clic en \"Cargar plano\"\npara agregar el primero."
        )
        self._lbl_vacio_panel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_vacio_panel.setWordWrap(True)
        self._lbl_vacio_panel.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO};
            font-size: 11px;
            padding: 40px 6px;
            background: transparent;
        """)
        v.addWidget(self._lbl_vacio_panel)

        return panel

    def _construir_panel_canvas(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet(f"background: {COLOR_FONDO};")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Canvas (creado ANTES del ribbon porque el ribbon se conecta al canvas)
        self._canvas = CanvasPlano()

        # Ribbon
        self._ribbon = _RibbonCanvas(self._canvas)
        v.addWidget(self._ribbon)

        # Contenedor stack: cuando no hay plano, mostramos placeholder
        self._stack_area = QWidget()
        self._stack_area.setStyleSheet("background: transparent;")
        stack_v = QVBoxLayout(self._stack_area)
        stack_v.setContentsMargins(0, 0, 0, 0)
        stack_v.setSpacing(0)

        # Placeholder cuando no hay planos
        self._placeholder_canvas = QLabel(
            "Carga tu primer plano para empezar a trabajar."
        )
        self._placeholder_canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_canvas.setStyleSheet(f"""
            color: {COLOR_TEXTO_APAGADO};
            font-size: 13px;
            background-color: {COLOR_FONDO};
        """)

        stack_v.addWidget(self._canvas, 1)
        stack_v.addWidget(self._placeholder_canvas)
        v.addWidget(self._stack_area, 1)

        # Status bar delgado
        self._status = self._construir_status_bar()
        v.addWidget(self._status)

        # Conexiones canvas → status bar
        self._canvas.zoom_cambiado.connect(self._on_zoom_cambiado)
        self._canvas.posicion_cursor.connect(self._on_cursor_pt)
        self._canvas.posicion_cursor_metros.connect(self._on_cursor_m)
        self._canvas.escala_cambiada.connect(self._on_escala_cambiada_canvas)
        self._canvas.error_carga.connect(self._on_error_carga)
        self._canvas.calibrador().estado_mensaje.connect(
            self._on_mensaje_estado
        )
        self._canvas.medidor().estado_mensaje.connect(
            self._on_mensaje_estado
        )
        self._canvas.modo_borrar_individual_cambiado.connect(
            self._on_modo_borrar_ui_status
        )

        return wrap

    def _construir_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("statusBarPlanos")
        bar.setFixedHeight(28)
        bar.setStyleSheet(f"""
            QFrame#statusBarPlanos {{
                background: {COLOR_SIDEBAR};
                border-top: 1px solid {COLOR_BORDE};
            }}
            QLabel {{
                color: {COLOR_TEXTO_SUAVE};
                font-size: 11px;
                padding: 4px 12px;
                background: transparent;
            }}
            QLabel#muted {{ color: {COLOR_TEXTO_APAGADO}; }}
            QLabel#msgEstado {{
                color: {COLOR_ACENTO_BRILL};
                font-weight: bold;
            }}
            QFrame#sepStatus {{
                background: {COLOR_BORDE};
                min-width: 1px; max-width: 1px;
                margin: 4px 0px;
            }}
        """)

        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self._lbl_plano_activo = QLabel("Ningún plano abierto")
        self._lbl_plano_activo.setObjectName("muted")
        h.addWidget(self._lbl_plano_activo)

        h.addWidget(self._sep_status())

        self._lbl_cursor = QLabel("cursor: —")
        self._lbl_cursor.setObjectName("muted")
        h.addWidget(self._lbl_cursor)

        h.addStretch(1)

        self._lbl_msg = QLabel("")
        self._lbl_msg.setObjectName("msgEstado")
        h.addWidget(self._lbl_msg)

        h.addWidget(self._sep_status())

        self._lbl_escala = QLabel("escala: sin calibrar")
        self._lbl_escala.setObjectName("muted")
        h.addWidget(self._lbl_escala)

        h.addWidget(self._sep_status())

        self._lbl_zoom = QLabel("zoom: —")
        h.addWidget(self._lbl_zoom)

        return bar

    def _sep_status(self) -> QFrame:
        s = QFrame()
        s.setObjectName("sepStatus")
        return s

    # ------------------------------------------------- Callbacks del modelo

    def _on_plano_agregado(self, plano: PlanoDeProyecto) -> None:
        card = CardPlano(plano)
        card.seleccionada.connect(self._abrir_plano_en_canvas)
        card.renombrar_solicitado.connect(self._solicitar_renombrar)
        card.eliminar_solicitado.connect(self._solicitar_eliminar)
        self._cards[plano.id] = card
        # Insertar antes del stretch final
        idx = self._layout_cards.count() - 1
        self._layout_cards.insertWidget(idx, card)
        self._actualizar_estado_vacio()
        # Abrir automáticamente el primer plano cargado
        if self._plano_activo_id is None:
            self._abrir_plano_en_canvas(plano.id)

    def _on_plano_eliminado(self, plano_id: str) -> None:
        card = self._cards.pop(plano_id, None)
        if card is not None:
            card.hide()
            card.deleteLater()
        if self._plano_activo_id == plano_id:
            self._plano_activo_id = None
            self._canvas.descargar_plano()
            self._lbl_plano_activo.setText("Ningún plano abierto")
            self._lbl_plano_activo.setObjectName("muted")
            self._reaplicar(self._lbl_plano_activo)
        self._actualizar_estado_vacio()

    def _on_plano_actualizado(self, plano: PlanoDeProyecto) -> None:
        card = self._cards.get(plano.id)
        if card is not None:
            card.actualizar_plano(plano)
        if self._plano_activo_id == plano.id:
            self._lbl_plano_activo.setText(plano.titulo)

    def _on_escala_actualizada_modelo(
        self, plano_id: str, escala: Optional[EscalaCalibrada]
    ) -> None:
        plano = self._proyecto.plano_por_id(plano_id)
        if plano is None:
            return
        card = self._cards.get(plano_id)
        if card is not None:
            card.actualizar_plano(plano)

    # ------------------------------------------------- Callbacks del canvas

    def _on_zoom_cambiado(self, f: float) -> None:
        self._lbl_zoom.setText(f"zoom: {f * 100:.0f}%")

    def _on_cursor_pt(self, pos) -> None:
        if self._canvas.escala_actual() is None:
            self._lbl_cursor.setText(
                f"cursor: {pos.x():.0f}, {pos.y():.0f} pt"
            )

    def _on_cursor_m(self, pos_m) -> None:
        self._lbl_cursor.setText(
            f"cursor: {pos_m.x():.3f}, {pos_m.y():.3f} m"
        )

    def _on_escala_cambiada_canvas(
        self, escala: Optional[EscalaCalibrada]
    ) -> None:
        # Actualizar label
        if escala is None:
            self._lbl_escala.setText("escala: sin calibrar")
            self._lbl_escala.setObjectName("muted")
        else:
            self._lbl_escala.setText(f"escala: {escala.resumen_legible()}")
            self._lbl_escala.setObjectName("")
        self._reaplicar(self._lbl_escala)
        # Persistir la escala en el modelo del plano actualmente abierto
        if self._plano_activo_id is not None:
            self._proyecto.actualizar_escala(self._plano_activo_id, escala)

    def _on_mensaje_estado(self, msg: str) -> None:
        self._lbl_msg.setText(msg)

    def _on_modo_borrar_ui_status(self, activo: bool) -> None:
        if not activo:
            txt = self._lbl_msg.text()
            if txt.startswith("Borrar una por una"):
                self._lbl_msg.setText("")

    def _on_error_carga(self, mensaje: str) -> None:
        QMessageBox.warning(self, "No se pudo cargar el plano", mensaje)

    # --------------------------------------------- Acciones del panel

    def _abrir_dialogo_cargar(self) -> None:
        dlg = DialogoCargarPlano(parent=self.window())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        titulo, path = dlg.datos()
        try:
            self._proyecto.agregar_plano(titulo, path)
        except ValueError as exc:
            QMessageBox.warning(self, "Cargar plano", str(exc))

    def _abrir_plano_en_canvas(self, plano_id: str) -> None:
        plano = self._proyecto.plano_por_id(plano_id)
        if plano is None:
            return
        if not plano.existe_archivo():
            QMessageBox.warning(
                self, "Plano no encontrado",
                f"El archivo del plano ya no existe en:\n{plano.path}"
            )
            return

        # Cargar en canvas — el canvas emite escala_cambiada(None)
        # dentro de cargar_plano. Al haber cambio de plano, aplicamos
        # la escala persistida (si la hay) DESPUÉS de la carga.
        if not self._canvas.cargar_plano(plano.path):
            return

        # Aplicar escala guardada (si el plano ya estaba calibrado)
        if plano.esta_calibrado():
            self._canvas.set_escala(plano.escala)

        # Actualizar estado activo y visual de las cards
        self._plano_activo_id = plano.id
        self._lbl_plano_activo.setText(plano.titulo)
        self._lbl_plano_activo.setObjectName("")
        self._reaplicar(self._lbl_plano_activo)
        for pid, card in self._cards.items():
            card.set_activa(pid == plano.id)
        # Ocultar placeholder si estaba
        self._placeholder_canvas.setVisible(False)
        self._canvas.setVisible(True)
        # Sincronizar plano activo GLOBAL con el modelo — así otras
        # etapas (Delimitación, Elementos...) pueden abrirlo también.
        self._proyecto.set_plano_activo(plano.id)

    def _solicitar_renombrar(self, plano_id: str) -> None:
        plano = self._proyecto.plano_por_id(plano_id)
        if plano is None:
            return
        titulo_actual = plano.titulo
        # Diálogo simple con QLineEdit inline
        from PyQt6.QtWidgets import QInputDialog
        nuevo, ok = QInputDialog.getText(
            self, "Renombrar plano",
            f"Nuevo título para '{titulo_actual}':",
            text=titulo_actual,
        )
        if ok and nuevo.strip():
            self._proyecto.renombrar_plano(plano_id, nuevo.strip())

    def _solicitar_eliminar(self, plano_id: str) -> None:
        plano = self._proyecto.plano_por_id(plano_id)
        if plano is None:
            return
        resp = QMessageBox.question(
            self, "Eliminar plano",
            f"¿Eliminar el plano '{plano.titulo}' del proyecto?\n\n"
            "Esto no borra el archivo original, solo lo quita del "
            "proyecto. Las mediciones y calibración de este plano se "
            "pierden.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self._proyecto.eliminar_plano(plano_id)

    # ------------------------------------------------- Utilidades UI

    def _actualizar_estado_vacio(self) -> None:
        hay_planos = self._proyecto.cantidad_planos() > 0
        self._lbl_vacio_panel.setVisible(not hay_planos)
        # Placeholder del canvas visible solo si NO hay plano activo
        # (aunque haya otros planos en el listado sin abrir aún).
        sin_plano_activo = self._plano_activo_id is None
        self._placeholder_canvas.setVisible(sin_plano_activo)
        self._canvas.setVisible(not sin_plano_activo)

    @staticmethod
    def _reaplicar(w: QWidget) -> None:
        s = w.style()
        if s is not None:
            s.unpolish(w)
            s.polish(w)


# ---------------------------------------------------------------------------
# Ejecución independiente (desarrollo)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    proyecto_demo = ProyectoAbierto({
        "id": "PRJ-DEMO",
        "nombre": "Proyecto Demo",
        "cliente": "Cliente Demo",
        "tipo": "edificio",
        "subtipo": "Demo · desarrollo",
        "estado": "borrador",
    })
    main = QMainWindow()
    main.setWindowTitle("PaginaPlanos — Demo")
    main.resize(1400, 820)
    main.setStyleSheet(f"QMainWindow {{ background: {COLOR_FONDO}; }}")
    main.setCentralWidget(PaginaPlanos(proyecto_demo))
    main.show()
    sys.exit(app.exec())
