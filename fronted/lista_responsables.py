from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QWidget, QMenu, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QMessageBox, QLabel, QGridLayout, QHBoxLayout,
    QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from db_manager import ejecutar_query, connect_db
from agregar_responsable import AgregarResponsableDialog
import json

class ListaResponsablesDialog(QDialog):
    responsable_asignado = pyqtSignal(dict)

    def __init__(self, parent = None):
        super().__init__(parent)
        self.setWindowTitle("Lista de responsables")
        self.resize(900, 500)

        self.init_ui()

        self.overlays = {}
        self.item_expandido = None

        self.tree_proveedores.itemExpanded.connect(self.mostrar_overlay)
        self.tree_proveedores.itemCollapsed.connect(self.ocultar_overlay)

        self.cargar_personal()
        self.cargar_proveedores()

        self._ultima_fila_personal = None
        self._ultimo_item_proveedor = None

        self.tabla_personal.itemSelectionChanged.connect(self.actualizar_estado_asignar)
        self.tree_proveedores.itemSelectionChanged.connect(self.actualizar_estado_asignar)
        self.tabs.currentChanged.connect(self.actualizar_estado_asignar)

    def init_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tabs
        self.tab_personal = QWidget()
        self.tab_proveedor = QWidget()

        self.init_tab_personal()
        self.init_tab_proveedor()

        footer = QHBoxLayout()

        self.btn_asignar = QPushButton("Asignar")
        self.btn_asignar.setEnabled(False)
        self.btn_asignar.setFixedHeight(36)
        self.btn_asignar.clicked.connect(self.asignar_responsable)
        self.btn_asignar.setStyleSheet("""
        QPushButton:disabled {
            background-color: #262626;
            color: #777;
        }
        """)

        self.btn_quitar = QPushButton("Quitar")
        self.btn_quitar.setFixedHeight(36)
        self.btn_quitar.setVisible(False)
        self.btn_quitar.clicked.connect(self.quitar_responsable)

        footer.addStretch()
        footer.addWidget(self.btn_asignar)
        footer.addWidget(self.btn_quitar)

        layout.addLayout(footer)

    def _sincronizar_tabs(self):
        """
        Muestra cada pestaña sólo si su tabla/árbol tiene contenido.
        Mantiene el orden estable: 'Personal' siempre antes que 'Proveedor'.
        Llámese tras cargar_personal y cargar_proveedores.
        """
        # ---- Personal: siempre en posición 0 ----
        idx_p = self.tabs.indexOf(self.tab_personal)
        hay_personal = self.tabla_personal.rowCount() > 0
        if hay_personal and idx_p == -1:
            self.tabs.insertTab(0, self.tab_personal, "Personal")
        elif not hay_personal and idx_p != -1:
            self.tabs.removeTab(idx_p)
 
        # ---- Proveedor: siempre al final ----
        idx_v = self.tabs.indexOf(self.tab_proveedor)
        hay_proveedores = self.tree_proveedores.topLevelItemCount() > 0
        if hay_proveedores and idx_v == -1:
            self.tabs.addTab(self.tab_proveedor, "Proveedor")
        elif not hay_proveedores and idx_v != -1:
            self.tabs.removeTab(idx_v)

    # ─────────── Persistencia de anchos de columnas ────────────
    # Guardamos en ui_state.json los anchos que el usuario fija a mano
    # arrastrando los bordes del header. Al volver a abrir el diálogo (o
    # el programa) se reaplican, así la configuración del usuario sobrevive.

    def _guardar_anchos(self, clave: str, widget):
        """Guarda los anchos actuales del widget bajo la clave dada."""
        # Evita guardar durante la carga inicial (cuando aplicamos los anchos
        # guardados, sectionResized también dispara — sin esto se machacarían
        # con los mismos valores, pero también consume IO innecesaria).
        if getattr(self, "_cargando_anchos", False):
            return
        from ui_state import guardar_valor
        anchos = [widget.columnWidth(c) for c in range(widget.columnCount())]
        guardar_valor(clave, anchos)

    def _aplicar_anchos_guardados(self, clave: str, widget):
        """Aplica los anchos guardados al widget, si existen y son válidos."""
        from ui_state import obtener_valor
        anchos = obtener_valor(clave, [])
        if not anchos or len(anchos) != widget.columnCount():
            return
        # Preservamos el valor previo del flag y lo forzamos True mientras
        # aplicamos. Esto evita que sectionResized rebote y guarde estos
        # mismos anchos (innecesario), y permite anidar con el flag del
        # caller (cargar_*) sin volverlo a False prematuramente.
        previo = getattr(self, "_cargando_anchos", False)
        self._cargando_anchos = True
        try:
            for c, w in enumerate(anchos):
                if isinstance(w, int) and w > 0:
                    widget.setColumnWidth(c, w)
        finally:
            self._cargando_anchos = previo

    #----------------------- Personal ----------------------------
    def init_tab_personal(self):
        layout = QVBoxLayout(self.tab_personal)

        self.tabla_personal = QTableWidget()
        self.tabla_personal.setColumnCount(7)
        self.tabla_personal.setHorizontalHeaderLabels([
            "ID",
            "Nombre",
            "Apellido paterno",
            "Apellido materno",
            "Teléfono",
            "Correo",
            "Puesto"
        ])

        self.tabla_personal.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla_personal.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabla_personal.cellClicked.connect(self.toggle_seleccion_personal)
        self.tabla_personal.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabla_personal.customContextMenuRequested.connect(self.menu_contextual_personal)

        self.tabla_personal.horizontalHeader().setStretchLastSection(True)

        header = self.tabla_personal.horizontalHeader()
        font = header.font()
        font.setBold(True)
        header.setFont(font)

        # Persistir anchos cuando el usuario los ajusta manualmente
        header.sectionResized.connect(
            lambda *_: self._guardar_anchos("anchos_tabla_personal", self.tabla_personal)
        )

        layout.addWidget(self.tabla_personal)

    def cargar_personal(self):
        query = """
        SELECT
            id_personal,
            nombre,
            ap_paterno,
            ap_materno,
            telefono,
            correo,
            puesto
        FROM personal
        ORDER BY nombre
        """

        resultados = ejecutar_query(query)

        self.tabla_personal.setRowCount(0)
        # setRowCount(0) destruye los QTableWidgetItem; anular la última
        # fila guardada para que toggle_seleccion_personal no apunte a basura.
        self._ultima_fila_personal = None

        if resultados:
            for fila, registro in enumerate(resultados):
                self.tabla_personal.insertRow(fila)

                for columna, valor in enumerate(registro):
                    item = QTableWidgetItem(str(valor))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.tabla_personal.setItem(fila, columna, item)

        # Bloquear sectionResized durante todo el ajuste de anchos. Sin
        # esto, resizeColumnsToContents dispara la señal y machaca los
        # anchos guardados del usuario (que aplicaremos justo después).
        self._cargando_anchos = True
        try:
            self.tabla_personal.resizeColumnsToContents()
            # Insertar la pestaña al QTabWidget ANTES de aplicar los anchos
            # guardados; si no, el widget aún no tiene geometría asignada y
            # el setColumnWidth se pierde al insertar más tarde.
            self._sincronizar_tabs()
            self._aplicar_anchos_guardados("anchos_tabla_personal", self.tabla_personal)
        finally:
            self._cargando_anchos = False

    def toggle_seleccion_personal(self, row, column):
        if self._ultima_fila_personal == row:
            # Deseleccionar
            self.tabla_personal.clearSelection()
            self.tabla_personal.setCurrentCell(-1, -1)
            self._ultima_fila_personal = None
        else:
            # Seleccionar
            self.tabla_personal.clearSelection()
            self.tabla_personal.selectRow(row)
            self.tabla_personal.setCurrentCell(row, 0)
            self._ultima_fila_personal = row

        self.actualizar_estado_asignar()
    
    def menu_contextual_personal(self, pos):
        fila = self.tabla_personal.rowAt(pos.y())
        if fila < 0:
            return

        menu = QMenu()

        accion_editar = menu.addAction("Editar")
        accion_eliminar = menu.addAction("Eliminar")

        accion = menu.exec(self.tabla_personal.viewport().mapToGlobal(pos))

        if accion == accion_editar:
            self.editar_personal(fila)

        elif accion == accion_eliminar:
            self.eliminar_personal(fila)

    def editar_personal(self, fila):
        id_personal = self.tabla_personal.item(fila, 0).text()

        # Obtener datos actuales de BD
        resultado = ejecutar_query(
            """
            SELECT
                id,
                id_personal,
                nombre,
                ap_paterno,
                ap_materno,
                telefono,
                correo,
                puesto
            FROM personal
            WHERE id_personal = ?
            """,
            (id_personal,)
        )

        if not resultado:
            return

        datos = resultado[0]

        dialogo = AgregarResponsableDialog(
            personal_registrado=[],
            proveedores_registrados=[],
            parent=self,
            modo_edicion=True,
            tipo="personal",
            datos={
                "id": datos[0],             
                "id_personal": datos[1],
                "nombre": datos[2],
                "ap_paterno": datos[3],
                "ap_materno": datos[4],
                "telefono": datos[5],
                "correo": datos[6],
                "puesto": datos[7]
            }
        )

        if dialogo.exec():
            self.cargar_personal()

    def eliminar_personal(self, fila):
        id_personal = self.tabla_personal.item(fila, 0).text()

        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar personal")
        msg.setText("¿Deseas eliminar este registro?")
        msg.setIcon(QMessageBox.Icon.Question)

        btn_si = msg.addButton("Sí", QMessageBox.ButtonRole.YesRole)
        btn_no = msg.addButton("No", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_no)

        msg.exec()

        if msg.clickedButton() != btn_si:
            return

        try:
            conn = connect_db(create_if_missing=True)
            cur = conn.cursor()

            cur.execute(
                "DELETE FROM personal WHERE id_personal = ?",
                (id_personal,)
            )

            conn.commit()
            conn.close()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error al eliminar",
                f"Ocurrió un error al eliminar el personal:\n{e}"
            )
            return

        # Eliminar de la UI SOLO si la BD se eliminó correctamente
        self.tabla_personal.removeRow(fila)
        # Si era la última fila, hay que quitar la pestaña Personal.
        self._sincronizar_tabs()

        QMessageBox.information(
            self,
            "Personal eliminado",
            "El registro se eliminó correctamente."
        )

    #---------------------- Proveedor -----------------------
    def init_tab_proveedor(self):
        layout = QVBoxLayout(self.tab_proveedor)

        self.tree_proveedores = QTreeWidget()
        self.tree_proveedores.setColumnCount(4)
        self.tree_proveedores.setHeaderLabels([
            "ID",
            "Empresa",
            "Teléfono",
            "Correo"
        ])

        # Comportamiento
        self.tree_proveedores.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.tree_proveedores.itemClicked.connect(self.toggle_seleccion_proveedor)
        self.tree_proveedores.setExpandsOnDoubleClick(False)
        self.tree_proveedores.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.tree_proveedores.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_proveedores.customContextMenuRequested.connect(self.menu_contextual_proveedor)

        header = self.tree_proveedores.header()
        header.setStretchLastSection(True)

        for i in range(self.tree_proveedores.columnCount()):
            header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

        header.setFixedHeight(self.tabla_personal.horizontalHeader().height())

        self.tree_proveedores.setStyleSheet("""
            QTreeWidget::item {
                height: 32px;
            }
            QHeaderView::section {
                padding: 6px;
                font-weight: bold;
            }
        """)

        self.tree_proveedores.setRootIsDecorated(True)
        self.tree_proveedores.itemSelectionChanged.connect(self.on_proveedor_seleccionado)

        # Persistir anchos cuando el usuario los ajusta manualmente
        header.sectionResized.connect(
            lambda *_: self._guardar_anchos("anchos_tree_proveedores", self.tree_proveedores)
        )

        layout.addWidget(self.tree_proveedores)

    def cargar_proveedores(self):
        query = """
        SELECT id, id_proveedor, empresa, telefono, correo, contactos_json
        FROM proveedores
        ORDER BY empresa
        """
        resultados = ejecutar_query(query)

        # Destruir los overlays viejos ANTES de vaciar el dict. Sin esto,
        # los QFrame siguen visibles flotando sobre el tree (porque no son
        # hijos del item) y aparecen "plasmados" tras una edición. hide()
        # los oculta inmediatamente; deleteLater() libera la memoria
        # cuando Qt complete el ciclo de eventos.
        for overlay in self.overlays.values():
            try:
                overlay.hide()
                overlay.deleteLater()
            except RuntimeError:
                pass  # ya destruido por Qt en otra parte
        self.overlays = {}

        self.tree_proveedores.clear()
        # clear() destruye los QTreeWidgetItem en C++; cualquier referencia
        # Python a esos items queda apuntando a un objeto inválido y crashea
        # al usarse (RuntimeError: wrapped C/C++ object has been deleted).
        # Reseteamos las que mantenemos como estado.
        self.item_expandido = None
        self._ultimo_item_proveedor = None

        if resultados:
            font_personal = self.tabla_personal.font()

            for registro in resultados:
                id_db, id_proveedor, empresa, telefono, correo, contactos_json = registro

                # --- Fila principal: proveedor ---
                item_proveedor = QTreeWidgetItem([
                    str(id_proveedor),
                    empresa,
                    telefono or "",
                    correo or ""
                ])
                for col in range(4):
                    item_proveedor.setFont(col, font_personal)
                    item_proveedor.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
                item_proveedor.setData(0, Qt.ItemDataRole.UserRole, id_db)

                # Guardamos contactos en UserRole+1 para usar en overlay
                item_proveedor.setData(0, Qt.ItemDataRole.UserRole + 1, contactos_json or "[]")

                # --- Creamos hijo dummy para que Qt dibuje flecha si hay contactos ---
                try:
                    contactos = json.loads(contactos_json) if contactos_json else []
                except json.JSONDecodeError:
                    contactos = []

                if contactos:
                    item_dummy = QTreeWidgetItem(item_proveedor)
                    item_dummy.setText(0, "")  # No mostrar texto
                    item_dummy.setFlags(Qt.ItemFlag.ItemIsEnabled)  # Permite que Qt dibuje la flecha
                    item_dummy.setFirstColumnSpanned(True)  # Span sobre todas las columnas

                self.tree_proveedores.addTopLevelItem(item_proveedor)

            self.tree_proveedores.collapseAll()

        # Bloquear sectionResized durante el ajuste para no machacar los
        # anchos guardados con los que calculan automáticamente.
        self._cargando_anchos = True
        try:
            for c in range(self.tree_proveedores.columnCount()):
                self.tree_proveedores.resizeColumnToContents(c)
            self._sincronizar_tabs()
            self._aplicar_anchos_guardados("anchos_tree_proveedores", self.tree_proveedores)
        finally:
            self._cargando_anchos = False
    
    def toggle_seleccion_proveedor(self, item, column):
        if self._ultimo_item_proveedor is item:
            # Deseleccionar
            self.tree_proveedores.clearSelection()
            self.tree_proveedores.setCurrentItem(None)
            self._ultimo_item_proveedor = None

            # 🔹 OCULTAR overlay si está abierto
            if self.item_expandido is item:
                self.ocultar_overlay(item)

            # 🔹 COLAPSAR la flecha / hijo dummy
            item.setExpanded(False)

        else:
            # Seleccionar
            self.tree_proveedores.clearSelection()
            self.tree_proveedores.setCurrentItem(item)
            self._ultimo_item_proveedor = item

            if item.parent() is None and item.childCount() > 0:
                item.setExpanded(True)

        self.actualizar_estado_asignar()
    
    def mostrar_overlay(self, item_proveedor):
        # --- Si hay otro item abierto, cerrarlo ---
        if self.item_expandido and self.item_expandido is not item_proveedor:
            self.tree_proveedores.collapseItem(self.item_expandido)

        # --- Ocultar cualquier overlay existente ---
        for overlay in self.overlays.values():
            overlay.hide()
        self.overlays.clear()

        contactos_json = item_proveedor.data(0, Qt.ItemDataRole.UserRole + 1)
        try:
            contactos = json.loads(contactos_json)
        except json.JSONDecodeError:
            contactos = []

        if not contactos:
            return

        # --- Crear overlay ---
        overlay = QWidget(self.tree_proveedores.viewport())
        layout = QGridLayout(overlay)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        max_columnas = 3
        row = col = 0

        for c in contactos:
            lbl_contacto = QLabel(
                f"{c.get('nombre','')}\n"
                f"📞 {c.get('telefono','')}\n"
                f"📧 {c.get('correo','')}"
            )

            lbl_contacto.setWordWrap(True)
            lbl_contacto.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            lbl_contacto.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    font-weight: 500;
                    color: #f0f0f0;
                    background-color: #3a3a3a;
                    border: 1px solid #555;
                    border-radius: 4px;
                    padding: 6px;
                }
            """)

            layout.addWidget(lbl_contacto, row, col)

            col += 1
            if col >= max_columnas:
                col = 0
                row += 1

        # --- Posición: debajo de la fila ---
        rect_item = self.tree_proveedores.visualItemRect(item_proveedor)
        pos = rect_item.bottomLeft()
        overlay.move(pos)

        # --- Tamaño ---
        overlay.setFixedWidth(self.tree_proveedores.viewport().width())
        overlay.setFixedHeight(layout.sizeHint().height())

        overlay.raise_()
        overlay.show()

        self.overlays[id(item_proveedor)] = overlay
        self.tree_proveedores.expandItem(item_proveedor)

        self.item_expandido = item_proveedor

    def ocultar_overlay(self, item_proveedor):
        item_id = id(item_proveedor)
        if item_id in self.overlays:
            self.overlays[item_id].hide()
            del self.overlays[item_id]

        if self.item_expandido is item_proveedor:
            self.item_expandido = None
        
    def on_proveedor_seleccionado(self):
        # Al seleccionar un proveedor, expandir su lista de contactos
        items = self.tree_proveedores.selectedItems()
        if not items:
            return

        item = items[0]

        # Solo expandir si es top-level (proveedor)
        if item.parent() is None and item.childCount() > 0:
            item.setExpanded(not item.isExpanded())
        
    def menu_contextual_proveedor(self, pos):
        item = self.tree_proveedores.itemAt(pos)
        if not item:
            return
        
        if item.parent() is not None:
            return

        menu = QMenu()

        accion_editar = menu.addAction("Editar")
        accion_eliminar = menu.addAction("Eliminar")

        accion = menu.exec(self.tree_proveedores.viewport().mapToGlobal(pos))

        if accion == accion_editar:
            self.editar_proveedor(item)

        elif accion == accion_eliminar:
            self.eliminar_proveedor(item)

    def editar_proveedor(self, item):
        id_proveedor = item.text(0)

        resultado = ejecutar_query(
            """
            SELECT
                id,
                id_proveedor,
                empresa,
                telefono,
                correo,
                contactos_json
            FROM proveedores
            WHERE id_proveedor = ?
            """,
            (id_proveedor,)
        )

        if not resultado:
            return

        datos = resultado[0]

        dialogo = AgregarResponsableDialog(
            personal_registrado = [],
            proveedores_registrados = [],
            parent = self,
            modo_edicion = True,
            tipo = "proveedor",
            datos = {
                "id": datos[0],
                "id_proveedor": datos[1],
                "empresa": datos[2],
                "telefono": datos[3],
                "correo": datos[4],
                "contactos": json.loads(datos[5]) if datos[5] else []
            }
        )

        if dialogo.exec():
            self.cargar_proveedores()

    def eliminar_proveedor(self, item):
        id_proveedor = item.text(0)

        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar proveedor")
        msg.setText("¿Deseas eliminar este registro?")
        msg.setIcon(QMessageBox.Icon.Question)

        btn_si = msg.addButton("Sí", QMessageBox.ButtonRole.YesRole)
        btn_no = msg.addButton("No", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_no)

        msg.exec()

        if msg.clickedButton() != btn_si:
            return

        try:
            conn = connect_db(create_if_missing=True)
            cur = conn.cursor()

            cur.execute(
                "DELETE FROM proveedores WHERE id_proveedor = ?",
                (id_proveedor,)
            )

            conn.commit()
            conn.close()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error al eliminar",
                f"Ocurrió un error al eliminar el proveedor:\n{e}"
            )
            return

        index = self.tree_proveedores.indexOfTopLevelItem(item)
        if index >= 0:
            self.tree_proveedores.takeTopLevelItem(index)
        # La referencia anterior queda obsoleta; evita un crash si después
        # mostrar_overlay intenta colapsarla.
        if self.item_expandido is item:
            self.item_expandido = None
        if self._ultimo_item_proveedor is item:
            self._ultimo_item_proveedor = None
        # Si era el último proveedor, hay que quitar la pestaña.
        self._sincronizar_tabs()

        QMessageBox.information(
            self,
            "Proveedor eliminado",
            "El registro se eliminó correctamente."
        )

    def actualizar_estado_asignar(self):
        if self.tabs.currentIndex() == 0:
            hay_seleccion = bool(self.tabla_personal.selectedItems())
        else:
            hay_seleccion = bool(self.tree_proveedores.selectedItems())

        self.btn_asignar.setEnabled(hay_seleccion)

    def asignar_responsable(self):
        if self.tabs.currentIndex() == 0:
            # -------- Personal --------
            items = self.tabla_personal.selectedItems()
            if not items:
                return  # NO hay selección real

            fila = items[0].row()

            data = {
                "tipo": "personal",
                "id": self.tabla_personal.item(fila, 0).text(),
                "nombre": " ".join([
                    self.tabla_personal.item(fila, i).text() 
                    for i in range(1, 4) 
                    if self.tabla_personal.item(fila, i).text() 
                ]),
                "telefono": self.tabla_personal.item(fila, 4).text(),
                "correo": self.tabla_personal.item(fila, 5).text()
            }

        else:
            # -------- Proveedor --------
            item = self.tree_proveedores.currentItem()
            if not item:
                return

            data = {
                "tipo": "proveedor",
                "id": item.text(0),
                "nombre": item.text(1),
                "telefono": item.text(2),
                "correo": item.text(3)
            }

        # Emitimos sin cerrar la ventana
        self.responsable_asignado.emit(data)
        self.btn_quitar.setVisible(True)
        self.btn_asignar.setEnabled(False)    

    def quitar_responsable(self):
        self.btn_quitar.setVisible(False)
        self.btn_asignar.setEnabled(False)

        self.tabla_personal.clearSelection()
        self.tree_proveedores.clearSelection()

        self.tree_proveedores.collapseAll()
        for overlay in self.overlays.values():
            overlay.hide()

        self.overlays.clear()
        self.item_expandido = None

        self.responsable_asignado.emit({
            "tipo": None,
            "id": None,
            "nombre": ""
        })