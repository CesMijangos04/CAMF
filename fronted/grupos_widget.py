"""
grupos_widget.py
────────────────
Widget de árbol colapsable para agrupar tableros y transformadores.
Se integra en inventario.py reemplazando el QTableWidget plano.

Uso rápido:
    from grupos_widget import VistaGrupos
    self.vista_tableros = VistaGrupos("tableros", columnas, parent=self)
    layout.addWidget(self.vista_tableros)
    self.vista_tableros.recargar()
"""

from __future__ import annotations
from typing import List, Optional, Callable
 
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QScrollArea, QSizePolicy, QDialog, QLineEdit,
    QComboBox, QFormLayout, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QCursor
 
import db_manager as db
 
# ─────────────────────────────────────────────
#  Paleta oscura (igual a tu app)
# ─────────────────────────────────────────────
STYLE_GRUPO_HEADER = """
    QFrame#grupoHeader {{
        background-color: {bg};
        border: none;
        border-left: 3px solid {acento};
        border-radius: 0px;
    }}
"""
COLOR_NIVEL = [
    ("#1e1e1e", "#0078d7"),   # nivel 0 — azul
    ("#252525", "#1D9E75"),   # nivel 1 — teal
    ("#2a2a2a", "#EF9F27"),   # nivel 2 — ámbar
    ("#2e2e2e", "#D85A30"),   # nivel 3+ — coral
]
 
STYLE_TABLE = """
    QTableWidget {
        background-color: #1a1a1a;
        color: white;
        border: none;
        gridline-color: #333;
    }
    QHeaderView::section {
        background-color: #2a2a2a;
        color: white;
        padding: 4px;
        border: 1px solid #444;
        min-height: 26px;
    }
    QTableWidget::item:selected {
        background-color: #0078d7;
        color: white;
    }
"""
 
STYLE_BTN_ACCION = """
    QPushButton {
        background: transparent;
        color: #aaa;
        border: 1px solid #444;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 11px;
    }
    QPushButton:hover { color: white; border-color: #888; }
"""
 
STYLE_BTN_PELIGRO = """
    QPushButton {
        background: transparent;
        color: #e05555;
        border: 1px solid #663333;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 11px;
    }
    QPushButton:hover { color: #ff7777; border-color: #aa4444; }
"""
 
 
# ══════════════════════════════════════════════════════════════
#  Diálogo: crear / renombrar grupo
# ══════════════════════════════════════════════════════════════
class DialogoGrupo(QDialog):
    def __init__(self, parent=None, nombre_actual: str = "", titulo: str = "Nuevo grupo"):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setFixedSize(340, 130)
        self.setStyleSheet("QDialog { background: #1e1e1e; color: white; } "
                           "QLineEdit { background: #2a2a2a; color: white; border: 1px solid #555; "
                           "border-radius: 5px; padding: 4px 8px; } "
                           "QLabel { color: #ccc; } "
                           "QPushButton { background: #3a3a3a; color: white; border-radius: 6px; "
                           "padding: 5px 14px; } "
                           "QPushButton:hover { background: #505050; } "
                           "QPushButton#btnOk { background: #0078d7; } "
                           "QPushButton#btnOk:hover { background: #005a9e; }")
 
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.input_nombre = QLineEdit(nombre_actual)
        self.input_nombre.setPlaceholderText("Ej. Empresa ABC, Edificio A, Piso 2…")
        form.addRow("Nombre:", self.input_nombre)
        layout.addLayout(form)
 
        botones = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        self.btn_ok = QPushButton("Guardar")
        self.btn_ok.setObjectName("btnOk")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._validar)
        botones.addStretch()
        botones.addWidget(btn_cancel)
        botones.addWidget(self.btn_ok)
        layout.addLayout(botones)
 
    def _validar(self):
        if self.input_nombre.text().strip():
            self.accept()
        else:
            self.input_nombre.setStyleSheet("border: 1px solid #e05555;")
 
    def nombre(self) -> str:
        return self.input_nombre.text().strip()
 
 
# ══════════════════════════════════════════════════════════════
#  Tabla de equipos dentro de un grupo
# ══════════════════════════════════════════════════════════════
class TablaEquipos(QTableWidget):
    """QTableWidget estilizado con las columnas de tableros o transformadores."""
 
    def __init__(self, columnas: List[str], parent=None):
        super().__init__(0, len(columnas), parent)
        self.setHorizontalHeaderLabels(columnas)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalHeader().setVisible(False)
        self.setStyleSheet(STYLE_TABLE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(36)
 
        self._auto_registrar_en_vista()
 
    def _auto_registrar_en_vista(self):
        """Sube buscando la VistaGrupos para registrarse al crearse."""
        widget = self.parent()
        while widget is not None:
            if hasattr(widget, "registrar_tabla") and callable(widget.registrar_tabla):
                widget.registrar_tabla(self)
                return
            widget = widget.parent()
 
    def mousePressEvent(self, event):
        """
        Custom mouse handling:
        - Click izquierdo SIN Ctrl: limpia selecciones de otras tablas hermanas
          y permite deseleccionar (toggle) si se hace clic en una fila ya seleccionada.
        - Click izquierdo CON Ctrl: deja el comportamiento por defecto de Qt
          (selección múltiple, deselección, etc).
        """
        from PyQt6.QtCore import Qt as _Qt
        ctrl_held = bool(event.modifiers() & _Qt.KeyboardModifier.ControlModifier)
        button_left = event.button() == _Qt.MouseButton.LeftButton
 
        if button_left and not ctrl_held:
            # Identificar la fila bajo el cursor
            idx = self.indexAt(event.pos())
            row = idx.row()
 
            # Avisar a la vista padre que limpie las selecciones de las demás tablas
            self._notificar_vista_padre()
 
            # Si la fila clickeada ya estaba seleccionada, deseleccionar (toggle)
            if row >= 0 and row in [i.row() for i in self.selectionModel().selectedRows()]:
                self.clearSelection()
                event.accept()
                return
 
        super().mousePressEvent(event)
 
    def _notificar_vista_padre(self):
        """Sube por los padres buscando la VistaGrupos para limpiar selecciones de tablas hermanas."""
        widget = self.parent()
        while widget is not None:
            if hasattr(widget, "limpiar_selecciones_excepto") and callable(widget.limpiar_selecciones_excepto):
                widget.limpiar_selecciones_excepto(self)
                return
            widget = widget.parent()
 
    def ajustar_altura(self):
        """Ajusta la altura del widget al contenido real de las filas."""
        alto = self.horizontalHeader().height()
        for r in range(self.rowCount()):
            alto += self.rowHeight(r)
        self.setFixedHeight(min(alto + 4, 400))   # máx 400px antes de scroll
 
    def poblar(self, filas: list, indices_cols: List[int]):
        """
        Llena la tabla con las filas de la DB.
        indices_cols indica qué columna de la tupla de DB va a cada columna visual.
        """
        self.setRowCount(0)
        for fila in filas:
            r = self.rowCount()
            self.insertRow(r)
            for col_vis, col_db in enumerate(indices_cols):
                valor = str(fila[col_db]) if fila[col_db] is not None else ""
                item = QTableWidgetItem(valor)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.setItem(r, col_vis, item)
        self.ajustar_altura()
 
 
# ══════════════════════════════════════════════════════════════
#  Widget de un grupo (cabecera colapsable + hijos recursivos)
# ══════════════════════════════════════════════════════════════
class GrupoWidget(QWidget):
    solicitar_recarga = pyqtSignal()   # sube hasta VistaGrupos para recargar todo
 
    def __init__(self,
                 nodo: dict,
                 tabla_db: str,
                 columnas: List[str],
                 indices_cols: List[int],
                 nivel: int = 0,
                 menu_equipo_fn: Optional[Callable] = None,
                 dbl_click_fn: Optional[Callable] = None,
                 parent=None):
        super().__init__(parent)
        self.nodo = nodo
        self.tabla_db = tabla_db
        self.columnas = columnas
        self.indices_cols = indices_cols
        self.nivel = nivel
        self.menu_equipo_fn = menu_equipo_fn
        self.dbl_click_fn = dbl_click_fn
        self._expandido = True
 
        # Estado inicial: si el grupo estaba contraído antes (persistido), arrancar contraído
        vista = self._buscar_vista_padre()
        if vista is not None and vista.es_grupo_contraido(nodo["id"]):
            self._expandido = False
        else:
            self._expandido = True
 
        self._construir_ui()
 
    def _buscar_vista_padre(self):
        """Sube por los padres buscando la VistaGrupos para sincronizar estado contraído."""
        widget = self.parent()
        while widget is not None:
            if hasattr(widget, "es_grupo_contraido") and callable(widget.es_grupo_contraido):
                return widget
            widget = widget.parent()
        return None
 
    def _construir_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 4)
        self._layout.setSpacing(2)
 
        # ── Cabecera ──────────────────────────────────────────
        color_idx = min(self.nivel, len(COLOR_NIVEL) - 1)
        bg, acento = COLOR_NIVEL[color_idx]
 
        self._header = QFrame()
        self._header.setObjectName("grupoHeader")
        self._header.setStyleSheet(
            STYLE_GRUPO_HEADER.format(bg=bg, acento=acento)
        )
        self._header.setFixedHeight(38)
        self._header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
 
        h_layout = QHBoxLayout(self._header)
        h_layout.setContentsMargins(10, 0, 8, 0)
        h_layout.setSpacing(8)
 
        # Flecha
        self._flecha = QLabel("▾" if self._expandido else "▸")
        self._flecha.setStyleSheet(f"color: {acento}; font-size: 14px;")
        self._flecha.setFixedWidth(16)
 
        # Nombre del grupo
        self._lbl_nombre = QLabel(self.nodo["nombre"])
        self._lbl_nombre.setStyleSheet("color: white; font-size: 13px; font-weight: 500;")
 
        # Contador de equipos
        total = self._contar_equipos_recursivo(self.nodo)
        self._lbl_count = QLabel(f"{total} equipo{'s' if total != 1 else ''}")
        self._lbl_count.setStyleSheet("color: #888; font-size: 11px;")
 
        # Botones de acción (visibles solo en hover)
        self._btn_subgrupo = QPushButton("+ Subgrupo")
        self._btn_subgrupo.setStyleSheet(STYLE_BTN_ACCION)
        self._btn_subgrupo.setFixedHeight(24)
        self._btn_subgrupo.clicked.connect(self._crear_subgrupo)
 
        self._btn_renombrar = QPushButton("Renombrar")
        self._btn_renombrar.setStyleSheet(STYLE_BTN_ACCION)
        self._btn_renombrar.setFixedHeight(24)
        self._btn_renombrar.clicked.connect(self._renombrar)
 
        self._btn_eliminar = QPushButton("Eliminar")
        self._btn_eliminar.setStyleSheet(STYLE_BTN_PELIGRO)
        self._btn_eliminar.setFixedHeight(24)
        self._btn_eliminar.clicked.connect(self._eliminar)
 
        # Botón de unifilar: solo aparece en hover (como los demás), pero sólo
        # cuando el grupo tiene contenido eléctrico que mostrar.
        self._btn_unifilar = QPushButton("⚡")
        self._btn_unifilar.setStyleSheet(STYLE_BTN_ACCION)
        self._btn_unifilar.setFixedHeight(24)
        self._btn_unifilar.setFixedWidth(28)
        self._btn_unifilar.setToolTip("Ver diagrama unifilar")
        self._btn_unifilar.clicked.connect(self._ver_unifilar)
        self._btn_unifilar.hide()  # oculto por default
 
        # Botón de cuadro de cargas: igual que el unifilar.
        self._btn_cuadro = QPushButton("📋")
        self._btn_cuadro.setStyleSheet(STYLE_BTN_ACCION)
        self._btn_cuadro.setFixedHeight(24)
        self._btn_cuadro.setFixedWidth(28)
        self._btn_cuadro.setToolTip("Ver cuadro de cargas")
        self._btn_cuadro.clicked.connect(self._ver_cuadro_cargas)
        self._btn_cuadro.hide()  # oculto por default
 
        # Ocultar botones inicialmente
        for b in [self._btn_subgrupo, self._btn_renombrar, self._btn_eliminar]:
            b.hide()
 
        h_layout.addWidget(self._flecha)
        h_layout.addWidget(self._lbl_nombre)
        h_layout.addStretch()
        h_layout.addWidget(self._lbl_count)
        h_layout.addWidget(self._btn_unifilar)
        h_layout.addWidget(self._btn_cuadro)
        h_layout.addWidget(self._btn_subgrupo)
        h_layout.addWidget(self._btn_renombrar)
        h_layout.addWidget(self._btn_eliminar)
 
        self._header.mousePressEvent = lambda e: self._toggle()
        self._header.enterEvent = lambda e: self._mostrar_botones(True)
        self._header.leaveEvent = lambda e: self._mostrar_botones(False)
 
        # Evaluar si el grupo tiene contenido para mostrar unifilar
        self._evaluar_unifilar_visible()
 
        self._layout.addWidget(self._header)
 
        # ── Contenido (tabla + hijos) ─────────────────────────
        self._contenedor = QWidget()
        self._cont_layout = QVBoxLayout(self._contenedor)
        self._cont_layout.setContentsMargins(self.nivel * 16 + 16, 4, 4, 4)
        self._cont_layout.setSpacing(4)
 
        # Tabla de equipos propios de este grupo
        equipos = db.obtener_equipos_por_grupo(self.tabla_db, self.nodo["id"])
        if equipos:
            self._tabla = TablaEquipos(self.columnas, self)
            self._tabla.poblar(equipos, self.indices_cols)
            if self.menu_equipo_fn:
                self._tabla.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                self._tabla.customContextMenuRequested.connect(self.menu_equipo_fn)
            if self.dbl_click_fn:
                self._tabla.cellDoubleClicked.connect(self.dbl_click_fn)
            self._cont_layout.addWidget(self._tabla)
        else:
            lbl = QLabel("Sin equipos en este grupo")
            lbl.setStyleSheet("color: #555; font-size: 11px; padding: 4px 0;")
            self._cont_layout.addWidget(lbl)
 
        # Subgrupos hijos (recursivo)
        for hijo in self.nodo.get("hijos", []):
            hijo_widget = GrupoWidget(
                nodo=hijo,
                tabla_db=self.tabla_db,
                columnas=self.columnas,
                indices_cols=self.indices_cols,
                nivel=self.nivel + 1,
                menu_equipo_fn=self.menu_equipo_fn,
                dbl_click_fn=self.dbl_click_fn,
                parent=self
            )
            hijo_widget.solicitar_recarga.connect(self.solicitar_recarga)
            self._cont_layout.addWidget(hijo_widget)
 
        self._layout.addWidget(self._contenedor)
 
        # Aplicar estado contraído inicial (persistido entre sesiones)
        if not self._expandido:
            self._contenedor.setVisible(False)
 
    def _contar_equipos_recursivo(self, nodo) -> int:
        count = len(db.obtener_equipos_por_grupo(self.tabla_db, nodo["id"]))
        for hijo in nodo.get("hijos", []):
            count += self._contar_equipos_recursivo(hijo)
        return count
 
    def _toggle(self):
        self._expandido = not self._expandido
        self._contenedor.setVisible(self._expandido)
        self._flecha.setText("▾" if self._expandido else "▸")
 
        # Persistir el cambio entre sesiones
        vista = self._buscar_vista_padre()
        if vista is not None:
            vista.marcar_grupo_contraido(self.nodo["id"], not self._expandido)
 
    def _mostrar_botones(self, visible: bool):
        for b in [self._btn_subgrupo, self._btn_renombrar, self._btn_eliminar]:
            b.setVisible(visible)
        # El botón de unifilar solo aparece en hover si el grupo tiene contenido eléctrico
        if visible and self._unifilar_disponible:
            self._btn_unifilar.setVisible(True)
        else:
            self._btn_unifilar.setVisible(False)
        # El botón de cuadro de cargas solo aparece en hover si hay circuitos guardados
        if visible and self._cuadro_disponible:
            self._btn_cuadro.setVisible(True)
        else:
            self._btn_cuadro.setVisible(False)
 
    def _evaluar_unifilar_visible(self):
        """
        Determina si el grupo tiene tableros o transformadores para mostrar unifilar.
        Solo guarda el flag; la visibilidad se controla por hover en _mostrar_botones.
        También evalúa si hay datos para el cuadro de cargas.
        """
        self._unifilar_disponible = False
        self._cuadro_disponible = False
        try:
            from unifilar import UnifilarManager
            mgr = UnifilarManager(self)
            self._unifilar_disponible = mgr.grupo_tiene_unifilar(self.nodo["id"])
        except Exception as e:
            print(f"[UNIFILAR] No se pudo evaluar visibilidad: {e}")
            self._unifilar_disponible = False
        try:
            from cuadro_cargas import CuadroCargasManager
            mgr_cc = CuadroCargasManager(self)
            self._cuadro_disponible = mgr_cc.grupo_tiene_cuadro(self.nodo["id"])
        except Exception as e:
            print(f"[CUADRO] No se pudo evaluar visibilidad: {e}")
            self._cuadro_disponible = False
 
    def _ver_unifilar(self):
        """Abre la ventana del diagrama unifilar para este grupo."""
        try:
            from unifilar import VentanaUnifilar
            self._ventana_unifilar = VentanaUnifilar(
                grupo_id=self.nodo["id"],
                grupo_nombre=self.nodo.get("nombre", ""),
                parent=None,
            )
            self._ventana_unifilar.show()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error al abrir unifilar",
                                 f"No se pudo abrir el diagrama:\n{e}")
            print(f"[UNIFILAR] Error: {e}")
            import traceback
            traceback.print_exc()
 
    def _ver_cuadro_cargas(self):
        """Abre la ventana del cuadro de cargas para este grupo."""
        try:
            from cuadro_cargas import VentanaCuadroCargas
            self._ventana_cuadro = VentanaCuadroCargas(
                grupo_id=self.nodo["id"],
                grupo_nombre=self.nodo.get("nombre", ""),
                parent=None,
            )
            self._ventana_cuadro.show()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error al abrir cuadro de cargas",
                                 f"No se pudo abrir el cuadro:\n{e}")
            print(f"[CUADRO] Error: {e}")
            import traceback
            traceback.print_exc()
 
 
    def _crear_subgrupo(self):
        dlg = DialogoGrupo(self, titulo=f"Nuevo subgrupo en '{self.nodo['nombre']}'")
        if dlg.exec():
            db.crear_grupo(dlg.nombre(), padre_id=self.nodo["id"])
            self.solicitar_recarga.emit()
 
    def _renombrar(self):
        dlg = DialogoGrupo(self, nombre_actual=self.nodo["nombre"], titulo="Renombrar grupo")
        if dlg.exec():
            db.renombrar_grupo(self.nodo["id"], dlg.nombre())
            self.solicitar_recarga.emit()
 
    def _eliminar(self):
        hijos = self.nodo.get("hijos", [])
        equipos = db.obtener_equipos_por_grupo(self.tabla_db, self.nodo["id"])
        msg = f"¿Eliminar el grupo '{self.nodo['nombre']}'?"
        if hijos or equipos:
            msg += "\n\nLos subgrupos y equipos dentro quedarán sin grupo asignado."
        resp = QMessageBox.question(self, "Confirmar eliminación", msg)
        if resp == QMessageBox.StandardButton.Yes:
            db.eliminar_grupo(self.nodo["id"])
            self.solicitar_recarga.emit()
 
 
# ══════════════════════════════════════════════════════════════
#  Vista principal: árbol completo + equipos sin grupo
# ══════════════════════════════════════════════════════════════
class VistaGrupos(QWidget):
    """
    Widget principal que va dentro de cada pestaña (Tableros / Transformadores).
    Reemplaza al QTableWidget plano.
 
    Parámetros:
        tabla_db      : 'tableros' o 'transformadores'
        columnas      : encabezados visuales
        indices_cols  : posición de cada campo en la tupla que devuelve la DB
        menu_equipo_fn: función(pos) para el menú contextual (la que ya tienes)
    """
 
    def __init__(self,
                 tabla_db: str,
                 columnas: List[str],
                 indices_cols: List[int],
                 menu_equipo_fn: Optional[Callable] = None,
                 dbl_click_fn: Optional[Callable] = None,
                 parent=None):
        super().__init__(parent)
        self.tabla_db = tabla_db
        self.columnas = columnas
        self.indices_cols = indices_cols
        self.menu_equipo_fn = menu_equipo_fn
        self.dbl_click_fn = dbl_click_fn
 
        # Registro de tablas hijas para selección única entre todas ellas
        self._tablas_registradas = []
 
        # IDs de grupos contraídos persistidos entre sesiones
        # Se carga al iniciar y se sincroniza con disco cada vez que cambia.
        from ui_state import obtener_grupos_contraidos
        self._grupos_contraidos = obtener_grupos_contraidos(tabla_db)
 
        self._construir_ui()
 
    # ── selección única entre tablas hermanas ──────────────
    def registrar_tabla(self, tabla):
        """Las tablas hijas se registran aquí al crearse."""
        if tabla not in self._tablas_registradas:
            self._tablas_registradas.append(tabla)
 
    def limpiar_selecciones_excepto(self, tabla_actual):
        """Llamado por una tabla al recibir clic: limpia el resto."""
        for t in self._tablas_registradas:
            if t is not tabla_actual:
                try:
                    t.clearSelection()
                except Exception:
                    pass  # tabla ya destruida
 
    # ── Persistencia de grupos contraídos ────────────────────
    def es_grupo_contraido(self, grupo_id: int) -> bool:
        return grupo_id in self._grupos_contraidos
 
    def marcar_grupo_contraido(self, grupo_id: int, contraido: bool):
        """Actualiza el set y guarda en disco inmediatamente."""
        from ui_state import guardar_grupos_contraidos
        if contraido:
            self._grupos_contraidos.add(grupo_id)
        else:
            self._grupos_contraidos.discard(grupo_id)
        guardar_grupos_contraidos(self.tabla_db, self._grupos_contraidos)
 
    def _construir_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
 
        # Barra superior con botón "Nuevo grupo"
        barra = QHBoxLayout()
        barra.setContentsMargins(8, 6, 8, 6)
        self._btn_nuevo_grupo = QPushButton("+ Nuevo grupo")
        self._btn_nuevo_grupo.setStyleSheet("""
            QPushButton {
                background: #0078d7; color: white; border-radius: 6px;
                padding: 5px 14px; font-size: 12px;
            }
            QPushButton:hover { background: #005a9e; }
        """)
        self._btn_nuevo_grupo.clicked.connect(self._crear_grupo_raiz)
        barra.addStretch()
        barra.addWidget(self._btn_nuevo_grupo)
        raiz.addLayout(barra)
 
        # Área de scroll con el árbol
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        raiz.addWidget(self._scroll)
 
        self.recargar()
 
    def recargar(self):
        """Reconstruye el árbol completo desde la DB."""
        # Limpiar registro de tablas previas (se van a recrear)
        self._tablas_registradas = []
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(contenedor)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)
 
        arbol = db.construir_arbol_grupos(tabla_db=self.tabla_db)
 
        # Grupos con sus equipos
        for nodo_raiz in arbol:
            gw = GrupoWidget(
                nodo=nodo_raiz,
                tabla_db=self.tabla_db,
                columnas=self.columnas,
                indices_cols=self.indices_cols,
                nivel=0,
                menu_equipo_fn=self.menu_equipo_fn,
                dbl_click_fn=self.dbl_click_fn,
                parent=self
            )
            gw.solicitar_recarga.connect(self.recargar)
            layout.addWidget(gw)
 
        # Equipos sin grupo asignado
        sin_grupo = db.obtener_equipos_por_grupo(self.tabla_db, None)
        if sin_grupo:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("color: #333;")
            layout.addWidget(sep)
 
            lbl = QLabel("Sin grupo asignado")
            lbl.setStyleSheet("color: #666; font-size: 11px; padding: 4px 4px 2px;")
            layout.addWidget(lbl)
 
            tabla_sg = TablaEquipos(self.columnas, self)
            tabla_sg.poblar(sin_grupo, self.indices_cols)
            if self.menu_equipo_fn:
                tabla_sg.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                tabla_sg.customContextMenuRequested.connect(self.menu_equipo_fn)
            if self.dbl_click_fn:
                tabla_sg.cellDoubleClicked.connect(self.dbl_click_fn)
            layout.addWidget(tabla_sg)
 
        # Mensaje vacío si no hay nada
        if not arbol and not sin_grupo:
            lbl_vacio = QLabel("No hay grupos ni equipos aún.\nUsa '+ Nuevo grupo' para empezar.")
            lbl_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_vacio.setStyleSheet("color: #555; font-size: 13px; padding: 40px;")
            layout.addWidget(lbl_vacio)
 
        layout.addStretch()
        self._scroll.setWidget(contenedor)
 
    def _crear_grupo_raiz(self):
        dlg = DialogoGrupo(self, titulo="Nuevo grupo")
        if dlg.exec():
            db.crear_grupo(dlg.nombre(), padre_id=None)
            self.recargar()