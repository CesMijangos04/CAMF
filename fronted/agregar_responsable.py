from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QWidget, QMessageBox, QTableWidgetItem,
    QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QMenu,
    QCheckBox, QTableWidget
)
from PyQt6.QtGui import QIntValidator
from PyQt6.QtCore import Qt
from db_manager import insertar_datos, ejecutar_query, connect_db
import json
import re

class AgregarResponsableDialog(QDialog):
    def __init__(self, personal_registrado, proveedores_registrados, parent=None, modo_edicion=False,
                 tipo=None, datos=None, on_guardado=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar responsable")
        self.setModal(True)
        self.resize(500, 420)

        self.personal_registrado = personal_registrado
        self.proveedores_registrados = proveedores_registrados

        self.modo_edicion = modo_edicion
        self.tipo = tipo
        self.datos = datos
        self.contactos_proveedor = []

        # Callback opcional que se llama después de cada guardado exitoso
        # (sin cerrar el diálogo). Lo usamos en configuración para refrescar
        # la lista detrás del diálogo en tiempo real.
        self.on_guardado = on_guardado

        if self.modo_edicion and self.datos:
            self.id_original = self.datos["id"]

        self.init_ui()

        # Si viene con `tipo` (sea para agregar o editar), escondemos la pestaña
        # contraria — así desde la pantalla de configuración solo aparece la
        # pestaña relevante (Personal o Proveedor, no ambas).
        if self.tipo == "personal":
            self.setWindowTitle("Editar personal" if self.modo_edicion else "Agregar personal")
            self.tabs.setCurrentIndex(0)
            self.tabs.removeTab(1)
        elif self.tipo == "proveedor":
            self.setWindowTitle("Editar proveedor" if self.modo_edicion else "Agregar proveedor")
            self.tabs.setCurrentIndex(0)
            self.tabs.removeTab(0)

        # En modo edición además precargamos los datos del registro.
        if self.modo_edicion and self.tipo:
            if self.tipo == "personal":
                self.cargar_datos_edicion_personal()
            elif self.tipo == "proveedor":
                self.cargar_datos_edicion_proveedor()

    def init_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.tab_personal(), "Personal")
        self.tabs.addTab(self.tab_proveedor(), "Proveedor")

        layout.addWidget(self.tabs)

    def _notificar_parent_responsable_guardado(self):
        # 1. Compatibilidad con programar_nuevo (su botón circular tiene que
        #    refrescar su estado de habilitado/deshabilitado).
        padre = self.parent()
        if padre is not None and hasattr(padre, "actualizar_estado_boton_lista_personal"):
            try:
                padre.actualizar_estado_boton_lista_personal()
            except Exception as e:
                print(f"[AgregarResponsable] callback al parent falló: {e}")

        # 2. Callback explícito para refresco en vivo (lo usa configuración
        #    para actualizar la lista que está detrás del diálogo). Es
        #    independiente del parent porque desde configuración pasamos
        #    programar_nuevo como parent (truco de estilo), pero queremos
        #    notificar a la página que sí abrió el diálogo.
        if self.on_guardado is not None:
            try:
                self.on_guardado()
            except Exception as e:
                print(f"[AgregarResponsable] on_guardado callback falló: {e}")

    def cargar_datos_edicion_personal(self):
        self.p_id.setText(self.datos["id_personal"])
        self.p_nombre.setText(self.datos["nombre"])
        self.p_ap_paterno.setText(self.datos["ap_paterno"])
        self.p_ap_materno.setText(self.datos["ap_materno"])
        self.p_telefono.setText(self.datos["telefono"])
        self.p_correo.setText(self.datos["correo"])
        self.p_puesto.setText(self.datos["puesto"])

    def cargar_datos_edicion_proveedor(self):
        self.v_id.setText(self.datos["id_proveedor"])
        self.v_empresa.setText(self.datos["empresa"])
        self.v_telefono.setText(self.datos["telefono"])
        self.v_correo.setText(self.datos["correo"])

        # Contactos (si los usas)
        self.lista_contactos.setRowCount(0)
        contactos = self.datos.get("contactos", [])
        self.contactos_proveedor = contactos.copy()

        for contacto in contactos:
            row = self.lista_contactos.rowCount()
            self.lista_contactos.insertRow(row)
            self.lista_contactos.setItem(row, 0, QTableWidgetItem(contacto["nombre"]))
            self.lista_contactos.setItem(row, 1, QTableWidgetItem(contacto["telefono"]))
            self.lista_contactos.setItem(row, 2, QTableWidgetItem(contacto["correo"]))

        self._sincronizar_personal_proveedor_ui()

    #--------------Formulario personal-----------------
    def tab_personal(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()

        self.p_id = QLineEdit()
        self.p_nombre = QLineEdit()
        self.p_ap_paterno = QLineEdit()
        self.p_ap_materno = QLineEdit()
        self.p_telefono = QLineEdit()
        self.p_telefono.setValidator(QIntValidator())
        self.p_correo = QLineEdit()
        self.p_puesto = QLineEdit()

        form.addRow("ID:", self.p_id)
        form.addRow("Nombre(s):", self.p_nombre)
        form.addRow("Apellido paterno:", self.p_ap_paterno)
        form.addRow("Apellido materno:", self.p_ap_materno)
        form.addRow("Teléfono:", self.p_telefono)
        form.addRow("Correo:", self.p_correo)
        form.addRow("Puesto:", self.p_puesto)

        layout.addLayout(form)
        
        btn_guardar = QPushButton("Guardar")
        btn_guardar.clicked.connect(self.guardar_personal)
        layout.addWidget(btn_guardar)
        
        return tab

    #--------------Formulario proveedor-----------------
    def tab_proveedor(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.v_id = QLineEdit()
        self.v_empresa = QLineEdit()
        self.v_telefono = QLineEdit()
        self.v_telefono.setValidator(QIntValidator())
        self.v_correo = QLineEdit()

        form.addRow("ID:", self.v_id)
        form.addRow("Empresa:", self.v_empresa)
        form.addRow("Teléfono:", self.v_telefono)
        form.addRow("Correo:", self.v_correo)

        layout.addLayout(form)

        # Checkbox si existe Personal
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
        QCheckBox::indicator:checked:hover {
            background-color: #0094ff;
        }
        """

        self.chk_personal_proveedor = QCheckBox("Personal del proveedor")
        self.chk_personal_proveedor.setStyleSheet(CHECKBOX_STYLE)
        self.chk_personal_proveedor.clicked.connect(self.toggle_personal_proveedor)
        layout.addWidget(self.chk_personal_proveedor)

        # Lista de contactos
        self.lista_contactos = QTableWidget()
        self.lista_contactos.setColumnCount(3)
        self.lista_contactos.setHorizontalHeaderLabels(["Nombre", "Teléfono", "Correo"])
        self.lista_contactos.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # evitar edición directa
        self.lista_contactos.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.lista_contactos.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.lista_contactos.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista_contactos.customContextMenuRequested.connect(self.mostrar_menu_contacto)
        self.lista_contactos.setEnabled(False)
        layout.addWidget(self.lista_contactos)

        # Botones Agregar/Eliminar
        btns = QHBoxLayout()

        self.btn_agregar_contacto = QPushButton("Agregar contacto")
        self.btn_agregar_contacto.setEnabled(False)
        self.btn_agregar_contacto.clicked.connect(self.abrir_form_contacto)
        self._actualizar_estilo_boton(self.btn_agregar_contacto)

        self.btn_eliminar_contacto = QPushButton("Eliminar contacto")
        self.btn_eliminar_contacto.setEnabled(False)
        self.btn_eliminar_contacto.clicked.connect(self.eliminar_contacto)
        self._actualizar_estilo_boton(self.btn_eliminar_contacto)

        btns.addWidget(self.btn_agregar_contacto)
        btns.addWidget(self.btn_eliminar_contacto)
        layout.addLayout(btns)

        btn_guardar = QPushButton("Guardar")
        btn_guardar.clicked.connect(self.guardar_proveedor)
        layout.addWidget(btn_guardar)

        self.contactos_proveedor = []

        return tab
    
    def toggle_personal_proveedor(self, checked: bool):
        # CASO: quiere desmarcar y hay contactos
        if not checked and self.contactos_proveedor:
            # Crear mensaje personalizado
            msg = QMessageBox(self)
            msg.setWindowTitle("Confirmar acción")
            msg.setText(
                "Existen contactos registrados.\n"
                "Si continúas, se eliminarán todos.\n\n"
                "¿Deseas continuar?"
            )

            # Botones personalizados en español
            btn_si = msg.addButton("Sí", QMessageBox.ButtonRole.YesRole)
            btn_no = msg.addButton("No", QMessageBox.ButtonRole.NoRole)

            # Botón por defecto
            msg.setDefaultButton(btn_no)

            # Mostrar mensaje
            msg.exec()

            if msg.clickedButton() == btn_no:
                # Cancelar → revertir inmediatamente
                self.chk_personal_proveedor.setChecked(True)
                return

            # Aceptar → borrar contactos
            self.contactos_proveedor.clear()
            self.lista_contactos.setRowCount(0)

        # Aplicar estado FINAL
        self.lista_contactos.setEnabled(checked)

        self.btn_agregar_contacto.setEnabled(checked)
        self._actualizar_estilo_boton(self.btn_agregar_contacto)

        self.btn_eliminar_contacto.setEnabled(checked and bool(self.contactos_proveedor))
        self._actualizar_estilo_boton(self.btn_eliminar_contacto)

    def _sincronizar_personal_proveedor_ui(self):
        tiene_contactos = bool(self.contactos_proveedor)

        # Marcar/desmarcar checkbox sin disparar lógica de borrado
        self.chk_personal_proveedor.blockSignals(True)
        self.chk_personal_proveedor.setChecked(tiene_contactos)
        self.chk_personal_proveedor.blockSignals(False)

        # Aplicar estado final
        self.lista_contactos.setEnabled(tiene_contactos)

        self.btn_agregar_contacto.setEnabled(tiene_contactos)
        self._actualizar_estilo_boton(self.btn_agregar_contacto)

        self.btn_eliminar_contacto.setEnabled(
            tiene_contactos and bool(self.contactos_proveedor)
        )
        self._actualizar_estilo_boton(self.btn_eliminar_contacto)

    def _actualizar_estilo_boton(self, boton: QPushButton):
        """Actualiza el estilo del botón según esté habilitado o no."""
        if boton.isEnabled():
            boton.setStyleSheet("")  # estilo normal del sistema
        else:
            boton.setStyleSheet("""
                QPushButton {
                    background-color: #262626;
                    color: #777;
                    border: 1px solid #2a2a2a;
                    border-radius: 4px;
                    padding: 4px 12px;
                }
            """)

        boton.style().unpolish(boton)
        boton.style().polish(boton)
        boton.update()
    
    def abrir_form_contacto(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Agregar contacto")

        layout = QFormLayout(dialog)

        nombre = QLineEdit()
        telefono = QLineEdit()
        telefono.setValidator(QIntValidator())
        correo = QLineEdit()

        layout.addRow("Nombre completo:", nombre)
        layout.addRow("Teléfono:", telefono)
        layout.addRow("Correo:", correo)

        btn_guardar = QPushButton("Guardar")
        btn_guardar.clicked.connect(lambda: self.guardar_contacto(dialog, nombre, telefono, correo))

        layout.addWidget(btn_guardar)
        dialog.exec()

    def guardar_contacto(self, dialog, nombre, telefono, correo):
        if not nombre.text().strip():
            QMessageBox.warning(dialog, "Campo obligatorio", "El nombre es obligatorio.")
            return

        contacto = {
            "nombre": nombre.text().strip(),
            "telefono": telefono.text().strip(),
            "correo": correo.text().strip()
        }

        self.contactos_proveedor.append(contacto)

        fila = self.lista_contactos.rowCount()
        self.lista_contactos.insertRow(fila)

        # Crear items y asignarlos a la fila
        item_nombre = QTableWidgetItem(contacto["nombre"])
        item_telefono = QTableWidgetItem(contacto["telefono"])
        item_correo = QTableWidgetItem(contacto["correo"])

        # Alinear cada celda a la izquierda o centro según quieras
        item_nombre.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        item_telefono.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item_correo.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Insertar en la tabla
        self.lista_contactos.setItem(fila, 0, item_nombre)
        self.lista_contactos.setItem(fila, 1, item_telefono)
        self.lista_contactos.setItem(fila, 2, item_correo)

        self.btn_eliminar_contacto.setEnabled(True)
        self._actualizar_estilo_boton(self.btn_eliminar_contacto)
        dialog.accept()

    def mostrar_menu_contacto(self, pos):
        row = self.lista_contactos.rowAt(pos.y())
        if row < 0:
            return  # No hay fila debajo del cursor

        menu = QMenu(self)
        editar_action = menu.addAction("Editar")
        action = menu.exec(self.lista_contactos.viewport().mapToGlobal(pos))

        if action == editar_action:
            self.editar_contacto(row)
    
    def editar_contacto(self, row):
        contacto = self.contactos_proveedor[row]

        dialog = QDialog(self)
        dialog.setWindowTitle("Editar contacto")
        layout = QFormLayout(dialog)

        nombre = QLineEdit(contacto["nombre"])
        telefono = QLineEdit(contacto["telefono"])
        telefono.setValidator(QIntValidator())
        correo = QLineEdit(contacto["correo"])

        layout.addRow("Nombre completo:", nombre)
        layout.addRow("Teléfono:", telefono)
        layout.addRow("Correo:", correo)

        btn_guardar = QPushButton("Guardar")
        layout.addWidget(btn_guardar)

        # Función interna para guardar los cambios
        def guardar_cambios():
            if not nombre.text().strip():
                QMessageBox.warning(dialog, "Campo obligatorio", "El nombre es obligatorio.")
                return

            # Actualizar la lista interna
            self.contactos_proveedor[row] = {
                "nombre": nombre.text().strip(),
                "telefono": telefono.text().strip(),
                "correo": correo.text().strip()
            }

            # Crear items con alineación
            item_nombre = QTableWidgetItem(nombre.text().strip())
            item_telefono = QTableWidgetItem(telefono.text().strip())
            item_correo = QTableWidgetItem(correo.text().strip())

            # Alineación: nombre y correo a la izquierda, teléfono centrado
            item_nombre.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item_telefono.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_correo.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            # Actualizar la tabla visual
            self.lista_contactos.setItem(row, 0, item_nombre)
            self.lista_contactos.setItem(row, 1, item_telefono)
            self.lista_contactos.setItem(row, 2, item_correo)

            dialog.accept()

        btn_guardar.clicked.connect(guardar_cambios)
        dialog.exec()
    
    def eliminar_contacto(self):
        row = self.lista_contactos.currentRow()
        if row < 0:
            return

        self.lista_contactos.removeRow(row)
        self.contactos_proveedor.pop(row)

        if not self.contactos_proveedor:
            self.btn_eliminar_contacto.setEnabled(False)
            self._actualizar_estilo_boton(self.btn_eliminar_contacto)
    
    #-----------------Guardado de Personal y Proveedor------------------
    def guardar_personal(self):
        # 1. Obtener valores
        id_personal = self.p_id.text().strip()
        nombre = self.p_nombre.text().strip()
        ap_paterno = self.p_ap_paterno.text().strip()
        ap_materno = self.p_ap_materno.text().strip()
        telefono = self.p_telefono.text().strip()
        correo = self.p_correo.text().strip()
        puesto = self.p_puesto.text().strip()

        # 2. Validar campos completos
        if not all([id_personal, nombre, ap_paterno, ap_materno, telefono, correo, puesto]):
            QMessageBox.warning(
                self,
                "Campos incompletos",
                "Debes llenar todos los campos para guardar el personal."
            )
            return

        # 3. Validar teléfono (solo números)
        if not telefono.isdigit():
            QMessageBox.warning(
                self,
                "Teléfono inválido",
                "El teléfono solo debe contener números."
            )
            return
        
        try:
            conn = connect_db(create_if_missing=True)
            if conn is None:
                raise Exception("No se pudo abrir la base de datos")
            cur = conn.cursor()

        # 4. MODO EDICIÓN → UPDATE
            if self.modo_edicion:
                # Validar ID duplicado
                cur.execute(
                    "SELECT 1 FROM personal WHERE id_personal = ? AND id != ?",
                    (id_personal, self.id_original)
                )
                if cur.fetchone():
                    QMessageBox.warning(
                        self,
                        "ID duplicado",
                        "El ID ingresado ya pertenece a otro personal."
                    )
                    conn.close()
                    return

                cur.execute("""
                    UPDATE personal
                    SET id_personal=?, nombre=?, ap_paterno=?, ap_materno=?,
                        telefono=?, correo=?, puesto=?
                    WHERE id=?
                """, (
                    id_personal, nombre, ap_paterno, ap_materno,
                    telefono, correo, puesto, self.id_original
                ))

                conn.commit()
                conn.close()

                QMessageBox.information(
                    self,
                    "Personal actualizado",
                    "Los datos se actualizaron correctamente."
                )
                self._notificar_parent_responsable_guardado()
                self.accept()
                return
        
        # 5. Nuevo INSERT
            cur.execute(
                "SELECT 1 FROM personal WHERE id_personal = ?",
                (id_personal,)
            )
            if cur.fetchone():
                QMessageBox.warning(
                    self,
                    "ID duplicado",
                    "El ID ingresado ya está registrado."
                )
                conn.close()
                return

            cur.execute("""
                INSERT INTO personal
                (id_personal, nombre, ap_paterno, ap_materno, telefono, correo, puesto)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                id_personal, nombre, ap_paterno, ap_materno,
                telefono, correo, puesto
            ))

            conn.commit()
            conn.close()

            QMessageBox.information(
                self,
                "Personal guardado",
                "El personal se registró correctamente."
            )
            self._notificar_parent_responsable_guardado()

        # 6. Limpiar formulario
            self.p_id.clear()
            self.p_nombre.clear()
            self.p_ap_paterno.clear()
            self.p_ap_materno.clear()
            self.p_telefono.clear()
            self.p_correo.clear()
            self.p_puesto.clear()
        
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error al guardar",
                f"Ocurrió un error al guardar el personal:\n{e}"
            )
            print("Error en guardar_personal:", e)

    def guardar_proveedor(self):
        # 1. Obtener valores
        id_proveedor = self.v_id.text().strip()
        empresa = self.v_empresa.text().strip()
        telefono = self.v_telefono.text().strip()
        correo = self.v_correo.text().strip()

        # 2. Validar campos completos
        if not all([id_proveedor, empresa, telefono, correo]):
            QMessageBox.warning(
                self,
                "Campos incompletos",
                "Debes llenar todos los campos del proveedor."
            )
            return

        # 3. Validar teléfono (solo números)
        if not telefono.isdigit():
            QMessageBox.warning(
                self,
                "Teléfono inválido",
                "El teléfono solo debe contener números."
            )
            return

        # 4. Obtener contactos del QTableWidget
        contactos = []
        for row in range(self.lista_contactos.rowCount()):
            contacto = {
                "nombre": self.lista_contactos.item(row, 0).text(),
                "telefono": self.lista_contactos.item(row, 1).text(),
                "correo": self.lista_contactos.item(row, 2).text()
            }
            contactos.append(contacto)

        contactos_json = json.dumps(contactos, ensure_ascii=False)

        try:
            conn = connect_db(create_if_missing=True)
            if conn is None:
                raise Exception("No se pudo abrir la base de datos")

            cur = conn.cursor()

            # 5. MODO EDICIÓN → UPDATE
            if self.modo_edicion:
                # Validar ID duplicado (excepto el propio registro)
                cur.execute(
                    "SELECT 1 FROM proveedores WHERE id_proveedor = ? AND id != ?",
                    (id_proveedor, self.id_original)
                )
                if cur.fetchone():
                    QMessageBox.warning(
                        self,
                        "ID duplicado",
                        "El ID ingresado ya pertenece a otro proveedor."
                    )
                    conn.close()
                    return

                cur.execute("""
                    UPDATE proveedores
                    SET id_proveedor = ?, empresa = ?, telefono = ?, correo = ?, contactos_json = ?
                    WHERE id = ?
                """, (
                    id_proveedor,
                    empresa,
                    telefono,
                    correo,
                    contactos_json,
                    self.id_original
                ))

                conn.commit()
                conn.close()

                QMessageBox.information(
                    self,
                    "Proveedor actualizado",
                    "Los datos del proveedor se actualizaron correctamente."
                )
                self._notificar_parent_responsable_guardado()
                self.accept()
                return

            # 6. NUEVO REGISTRO → INSERT
            cur.execute(
                "SELECT 1 FROM proveedores WHERE id_proveedor = ?",
                (id_proveedor,)
            )
            if cur.fetchone():
                QMessageBox.warning(
                    self,
                    "ID duplicado",
                    "El ID de proveedor ya está registrado."
                )
                conn.close()
                return

            cur.execute("""
                INSERT INTO proveedores
                (id_proveedor, empresa, telefono, correo, contactos_json)
                VALUES (?, ?, ?, ?, ?)
            """, (
                id_proveedor,
                empresa,
                telefono,
                correo,
                contactos_json
            ))

            conn.commit()
            conn.close()

            QMessageBox.information(
                self,
                "Guardado exitoso",
                "Proveedor registrado correctamente."
            )
            self._notificar_parent_responsable_guardado()

            # 7. Limpiar formulario
            self.v_id.clear()
            self.v_empresa.clear()
            self.v_telefono.clear()
            self.v_correo.clear()
            self.contactos_proveedor.clear()
            self.lista_contactos.setRowCount(0)

            self.chk_personal_proveedor.setChecked(False)
            self.toggle_personal_proveedor(False)

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error al guardar",
                f"Ocurrió un error al guardar el proveedor:\n{e}"
            )
            print("Error en guardar_proveedor:", e)
