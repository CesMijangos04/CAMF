"""
selector_equipo_dialog.py
─────────────────────────
Diálogo modal para seleccionar uno o varios equipos (tableros o transformadores)
desde el árbol de grupos. Reusa la paleta de colores de grupos_widget.py.
 
Características:
  - Árbol colapsable por grupo / subgrupo (mismo estilo que VistaGrupos).
  - Checkbox tri-state en cada cabecera de grupo:
        vacío    → ningún equipo del grupo (ni subgrupos) seleccionado.
        parcial  → algunos seleccionados.
        lleno    → todos seleccionados.
    Click en el checkbox del grupo: alterna todos sus equipos (recursivo).
  - Checkbox individual en cada fila de equipo.
  - Sección "Sin grupo asignado" al final si aplica.
  - Contador en vivo "N equipos seleccionados" abajo a la izquierda.
  - Botones Cancelar / Aceptar (Aceptar deshabilitado mientras no haya selección).
  - Resultado: lista de dicts {"id": ..., "tipo": "tableros"|"transformadores",
                               "ubicacion": ...} accesible vía `equipos_seleccionados`.
"""
 
from __future__ import annotations
from typing import List, Optional, Dict, Callable
 
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QScrollArea, QSizePolicy, QCheckBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QWidget,
    QHeaderView
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
 
import db_manager as db
 
 
# ─────────────────────────────────────────────
#  Paleta (igual a grupos_widget.py)
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
    ("#1e1e1e", "#0078d7"),   # nivel 0
    ("#252525", "#1D9E75"),   # nivel 1
    ("#2a2a2a", "#EF9F27"),   # nivel 2
    ("#2e2e2e", "#D85A30"),   # nivel 3+
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
        min-height: 24px;
    }
"""
 
CHECKBOX_STYLE = """
    QCheckBox {
        color: white;
        spacing: 8px;
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
"""
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  Cabecera colapsable + tabla de equipos del grupo
# ══════════════════════════════════════════════════════════════════════════════
class GrupoSeleccionableWidget(QWidget):
    """
    Cabecera + tabla de equipos + subgrupos recursivos.
    Emite `cambio_seleccion` cada vez que un checkbox cambia.
    """
    cambio_seleccion = pyqtSignal()
 
    def __init__(self,
                 nodo: dict,
                 tabla_db: str,
                 columnas_visibles: List[str],
                 indices_cols: List[int],
                 nivel: int = 0,
                 grupos_contraidos: Optional[set] = None,
                 preseleccionados: Optional[set] = None,
                 parent=None):
        super().__init__(parent)
        self.nodo = nodo
        self.tabla_db = tabla_db
        self.columnas_visibles = columnas_visibles
        self.indices_cols = indices_cols
        self.nivel = nivel
        # Sets compartidos por referencia con el SelectorEquipoDialog.
        # Modificarlos aquí afecta al estado global del diálogo.
        self._grupos_contraidos: set = grupos_contraidos if grupos_contraidos is not None else set()
        self._preseleccionados: set = preseleccionados if preseleccionados is not None else set()
        # Estado inicial: si este grupo está en el set de contraídos, arranca contraído
        self._expandido = (self.nodo["id"] not in self._grupos_contraidos)
 
        # Subgrupos hijos (instancias de GrupoSeleccionableWidget)
        self._hijos_widgets: List[GrupoSeleccionableWidget] = []
        # Filas de equipos: lista de (checkbox, equipo_id, equipo_tipo)
        self._filas_equipos: List = []
 
        self._construir_ui()
 
    # ── construcción ─────────────────────────────────────────────────────
    def _construir_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 4)
        self._layout.setSpacing(2)
 
        # Cabecera coloreada por nivel
        color_idx = min(self.nivel, len(COLOR_NIVEL) - 1)
        bg, acento = COLOR_NIVEL[color_idx]
 
        self._header = QFrame()
        self._header.setObjectName("grupoHeader")
        self._header.setStyleSheet(STYLE_GRUPO_HEADER.format(bg=bg, acento=acento))
        self._header.setFixedHeight(36)
        self._header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
 
        h_layout = QHBoxLayout(self._header)
        h_layout.setContentsMargins(10, 0, 8, 0)
        h_layout.setSpacing(8)
 
        # Flecha de expandir/colapsar
        self._flecha = QLabel("▾" if self._expandido else "▸")
        self._flecha.setStyleSheet(f"color: {acento}; font-size: 14px;")
        self._flecha.setFixedWidth(16)
        h_layout.addWidget(self._flecha)
 
        # Checkbox tri-state para el grupo completo
        self._chk_grupo = QCheckBox()
        self._chk_grupo.setStyleSheet(CHECKBOX_STYLE)
        self._chk_grupo.setTristate(False)  # el usuario sólo alterna entre marcado/desmarcado;
                                            # el estado parcial lo ponemos nosotros programáticamente
        self._chk_grupo.clicked.connect(self._on_chk_grupo_clicked)
        h_layout.addWidget(self._chk_grupo)
 
        # Nombre del grupo
        lbl_nombre = QLabel(self.nodo["nombre"])
        lbl_nombre.setStyleSheet("color: white; font-size: 13px; font-weight: 500;")
        h_layout.addWidget(lbl_nombre)
 
        # Contador de equipos (total recursivo)
        total = self._contar_equipos_recursivo(self.nodo)
        self._lbl_count = QLabel(f"{total} equipo{'s' if total != 1 else ''}")
        self._lbl_count.setStyleSheet("color: #888; font-size: 11px;")
        h_layout.addWidget(self._lbl_count)
 
        h_layout.addStretch()
        self._layout.addWidget(self._header)
 
        # Click en cualquier parte del header (excepto checkbox) → colapsar/expandir
        self._header.mousePressEvent = self._on_header_clicked
 
        # Contenedor de hijos (subgrupos + tabla de equipos del grupo)
        self._contenedor_hijos = QWidget()
        self._layout_hijos = QVBoxLayout(self._contenedor_hijos)
        self._layout_hijos.setContentsMargins(20, 0, 0, 0)  # indent visual
        self._layout_hijos.setSpacing(2)
        self._layout.addWidget(self._contenedor_hijos)
 
        # 1) Subgrupos
        for sub in self.nodo.get("hijos", []):
            sub_widget = GrupoSeleccionableWidget(
                nodo=sub,
                tabla_db=self.tabla_db,
                columnas_visibles=self.columnas_visibles,
                indices_cols=self.indices_cols,
                nivel=self.nivel + 1,
                grupos_contraidos=self._grupos_contraidos,
                preseleccionados=self._preseleccionados,
                parent=self
            )
            sub_widget.cambio_seleccion.connect(self._propagar_cambio_desde_hijo)
            self._hijos_widgets.append(sub_widget)
            self._layout_hijos.addWidget(sub_widget)
 
        # 2) Equipos del grupo (no de sus hijos — esos los maneja el sub-widget)
        equipos = db.obtener_equipos_por_grupo(self.tabla_db, self.nodo["id"])
        if equipos:
            self._construir_tabla_equipos(equipos)
 
        # Aplicar estado de colapso inicial (heredado del set persistido)
        self._contenedor_hijos.setVisible(self._expandido)
        # Sincronizar el checkbox del grupo según las preselecciones aplicadas
        self._sincronizar_chk_grupo()
 
    def _construir_tabla_equipos(self, equipos):
        """Crea una QTableWidget con checkbox en la primera columna."""
        n_cols = 1 + len(self.columnas_visibles)
        tabla = QTableWidget(0, n_cols)
        tabla.setHorizontalHeaderLabels(["", *self.columnas_visibles])
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.verticalHeader().setVisible(False)
        tabla.setStyleSheet(STYLE_TABLE)
        tabla.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        # Columna 0 (checkbox) fija; resto repartido proporcionalmente
        header = tabla.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for c in range(1, n_cols):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
 
        # Columna 0 (checkbox) angosta
        tabla.setColumnWidth(0, 36)
 
        for fila_db in equipos:
            r = tabla.rowCount()
            tabla.insertRow(r)
 
            chk = QCheckBox()
            chk.setStyleSheet(CHECKBOX_STYLE)
 
            equipo_id = fila_db[0]  # primer campo siempre es id
            # Pre-selección: si este (id, tipo) viene en el set, marcarlo antes
            # de conectar la señal para no disparar updates innecesarios.
            if (equipo_id, self.tabla_db) in self._preseleccionados:
                chk.setChecked(True)
            chk.stateChanged.connect(self._on_chk_equipo_changed)
 
            self._filas_equipos.append((chk, equipo_id, self.tabla_db))
 
            # El checkbox se coloca centrado en una celda
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.addWidget(chk, alignment=Qt.AlignmentFlag.AlignCenter)
            tabla.setCellWidget(r, 0, cell)
 
            for col_vis, col_db in enumerate(self.indices_cols, start=1):
                valor = str(fila_db[col_db]) if fila_db[col_db] is not None else ""
                item = QTableWidgetItem(valor)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                tabla.setItem(r, col_vis, item)
 
        # Ajustar altura para mostrar todas las filas sin scroll propio
        alto = tabla.horizontalHeader().height()
        for r in range(tabla.rowCount()):
            alto += tabla.rowHeight(r)
        tabla.setFixedHeight(alto + 4)
 
        self._layout_hijos.addWidget(tabla)
 
    # ── Lógica de selección ──────────────────────────────────────────────
    def _on_chk_grupo_clicked(self, _checked):
        """
        Click del usuario en el checkbox de grupo.
        Si actualmente está PARCIAL o VACÍO → marcar todos.
        Si está LLENO → desmarcar todos.
        """
        # Calculamos el estado antes de aplicar el "toggle" automático que hizo Qt
        # tras el clic. Mejor leemos el estado actual de los hijos para decidir.
        total, marcados = self._contar_seleccionados()
        if marcados < total:
            self._set_todos(True)
        else:
            self._set_todos(False)
        # Sincronizar el visual del propio checkbox según el nuevo estado
        self._sincronizar_chk_grupo()
        self.cambio_seleccion.emit()
 
    def _set_todos(self, marcado: bool):
        """Recursivamente marca/desmarca todos los equipos del grupo y subgrupos."""
        for chk, _, _ in self._filas_equipos:
            chk.blockSignals(True)
            chk.setChecked(marcado)
            chk.blockSignals(False)
        for hijo in self._hijos_widgets:
            hijo._set_todos(marcado)
            hijo._sincronizar_chk_grupo()
 
    def _on_chk_equipo_changed(self, _state):
        """Cuando un checkbox de equipo cambia, refrescar el estado del grupo."""
        self._sincronizar_chk_grupo()
        self.cambio_seleccion.emit()
 
    def _propagar_cambio_desde_hijo(self):
        """Cuando un subgrupo notifica cambio, refrescar el estado de este grupo."""
        self._sincronizar_chk_grupo()
        self.cambio_seleccion.emit()
 
    def _sincronizar_chk_grupo(self):
        """Actualiza el checkbox del grupo (vacío / parcial / lleno) sin emitir clicked."""
        total, marcados = self._contar_seleccionados()
        self._chk_grupo.blockSignals(True)
        # Para mostrar el estado parcial necesitamos tristate temporal
        if marcados == 0:
            self._chk_grupo.setTristate(False)
            self._chk_grupo.setCheckState(Qt.CheckState.Unchecked)
        elif marcados == total:
            self._chk_grupo.setTristate(False)
            self._chk_grupo.setCheckState(Qt.CheckState.Checked)
        else:
            self._chk_grupo.setTristate(True)
            self._chk_grupo.setCheckState(Qt.CheckState.PartiallyChecked)
        self._chk_grupo.blockSignals(False)
 
    def _contar_seleccionados(self):
        """Devuelve (total_equipos, equipos_marcados) considerando subgrupos."""
        total = len(self._filas_equipos)
        marcados = sum(1 for chk, _, _ in self._filas_equipos if chk.isChecked())
        for hijo in self._hijos_widgets:
            t, m = hijo._contar_seleccionados()
            total += t
            marcados += m
        return total, marcados
 
    def _contar_equipos_recursivo(self, nodo):
        """Cuenta los equipos del nodo y todos sus descendientes."""
        equipos = db.obtener_equipos_por_grupo(self.tabla_db, nodo["id"])
        n = len(equipos)
        for hijo in nodo.get("hijos", []):
            n += self._contar_equipos_recursivo(hijo)
        return n
 
    # ── colapsar / expandir ──────────────────────────────────────────────
    def _on_header_clicked(self, event):
        self._expandido = not self._expandido
        self._contenedor_hijos.setVisible(self._expandido)
        self._flecha.setText("▾" if self._expandido else "▸")
        # Mantener el set compartido al día (lo recupera el diálogo al cerrar)
        if self._expandido:
            self._grupos_contraidos.discard(self.nodo["id"])
        else:
            self._grupos_contraidos.add(self.nodo["id"])
 
    # ── Recolección de la selección final ────────────────────────────────
    def recolectar_seleccionados(self) -> List[Dict]:
        """Devuelve lista de dicts {id, tipo} de equipos marcados."""
        resultado = []
        for chk, eq_id, eq_tipo in self._filas_equipos:
            if chk.isChecked():
                resultado.append({"id": eq_id, "tipo": eq_tipo})
        for hijo in self._hijos_widgets:
            resultado.extend(hijo.recolectar_seleccionados())
        return resultado
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  Diálogo principal
# ══════════════════════════════════════════════════════════════════════════════
class SelectorEquipoDialog(QDialog):
    """
    Diálogo modal de selección múltiple de equipos.
 
    Uso:
        dlg = SelectorEquipoDialog("tableros", parent)
        if dlg.exec():
            equipos = dlg.equipos_seleccionados  # lista de dicts
    """
 
    # Definición de columnas visibles por tipo de equipo
    _COLS_TABLEROS = {
        "columnas": ["ID", "Nombre", "Ubicación", "Tipo", "Nº circuitos"],
        "indices":  [0, 1, 2, 5, 6],  # según schema de 'tableros'
    }
    _COLS_TRANSFORMADORES = {
        "columnas": ["ID", "Ubicación", "Capacidad", "Tensión"],
        "indices":  [0, 1, 2, 3],  # según schema de 'transformadores'
    }
 
    def __init__(self, tabla_db: str, parent=None,
                 grupos_contraidos: Optional[set] = None,
                 equipos_preseleccionados: Optional[List[Dict]] = None):
        super().__init__(parent)
        if tabla_db not in ("tableros", "transformadores"):
            raise ValueError(f"tabla_db debe ser 'tableros' o 'transformadores', no {tabla_db!r}")
        self.tabla_db = tabla_db
        self.equipos_seleccionados: List[Dict] = []
 
        # Estado de colapso persistido entre aperturas (se devuelve al cerrar
        # vía obtener_grupos_contraidos()). Se pasa por referencia para que
        # los GrupoSeleccionableWidget puedan ir actualizándolo al colapsar/expandir.
        self._grupos_contraidos: set = set(grupos_contraidos) if grupos_contraidos else set()
 
        # IDs ya seleccionados (para volver a marcar los checkboxes al reabrir).
        # Tuplas (equipo_id, equipo_tipo) para lookup O(1).
        self._preseleccionados: set = set()
        if equipos_preseleccionados:
            for eq in equipos_preseleccionados:
                self._preseleccionados.add((eq["id"], eq["tipo"]))
 
        cfg = self._COLS_TABLEROS if tabla_db == "tableros" else self._COLS_TRANSFORMADORES
        self.columnas = cfg["columnas"]
        self.indices_cols = cfg["indices"]
 
        titulo = "Seleccionar tableros" if tabla_db == "tableros" else "Seleccionar transformadores"
        self.setWindowTitle(titulo)
        self.resize(720, 520)
        self.setStyleSheet("""
            QDialog { background-color: #121212; color: white; }
            QLabel { color: white; }
        """)
 
        self._grupos_widgets: List[GrupoSeleccionableWidget] = []
        self._filas_sin_grupo: List = []  # (chk, equipo_id, equipo_tipo)
 
        self._construir_ui()
        self._actualizar_contador()
 
    def _construir_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
 
        # Banner superior
        banner = QLabel("Marca los equipos que deseas incluir en el mantenimiento. "
                        "Puedes marcar la cabecera de un grupo para seleccionarlo completo.")
        banner.setWordWrap(True)
        banner.setStyleSheet("color: #aaa; font-size: 12px; padding: 4px;")
        layout.addWidget(banner)
 
        # Área scrollable con el árbol
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #2a2a2a; background: transparent; }")
 
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        v = QVBoxLayout(contenedor)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)
 
        # Cargar árbol de grupos filtrado por tabla
        arbol = db.construir_arbol_grupos(tabla_db=self.tabla_db)
 
        for nodo_raiz in arbol:
            gw = GrupoSeleccionableWidget(
                nodo=nodo_raiz,
                tabla_db=self.tabla_db,
                columnas_visibles=self.columnas,
                indices_cols=self.indices_cols,
                nivel=0,
                grupos_contraidos=self._grupos_contraidos,
                preseleccionados=self._preseleccionados,
                parent=contenedor
            )
            gw.cambio_seleccion.connect(self._actualizar_contador)
            self._grupos_widgets.append(gw)
            v.addWidget(gw)
 
        # Equipos sin grupo asignado
        sin_grupo = db.obtener_equipos_por_grupo(self.tabla_db, None)
        if sin_grupo:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("color: #333;")
            v.addWidget(sep)
 
            lbl_sg = QLabel("Sin grupo asignado")
            lbl_sg.setStyleSheet("color: #888; font-size: 11px; padding: 4px 4px 2px;")
            v.addWidget(lbl_sg)
 
            self._construir_tabla_sin_grupo(sin_grupo, v)
 
        # Mensaje vacío si no hay nada
        if not arbol and not sin_grupo:
            lbl_vacio = QLabel(
                f"No hay {self.tabla_db} registrados.\n"
                "Agrégalos primero desde la pestaña Inventario."
            )
            lbl_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_vacio.setStyleSheet("color: #555; font-size: 13px; padding: 40px;")
            v.addWidget(lbl_vacio)
 
        v.addStretch()
        scroll.setWidget(contenedor)
        layout.addWidget(scroll, 1)
 
        # Footer: contador + botones
        footer = QHBoxLayout()
        self._lbl_contador = QLabel("0 equipos seleccionados")
        self._lbl_contador.setStyleSheet("color: #aaa; font-size: 12px;")
        footer.addWidget(self._lbl_contador)
        footer.addStretch()
 
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setStyleSheet("""
            QPushButton { background-color: #3a3a3a; color: white; border-radius: 6px;
                          padding: 6px 18px; }
            QPushButton:hover { background-color: #505050; }
        """)
        btn_cancelar.clicked.connect(self.reject)
        footer.addWidget(btn_cancelar)
 
        self._btn_aceptar = QPushButton("Aceptar")
        self._btn_aceptar.setEnabled(False)
        self._btn_aceptar.setStyleSheet("""
            QPushButton { background-color: #0078d7; color: white; border-radius: 6px;
                          padding: 6px 18px; font-weight: bold; }
            QPushButton:hover { background-color: #0094ff; }
            QPushButton:disabled { background-color: #2a4055; color: #777; }
        """)
        self._btn_aceptar.clicked.connect(self._aceptar)
        footer.addWidget(self._btn_aceptar)
 
        layout.addLayout(footer)
 
    def _construir_tabla_sin_grupo(self, equipos, layout_padre):
        """Tabla simple para los equipos sin grupo asignado."""
        n_cols = 1 + len(self.columnas)
        tabla = QTableWidget(0, n_cols)
        tabla.setHorizontalHeaderLabels(["", *self.columnas])
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.verticalHeader().setVisible(False)
        tabla.setStyleSheet(STYLE_TABLE)
        tabla.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        header = tabla.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for c in range(1, n_cols):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        tabla.setColumnWidth(0, 36)
 
        for fila_db in equipos:
            r = tabla.rowCount()
            tabla.insertRow(r)
            chk = QCheckBox()
            chk.setStyleSheet(CHECKBOX_STYLE)
 
            equipo_id = fila_db[0]
            if (equipo_id, self.tabla_db) in self._preseleccionados:
                chk.setChecked(True)
            chk.stateChanged.connect(self._actualizar_contador)
 
            self._filas_sin_grupo.append((chk, equipo_id, self.tabla_db))
 
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.addWidget(chk, alignment=Qt.AlignmentFlag.AlignCenter)
            tabla.setCellWidget(r, 0, cell)
 
            for col_vis, col_db in enumerate(self.indices_cols, start=1):
                valor = str(fila_db[col_db]) if fila_db[col_db] is not None else ""
                item = QTableWidgetItem(valor)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                tabla.setItem(r, col_vis, item)
 
        alto = tabla.horizontalHeader().height()
        for r in range(tabla.rowCount()):
            alto += tabla.rowHeight(r)
        tabla.setFixedHeight(alto + 4)
 
        layout_padre.addWidget(tabla)
 
    # ── recolección y validación ─────────────────────────────────────────
    def _recolectar_todos(self) -> List[Dict]:
        resultado = []
        for gw in self._grupos_widgets:
            resultado.extend(gw.recolectar_seleccionados())
        for chk, eq_id, eq_tipo in self._filas_sin_grupo:
            if chk.isChecked():
                resultado.append({"id": eq_id, "tipo": eq_tipo})
        return resultado
 
    def _actualizar_contador(self):
        seleccionados = self._recolectar_todos()
        n = len(seleccionados)
        self._lbl_contador.setText(f"{n} equipo{'s' if n != 1 else ''} seleccionado{'s' if n != 1 else ''}")
        self._btn_aceptar.setEnabled(n > 0)
 
    def _aceptar(self):
        self.equipos_seleccionados = self._recolectar_todos()
        self.accept()
 
    def obtener_grupos_contraidos(self) -> set:
        """
        Devuelve el set de IDs de grupos contraídos en el momento del cierre.
        Pensado para que el caller persista el estado entre aperturas.
        """
        return set(self._grupos_contraidos)