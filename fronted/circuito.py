# circuitos.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QMessageBox, QMenu,
    QRadioButton, QButtonGroup, QStackedWidget, QWidget, QGroupBox
)
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QAction
from db_manager import connect_db

class CircuitoManager:
    """
    Maneja la persistencia y consultas de circuitos.
    Mismo patrón que TableroManager y TransformadorManager.
    """
    def __init__(self, parent=None):
        self.parent = parent  # referencia a la ventana que lo usa (opcional)
 
    # ---------------- persistencia ----------------
    def guardar_circuitos_de_tablero(self, tablero_id, circuitos):
        """
        Reemplaza todos los circuitos de un tablero.
        `circuitos` es una lista de dicts con claves de la tabla circuitos
        (sin id ni tablero_id). Los espacios libres no se guardan a menos que
        el dict traiga 'guardar_libre': True.
        """
        try:
            conn = connect_db(create_if_missing=True)
            cur = conn.cursor()
            cur.execute("DELETE FROM circuitos WHERE tablero_id = ?", (tablero_id,))
 
            for c in circuitos:
                if not c:
                    continue
                datos = {
                    "tablero_id": tablero_id,
                    "espacio_inicio": c["espacio_inicio"],
                    "polos": c["polos"],
                    "tipo_carga": c["tipo_carga"],
                    "nombre": c.get("nombre"),
                    "descripcion": c.get("descripcion"),
                    "amperaje_a": c.get("amperaje_a"),
                    "capacidad_int_ka": c.get("capacidad_int_ka"),
                    "calibre_fase": c.get("calibre_fase"),
                    "calibre_neutro": c.get("calibre_neutro"),
                    "calibre_tierra": c.get("calibre_tierra"),
                    "num_fase": c.get("num_fase"),
                    "aislamiento": c.get("aislamiento"),
                    "material": c.get("material", "cobre"),
                    "tuberia_mm": c.get("tuberia_mm"),
                    "longitud_m": c.get("longitud_m"),
                    "caida_pct": c.get("caida_pct"),
                    "fase_asignada": c.get("fase_asignada"),
                    "carga_w": c.get("carga_w"),
                    "factor_potencia": c.get("factor_potencia"),
                    "factor_demanda": c.get("factor_demanda"),
                    "tension_v": c.get("tension_v"),
                    "corriente_a": c.get("corriente_a"),
                    "tablero_hijo_id": c.get("tablero_hijo_id"),
                    "transformador_hijo_id": c.get("transformador_hijo_id"),
                    "datos_especificos": c.get("datos_especificos"),
                    "origen_datos": c.get("origen_datos", "inventario"),
                    "cumple_nom": c.get("cumple_nom", 1),
                    "observaciones": c.get("observaciones"),
                }
                columnas = ", ".join(datos.keys())
                placeholders = ", ".join(["?"] * len(datos))
                valores = tuple(datos.values())
                cur.execute(
                    f"INSERT INTO circuitos ({columnas}) VALUES ({placeholders})",
                    valores
                )
            conn.commit()
            conn.close()
            print(f"[CIRCUITOS] Guardados {len(circuitos)} circuitos del tablero {tablero_id}")
        except Exception as e:
            print(f"[ERROR] No se pudieron guardar los circuitos: {e}")
            if self.parent:
                QMessageBox.critical(self.parent, "Error",
                                     f"No se pudieron guardar los circuitos:\n{e}")
 
    def cargar_circuitos_de_tablero(self, tablero_id):
        """
        Devuelve los circuitos de un tablero como lista de diccionarios.
        Solo los espacios ocupados; los huecos los reconstruye la UI.
        """
        try:
            conn = connect_db()
            if conn is None:
                return []
            cur = conn.cursor()
            cur.execute("""
                SELECT id, espacio_inicio, polos, tipo_carga, nombre, descripcion,
                       amperaje_a, capacidad_int_ka,
                       calibre_fase, calibre_neutro, calibre_tierra, num_fase, aislamiento,
                       material,
                       tuberia_mm, longitud_m, caida_pct,
                       fase_asignada, carga_w, factor_potencia, factor_demanda,
                       tension_v, corriente_a,
                       tablero_hijo_id, transformador_hijo_id,
                       datos_especificos, origen_datos, cumple_nom, observaciones
                FROM circuitos WHERE tablero_id = ? ORDER BY espacio_inicio
            """, (tablero_id,))
            cols = [d[0] for d in cur.description]
            resultado = [dict(zip(cols, row)) for row in cur.fetchall()]
            conn.close()
            print(f"[CIRCUITOS] Cargados {len(resultado)} circuitos del tablero {tablero_id}")
            return resultado
        except Exception as e:
            print(f"[ERROR] No se pudieron cargar los circuitos: {e}")
            return []
 
    # ---------------- consultas para combos del diálogo ----------------
    def tableros_disponibles_como_hijo(self, grupo_id, tablero_padre_id):
        """
        Tableros que pueden asignarse como hijo en un circuito del tablero padre.
        Filtros: mismo grupo o subgrupos + sin padre asignado + no es sí mismo.
        Devuelve [(id, nombre), ...] para alimentar un combo.
        """
        conn = connect_db()
        if conn is None:
            return []
        cur = conn.cursor()
        if grupo_id is None:
            cur.execute("""
                SELECT id, nombre FROM tableros
                WHERE grupo_id IS NULL
                  AND id != ?
                  AND id NOT IN (SELECT tablero_hijo_id FROM circuitos
                                 WHERE tablero_hijo_id IS NOT NULL)
                  AND id NOT IN (SELECT tablero_alimentado_id FROM transformadores
                                 WHERE tablero_alimentado_id IS NOT NULL)
                ORDER BY id
            """, (tablero_padre_id,))
        else:
            cur.execute("""
                WITH RECURSIVE subarbol(id) AS (
                    SELECT ?
                    UNION ALL
                    SELECT g.id FROM grupos g
                    JOIN subarbol s ON g.padre_id = s.id
                )
                SELECT t.id, t.nombre FROM tableros t
                WHERE t.grupo_id IN (SELECT id FROM subarbol)
                  AND t.id != ?
                  AND t.id NOT IN (SELECT tablero_hijo_id FROM circuitos
                                   WHERE tablero_hijo_id IS NOT NULL)
                  AND t.id NOT IN (SELECT tablero_alimentado_id FROM transformadores
                                   WHERE tablero_alimentado_id IS NOT NULL)
                ORDER BY t.id
            """, (grupo_id, tablero_padre_id))
        rows = cur.fetchall()
        conn.close()
        return rows
 
    def transformadores_disponibles_como_hijo(self, grupo_id):
        """
        Transformadores que pueden asignarse como hijo de un circuito (caso raro,
        transformadores elevadores o de aislamiento).
        """
        conn = connect_db()
        if conn is None:
            return []
        cur = conn.cursor()
        if grupo_id is None:
            cur.execute("""
                SELECT id, ubicacion FROM transformadores
                WHERE grupo_id IS NULL
                  AND id NOT IN (SELECT transformador_hijo_id FROM circuitos
                                 WHERE transformador_hijo_id IS NOT NULL)
                ORDER BY id
            """)
        else:
            cur.execute("""
                WITH RECURSIVE subarbol(id) AS (
                    SELECT ?
                    UNION ALL
                    SELECT g.id FROM grupos g
                    JOIN subarbol s ON g.padre_id = s.id
                )
                SELECT t.id, t.ubicacion FROM transformadores t
                WHERE t.grupo_id IN (SELECT id FROM subarbol)
                  AND t.id NOT IN (SELECT transformador_hijo_id FROM circuitos
                                   WHERE transformador_hijo_id IS NOT NULL)
                ORDER BY t.id
            """, (grupo_id,))
        rows = cur.fetchall()
        conn.close()
        return rows
 
# Tipos de carga soportados 
TIPOS_CARGA = [
    ("carga",          "Carga general (alumbrado, contactos, equipo)"),
    ("motor",          "Motor individual"),
    ("elevador",       "Elevador"),
    ("aa",             "Aire acondicionado"),
    ("bomba_incendio", "Bomba contra incendio"),
]
 
class VentanaCircuitos(QDialog):
    def __init__(self, num_espacios=24, tablero_id=None, grupo_id=None, circuitos_iniciales=None):
        super().__init__()
        self.setWindowTitle("Circuitos del tablero")
        self.num_espacios = num_espacios
        self.tablero_id = tablero_id
        self.grupo_id = grupo_id
 
        # self.espacios[i] guarda el dict del circuito que ocupa el espacio i+1.
        # Los espacios "continuación" (de bifásico/trifásico) apuntan al inicio.
        self.espacios = [None] * num_espacios
 
        if circuitos_iniciales:
            self._cargar_circuitos_existentes(circuitos_iniciales)
 
        self.layout = QVBoxLayout(self)
        self.grid = QGridLayout()
        self.layout.addLayout(self.grid)
 
        self._crear_botones_espacios()
        self._actualizar_vista()
 
        btn_guardar = QPushButton("Guardar")
        btn_guardar.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 6px;")
        btn_guardar.clicked.connect(self.accept)
        self.layout.addWidget(btn_guardar)
 
    # ────────────────────────────────────────────────────────────────
    # CARGA INICIAL (si venimos editando un tablero existente)
    # ────────────────────────────────────────────────────────────────
    def _cargar_circuitos_existentes(self, circuitos: list):
        """
        Recibe lista de dicts (formato de cargar_circuitos_de_tablero).
        Llena self.espacios reconstruyendo los espacios ocupados por
        circuitos bifásicos/trifásicos.
        """
        for c in circuitos:
            inicio = c["espacio_inicio"] - 1  # base 0
            polos = c["polos"]
            # El espacio inicial guarda el dict completo
            self.espacios[inicio] = dict(c)
            # Los espacios de continuación guardan una marca con 'inicio'
            for i in range(1, polos):
                pos = inicio + i * 2
                if pos < self.num_espacios:
                    self.espacios[pos] = {
                        "nombre": None,
                        "_continuacion_de": inicio,
                    }
 
    # ────────────────────────────────────────────────────────────────
    # OBTENER CIRCUITOS PARA GUARDAR (lo lee el TableroManager)
    # ────────────────────────────────────────────────────────────────
    def obtener_circuitos_para_guardar(self) -> list:
        """
        Devuelve solo los espacios que son INICIO de circuito (no continuaciones,
        no huecos) listos para enviarse a guardar_circuitos_de_tablero().
        """
        salida = []
        for i, data in enumerate(self.espacios):
            if not data:
                continue
            if data.get("_continuacion_de") is not None:
                continue
            # Es el inicio de un circuito real
            d = dict(data)
            d["espacio_inicio"] = i + 1  # base 1
            salida.append(d)
        return salida
 
    # ────────────────────────────────────────────────────────────────
    # CUADRÍCULA DE ESPACIOS
    # ────────────────────────────────────────────────────────────────
    def _crear_botones_espacios(self):
        columnas = 2
        for i in range(self.num_espacios):
            btn = QPushButton(f"{i+1}")
            btn.setFixedSize(220, 40)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, idx=i: self._menu_contextual(idx, pos)
            )
            btn.clicked.connect(lambda _, idx=i: self._click_espacio(idx))
            self.grid.addWidget(btn, i // columnas, i % columnas)
 
    def _click_espacio(self, idx):
        """Si está vacío → abrir diálogo de agregar. Si ocupado → mostrar info."""
        data = self.espacios[idx]
        if data is None:
            self._dialogo_agregar(idx)
        elif data.get("_continuacion_de") is not None:
            base = data["_continuacion_de"]
            QMessageBox.information(
                self, "Espacio ocupado",
                f"Este espacio es la continuación del circuito que inicia en "
                f"el espacio {base + 1}."
            )
        else:
            self._dialogo_editar(idx)
 
    def _menu_contextual(self, idx, pos: QPoint):
        data = self.espacios[idx]
        if not data:
            return
        # Si es continuación, redirigir al inicio
        base = data.get("_continuacion_de")
        if base is not None:
            idx = base
            data = self.espacios[idx]
            if not data:
                return
 
        menu = QMenu(self)
        editar = QAction("Editar circuito", self)
        eliminar = QAction("Eliminar circuito", self)
        editar.triggered.connect(lambda: self._dialogo_editar(idx))
        eliminar.triggered.connect(lambda: self._eliminar_circuito(idx))
        menu.addAction(editar)
        menu.addAction(eliminar)
 
        boton = self.grid.itemAt(idx).widget()
        menu.exec(boton.mapToGlobal(QPoint(boton.width(), 0)))
 
    # ────────────────────────────────────────────────────────────────
    # DIÁLOGO AGREGAR / EDITAR
    # ────────────────────────────────────────────────────────────────
    def _dialogo_agregar(self, idx):
        dlg = DialogoCircuito(
            parent=self,
            espacio=idx + 1,
            tablero_padre_id=self.tablero_id,
            grupo_id=self.grupo_id,
            num_espacios=self.num_espacios,
            datos_previos=None,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._guardar_desde_dialogo(idx, dlg.resultado)
 
    def _dialogo_editar(self, idx):
        data = self.espacios[idx]
        dlg = DialogoCircuito(
            parent=self,
            espacio=idx + 1,
            tablero_padre_id=self.tablero_id,
            grupo_id=self.grupo_id,
            num_espacios=self.num_espacios,
            datos_previos=data,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Primero limpiar el circuito viejo
            self._limpiar_espacios_de_circuito(idx, silent=True)
            self._guardar_desde_dialogo(idx, dlg.resultado)
 
    def _guardar_desde_dialogo(self, idx, resultado: dict):
        """Acomoda el resultado del diálogo en self.espacios."""
        polos = resultado["polos"]
        # Validar que hay espacios disponibles
        indices = [idx + i * 2 for i in range(polos)]
        if any(p >= self.num_espacios for p in indices):
            QMessageBox.warning(
                self, "Sin espacio",
                "No hay espacio suficiente hacia abajo para este interruptor."
            )
            return
        if any(self.espacios[p] for p in indices):
            QMessageBox.warning(
                self, "Espacios ocupados",
                "Algunos espacios necesarios ya están ocupados."
            )
            return
 
        # Colocar el dict completo en el inicio
        self.espacios[idx] = resultado
        # Marcar continuaciones
        for i in range(1, polos):
            pos = idx + i * 2
            self.espacios[pos] = {
                "nombre": None,
                "_continuacion_de": idx,
            }
        self._actualizar_vista()
 
    def _eliminar_circuito(self, idx):
        resp = QMessageBox.question(
            self, "Eliminar",
            "¿Eliminar este circuito?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self._limpiar_espacios_de_circuito(idx)
 
    def _limpiar_espacios_de_circuito(self, idx, silent=False):
        data = self.espacios[idx]
        if not data:
            return
        polos = data.get("polos", 1)
        for i in range(polos):
            pos = idx + i * 2
            if pos < self.num_espacios:
                self.espacios[pos] = None
        if not silent:
            self._actualizar_vista()
        else:
            # Aún así refrescar al final (lo hace _guardar_desde_dialogo)
            pass
 
    # ────────────────────────────────────────────────────────────────
    # PINTAR LOS BOTONES SEGÚN ESTADO
    # ────────────────────────────────────────────────────────────────
    def _actualizar_vista(self):
        for i in range(self.num_espacios):
            btn = self.grid.itemAt(i).widget()
            data = self.espacios[i]
 
            if data is None:
                btn.setStyleSheet(
                    "background-color: #d3d3d3; border: 1px solid gray; color: black;"
                )
                btn.setText(f"{i + 1}")
                continue
 
            if data.get("_continuacion_de") is not None:
                # Espacio continuación de bifásico/trifásico
                btn.setStyleSheet(
                    "background-color: #6A95C2; border: 1px solid black; color: white;"
                )
                btn.setText(f"{i + 1}\n│")
                continue
 
            # Espacio inicio de un circuito real
            tipo = data.get("tipo_carga", "carga")
            nombre = data.get("nombre", "Sin nombre")
            color = self._color_por_tipo(tipo)
            btn.setStyleSheet(
                f"background-color: {color}; border: 1px solid black; color: white;"
            )
            etiqueta_tipo = self._etiqueta_corta_tipo(tipo)
            btn.setText(f"{i + 1}  [{etiqueta_tipo}]\n{nombre}")
 
    @staticmethod
    def _color_por_tipo(tipo: str) -> str:
        return {
            "tablero":        "#1565C0",  # azul
            "carga":          "#4682B4",  # azul acero
            "motor":          "#8E24AA",  # morado
            "elevador":       "#6D4C41",  # café
            "aa":             "#00897B",  # verde agua
            "bomba_incendio": "#C62828",  # rojo
            "transformador":  "#EF6C00",  # naranja
            "libre":          "#9E9E9E",  # gris
        }.get(tipo, "#4682B4")
 
    @staticmethod
    def _etiqueta_corta_tipo(tipo: str) -> str:
        return {
            "tablero": "TAB",
            "carga": "CARGA",
            "motor": "MOT",
            "elevador": "ELEV",
            "aa": "A/A",
            "bomba_incendio": "BCI",
            "transformador": "TRF",
            "libre": "LIBRE",
        }.get(tipo, tipo.upper())
  
# ════════════════════════════════════════════════════════════════════
# DIÁLOGO DE CIRCUITO (selector de tipo + campos según tipo)
# ════════════════════════════════════════════════════════════════════
class DialogoCircuito(QDialog):
    """
    Diálogo unificado: primero selector de tipo, luego campos.
    Resultado en self.resultado (dict listo para self.espacios[idx]).
    """
 
    def __init__(self, parent, espacio, tablero_padre_id, grupo_id,
                 num_espacios, datos_previos=None):
        super().__init__(parent)
        self.setWindowTitle(f"Circuito — espacio {espacio}")
        self.setMinimumWidth(460)
        self.espacio = espacio
        self.tablero_padre_id = tablero_padre_id
        self.grupo_id = grupo_id
        self.num_espacios = num_espacios
        self.datos_previos = datos_previos
        self.resultado = None
 
        layout = QVBoxLayout(self)
 
        # ── Paso 1: tipo de uso del espacio ──
        gb_tipo = QGroupBox("Tipo de uso del espacio")
        v_tipo = QVBoxLayout(gb_tipo)
        self.grp_tipo = QButtonGroup(self)
 
        self.rb_tablero = QRadioButton("Alimenta a un tablero existente")
        self.rb_carga = QRadioButton("Es una carga")
        self.rb_transformador = QRadioButton("Alimenta a un transformador")
 
        for rb in (self.rb_tablero, self.rb_carga, self.rb_transformador):
            self.grp_tipo.addButton(rb)
            v_tipo.addWidget(rb)
 
        self.rb_carga.setChecked(True)  # default
        layout.addWidget(gb_tipo)
 
        # ── Paso 2: stacked widget con los campos según el tipo ──
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
 
        self.pg_tablero = self._pagina_tablero()
        self.pg_carga = self._pagina_carga()
        self.pg_transformador = self._pagina_transformador()
 
        self.stack.addWidget(self.pg_tablero)
        self.stack.addWidget(self.pg_carga)
        self.stack.addWidget(self.pg_transformador)
 
        # Conectar radios → cambio de página
        self.rb_tablero.toggled.connect(
            lambda checked: checked and self._on_tipo_cambio("tablero")
        )
        self.rb_carga.toggled.connect(
            lambda checked: checked and self._on_tipo_cambio("carga")
        )
        self.rb_transformador.toggled.connect(
            lambda checked: checked and self._on_tipo_cambio("transformador")
        )
 
        # ── Paso 3: bloque ÚNICO de datos eléctricos del circuito ──
        # (visible siempre excepto cuando se elige "Libre")
        self.gb_datos_electricos = QGroupBox("Datos eléctricos del circuito")
        gb_layout = QVBoxLayout(self.gb_datos_electricos)
        gb_layout.addLayout(self._campos_electricos_comunes())
        layout.addWidget(self.gb_datos_electricos)
 
        # ── Botones de acción ──
        botones = QHBoxLayout()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        btn_guardar = QPushButton("Guardar")
        btn_guardar.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        btn_guardar.clicked.connect(self._on_guardar)
        botones.addStretch()
        botones.addWidget(btn_cancelar)
        botones.addWidget(btn_guardar)
        layout.addLayout(botones)
 
        # Si venimos editando, precargar
        if datos_previos:
            self._precargar(datos_previos)
        else:
            # Sincronizar estado inicial con el radio por default (carga)
            self._on_tipo_cambio("carga")
 
    # ── Campos comunes (polos, amperaje, calibres) ──
    def _campos_electricos_comunes(self) -> QFormLayout:
        """Devuelve un QFormLayout con los campos comunes. Los widgets quedan
        accesibles como atributos de self para que el caller los lea."""
        form = QFormLayout()
 
        # Listas reutilizables (de las tablas NOM del motor de cálculos)
        # Calibres en orden ascendente. Los 18 y 16 AWG existen solo a 90°C y casi
        # nunca se usan en instalaciones eléctricas, así que no se incluyen.
        CALIBRES_NOM = [
            "14 AWG", "12 AWG", "10 AWG", "8 AWG", "6 AWG",
            "4 AWG", "3 AWG", "2 AWG", "1 AWG",
            "1/0 AWG", "2/0 AWG", "3/0 AWG", "4/0 AWG",
            "250 KCM", "300 KCM", "350 KCM", "400 KCM",
            "500 KCM", "600 KCM", "700 KCM", "750 KCM",
            "800 KCM", "900 KCM", "1000 KCM",
            "1250 KCM", "1500 KCM", "1750 KCM", "2000 KCM",
        ]
        # Tuberías estándar NOM/NEC 358.2 — diámetros métricos oficiales
        TUBERIAS_NOM = [
            '16 mm (1/2")',
            '21 mm (3/4")',
            '27 mm (1")',
            '35 mm (1-1/4")',
            '41 mm (1-1/2")',
            '53 mm (2")',
            '63 mm (2-1/2")',
            '78 mm (3")',
            '91 mm (3-1/2")',
            '103 mm (4")',
            '129 mm (5")',
            '155 mm (6")',
        ]
 
        self.cb_polos = QComboBox()
        self.cb_polos.addItems(["1 (Monofásico)", "2 (Bifásico)", "3 (Trifásico)"])
        form.addRow("Polos:", self.cb_polos)
 
        self.le_amperaje = QLineEdit()
        self.le_amperaje.setPlaceholderText("Ej. 30")
        form.addRow("Amperaje del ITM (A):", self.le_amperaje)
 
        self.le_ka = QLineEdit()
        self.le_ka.setPlaceholderText("Ej. 10")
        form.addRow("Capacidad interruptiva (kA):", self.le_ka)
 
        self.le_carga_w = QLineEdit()
        self.le_carga_w.setPlaceholderText("Watts conectados (opcional)")
        form.addRow("Carga (W):", self.le_carga_w)
 
        self.le_fp = QLineEdit()
        self.le_fp.setPlaceholderText("0.85, 0.9, etc. (opcional)")
        form.addRow("Factor de potencia:", self.le_fp)
 
        # Material del conductor (cobre/aluminio)
        # Sin selección por default — si queda vacío, el motor del cuadro
        # asume cobre como sugerencia.
        self.cb_material = QComboBox()
        self.cb_material.addItem("— Seleccionar —", userData=None)
        self.cb_material.addItem("Cobre", userData="cobre")
        self.cb_material.addItem("Aluminio", userData="aluminio")
        form.addRow("Material conductor:", self.cb_material)
 
        # Calibres: dropdown con la lista NOM
        self.le_cal_f = QComboBox()
        self.le_cal_f.setEditable(False)
        self.le_cal_f.addItem("— Seleccionar —", userData=None)
        for cal in CALIBRES_NOM:
            self.le_cal_f.addItem(cal, userData=cal)
        form.addRow("Calibre fase:", self.le_cal_f)
 
        self.le_cal_n = QComboBox()
        self.le_cal_n.setEditable(False)
        self.le_cal_n.addItem("— Seleccionar —", userData=None)
        for cal in CALIBRES_NOM:
            self.le_cal_n.addItem(cal, userData=cal)
        form.addRow("Calibre neutro:", self.le_cal_n)
 
        self.le_cal_t = QComboBox()
        self.le_cal_t.setEditable(False)
        self.le_cal_t.addItem("— Seleccionar —", userData=None)
        for cal in CALIBRES_NOM:
            self.le_cal_t.addItem(cal, userData=cal)
        form.addRow("Calibre tierra:", self.le_cal_t)
 
        # Tubería: dropdown con tuberías estándar
        self.le_tuberia = QComboBox()
        self.le_tuberia.setEditable(False)
        self.le_tuberia.addItem("— Seleccionar —", userData=None)
        for tub in TUBERIAS_NOM:
            # userData = solo el valor numérico en mm (para guardar en BD como REAL)
            mm = float(tub.split(" ")[0])
            self.le_tuberia.addItem(tub, userData=mm)
        form.addRow("Tubería:", self.le_tuberia)
 
        self.le_longitud = QLineEdit()
        self.le_longitud.setPlaceholderText("Metros")
        form.addRow("Longitud (m):", self.le_longitud)
 
        return form
 
    def _on_tipo_cambio(self, tipo: str):
        """Cambia la página visible del stack y muestra/oculta el bloque eléctrico."""
        if tipo == "tablero":
            self.stack.setCurrentWidget(self.pg_tablero)
            # Para tablero, default trifásico
            self.cb_polos.setCurrentIndex(2)
        elif tipo == "carga":
            self.stack.setCurrentWidget(self.pg_carga)
        elif tipo == "transformador":
            self.stack.setCurrentWidget(self.pg_transformador)
            self.cb_polos.setCurrentIndex(2)
 
    # ── Página: Tablero existente ──
    def _pagina_tablero(self) -> QWidget:
 
        w = QWidget()
        v = QVBoxLayout(w)
 
        info = QLabel(
            "Selecciona el tablero que será alimentado desde este circuito.\n"
            "Solo aparecen tableros del mismo grupo (o subgrupos) que aún no tienen "
            "padre asignado."
        )
        info.setStyleSheet("color: #555; font-style: italic;")
        info.setWordWrap(True)
        v.addWidget(info)
 
        form = QFormLayout()
        self.cb_tablero_hijo = QComboBox()
        # Cargar opciones
        if self.tablero_padre_id:
            manager = CircuitoManager()
            opciones = manager.tableros_disponibles_como_hijo(
                self.grupo_id, self.tablero_padre_id
            )
            for tid, nom in opciones:
                texto = f"{tid} — {nom}" if nom else f"{tid}"
                self.cb_tablero_hijo.addItem(texto, userData=tid)
            if not opciones:
                self.cb_tablero_hijo.addItem("(no hay tableros disponibles)", userData=None)
        else:
            self.cb_tablero_hijo.addItem(
                "(guarda el tablero primero para asignar hijos)", userData=None
            )
        form.addRow("Tablero hijo:", self.cb_tablero_hijo)
 
        v.addLayout(form)
        v.addStretch()
        return w
 
    # ── Página: Carga ──
    def _pagina_carga(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
 
        form_top = QFormLayout()
        self.cb_tipo_carga = QComboBox()
        for clave, etiqueta in TIPOS_CARGA:
            self.cb_tipo_carga.addItem(etiqueta, userData=clave)
        form_top.addRow("Tipo de carga:", self.cb_tipo_carga)
 
        self.le_nombre = QLineEdit()
        self.le_nombre.setPlaceholderText("Ej. Alumbrado oficina, Bomba 1, Elevador A")
        form_top.addRow("Nombre / descripción:", self.le_nombre)
 
        v.addLayout(form_top)
        v.addStretch()
        return w
 
    # ── Página: Transformador ──
    def _pagina_transformador(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
 
        info = QLabel(
            "Selecciona el transformador alimentado desde este circuito.\n"
            "Caso raro (transformadores elevadores o de aislamiento)."
        )
        info.setStyleSheet("color: #555; font-style: italic;")
        info.setWordWrap(True)
        v.addWidget(info)
 
        form = QFormLayout()
        self.cb_trafo_hijo = QComboBox()
        manager = CircuitoManager()
        opciones = manager.transformadores_disponibles_como_hijo(self.grupo_id)
        for tid, ubic in opciones:
            self.cb_trafo_hijo.addItem(f"{tid} — {ubic}", userData=tid)
        if not opciones:
            self.cb_trafo_hijo.addItem("(no hay transformadores disponibles)", userData=None)
        form.addRow("Transformador:", self.cb_trafo_hijo)
        v.addLayout(form)
        v.addStretch()
        return w
 
    # ── Precargar datos al editar ──
    def _precargar(self, data: dict):
        tipo = data.get("tipo_carga", "carga")
        if tipo == "tablero":
            self.rb_tablero.setChecked(True)
            # Forzar el cambio de página por si el radio ya estaba marcado
            # (en ese caso .setChecked no dispara la señal toggled).
            self._on_tipo_cambio("tablero")
            tid = data.get("tablero_hijo_id")
            if tid:
                idx = self.cb_tablero_hijo.findData(tid)
                if idx < 0:
                    # El tablero asignado no está en el combo (porque ya está tomado).
                    # Lo agregamos manualmente para no perder la referencia.
                    self.cb_tablero_hijo.insertItem(0, f"{tid} (actual)", userData=tid)
                    idx = 0
                self.cb_tablero_hijo.setCurrentIndex(idx)
        elif tipo == "transformador":
            self.rb_transformador.setChecked(True)
            self._on_tipo_cambio("transformador")
            tid = data.get("transformador_hijo_id")
            if tid:
                idx = self.cb_trafo_hijo.findData(tid)
                if idx < 0:
                    self.cb_trafo_hijo.insertItem(0, f"{tid} (actual)", userData=tid)
                    idx = 0
                self.cb_trafo_hijo.setCurrentIndex(idx)
        else:
            self.rb_carga.setChecked(True)
            self._on_tipo_cambio("carga")
            # Tipo específico de carga: buscar por clave (no por índice fijo)
            tipo_actual = tipo or "carga"
            idx_tc = next(
                (i for i, (k, _) in enumerate(TIPOS_CARGA) if k == tipo_actual), 0
            )
            self.cb_tipo_carga.setCurrentIndex(idx_tc)
            self.le_nombre.setText(data.get("nombre") or "")
 
        # Campos comunes (siempre, para todos los tipos excepto "libre")
        polos = data.get("polos", 1)
        self.cb_polos.setCurrentIndex(polos - 1)
        if data.get("amperaje_a") is not None:
            self.le_amperaje.setText(str(data["amperaje_a"]))
        if data.get("capacidad_int_ka") is not None:
            self.le_ka.setText(str(data["capacidad_int_ka"]))
        if data.get("carga_w") is not None:
            self.le_carga_w.setText(str(data["carga_w"]))
        if data.get("factor_potencia") is not None:
            self.le_fp.setText(str(data["factor_potencia"]))
 
        # Material conductor (dropdown). Si no está guardado, queda en "— Seleccionar —".
        mat = data.get("material")
        if mat:
            idx_mat = self.cb_material.findData(str(mat).lower())
            if idx_mat < 0:
                idx_mat = 0
            self.cb_material.setCurrentIndex(idx_mat)
        else:
            self.cb_material.setCurrentIndex(0)  # "— Seleccionar —"
 
        # Calibres ahora son QComboBox, buscar por userData
        def _seleccionar_calibre(combo, valor):
            if not valor:
                combo.setCurrentIndex(0)  # "— Seleccionar —"
                return
            idx = combo.findData(valor)
            if idx < 0:
                # El calibre guardado no está en la lista. Lo agregamos.
                combo.addItem(valor, userData=valor)
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
 
        _seleccionar_calibre(self.le_cal_f, data.get("calibre_fase"))
        _seleccionar_calibre(self.le_cal_n, data.get("calibre_neutro"))
        _seleccionar_calibre(self.le_cal_t, data.get("calibre_tierra"))
 
        # Tubería (dropdown con valores mm)
        if data.get("tuberia_mm") is not None:
            try:
                mm_val = float(data["tuberia_mm"])
                idx_tub = self.le_tuberia.findData(mm_val)
                if idx_tub < 0:
                    # Si el valor guardado no coincide exacto con la lista, lo agregamos.
                    self.le_tuberia.addItem(f"{mm_val:g} mm (custom)", userData=mm_val)
                    idx_tub = self.le_tuberia.count() - 1
                self.le_tuberia.setCurrentIndex(idx_tub)
            except (ValueError, TypeError):
                self.le_tuberia.setCurrentIndex(0)
 
        if data.get("longitud_m") is not None:
            self.le_longitud.setText(str(data["longitud_m"]))
 
    # ── Validar y armar resultado ──
    def _on_guardar(self):
        try:
            polos = self.cb_polos.currentIndex() + 1
            amp = self._parse_float(self.le_amperaje.text(), "Amperaje del ITM", obligatorio=True)
            if amp is None:
                return
            ka = self._parse_float(self.le_ka.text(), "Capacidad interruptiva")
            # Tubería ahora es QComboBox: el userData ya es float en mm
            tub = self.le_tuberia.currentData()
            lon = self._parse_float(self.le_longitud.text(), "Longitud")
 
            base = {
                "polos": polos,
                "amperaje_a": amp,
                "capacidad_int_ka": ka,
                "carga_w": self._parse_float(self.le_carga_w.text(), "Carga (W)"),
                "factor_potencia": self._parse_float(self.le_fp.text(), "FP"),
                "material": self.cb_material.currentData(),
                "calibre_fase":   self.le_cal_f.currentData(),
                "calibre_neutro": self.le_cal_n.currentData(),
                "calibre_tierra": self.le_cal_t.currentData(),
                "tuberia_mm": tub,
                "longitud_m": lon,
                "origen_datos": "inventario",
            }
 
            if self.rb_tablero.isChecked():
                tid = self.cb_tablero_hijo.currentData()
                if not tid:
                    QMessageBox.warning(self, "Sin tablero",
                                        "No has seleccionado un tablero hijo válido.")
                    return
                base["tipo_carga"] = "tablero"
                base["tablero_hijo_id"] = tid
                # Guardar el NOMBRE del tablero hijo (no el ID). Lo leemos directo
                # de la BD para evitar parsear el texto del combo (que puede tener
                # formato "TAB002 — Nombre" o "TAB002 (actual)").
                nombre_tab = self._obtener_nombre_tablero(tid)
                base["nombre"] = nombre_tab or tid  # fallback al id si no tiene nombre
 
            elif self.rb_transformador.isChecked():
                tid = self.cb_trafo_hijo.currentData()
                if not tid:
                    QMessageBox.warning(self, "Sin transformador",
                                        "No has seleccionado un transformador válido.")
                    return
                base["tipo_carga"] = "transformador"
                base["transformador_hijo_id"] = tid
                # Los transformadores no tienen campo nombre (solo ID).
                base["nombre"] = tid
 
            else:  # carga
                base["tipo_carga"] = self.cb_tipo_carga.currentData()
                nombre = self.le_nombre.text().strip()
                if not nombre:
                    QMessageBox.warning(self, "Falta nombre",
                                        "Indica un nombre / descripción para la carga.")
                    return
                base["nombre"] = nombre
 
            self.resultado = base
            self.accept()
 
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Ocurrió un error:\n{e}")
 
    @staticmethod
    def _parse_float(texto: str, etiqueta: str, obligatorio=False):
        s = texto.strip()
        if not s:
            if obligatorio:
                QMessageBox.warning(None, "Dato obligatorio",
                                    f"El campo '{etiqueta}' es obligatorio.")
                return None
            return None
        try:
            # Acepta '30', '30.5', '30,5'
            return float(s.replace(",", "."))
        except ValueError:
            QMessageBox.warning(None, "Dato inválido",
                                f"El campo '{etiqueta}' debe ser numérico.")
            return None
 
    @staticmethod
    def _obtener_nombre_tablero(tablero_id: str) -> Optional[str]:
        """Consulta el nombre amigable de un tablero por su ID. Devuelve None
        si no existe o no tiene nombre asignado."""
        if not tablero_id:
            return None
        conn = connect_db()
        if conn is None:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT nombre FROM tableros WHERE id = ?", (tablero_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None
        except Exception:
            return None
        finally:
            conn.close()
        
# ────────────────────────────────────────────────────────────────────
# Prueba independiente
# ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
 
    app = QApplication(sys.argv)
    # Para probar sin BD real, pasamos tablero_id y grupo_id en None.
    # El combo de "tablero existente" saldrá vacío, pero se puede usar "Carga".
    ventana = VentanaCircuitos(num_espacios=24, tablero_id=None, grupo_id=None)
    ventana.show()
    sys.exit(app.exec())