# transformador.py
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QStackedLayout,
    QTabWidget, QFormLayout, QLineEdit, QComboBox, QDateEdit, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QDialog, QListWidget,
    QListWidgetItem, QHBoxLayout, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, QPoint, QDate
from db_manager import insertar_datos, obtener_datos

class TransformadorManager:
    def __init__(self, parent):
        self.parent = parent  # referencia a InventarioWindow

    # -----------------------------------------------------------
    def crear_item(self, texto):
        """Crea un QTableWidgetItem centrado."""
        item = QTableWidgetItem(str(texto))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item
        
    def mostrarFormularioTransformador(self, datos_existentes=None, fila_idx=None):
        form = QFormLayout()
        dlg = QDialog(self.parent)
        dlg.setWindowTitle("Nuevo Transformador" if not datos_existentes else "Editar Transformador")
        dlg.setStyleSheet("background-color: #1e1e1e; color: white;")
        dlg.setFixedSize(400, 400)

        id_ = QLineEdit(datos_existentes[0] if datos_existentes else "")
        id_original = datos_existentes[0] if datos_existentes else None
        ubic = QLineEdit(datos_existentes[1] if datos_existentes else "")
        cap = QLineEdit(datos_existentes[2] if datos_existentes else "")
        tension = QComboBox()
        tension.addItems(["13.2 kV", "23 kV", "34.5 kV"])
        if datos_existentes:
            try: tension.setCurrentText(datos_existentes[3])
            except: pass
        fecha = QDateEdit(QDate.currentDate())
        fecha.setCalendarPopup(True)  # Muestra el calendario
        if datos_existentes:
            try: fecha.setDate(QDate.fromString(datos_existentes[4], "yyyy-MM-dd"))
            except: pass
        marca = QLineEdit(datos_existentes[5] if datos_existentes else "")
        enf = QComboBox()
        enf.addItems(["Aceite", "Aire"])
        if datos_existentes:
            try: enf.setCurrentText(datos_existentes[6])
            except: pass
        fases = QComboBox()
        fases.addItems(["Monofásico", "Trifásico"])
        if datos_existentes:
            try: fases.setCurrentText(datos_existentes[7])
            except: pass
        conexion = QComboBox()
        conexion.addItems(["Δ-Y", "Y-Δ", "Y-Y", "Δ-Δ"])
        if datos_existentes:
            try: conexion.setCurrentText(datos_existentes[8])
            except: pass
        tipo = QComboBox()
        tipo.addItems(["Pedestal", "Poste", "Subestación", "Sumergible"])
        if datos_existentes:
            try: tipo.setCurrentText(datos_existentes[9])
            except: pass

        # ── Selector de grupo (widget compartido) ────────────────────────
        from selector_grupo import SelectorGrupoWidget
        from db_manager import obtener_grupos, connect_db
 
        # Si editamos, leer grupo_id actual desde la BD
        grupo_id_actual = None
        if datos_existentes and id_original:
            conn_tmp = connect_db()
            if conn_tmp:
                cur_tmp = conn_tmp.cursor()
                cur_tmp.execute("SELECT grupo_id FROM transformadores WHERE id = ?", (id_original,))
                row_tmp = cur_tmp.fetchone()
                conn_tmp.close()
                if row_tmp:
                    grupo_id_actual = row_tmp[0]

        selector_grupo = SelectorGrupoWidget(grupo_id_actual=grupo_id_actual)

        # Aviso solo cuando es el primer elemento y no hay grupos creados
        if not datos_existentes and not obtener_grupos():
            lbl_aviso = QLabel("⚠ Crea un grupo antes de guardar.")
            lbl_aviso.setStyleSheet("color: #EF9F27; font-size: 11px;")
        else:
            lbl_aviso = None
        # ── FIN selector de grupo ─────────────────────────────────────────

        form.addRow("ID:", id_)
        form.addRow("Ubicación:", ubic)
        form.addRow("Capacidad:", cap)
        form.addRow("Tensión:", tension)
        form.addRow("Fecha instalación:", fecha)
        form.addRow("Marca:", marca)
        form.addRow("Enfriamiento:", enf)
        form.addRow("Fases:", fases)
        form.addRow("Conexión:", conexion)
        form.addRow("Tipo:", tipo)
        form.addRow("Grupo:", selector_grupo)          
        if lbl_aviso:
            form.addRow("", lbl_aviso)

        btn_guardar = QPushButton("Guardar")
        btn_guardar.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                color: white;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #505050; }
        """)
        btn_guardar.clicked.connect(lambda _, fila=fila_idx: self.guardarTransformador(
            id_.text(), ubic.text(), cap.text(), tension.currentText(),
            fecha.date().toString("yyyy-MM-dd"), marca.text(), enf.currentText(),
            fases.currentText(), conexion.currentText(), tipo.currentText(), 
            selector_grupo.grupo_seleccionado(), dlg, fila, id_original
        ))

        form.addWidget(btn_guardar)
        dlg.setLayout(form)
        dlg.exec()

    # ---------------- guardar (memoria + UI) ----------------
    def guardarTransformador(self, *datos):
        try:
            # desempaquetar con tolerancia (según si hay fila_idx o no)
            if len(datos) >= 14:
                id_, ubic, cap, tension, fecha, marca, enf, fases, conexion, tipo, grupo_id, dlg, fila_idx, id_original = datos[:14]
            elif len(datos) == 13:
                id_, ubic, cap, tension, fecha, marca, enf, fases, conexion, tipo, grupo_id, dlg, fila_idx = datos
                id_original = None
            else:
                QMessageBox.warning(self.parent, "Error", f"Número inesperado de argumentos ({len(datos)}).")
                return

            # construir lista con datos (excepto dlg y fila_idx)
            datos_lista = [id_, ubic, cap, tension, fecha, marca, enf, fases, conexion, tipo]

            # VALIDACIÓN OBLIGATORIA DE ID
            if not id_ or not id_.strip():
                QMessageBox.warning(self.parent, "ID obligatorio",
                                    "No se puede guardar un transformador sin ID.")
                return
 
            # Abrir conexión a la BD una sola vez
            from db_manager import connect_db
            conn = connect_db(create_if_missing=True)
            cur = conn.cursor()
 
            # Validación de ID único
            cur.execute(
                "SELECT COUNT(*) FROM transformadores WHERE id = ? AND id != ?",
                (id_, id_original if id_original else "")
            )
            if cur.fetchone()[0] > 0:
                QMessageBox.warning(self.parent, "ID duplicado",
                                    f"El ID '{id_}' ya está siendo usado por otro transformador.")
                conn.close()
                return

            # ── Bloque opcional: actualizar QTableWidget si existe (modo antiguo) ──
            if hasattr(self.parent, 'tabla_transformadores'):
                header = self.parent.tabla_transformadores.horizontalHeader()
                was_sorting = self.parent.tabla_transformadores.isSortingEnabled() and header.sortIndicatorSection() != -1
                current_sort_col = header.sortIndicatorSection()
                current_sort_order = header.sortIndicatorOrder()
 
                if was_sorting:
                    self.parent.tabla_transformadores.setSortingEnabled(False)
 
                if fila_idx is not None and isinstance(fila_idx, int) and fila_idx >= 0:
                    target_row = None
                    if id_:
                        for r in range(self.parent.tabla_transformadores.rowCount()):
                            item_id = self.parent.tabla_transformadores.item(r, 0)
                            if item_id and item_id.text() == str(id_):
                                target_row = r
                                break
                    if target_row is None:
                        target_row = fila_idx if fila_idx < self.parent.tabla_transformadores.rowCount() else None
 
                    if target_row is not None:
                        for i, d in enumerate(datos_lista):
                            item = self.parent.tabla_transformadores.item(target_row, i)
                            if item is None:
                                self.parent.tabla_transformadores.setItem(target_row, i, self.crear_item(d))
                            else:
                                item.setText(str(d))
                else:
                    fila = self.parent.tabla_transformadores.rowCount()
                    self.parent.tabla_transformadores.insertRow(fila)
                    for i, d in enumerate(datos_lista):
                        self.parent.tabla_transformadores.setItem(fila, i, self.crear_item(d))
 
                if was_sorting:
                    self.parent.tabla_transformadores.setSortingEnabled(True)
                    header.setSortIndicator(current_sort_col, current_sort_order)
 
                if hasattr(self.parent, 'registrarFilaOriginal'):
                    self.parent.registrarFilaOriginal(self.parent.tabla_transformadores)
            # ── Fin bloque QTableWidget ──────────────────────────────────────
 
            # GUARDAR EN BD
            if fila_idx is not None:
                cur.execute("""
                    UPDATE transformadores
                    SET id=?, ubicacion=?, capacidad=?, tension=?, fecha=?, marca=?,
                        enfriamiento=?, fases=?, conexion=?, tipo=?, grupo_id=?
                    WHERE id=?
                """, (id_, ubic, cap, tension, fecha, marca,
                      enf, fases, conexion, tipo, grupo_id,  # ← grupo_id incluido
                      id_original))
                print(f"[UPDATE] Transformador actualizado: {id_original} → {id_}")
            else:
                cur.execute("""
                    INSERT INTO transformadores
                    (id, ubicacion, capacidad, tension, fecha, marca, enfriamiento, fases, conexion, tipo, grupo_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (id_, ubic, cap, tension, fecha, marca,
                      enf, fases, conexion, tipo, grupo_id))  # ← grupo_id incluido
                print(f"[INSERT] Transformador {id_} insertado")
 
            conn.commit()
            conn.close()
 
            print(f"Transformador guardado correctamente.")
            print(f"Total en BD: {len(obtener_datos('transformadores'))}")
 
            # Recargar la vista de grupos para que aparezca el nuevo equipo
            if hasattr(self.parent, 'recargarVistas'):
                self.parent.recargarVistas()
 
            dlg.accept()
 
        except Exception as e:
            QMessageBox.critical(self.parent, "Error crítico", f"Ocurrió un error al guardar el transformador:\n{str(e)}")
            print("Error en guardarTransformador:", e)
            
    def menuContextTransformador(self, pos: QPoint):
        # Obtener la TablaEquipos que emitió la señal
        tabla = self.parent.sender()
        if tabla is None or not hasattr(tabla, "rowCount"):
            tabla = getattr(self.parent, 'tabla_transformadores', None)
        if tabla is None:
            return
 
        fila = tabla.currentRow()
        if fila < 0:
            return
 
        menu = QMenu()
        editar = menu.addAction("Editar")
        eliminar = menu.addAction("Eliminar")
        action = menu.exec(tabla.viewport().mapToGlobal(pos))
 
        id_item = tabla.item(fila, 0)
        id_val = id_item.text() if id_item else None
 
        if action == eliminar and id_val:
            confirm = QMessageBox.question(self.parent, "Eliminar transformador",
                                           f"¿Eliminar el transformador '{id_val}'?")
            if confirm == QMessageBox.StandardButton.Yes:
                try:
                    from db_manager import connect_db
                    conn = connect_db(create_if_missing=False)
                    if conn:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM transformadores WHERE id = ?", (id_val,))
                        conn.commit()
                        conn.close()
                        print(f"[ELIMINADO] Transformador con ID {id_val} eliminado de la BD.")
                except Exception as e:
                    print(f"Error al eliminar: {e}")
                
                if hasattr(self.parent, 'recargarVistas'):
                    self.parent.recargarVistas()
 
        elif action == editar and id_val:
            datos = []
            for c in range(tabla.columnCount()):
                item = tabla.item(fila, c)
                datos.append(item.text() if item else "")
            self.mostrarFormularioTransformador(datos_existentes=datos, fila_idx=fila)
 
    def cargarTransformadoresDesdeDB(self):
        """Carga los transformadores desde SQLite y los muestra en la tabla (modo antiguo)."""
        if not hasattr(self.parent, 'tabla_transformadores'):
            return  # En modo VistaGrupos no hace falta
        try:
            registros = obtener_datos("transformadores")
            tabla = self.parent.tabla_transformadores
            tabla.setRowCount(0)
            for fila_db in registros:
                fila = tabla.rowCount()
                tabla.insertRow(fila)
                # solo las primeras 10 columnas (sin grupo_id) para la UI antigua
                for col, valor in enumerate(fila_db[:10]):
                    item = QTableWidgetItem(str(valor) if valor is not None else "")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    tabla.setItem(fila, col, item)
            print(f"[CARGA] {len(registros)} transformadores cargados desde la BD.")
        except Exception as e:
            print(f"[ERROR] No se pudieron cargar los transformadores: {e}")
        pass

