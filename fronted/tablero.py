# tablero.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QMenu, QDialog, QFormLayout, QLineEdit, QComboBox,
    QDateEdit, QTextEdit, QMessageBox, QHBoxLayout, QAbstractItemView
)
from PyQt6.QtCore import Qt, QDate, QPoint
from db_manager import insertar_datos, obtener_datos
from circuito import VentanaCircuitos, CircuitoManager
from ui_tablero_visual import VistaTableroWidget

class TableroManager:
    def __init__(self, parent):
        self.parent = parent
        self.circuitos_tablero_actual = None  # temporal mientras se crea un tablero
        self.circuito_manager = CircuitoManager(parent)

    # ---------------- utilidades ----------------
    def crear_item(self, texto):
        """Crea un QTableWidgetItem centrado (para insertar en la UI)."""
        item = QTableWidgetItem(str(texto))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    # ---------------- formulario ----------------
    def mostrarFormularioTablero(self, datos_existentes=None, fila_idx=None):
        form = QFormLayout()
        dlg = QDialog(self.parent)
        dlg.setWindowTitle("Nuevo Tablero" if not datos_existentes else "Editar Tablero")
        dlg.setStyleSheet("background-color: #1e1e1e; color: white;")
        dlg.setFixedSize(420, 520)

        id_ = QLineEdit(datos_existentes[0] if datos_existentes else "")
        id_original = datos_existentes[0] if datos_existentes else None
        nombre = QLineEdit(datos_existentes[1] if datos_existentes else "")
        ubic = QLineEdit(datos_existentes[2] if datos_existentes else "")
        corriente = QLineEdit(datos_existentes[3] if datos_existentes else "")
        tension = QLineEdit(datos_existentes[4] if datos_existentes else "")

        tipo = QComboBox()
        tipo.addItems(["Principal", "Derivado", "Control", "Fuerza", "Alumbrado y contactos", "Emergencia"])
        if datos_existentes:
            try:
                tipo.setCurrentText(datos_existentes[5])
            except: pass

        marca = QComboBox()
        modelo = QComboBox()
        marca.addItems(["Seleccionar...", "Square D", "Siemens", "Eaton", "ABB"])

        familias = {
            "Square D": ["NQ", "NF", "I-Line", "QMB", "SWBD"],
            "Siemens": ["P1", "P2", "P3", "S4"],
            "Eaton": ["Pow-R-Line 1", "Pow-R-Line 2", "Pow-R-Line 3"],
            "ABB": ["MNS", "System pro E power"]
        }

        def actualizar_modelos():
            modelo.clear()
            modelo.addItems(familias.get(marca.currentText(), ["Seleccionar marca primero"]))
        marca.currentTextChanged.connect(actualizar_modelos)
        if datos_existentes:
            try: marca.setCurrentText(datos_existentes[7])
            except: pass
            try: modelo.setCurrentText(datos_existentes[7])
            except: pass

        num_circuitos = QComboBox()
        num_circuitos.addItems(["Seleccionar...", "12", "14", "20", "24", "30", "42", "54"])
        if datos_existentes:
            try:
                num_circuitos.setCurrentText(datos_existentes[6])
            except:
                pass

        # ---------- circuitos (temporal / UserRole) ----------
        circuitos_iniciales = None
        # si venimos en edición, leer circuitos guardados en el item ID
        if fila_idx is not None and hasattr(self.parent, 'tabla_tableros'):
            try:
                item_id = self.parent.tabla_tableros.item(fila_idx, 0)
                if item_id:
                    saved = item_id.data(Qt.ItemDataRole.UserRole)
                    if saved:
                        circuitos_iniciales = saved
            except Exception:
                circuitos_iniciales = None
         # En modo VistaGrupos, leer desde la BD
        elif fila_idx is not None and id_original:
            try:
                circuitos_iniciales = self.circuito_manager.cargar_circuitos_de_tablero(id_original)
                if not circuitos_iniciales:
                    circuitos_iniciales = None
            except Exception:
                circuitos_iniciales = None
        else:
            # nuevo tablero: usar variable temporal si existe
            if getattr(self.parent, 'circuitos_tablero_actual', None):
                circuitos_iniciales = self.parent.circuitos_tablero_actual

        btn_circuitos = QPushButton("Agregar circuitos (opcional)")
        btn_circuitos.setStyleSheet("""
            QPushButton {
                background-color: #0078d7;
                color: white;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #0094ff; }
        """)
        
        if circuitos_iniciales:
            btn_circuitos.setText("Editar circuitos")

        def abrir_circuitos():
            nonlocal circuitos_iniciales
            try:
                num_esp = int(num_circuitos.currentText())
            except Exception:
                num_esp = 24

            # Determinar tablero_id y grupo_id actuales para filtrar combos
            tablero_id_actual = id_.text().strip() or id_original
            grupo_id_actual = selector_grupo.grupo_seleccionado()

            dlg_circ = VentanaCircuitos(
                num_espacios=num_esp,
                tablero_id=tablero_id_actual,
                grupo_id=grupo_id_actual,
                circuitos_iniciales=circuitos_iniciales,
            )

            resultado = dlg_circ.exec()

            if resultado == QDialog.DialogCode.Accepted:
                # Obtener la lista lista para persistir (sin huecos, solo inicios)
                nuevos = dlg_circ.obtener_circuitos_para_guardar()
                circuitos_iniciales = nuevos

                # Guardar temporalmente: si es nuevo tablero, guardarlo en parent.circuitos_tablero_actual,
                # si es edición, guardarlo directamente en el UserRole del item ID correspondiente.
                if fila_idx is None:
                    self.parent.circuitos_tablero_actual = nuevos
                else:
                    if hasattr(self.parent, 'tabla_tableros'):
                        item_id_local = self.parent.tabla_tableros.item(fila_idx, 0)
                        if item_id_local:
                            item_id_local.setData(Qt.ItemDataRole.UserRole, nuevos)
                    # En modo VistaGrupos, los circuitos se guardarán en el INSERT/UPDATE
                    self.parent.circuitos_tablero_actual = nuevos
                btn_circuitos.setText("Editar circuitos")

        btn_circuitos.clicked.connect(abrir_circuitos)

        fecha = QDateEdit(QDate.currentDate())
        fecha.setCalendarPopup(True)
        if datos_existentes:
            try:
                fecha.setDate(QDate.fromString(datos_existentes[8], "yyyy-MM-dd"))
            except:
                pass

        comentarios = QTextEdit(datos_existentes[9] if datos_existentes else "")

        # ── Selector de grupo (widget compartido) ────────────────────────
        from selector_grupo import SelectorGrupoWidget
        from db_manager import obtener_grupos, connect_db

        # Si editamos, preseleccionar el grupo actual desde la BD
        grupo_id_actual = None
        if datos_existentes and id_original:
            conn_tmp = connect_db()
            if conn_tmp:
                cur_tmp = conn_tmp.cursor()
                cur_tmp.execute("SELECT grupo_id FROM tableros WHERE id = ?", (id_original,))
                row_tmp = cur_tmp.fetchone()
                conn_tmp.close()
                if row_tmp:
                    grupo_id_actual = row_tmp[0]

        selector_grupo = SelectorGrupoWidget(grupo_id_actual=grupo_id_actual)

        if not datos_existentes and not obtener_grupos():
            lbl_aviso = QLabel("⚠ Crea un grupo antes de guardar.")
            lbl_aviso.setStyleSheet("color: #EF9F27; font-size: 11px;")
        else:
            lbl_aviso = None
        # ── FIN selector de grupo ─────────────────────────────────────────

        # agregar campos al formulario
        form.addRow("ID:", id_)
        form.addRow("Nombre:", nombre)
        form.addRow("Ubicación:", ubic)
        form.addRow("Corriente nominal (A):", corriente)
        form.addRow("Tensión (V):", tension)
        form.addRow("Tipo:", tipo)
        form.addRow("Fabricante/Marca:", marca)
        form.addRow("Modelo:", modelo)
        form.addRow("Número de circuitos:", num_circuitos)
        form.addRow("", btn_circuitos)
        form.addRow("Fecha instalación:", fecha)
        form.addRow("Comentarios:", comentarios)
        form.addRow("Grupo:", selector_grupo)          
        if lbl_aviso:
            form.addRow("", lbl_aviso)

        # Guardar (usa fila_idx del cierre)
        def guardar_y_salir():
            if not id_.text():
                QMessageBox.warning(self.parent, "ID obligatorio", "No se puede guardar un tablero sin ID.")
                return

            try:
                # pasar fila_idx para que guardarTablero actualice correctamente si es edición
                self.guardarTablero(
                    id_.text(), nombre.text(), ubic.text(), corriente.text(), tension.text(),
                    tipo.currentText(), num_circuitos.currentText(), marca.currentText(),
                    fecha.text(), comentarios.toPlainText(), selector_grupo.grupo_seleccionado(),
                    dlg, fila_idx, id_original
                )
            except Exception as e:
                print("ERROR: al guardar tablero:", e)

            # limpiar temporal
            self.parent.circuitos_tablero_actual = None
            return

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
        btn_guardar.clicked.connect(guardar_y_salir)
        form.addWidget(btn_guardar)

        dlg.setLayout(form)
        dlg.exec()

    # ---------------- guardar (memoria + UI) ----------------
    def guardarTablero(self, *datos):
        try:
            if len(datos) == 14:
                id_, nombre, ubic, corriente, tension, tipo, num_circuitos, marca, fecha, comentarios, grupo_id, dlg, fila_idx, id_original = datos
            elif len(datos) == 13:
                id_, nombre, ubic, corriente, tension, tipo, num_circuitos, marca, fecha, comentarios, grupo_id, dlg, fila_idx = datos
                id_original = None
            else:
                QMessageBox.warning(self.parent, "Error", f"Número inesperado de argumentos ({len(datos)}).")
                return

            datos_lista = [id_, nombre, ubic, corriente, tension, tipo,
                            num_circuitos, marca, fecha, comentarios]

            # VALIDACIÓN OBLIGATORIA DE ID
            if not id_ or not id_.strip():
                QMessageBox.warning(self.parent, "ID obligatorio",
                                    "No se puede guardar un tablero sin ID.")
                return

            # Abrir conexión a la BD una sola vez
            from db_manager import connect_db
            conn = connect_db(create_if_missing=True)
            cur = conn.cursor()

            # VALIDAR ID ÚNICO
            cur.execute(
                "SELECT COUNT(*) FROM tableros WHERE id = ? AND id != ?",
                (id_, id_original if id_original else "")
            )
            if cur.fetchone()[0] > 0:
                QMessageBox.warning(self.parent, "ID duplicado",
                                    f"El ID '{id_}' ya está siendo usado por otro tablero.")
                conn.close()
                return

            #------------ OBTENER CIRCUITOS------------------
            circuitos = getattr(self.parent, "circuitos_tablero_actual", None)

            # GUARDAR EN BD
            if fila_idx is not None:
                cur.execute("""
                    UPDATE tableros
                    SET id=?, nombre=?, ubicacion=?, corriente_nominal=?, tension=?, tipo=?, num_circuitos=?,
                        marca=?, fecha_instalacion=?, comentarios=?, grupo_id=?
                    WHERE id=?
                """, (
                    id_, nombre, ubic, corriente, tension, tipo, num_circuitos,
                    marca, fecha, comentarios, grupo_id, id_original
                ))
                print(f"[UPDATE] Tablero actualizado: {id_original} → {id_}")
            else:
                cur.execute("""
                    INSERT INTO tableros
                    (id, nombre, ubicacion, corriente_nominal, tension, tipo, num_circuitos,
                     marca, fecha_instalacion, comentarios, grupo_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (id_, nombre, ubic, corriente, tension, tipo, num_circuitos,
                      marca, fecha, comentarios, grupo_id))
                print(f"[INSERT] Tablero {id_} insertado")
 
            conn.commit()
            conn.close()

            if circuitos is not None:
                self.circuito_manager.guardar_circuitos_de_tablero(id_, circuitos)
 
            print(f"Tablero guardado correctamente.")
            print(f"Total en BD: {len(obtener_datos('tableros'))}")
 
            # Recargar la vista de grupos
            if hasattr(self.parent, 'recargarVistas'):
                self.parent.recargarVistas()
 
            dlg.accept()
 
        except Exception as e:
            QMessageBox.critical(self.parent, "Error crítico", f"Ocurrió un error al guardar el tablero:\n{str(e)}")
            print("Error en guardarTablero:", e)
 
    # ---------------- doble clic en celda ----------------
    def dobleClicTablero(self, fila: int, columna: int):
        """
        Maneja el doble clic en una celda de la tabla.
        Si la columna es 'Comentarios' (índice 8), abre una ventana de solo
        lectura con el contenido completo. El resto de columnas no reaccionan.
        """
        # Columna 8 = Comentarios (según el orden definido en inventario.py)
        if columna != 8:
            return
 
        tabla = self.parent.sender()
        if tabla is None or not hasattr(tabla, "item"):
            return
 
        item = tabla.item(fila, columna)
        comentario = item.text() if item else ""
 
        if not comentario.strip():
            QMessageBox.information(self.parent, "Sin comentario",
                                    "Este tablero no tiene comentarios registrados.")
            return
 
        id_item = tabla.item(fila, 0)
        id_val = id_item.text() if id_item else ""
 
        dlg = QDialog(self.parent)
        dlg.setWindowTitle(f"Comentario — Tablero {id_val}")
        dlg.setFixedSize(440, 320)
        dlg.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; }
            QTextEdit {
                background-color: #2a2a2a; color: white;
                border: 1px solid #444; border-radius: 5px;
                padding: 6px;
            }
            QPushButton {
                background-color: #3a3a3a; color: white;
                border-radius: 6px; padding: 5px 14px;
            }
            QPushButton:hover { background-color: #505050; }
            QLabel { color: #aaa; font-size: 11px; }
        """)
        vl = QVBoxLayout(dlg)
        vl.addWidget(QLabel("Comentario (solo lectura):"))
 
        txt = QTextEdit()
        txt.setPlainText(comentario)
        txt.setReadOnly(True)
        vl.addWidget(txt, 1)
 
        botones = QHBoxLayout()
        botones.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(dlg.accept)
        botones.addWidget(btn_cerrar)
        vl.addLayout(botones)
 
        dlg.exec()

    # ---------------- menú contextual ----------------
    def menuContextTablero(self, pos: QPoint):
        # Obtener la TablaEquipos que emitió la señal
        tabla = self.parent.sender()
        if tabla is None or not hasattr(tabla, "rowCount"):
            tabla = getattr(self.parent, 'tabla_tableros', None)
        if tabla is None:
            return
 
        fila = tabla.currentRow()
        if fila < 0:
            return
        
        menu = QMenu()
        editar = menu.addAction("Editar")
        eliminar = menu.addAction("Eliminar")
        ver_circuitos = menu.addAction("Ver circuitos")
        
        # "Diagrama unifilar" solo aparece si el tablero ya tiene circuitos
        id_item_check = tabla.item(fila, 0)
        id_val_check = id_item_check.text() if id_item_check else None
        diagrama_unifilar = None
        if id_val_check:
            try:
                circuitos_existen = self.circuito_manager.cargar_circuitos_de_tablero(id_val_check)
            except Exception:
                circuitos_existen = None
            if circuitos_existen:
                diagrama_unifilar = menu.addAction("Diagrama unifilar")
        
        action = menu.exec(tabla.viewport().mapToGlobal(pos))
 
        id_item = tabla.item(fila, 0)
        id_val = id_item.text() if id_item else None
 
        if action == eliminar and id_val:
            confirm = QMessageBox.question(self.parent, "Eliminar tablero",
                                           f"¿Eliminar el tablero '{id_val}'?")
            if confirm == QMessageBox.StandardButton.Yes:
                try:
                    from db_manager import connect_db
                    conn = connect_db(create_if_missing=False)
                    if conn:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM tableros WHERE id = ?", (id_val,))
                        conn.commit()
                        conn.close()
                        print(f"[ELIMINADO] Tablero {id_val}")
                except Exception as e:
                    print(f"Error al eliminar: {e}")
                self.parent.recargarVistas()
 
        elif action == editar and id_val:
            self.mostrarFormularioTablero(
                datos_existentes=[id_val] + [tabla.item(fila, c).text() if tabla.item(fila, c) else "" for c in range(1, tabla.columnCount())],
                fila_idx=fila
            )
 
        elif action == ver_circuitos and id_val:
            # Leer circuitos directamente desde la BD
            try:
                from db_manager import connect_db
                conn = connect_db()
                if conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM tableros WHERE id = ?", (id_val,))
                    row = cur.fetchone()
                    conn.close()
                    if row:
                        # Cargar circuitos por separado desde la tabla circuitos
                        circuitos = self.circuito_manager.cargar_circuitos_de_tablero(id_val)
                        if not circuitos:
                            circuitos = None
                        try:
                            num = int(row[6]) if row[6] else 42
                        except Exception:
                            num = 42
                        modelo_val = row[7] or ""
                        self.abrirVentanaCircuitosDesdeMenu(id_val, modelo_val, circuitos, num, row)
            except Exception as e:
                print(f"Error al leer circuitos: {e}")

        elif diagrama_unifilar is not None and action == diagrama_unifilar and id_val:
            # Abrir el unifilar mostrando SOLO este tablero y su subárbol
            nombre_tablero = tabla.item(fila, 1).text() if tabla.item(fila, 1) else id_val
            try:
                from unifilar import VentanaUnifilar
                # Se guarda en self para que no se destruya al salir del método
                self.ventana_unifilar = VentanaUnifilar(
                    tablero_id=id_val,
                    tablero_nombre=nombre_tablero,
                    parent=self.parent
                )
                self.ventana_unifilar.show()
            except Exception as e:
                print(f"Error al abrir diagrama unifilar: {e}")
                QMessageBox.critical(
                    self.parent, "Error",
                    f"No se pudo abrir el diagrama unifilar:\n{e}"
                )

    # ---------------- visualizar circuitos ----------------
    def abrirVentanaCircuitosDesdeMenu(self, id_tablero, modelo, circuitos, num_circuitos=42, row=None):
        if not circuitos:
            QMessageBox.information(
                self.parent,
                "Sin circuitos",
                f"El tablero '{id_tablero}' no tiene circuitos registrados.\n\n"
                f"Puedes agregarlos editando el tablero."
            )
            return
 
        # Construir tablero_data
        if row is not None:
            # Datos desde la BD
            tablero_data = {
                "id": row[0],
                "nombre": row[1] or "",
                "ubicacion": row[2] or "",
                "corriente": row[3] or "",
                "tension": row[4] or "",
                "tipo": row[5] or "",
                "marca": row[7] or modelo
            }
        elif hasattr(self.parent, 'tabla_tableros'):
            # Datos desde la tabla antigua
            tabla = self.parent.tabla_tableros
            fila = None
            for i in range(tabla.rowCount()):
                item_id = tabla.item(i, 0)
                if item_id and item_id.text() == id_tablero:
                    fila = i
                    break
            if fila is None:
                QMessageBox.warning(self.parent, "Error", "No se encontró el tablero.")
                return
            tablero_data = {
                "id":        tabla.item(fila, 0).text(),
                "nombre":    tabla.item(fila, 1).text() if tabla.item(fila, 1) else "",
                "ubicacion": tabla.item(fila, 2).text() if tabla.item(fila, 2) else "",
                "corriente": tabla.item(fila, 3).text() if tabla.item(fila, 3) else "",
                "tension":   tabla.item(fila, 4).text() if tabla.item(fila, 4) else "",
                "tipo":      tabla.item(fila, 5).text() if tabla.item(fila, 5) else "",
                "marca":     tabla.item(fila, 7).text() if tabla.item(fila, 7) else ""
            }
        else:
            tablero_data = {"id": id_tablero, "marca": modelo}
 
        self.vista_tablero = VistaTableroWidget(circuitos, num_circuitos, tablero_data)
        self.vista_tablero.show()
 
    # ---------------- cargar desde DB ----------------
    def cargarTablerosDesdeDB(self):
        """Carga los tableros desde SQLite (modo antiguo, con tabla_tableros)."""
        if not hasattr(self.parent, 'tabla_tableros'):
            return  # En modo VistaGrupos no hace falta
        try:
            registros = obtener_datos("tableros")
 
            tabla = self.parent.tabla_tableros
            tabla.setRowCount(0)
 
            for fila_db in registros:
                fila = tabla.rowCount()
                tabla.insertRow(fila)
 
                item_id = QTableWidgetItem(str(fila_db[0]))
                item_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
 
                # Cargar circuitos del tablero desde la tabla circuitos (ya no vienen en el row)
                try:
                    circuitos = self.circuito_manager.cargar_circuitos_de_tablero(fila_db[0])
                except Exception as e:
                    print(f"[ERROR] No se pudieron cargar circuitos del tablero {fila_db[0]}: {e}")
                    circuitos = []
 
                item_id.setData(Qt.ItemDataRole.UserRole, circuitos)
                tabla.setItem(fila, 0, item_id)
 
                for col in range(1, 10):
                    valor = fila_db[col]
                    item = QTableWidgetItem(str(valor) if valor is not None else "")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    tabla.setItem(fila, col, item)
 
            print(f"[CARGA] {len(registros)} Tableros cargados desde la BD.")
 
        except Exception as e:
            print(f"[ERROR] No se pudieron cargar los tableros: {e}")
 