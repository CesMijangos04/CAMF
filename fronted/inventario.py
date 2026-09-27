import sys
import re
import sqlite3
import json

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QStackedLayout,
    QTabWidget, QFormLayout, QLineEdit, QComboBox, QDateEdit, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QDialog, QListWidget,
    QListWidgetItem, QHBoxLayout, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, QPoint, QDate
from PyQt6.QtGui import QIcon

from db_manager import insertar_datos, obtener_datos
from grupos_widget import VistaGrupos
from transformador import TransformadorManager
from tablero import TableroManager

# ---------------- Ventana de selección tipo ----------------
class SeleccionTipoDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Agregar nuevo elemento")
        self.setFixedSize(300, 220)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; }
            QListWidget {
                background-color: #2a2a2a; border: 1px solid #444;
                border-radius: 6px; padding: 4px;
            }
            QListWidget::item {
                padding: 10px; border-radius: 6px;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
            QListWidget::item:selected {
                background-color: #0078d7; color: white;
            }
        """)

        layout = QVBoxLayout()
        label = QLabel("Seleccione el tipo de elemento a agregar:")
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lista = QListWidget()
        self.lista.addItem(QListWidgetItem(QIcon(), "Transformador"))
        self.lista.addItem(QListWidgetItem(QIcon(), "Tablero"))

        layout.addWidget(self.lista)
        self.setLayout(layout)

        self.tipo = None
        self.lista.itemClicked.connect(self.seleccionar)

    def seleccionar(self, item):
        self.tipo = item.text()
        self.accept()

# ----------------Clase para orden numérico-------------------
class NumericItem(QTableWidgetItem):
    """Item que permite comparar correctamente valores numéricos incluso con texto (ej. '100 kVA', '250A')."""
    def __init__(self, value):
        super().__init__(str(value))
        self.numeric_value = self.extraer_numero(str(value))

    def extraer_numero(self, texto):
        """
        Busca el primer número decimal o entero en el texto.
        Si no hay número, devuelve infinito para que quede al final en el orden.
        """
        match = re.search(r"[-+]?\d*\.?\d+", texto.replace(",", "."))
        if match:
            try:
                return float(match.group())
            except ValueError:
                pass
        return float('inf')  # Si no hay número, se va al final al ordenar

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            return self.numeric_value < other.numeric_value
        return self.text().lower() < other.text().lower()

# ---------------- Ventana principal de Inventario ----------------
class InventarioWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inventario")
        self.resize(1000, 700)
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: white; }
            QLineEdit, QComboBox, QTextEdit, QDateEdit {
                background-color: #1e1e1e; color: white; border: 1px solid #444; border-radius: 5px;
            }
            QPushButton {
                background-color: #3a3a3a; color: white; border-radius: 8px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #505050; }
            QTabWidget::pane { border: 1px solid #333; }
            QHeaderView::section { background-color: #2a2a2a; }
        """)
        
        self.circuitos_tablero_actual = None  # <-- aquí guardamos temporalmente los circuitos
        self.transformador_manager = TransformadorManager(self)
        self.tablero_manager = TableroManager(self)
        
        # Layout principal
        self.layout_principal = QVBoxLayout(self)
        self.stack = QStackedLayout()
        self.layout_principal.addLayout(self.stack)

        # Pantalla inicial (Cuando no hay nada)
        self.pantalla_inicio = QWidget()
        vbox = QVBoxLayout()
        self.label_vacio = QLabel("No hay elementos en el inventario.")
        self.label_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_agregar_inicio = QPushButton("+")
        self.btn_agregar_inicio.setFixedSize(45, 45)
        self.btn_agregar_inicio.setStyleSheet("""
            QPushButton {
                font-size: 22px; background-color: #0078d7;
                border-radius: 22px; color: white;
            }
            QPushButton:hover { background-color: #005a9e; }
        """)
        self.btn_agregar_inicio.clicked.connect(self.mostrarSeleccionTipo)
        vbox.addStretch()
        vbox.addWidget(self.label_vacio, alignment=Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(self.btn_agregar_inicio, alignment=Qt.AlignmentFlag.AlignCenter)
        vbox.addStretch()
        self.pantalla_inicio.setLayout(vbox)

        # Tabs principales
        self.tabs = QTabWidget()
        self.tabs.hide()

        self.stack.addWidget(self.pantalla_inicio)
        self.stack.addWidget(self.tabs)

    #---------------------Mostrar inventario-----------------
    def mostrarInventario(self):
        """
        Decide si mostrar la tabla (si hay datos) o la pantalla vacía (botón +)
        """
        hay_transformadores = len(obtener_datos("transformadores")) > 0
        hay_tableros = len(obtener_datos("tableros")) > 0

        # ---------------- Transformadores ----------------
        if hay_transformadores:
            self.agregarPestaniaSiNoExiste("Transformador")
        else:
            # Si la pestaña existía pero ya no hay equipos, removerla
            if hasattr(self, "tab_transformadores"):
                idx = self.tabs.indexOf(self.tab_transformadores)
                if idx >= 0:
                    self.tabs.removeTab(idx)
                del self.tab_transformadores
                if hasattr(self, "vista_transformadores"):
                    del self.vista_transformadores

        # ---------------- Tableros ----------------
        if hay_tableros:
            self.agregarPestaniaSiNoExiste("Tablero")
        else:
            if hasattr(self, "tab_tableros"):
                idx = self.tabs.indexOf(self.tab_tableros)
                if idx >= 0:
                    self.tabs.removeTab(idx)
                del self.tab_tableros
                if hasattr(self, "vista_tableros"):
                    del self.vista_tableros

        # Mostrar pestañas o pantalla vacía
        if hay_transformadores or hay_tableros:
            self.pantalla_inicio.hide()
            self.tabs.show()
            self.stack.setCurrentWidget(self.tabs)
        else:
            self.tabs.hide()
            self.pantalla_inicio.show()
            self.stack.setCurrentWidget(self.pantalla_inicio)
        
    # ---------------- Mostrar selección ----------------
    def mostrarSeleccionTipo(self):
        dialog = SeleccionTipoDialog()
        if dialog.exec():
            if "Transformador" in dialog.tipo:
                self.transformador_manager.mostrarFormularioTransformador()
            elif "Tablero" in dialog.tipo:
                self.tablero_manager.mostrarFormularioTablero()

    # ── Botón "+" flotante dentro de cada pestaña ────────────────────────────
    def crearBotonAgregar(self):
        boton = QPushButton("+")
        boton.setFixedSize(40, 40)
        boton.setStyleSheet("""
            QPushButton {
                font-size: 20px; background-color: #0078d7;
                border-radius: 20px; color: white;
            }
            QPushButton:hover { background-color: #005a9e; }
        """)
        boton.clicked.connect(self.mostrarSeleccionTipo)
        return boton

    # ---------------- Crear pestañas dinámicas ----------------
    def agregarPestaniaSiNoExiste(self, tipo):
        self.stack.setCurrentWidget(self.tabs)
        self.tabs.show()
        self.tabs.currentChanged.connect(self.actualizarColorPestania)
        self.actualizarColorPestania()

        # --------------------Tab. Transformadores-----------------------
        if tipo == "Transformador" and not hasattr(self, 'tab_transformadores'):
            self.tab_transformadores = QWidget()
            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Botón "+" para agregar nuevo equipo
            layout.addWidget(self.crearBotonAgregar(), alignment=Qt.AlignmentFlag.AlignLeft)

            # Vista de grupos
            self.vista_transformadores = VistaGrupos(
                tabla_db="transformadores",
                columnas=[
                    "ID", "Ubicación", "Capacidad (kVA)", "Tensión (kV)",
                    "Fecha Instalación", "Marca", "Enfriamiento", "Fases", "Conexión", "Tipo"
                ],
                indices_cols=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
                menu_equipo_fn=lambda pos: self.transformador_manager.menuContextTransformador(pos),
                parent=self
            )
            layout.addWidget(self.vista_transformadores)
            self.tab_transformadores.setLayout(layout)
            self.tabs.addTab(self.tab_transformadores, "Transformadores")

        # --------------------Tab. Tableros------------------------
        elif tipo == "Tablero" and not hasattr(self, 'tab_tableros'):
            self.tab_tableros = QWidget()
            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
 
            layout.addWidget(self.crearBotonAgregar(), alignment=Qt.AlignmentFlag.AlignLeft)

            # Vista de grupos para tableros
            self.vista_tableros = VistaGrupos(
                tabla_db="tableros",
                columnas=[
                    "ID", "Nombre", "Ubicación", "Corriente nominal (A)", "Tensión (V)", "Tipo",
                    "Nº de circuitos", "Marca", "Fecha instalación", "Comentarios"
                ],
                indices_cols=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
                menu_equipo_fn=lambda pos: self.tablero_manager.menuContextTablero(pos),
                dbl_click_fn=lambda row, col: self.tablero_manager.dobleClicTablero(row, col),
                parent=self
            )
            layout.addWidget(self.vista_tableros)
            self.tab_tableros.setLayout(layout)
            self.tabs.addTab(self.tab_tableros, "Tableros")

    # ── Recargar vistas de grupos (llamar después de insertar un equipo) ──────
    def recargarVistas(self):
        """
        Llama esto desde TransformadorManager y TableroManager
        justo después de guardar un equipo nuevo en la DB.
        Crea la pestaña correspondiente si aún no existe y recarga la vista.
        """
        hay_transformadores = len(obtener_datos("transformadores")) > 0
        hay_tableros        = len(obtener_datos("tableros")) > 0

        # ── Transformadores ──────────────────────────────────────────────
        if hay_transformadores:
            self.agregarPestaniaSiNoExiste("Transformador")
            if hasattr(self, "vista_transformadores"):
                self.vista_transformadores.recargar()
        else:
            # Si la pestaña existía pero ya no hay datos, removerla
            if hasattr(self, "tab_transformadores"):
                idx = self.tabs.indexOf(self.tab_transformadores)
                if idx >= 0:
                    self.tabs.removeTab(idx)
                del self.tab_transformadores
                if hasattr(self, "vista_transformadores"):
                    del self.vista_transformadores

        # ── Tableros ─────────────────────────────────────────────────────
        if hay_tableros:
            self.agregarPestaniaSiNoExiste("Tablero")
            if hasattr(self, "vista_tableros"):
                self.vista_tableros.recargar()
        else:
            if hasattr(self, "tab_tableros"):
                idx = self.tabs.indexOf(self.tab_tableros)
                if idx >= 0:
                    self.tabs.removeTab(idx)
                del self.tab_tableros
                if hasattr(self, "vista_tableros"):
                    del self.vista_tableros

        # Mostrar pestañas o pantalla vacía según corresponda
        if hay_transformadores or hay_tableros:
            self.pantalla_inicio.hide()
            self.tabs.show()
            self.stack.setCurrentWidget(self.tabs)
        else:
            self.tabs.hide()
            self.pantalla_inicio.show()
            self.stack.setCurrentWidget(self.pantalla_inicio)

    # ── Estilo de pestañas ────────────────────────────────────────────────────
    def actualizarColorPestania(self):
        estilo = """
            QTabWidget::pane {
                border: none;
                background: #1e1e1e;
            }
            QTabBar::tab {
                background: #2a2a2a;
                color: white;
                padding: 8px 14px;
                border: none;
                border-top: 3px solid transparent;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                border-top: 3px solid #0078d7;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background: #333333;
            }
        """
        self.tabs.setStyleSheet(estilo)
 
    # ── Utilidades que conservamos por si otros managers las usan ────────────
    def crear_item(self, dato):
        """Crea un QTableWidgetItem con soporte de orden numérico."""
        texto = str(dato).strip()
        if re.search(r"\d", texto):
            return NumericItem(texto)
        return QTableWidgetItem(texto)
 
    def registrarFilaOriginal(self, tabla):
        """Mantiene compatibilidad con managers que aún llamen esta función."""
        if not hasattr(tabla, "_original_rows"):
            tabla._original_rows = []
        if not hasattr(tabla, "_original_order_initialized"):
            tabla._original_order_initialized = True
        filas_actuales = []
        for r in range(tabla.rowCount()):
            fila_datos = [
                tabla.item(r, c).text() if tabla.item(r, c) else ""
                for c in range(tabla.columnCount())
            ]
            filas_actuales.append(fila_datos)
        tabla._original_rows = filas_actuales
 
    # ── Cerrar pestañas vacías ────────────────────────────────────────────────
    def cerrarPestania(self, tipo):
        if tipo == "Transformador" and hasattr(self, 'tab_transformadores'):
            idx = self.tabs.indexOf(self.tab_transformadores)
            self.tabs.removeTab(idx)
            del self.tab_transformadores
            if hasattr(self, 'vista_transformadores'):
                del self.vista_transformadores
        elif tipo == "Tablero" and hasattr(self, 'tab_tableros'):
            idx = self.tabs.indexOf(self.tab_tableros)
            self.tabs.removeTab(idx)
            del self.tab_tableros
            if hasattr(self, 'vista_tableros'):
                del self.vista_tableros
 
        if self.tabs.count() == 0:
            self.tabs.hide()
            self.stack.setCurrentWidget(self.pantalla_inicio)
 
 
# ---------------- Ejecutar ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = InventarioWindow()
    ventana.show()
    sys.exit(app.exec())