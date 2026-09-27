# selector_grupo.py
"""
Componentes reutilizables para el manejo de grupos en formularios.
Lo usan tablero.py y transformador.py.

Incluye:
  - SelectorGrupoWidget: combo con árbol indentado + botones "+ Crear" y "⚙ Gestionar"
  - DialogoCrearGrupo: mini-diálogo para crear grupo o subgrupo (con padre opcional)
  - VentanaGestionarGrupos: lista jerárquica con renombrar y eliminar
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QDialog, QFormLayout, QMessageBox, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor

from db_manager import (
    obtener_grupos, crear_grupo, renombrar_grupo, eliminar_grupo,
    construir_arbol_grupos, obtener_equipos_por_grupo
)


# ══════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════

def _aplanar_arbol_indentado(nodos, nivel=0, resultado=None):
    """
    Recorre el árbol y devuelve una lista plana con (id, nombre_indentado, nivel).
    Ejemplo de salida:
        [(1, 'Edificio A', 0),
         (3, '   └ Piso 1', 1),
         (4, '   └ Piso 2', 1),
         (2, 'Edificio B', 0)]
    """
    if resultado is None:
        resultado = []
    for nodo in nodos:
        if nivel == 0:
            etiqueta = nodo["nombre"]
        else:
            prefijo = "   " * (nivel - 1) + "   └ "
            etiqueta = prefijo + nodo["nombre"]
        resultado.append((nodo["id"], etiqueta, nivel))
        if nodo.get("hijos"):
            _aplanar_arbol_indentado(nodo["hijos"], nivel + 1, resultado)
    return resultado


# ══════════════════════════════════════════════════════════════════════
#  Diálogo: Crear grupo o subgrupo
# ══════════════════════════════════════════════════════════════════════

class DialogoCrearGrupo(QDialog):
    """
    Diálogo para crear un grupo. El campo "Pertenece a" permite elegir el padre,
    así crear un grupo raíz o un subgrupo es la misma acción.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear grupo")
        self.setFixedSize(380, 180)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; }
            QLineEdit, QComboBox {
                background-color: #2a2a2a; color: white;
                border: 1px solid #555; border-radius: 5px;
                padding: 4px 8px;
            }
            QLabel { color: #ccc; }
            QPushButton {
                background-color: #3a3a3a; color: white;
                border-radius: 6px; padding: 5px 14px;
            }
            QPushButton:hover { background-color: #505050; }
            QPushButton#btnOk { background-color: #0078d7; }
            QPushButton#btnOk:hover { background-color: #005a9e; }
        """)

        self.id_creado = None  # se llena al crear

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.input_nombre = QLineEdit()
        self.input_nombre.setPlaceholderText("Ej. Edificio A, Piso 1, Planta Norte…")

        self.combo_padre = QComboBox()
        self.combo_padre.addItem("— Sin padre (grupo raíz) —", None)
        # Aplanamos el árbol completo (sin filtro) para poder elegir cualquier padre
        arbol = construir_arbol_grupos(tabla_db=None)
        for gid, etiqueta, _nivel in _aplanar_arbol_indentado(arbol):
            self.combo_padre.addItem(etiqueta, gid)

        form.addRow("Nombre:", self.input_nombre)
        form.addRow("Pertenece a:", self.combo_padre)
        layout.addLayout(form)

        botones = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        self.btn_ok = QPushButton("Crear")
        self.btn_ok.setObjectName("btnOk")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._guardar)
        botones.addStretch()
        botones.addWidget(btn_cancel)
        botones.addWidget(self.btn_ok)
        layout.addLayout(botones)

    def _guardar(self):
        nombre = self.input_nombre.text().strip()
        if not nombre:
            self.input_nombre.setStyleSheet("border: 1px solid #e05555;")
            return
        padre_id = self.combo_padre.currentData()
        self.id_creado = crear_grupo(nombre, padre_id=padre_id)
        self.accept()


# ══════════════════════════════════════════════════════════════════════
#  Ventana: Gestionar grupos
# ══════════════════════════════════════════════════════════════════════

class VentanaGestionarGrupos(QDialog):
    """
    Ventana que muestra todos los grupos en forma de árbol con opciones
    para renombrar y eliminar cada uno. Incluye los grupos vacíos.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar grupos")
        self.setFixedSize(540, 480)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; }
            QLabel#titulo {
                color: white; font-size: 14px; font-weight: bold;
                padding-bottom: 4px;
            }
            QScrollArea { border: none; background: transparent; }
            QPushButton {
                background-color: #3a3a3a; color: white;
                border-radius: 6px; padding: 5px 12px;
            }
            QPushButton:hover { background-color: #505050; }
            QPushButton#btnRen {
                background: transparent; color: #aaa;
                border: 1px solid #444; border-radius: 4px;
                padding: 2px 8px; font-size: 11px;
            }
            QPushButton#btnRen:hover { color: white; border-color: #888; }
            QPushButton#btnDel {
                background: transparent; color: #e05555;
                border: 1px solid #663333; border-radius: 4px;
                padding: 2px 8px; font-size: 11px;
            }
            QPushButton#btnDel:hover { color: #ff7777; border-color: #aa4444; }
            QLabel#vacio { color: #555; font-size: 13px; padding: 30px; }
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(10)

        # Cabecera
        cab = QHBoxLayout()
        titulo = QLabel("Todos los grupos del sistema")
        titulo.setObjectName("titulo")
        cab.addWidget(titulo)
        cab.addStretch()
        self._layout.addLayout(cab)

        # Scroll con la lista
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._layout.addWidget(self._scroll, 1)

        # Botón Cerrar
        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.accept)
        cerrar_box = QHBoxLayout()
        cerrar_box.addStretch()
        cerrar_box.addWidget(cerrar)
        self._layout.addLayout(cerrar_box)

        self._cargar_arbol()

    def _cargar_arbol(self):
        """Reconstruye el árbol cada vez que cambia algo."""
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        arbol = construir_arbol_grupos(tabla_db=None)  # TODOS los grupos
        if not arbol:
            lbl = QLabel("No hay grupos creados aún.\nPuedes crearlos desde el formulario al registrar un equipo.")
            lbl.setObjectName("vacio")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lbl)
        else:
            self._dibujar_nodos(arbol, lay, nivel=0)

        lay.addStretch()
        self._scroll.setWidget(cont)

    def _dibujar_nodos(self, nodos, layout, nivel):
        """Dibuja recursivamente cada grupo con sus botones."""
        for nodo in nodos:
            fila = QFrame()
            fila.setStyleSheet(
                "QFrame { background-color: #252525; border-radius: 4px; }"
                "QFrame:hover { background-color: #2e2e2e; }"
            )
            fila_layout = QHBoxLayout(fila)
            fila_layout.setContentsMargins(10 + nivel * 20, 6, 10, 6)

            # Indicador visual
            if nivel == 0:
                indicador = "●"
                color_ind = "#0078d7"
            else:
                indicador = "└"
                color_ind = "#888"
            lbl_ind = QLabel(indicador)
            lbl_ind.setStyleSheet(f"color: {color_ind}; font-size: 14px;")
            lbl_ind.setFixedWidth(16)

            lbl_nombre = QLabel(nodo["nombre"])
            lbl_nombre.setStyleSheet("color: white; font-size: 13px;")

            # Conteo de equipos para indicar uso
            n_directos = (len(obtener_equipos_por_grupo("tableros", nodo["id"]))
                          + len(obtener_equipos_por_grupo("transformadores", nodo["id"])))
            n_descendientes = self._contar_descendientes(nodo)
            total = n_directos + n_descendientes
 
            if total > 0:
                # Si todos vienen de subgrupos, mostrarlo claro
                if n_directos == 0 and n_descendientes > 0:
                    txt = f"{total} en subgrupos"
                else:
                    txt = f"{total} equipo{'s' if total != 1 else ''}"
                lbl_meta = QLabel(txt)
                lbl_meta.setStyleSheet("color: #777; font-size: 11px;")
            else:
                lbl_meta = QLabel("vacío")
                lbl_meta.setStyleSheet("color: #555; font-size: 11px; font-style: italic;")

            btn_ren = QPushButton("Renombrar")
            btn_ren.setObjectName("btnRen")
            btn_ren.setFixedHeight(24)
            btn_ren.clicked.connect(lambda _, n=nodo: self._renombrar(n))

            btn_del = QPushButton("Eliminar")
            btn_del.setObjectName("btnDel")
            btn_del.setFixedHeight(24)
            btn_del.clicked.connect(lambda _, n=nodo: self._eliminar(n))

            fila_layout.addWidget(lbl_ind)
            fila_layout.addWidget(lbl_nombre)
            fila_layout.addStretch()
            fila_layout.addWidget(lbl_meta)
            fila_layout.addWidget(btn_ren)
            fila_layout.addWidget(btn_del)

            layout.addWidget(fila)

            # Hijos recursivamente
            if nodo.get("hijos"):
                self._dibujar_nodos(nodo["hijos"], layout, nivel + 1)

    def _contar_descendientes(self, nodo):
        """Cuenta recursivamente los equipos en todos los subgrupos del nodo."""
        total = 0
        for hijo in nodo.get("hijos", []):
            total += len(obtener_equipos_por_grupo("tableros", hijo["id"]))
            total += len(obtener_equipos_por_grupo("transformadores", hijo["id"]))
            total += self._contar_descendientes(hijo)
        return total

    def _renombrar(self, nodo):
        dlg = QDialog(self)
        dlg.setWindowTitle("Renombrar grupo")
        dlg.setFixedSize(320, 110)
        dlg.setStyleSheet(self.styleSheet())
        vl = QVBoxLayout(dlg)
        inp = QLineEdit(nodo["nombre"])
        vl.addWidget(QLabel("Nuevo nombre:"))
        vl.addWidget(inp)
        botones = QHBoxLayout()
        b_cancel = QPushButton("Cancelar")
        b_ok = QPushButton("Guardar")
        b_ok.setStyleSheet("background-color: #0078d7;")
        b_cancel.clicked.connect(dlg.reject)
        b_ok.clicked.connect(dlg.accept)
        botones.addStretch(); botones.addWidget(b_cancel); botones.addWidget(b_ok)
        vl.addLayout(botones)
        if dlg.exec() and inp.text().strip():
            renombrar_grupo(nodo["id"], inp.text().strip())
            self._cargar_arbol()

    def _eliminar(self, nodo):
        n_tableros = len(obtener_equipos_por_grupo("tableros", nodo["id"]))
        n_trafos = len(obtener_equipos_por_grupo("transformadores", nodo["id"]))
        hijos = nodo.get("hijos", [])

        msg = f"¿Eliminar el grupo '{nodo['nombre']}'?"
        if hijos or n_tableros or n_trafos:
            msg += "\n\nLos equipos y subgrupos dentro quedarán sin grupo asignado (no se borrarán)."

        if QMessageBox.question(self, "Confirmar", msg) == QMessageBox.StandardButton.Yes:
            eliminar_grupo(nodo["id"])
            self._cargar_arbol()


# ══════════════════════════════════════════════════════════════════════
#  Widget: Selector de grupo (combo + crear + gestionar)
# ══════════════════════════════════════════════════════════════════════

class SelectorGrupoWidget(QWidget):
    """
    Widget que se inserta en el formulario. Contiene:
      - QComboBox con árbol indentado de grupos
      - Botón "+ Crear" → DialogoCrearGrupo
      - Botón "⚙ Gestionar" → VentanaGestionarGrupos
    """
    def __init__(self, grupo_id_actual=None, parent=None):
        super().__init__(parent)
        self.combo = QComboBox()
        self._ids_combo = []  # ids paralelos al combo

        btn_crear = QPushButton("+ Crear")
        btn_crear.setStyleSheet(
            "QPushButton { background:#1D9E75; color:white; border-radius:5px; padding:3px 10px; font-size:11px; }"
            "QPushButton:hover { background:#167a5a; }"
        )
        btn_crear.setFixedHeight(26)
        btn_crear.clicked.connect(self._crear)

        btn_gestionar = QPushButton("⚙ Gestionar")
        btn_gestionar.setStyleSheet(
            "QPushButton { background:#444; color:white; border-radius:5px; padding:3px 10px; font-size:11px; }"
            "QPushButton:hover { background:#555; }"
        )
        btn_gestionar.setFixedHeight(26)
        btn_gestionar.clicked.connect(self._gestionar)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.combo, 1)
        layout.addWidget(btn_crear)
        layout.addWidget(btn_gestionar)

        self._recargar_combo(seleccionar_id=grupo_id_actual)

    # ----------------------------------------------------------
    def _recargar_combo(self, seleccionar_id=None):
        """Reconstruye el combo con el árbol indentado."""
        self.combo.clear()
        self._ids_combo.clear()

        arbol = construir_arbol_grupos(tabla_db=None)  # todos los grupos

        if arbol:
            self.combo.addItem("Sin grupo", None)
            self._ids_combo.append(None)
            for gid, etiqueta, _nivel in _aplanar_arbol_indentado(arbol):
                self.combo.addItem(etiqueta, gid)
                self._ids_combo.append(gid)

            # Preseleccionar si nos pidieron uno
            if seleccionar_id is not None:
                for i, gid in enumerate(self._ids_combo):
                    if gid == seleccionar_id:
                        self.combo.setCurrentIndex(i)
                        break
        else:
            self.combo.addItem("(Sin grupos — crea uno primero)", None)
            self._ids_combo.append(None)

    def grupo_seleccionado(self):
        """Devuelve el id del grupo actualmente seleccionado, o None."""
        return self.combo.currentData()

    def hay_grupos(self):
        """¿Existe al menos un grupo creado?"""
        return len(obtener_grupos()) > 0

    def _crear(self):
        dlg = DialogoCrearGrupo(self)
        if dlg.exec() and dlg.id_creado:
            self._recargar_combo(seleccionar_id=dlg.id_creado)

    def _gestionar(self):
        ventana = VentanaGestionarGrupos(self)
        ventana.exec()
        # Al cerrar, refrescar el combo (puede haber cambios)
        actual = self.grupo_seleccionado()
        self._recargar_combo(seleccionar_id=actual)

        self._notificar_inventario()
 
    def _notificar_inventario(self):
        """
        Sube por el árbol de widgets buscando uno que tenga 'recargarVistas'
        (típicamente InventarioWindow) y lo llama. Si no encuentra, no hace nada.
        """
        widget = self.parent()
        while widget is not None:
            if hasattr(widget, "recargarVistas") and callable(widget.recargarVistas):
                widget.recargarVistas()
                return
            widget = widget.parent()