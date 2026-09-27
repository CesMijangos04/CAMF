# cuadro_cargas.py
"""
Cuadro de cargas profesional según formato CC-01.
 
Componentes:
  - CuadroCargasManager: consultas BD + integración con motor de cálculo.
  - WidgetTablaCuadroCargas: QTableWidget con todas las columnas
    agrupadas y coloreadas por estado NOM.
  - VentanaCuadroCargas: QMainWindow con QTabWidget, una pestaña por tablero.
 
Orden de filas: numérico secuencial (1, 2, 3, 4...).
"""
 
from typing import Optional, Dict, List, Tuple
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QToolBar, QFileDialog, QMessageBox,
    QLabel, QFrame, QApplication, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QColor, QBrush, QAction, QPainter, QPageLayout, QPageSize, QPdfWriter, QPen
 
from db_manager import connect_db
import calculos_electricos as ce
 
# ════════════════════════════════════════════════════════════════════
# COLORES DE ESTADO
# ════════════════════════════════════════════════════════════════════
COLOR_OK    = QColor("#C8E6C9")  # verde suave
COLOR_WARN  = QColor("#FFF3CD")  # amarillo suave
COLOR_FAIL  = QColor("#F8D7DA")  # rojo suave
COLOR_LIBRE = QColor("#F0F0F0")  # gris suave
COLOR_HEADER_GROUP = QColor("#34495E")  # azul oscuro para encabezados de grupo
COLOR_HEADER_COL   = QColor("#5D7689")  # azul medio para columnas
COLOR_TOTAL_BG     = QColor("#FFEB99")  # amarillo claro para fila TOTAL
COLOR_ALIM_BG      = QColor("#FF6F69")  # rojo claro para alimentador principal
 
 
# ════════════════════════════════════════════════════════════════════
# HEADER PERSONALIZADO (estilo Excel: grupos arriba + títulos abajo)
# ════════════════════════════════════════════════════════════════════
class HeaderConGrupos(QHeaderView):
    """
    QHeaderView custom que pinta DOS zonas dentro del header nativo:
      - Zona superior (ALTO_GRUPO): nombre del grupo, mergeado sobre las
        columnas que pertenecen al grupo.
      - Zona inferior (ALTO_TITULO): título individual de cada columna.
 
    Al ser el header NATIVO de QTableWidget:
      - Permite arrastrar para redimensionar columnas (manija nativa).
      - Se mueve con el scroll horizontal automáticamente.
      - Queda fijo arriba con scroll vertical (comportamiento nativo).
      - Las celdas mergeadas se ajustan automáticamente cuando cambia
        el ancho de columnas (porque dependemos de sectionSize).
    """
    ALTO_GRUPO  = 48
    ALTO_TITULO = 56
 
    def __init__(self, columnas_def, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.columnas_def = columnas_def
        # Cache de columnas planas (en orden: idx -> (titulo, key, ancho))
        self._cols_planas = []
        for grupo, cols in columnas_def:
            for col in cols:
                self._cols_planas.append(col)
        # Cache: idx_col -> (nombre_grupo, idx_inicio_grupo, num_cols_grupo)
        self._mapa_grupos = []
        acumulado = 0
        for grupo_nombre, cols in columnas_def:
            n = len(cols)
            for _ in range(n):
                self._mapa_grupos.append((grupo_nombre, acumulado, n))
            acumulado += n
 
        self.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        # Eliminar el "hover highlight" molesto de las secciones
        self.setHighlightSections(False)
        self.setSectionsClickable(False)
        # Desactivar el seguimiento del mouse para que no haya repintado por hover
        self.setMouseTracking(False)
        # Eliminar el efecto de "sort indicator" hover
        self.setSortIndicatorShown(False)
        # Forzar que las secciones no respondan al mouse visualmente
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, False)
 
    def event(self, e):
        # Suprimir los eventos de hover que provocan repintado y "sombra".
        # No tocamos eventos de mouse press/release/move para no romper
        # el arrastre de columnas que es la funcionalidad nativa del header.
        from PyQt6.QtCore import QEvent
        if e.type() in (QEvent.Type.HoverEnter,
                        QEvent.Type.HoverLeave,
                        QEvent.Type.HoverMove,
                        QEvent.Type.Enter,
                        QEvent.Type.Leave):
            return True  # consumido, no se procesa más
        return super().event(e)
 
    def sizeHint(self):
        sh = super().sizeHint()
        sh.setHeight(self.ALTO_GRUPO + self.ALTO_TITULO)
        return sh
 
    def paintEvent(self, event):
        """
        Override completo del paintEvent del header.
        Aquí controlamos TODO el dibujado: primero pintamos los títulos de cada
        columna, después los grupos extendidos encima. Esto garantiza orden
        correcto y elimina cualquier sombra del fondo nativo de Qt.
        """
        painter = QPainter(self.viewport())
        try:
            ancho = self.viewport().width()
            alto = self.viewport().height()
 
            # PASO 1: pintar TODO el fondo del header con un color base
            # para borrar cualquier rastro nativo de Qt.
            painter.fillRect(0, 0, ancho, alto, QColor("#5D7689"))
 
            # PASO 2: pintar la franja superior del header (zona de grupos)
            # de color azul oscuro.
            painter.fillRect(0, 0, ancho, self.ALTO_GRUPO, QColor("#34495E"))
 
            # PASO 3: para cada columna, pintar su título individual (zona inferior)
            font_titulo = painter.font()
            font_titulo.setBold(True)
            font_titulo.setPointSize(8)
            painter.setFont(font_titulo)
            painter.setPen(QPen(QColor("white")))
 
            for col_idx in range(self.count()):
                x = self.sectionViewportPosition(col_idx)
                w = self.sectionSize(col_idx)
                if w <= 0:
                    continue
                rect_titulo = QRect(x, self.ALTO_GRUPO, w, self.ALTO_TITULO)
                # Texto del título
                if col_idx < len(self._cols_planas):
                    titulo = self._cols_planas[col_idx][0]
                    flags = int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap)
                    painter.drawText(rect_titulo.adjusted(2, 2, -2, -2), flags, titulo)
                # Borde derecho de la sección
                painter.setPen(QPen(QColor("#3a4a57"), 1))
                painter.drawLine(x + w - 1, self.ALTO_GRUPO,
                                  x + w - 1, self.ALTO_GRUPO + self.ALTO_TITULO)
                painter.setPen(QPen(QColor("white")))
 
            # PASO 4: pintar los nombres de los grupos (encima del fondo azul oscuro)
            font_grupo = painter.font()
            font_grupo.setBold(True)
            font_grupo.setPointSize(9)
            painter.setFont(font_grupo)
 
            col_idx = 0
            for grupo_nombre, cols in self.columnas_def:
                ncols_grupo = len(cols)
                if col_idx >= self.count():
                    break
                x_inicio = self.sectionViewportPosition(col_idx)
                ancho_total = sum(self.sectionSize(col_idx + i)
                                   for i in range(ncols_grupo)
                                   if col_idx + i < self.count())
                if ancho_total > 0:
                    rect_grupo = QRect(x_inicio, 0, ancho_total, self.ALTO_GRUPO)
                    # Borde derecho del grupo
                    painter.setPen(QPen(QColor("#1f2d3a"), 1))
                    painter.drawLine(x_inicio + ancho_total - 1, 0,
                                      x_inicio + ancho_total - 1, self.ALTO_GRUPO)
                    # Texto centrado
                    painter.setPen(QPen(QColor("white")))
                    flags = int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap)
                    painter.drawText(rect_grupo.adjusted(4, 2, -4, -2), flags, grupo_nombre)
                col_idx += ncols_grupo
        finally:
            painter.end()
 
 
# ════════════════════════════════════════════════════════════════════
# DEFINICIÓN DE COLUMNAS (agrupadas como en el CC-01)
# ════════════════════════════════════════════════════════════════════
# Cada tupla: (titulo_grupo, [(titulo_col, key, ancho), ...])
COLUMNAS = [
    ("IDENTIFICACIÓN", [
        ("Circuito",      "circuito_label",   75),
        ("Área / Aplicación", "area",         140),
    ]),
    ("POTENCIA ELÉCTRICA ACTIVA", [
        ("Watts",         "watts",            60),
        ("kW Inst.",      "kw",               60),
        ("F.D. (%)",      "factor_demanda",   55),
        ("kW Dem.",       "kw_dem",           60),
        ("kVA",           "kva",               55),
        ("Voltaje (V)",   "tension_v",        55),
    ]),
    ("CORRIENTE", [
        ("In (A)",        "In",               55),
        ("Ic (A)",        "Ic",               55),
    ]),
    ("INTERRUPTOR TERMOMAGNÉTICO", [
        ("1 POLO\n120/240 Vca", "itm_1polo",  65),
        ("2 POLOS\n120/240 Vca", "itm_2polo", 65),
        ("3 POLOS\n120/240 Vca", "itm_3polo", 65),
        ("kA",            "capacidad_int_ka", 38),
    ]),
    ("SISTEMA ELÉCTRICO", [
        ("Núm. Fases",    "num_fases",        55),
        ("Núm. Neutros",  "num_neutros",      55),
        ("Núm. Tierra",   "num_tierras",      55),
    ]),
    ("FACTORES NOM", [
        ("F. agrup.\n310-15(b)(3)(a)", "factor_agrup",  60),
        ("F. temp.\n310-15(b)(2)(a)",  "factor_temp",   60),
    ]),
    ("CONDUCTOR DEL CIRCUITO\nTabla 310-15(b)(16) NOM-001(2012)", [
        ("Material",      "material",         60),
        ("Cal. Fase",     "calibre_fase",     65),
        ("Cal. Neutro",   "calibre_neutro",   65),
    ]),
    ("CONDUCTOR DE PUESTA A TIERRA\nNOM 250-122", [
        ("Material T.",   "material_tierra",  65),
        ("Cal. Tierra",   "calibre_tierra",   65),
    ]),
    ("CAÍDA DE TENSIÓN\nTabla 9 NEC", [
        ("XL (Ω/km)",     "reactancia",       60),
        ("R (Ω/km)",      "resistencia",      60),
        ("L (m)",         "longitud_m",       55),
        ("% e",           "caida_pct",        50),
    ]),
    ("BALANCEO FASES EN WATTS", [
        ("A",             "fase_A_w",         65),
        ("B",             "fase_B_w",         65),
        ("C",             "fase_C_w",         65),
    ]),
    ("CANALIZACIÓN", [
        ("Cond. activos", "cond_activos",     55),
        ("Tubería (mm)",  "tuberia_mm",       65),
    ]),
    ("CUMPLIMIENTO NOM", [
        ("Estado",        "estado_simbolo",   55),
        ("Observaciones", "observaciones_nom", 200),
    ]),
]
 
 
def _todas_las_columnas() -> List[Tuple[str, str, int]]:
    """Aplana las columnas agrupadas en lista plana."""
    result = []
    for grupo, cols in COLUMNAS:
        for col in cols:
            result.append(col)
    return result
 
 
def _num_columnas_grupo(grupo_idx: int) -> int:
    return len(COLUMNAS[grupo_idx][1])
 
 
# ════════════════════════════════════════════════════════════════════
# MANAGER
# ════════════════════════════════════════════════════════════════════
class CuadroCargasManager:
    """Consultas a BD y armado de filas con cálculos aplicados."""
 
    def __init__(self, parent=None):
        self.parent = parent
 
    def grupo_tiene_cuadro(self, grupo_id: int, solo_directos: bool = True) -> bool:
        """
        ¿El grupo tiene al menos un tablero con circuitos guardados?
 
        - solo_directos=True (default): solo cuenta tableros que pertenecen
          DIRECTAMENTE a este grupo, no a subgrupos. Esto evita que el botón
          aparezca en grupos padre que solo contienen otros subgrupos.
        - solo_directos=False: incluye también los tableros de subgrupos
          (comportamiento recursivo original).
        """
        if grupo_id is None:
            return False
        ids_grupos = [grupo_id] if solo_directos else self._subarbol_grupo(grupo_id)
        if not ids_grupos:
            return False
        conn = connect_db()
        if conn is None:
            return False
        try:
            cur = conn.cursor()
            placeholders = ",".join("?" * len(ids_grupos))
            cur.execute(f"""
                SELECT COUNT(*) FROM circuitos c
                JOIN tableros t ON c.tablero_id = t.id
                WHERE t.grupo_id IN ({placeholders})
            """, ids_grupos)
            n = cur.fetchone()[0]
            return n > 0
        except Exception as e:
            print(f"[CUADRO] Error verificando grupo: {e}")
            return False
        finally:
            conn.close()
 
    def tableros_del_grupo(self, grupo_id: int, solo_directos: bool = True) -> List[Dict]:
        """
        Devuelve los tableros del grupo que tienen circuitos.
 
        - solo_directos=True (default): solo tableros del grupo directo.
        - solo_directos=False: incluye los de subgrupos también.
        """
        ids_grupos = [grupo_id] if solo_directos else self._subarbol_grupo(grupo_id)
        if not ids_grupos:
            return []
        conn = connect_db()
        if conn is None:
            return []
        try:
            cur = conn.cursor()
            placeholders = ",".join("?" * len(ids_grupos))
            cur.execute(f"""
                SELECT DISTINCT t.id, t.nombre, t.ubicacion, t.corriente_nominal, t.tension,
                       t.tipo, t.num_circuitos, t.marca, t.fecha_instalacion,
                       t.comentarios, t.grupo_id
                FROM tableros t
                WHERE t.grupo_id IN ({placeholders})
                  AND EXISTS (SELECT 1 FROM circuitos c WHERE c.tablero_id = t.id)
                ORDER BY t.id
            """, ids_grupos)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception as e:
            print(f"[CUADRO] Error cargando tableros: {e}")
            return []
        finally:
            conn.close()
 
    def circuitos_del_tablero(self, tablero_id: str) -> List[Dict]:
        conn = connect_db()
        if conn is None:
            return []
        try:
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
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception as e:
            print(f"[CUADRO] Error cargando circuitos: {e}")
            return []
        finally:
            conn.close()
 
    def _subarbol_grupo(self, grupo_id: int) -> List[int]:
        if grupo_id is None:
            return []
        conn = connect_db()
        if conn is None:
            return []
        try:
            cur = conn.cursor()
            cur.execute("""
                WITH RECURSIVE subarbol(id) AS (
                    SELECT ?
                    UNION ALL
                    SELECT g.id FROM grupos g
                    JOIN subarbol s ON g.padre_id = s.id
                )
                SELECT id FROM subarbol
            """, (grupo_id,))
            return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
 
    def circuito_padre_del_tablero(self, tablero_id: str) -> Optional[Dict]:
        """
        Encuentra el circuito en otro tablero que alimenta a éste.
        Es decir, el ITM principal de este tablero.
        Devuelve None si el tablero es raíz (sin padre).
        """
        conn = connect_db()
        if conn is None:
            return None
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, tablero_id, espacio_inicio, polos, tipo_carga, nombre,
                       amperaje_a, capacidad_int_ka,
                       calibre_fase, calibre_neutro, calibre_tierra,
                       material,
                       tuberia_mm, longitud_m, caida_pct,
                       carga_w, factor_potencia, tension_v,
                       tablero_hijo_id
                FROM circuitos
                WHERE tablero_hijo_id = ?
                LIMIT 1
            """, (tablero_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        except Exception as e:
            print(f"[CUADRO] Error buscando padre de {tablero_id}: {e}")
            return None
        finally:
            conn.close()
 
    def construir_filas_tablero(self, tablero: Dict) -> Tuple[List[Dict], Dict, Dict]:
        """
        Devuelve:
          - filas: lista en orden SECUENCIAL (1, 2, 3, 4...) con circuitos y libres
          - total_fila: fila TOTAL con sumas
          - alimentador: bloque del alimentador principal con balance
        """
        circuitos = self.circuitos_del_tablero(tablero["id"])
        tension_tab = self._parse_tension(tablero.get("tension"))
 
        try:
            total_esp = int(tablero.get("num_circuitos") or 0)
        except (ValueError, TypeError):
            total_esp = 0
 
        # Mapear espacio físico → (circuito, es_primer_espacio)
        # Para circuitos multipolo, el primer espacio es donde se genera la fila;
        # los siguientes son "continuaciones" y se omiten en la tabla.
        espacio_a_circuito = {}
        for c in circuitos:
            inicio = c.get("espacio_inicio", 0)
            polos = int(c.get("polos") or 1)
            for k in range(polos):
                esp = inicio + k * 2
                espacio_a_circuito[esp] = (c, k == 0)
 
        # Si total_esp no está definido, usar el máximo espacio ocupado
        if total_esp <= 0 and espacio_a_circuito:
            total_esp = max(espacio_a_circuito.keys())
 
        # Construir filas en orden secuencial (1, 2, 3, ...)
        filas = []
        circuitos_para_balance = []
        circuitos_para_alim = []
 
        for esp in range(1, total_esp + 1):
            if esp in espacio_a_circuito:
                c, es_primero = espacio_a_circuito[esp]
                if not es_primero:
                    continue  # continuación de un circuito multipolo: ya representado
 
                fila = self._construir_fila_circuito(c, tension_tab)
                filas.append(fila)
                circuitos_para_balance.append({
                    "watts": fila.get("watts") or 0,
                    "fase_asignada": fila.get("fase_asignada"),
                })
                circuitos_para_alim.append({"watts": fila.get("watts") or 0})
            else:
                # Espacio libre
                filas.append(self._construir_fila_libre(esp))
 
        # ── ALIMENTADOR PRINCIPAL ─────────────────────────────────────
        # Toma los datos del circuito padre (el que alimenta este tablero
        # desde otro tablero) y los pone en la fila final.
        # Si no hay padre (tablero raíz), calcula el alimentador desde la suma.
        fps = [c.get("factor_potencia") for c in circuitos if c.get("factor_potencia")]
        fp_prom = sum(fps) / len(fps) if fps else 0.9
 
        alim_calc = ce.calcular_alimentador_principal(
            circuitos_para_alim, tension_v=tension_tab, fp_promedio=fp_prom
        )
        balance = ce.calcular_balance_fases(circuitos_para_balance)
 
        # Buscar el circuito que alimenta a este tablero (el ITM principal)
        circuito_padre = self.circuito_padre_del_tablero(tablero["id"])
 
        if circuito_padre:
            # Tomar los datos REALES del padre
            polos_padre = int(circuito_padre.get("polos") or 3)
            amperaje_padre = circuito_padre.get("amperaje_a")
            ka_padre = circuito_padre.get("capacidad_int_ka")
            calibre_f_padre = circuito_padre.get("calibre_fase")
            calibre_n_padre = circuito_padre.get("calibre_neutro")
            calibre_t_padre = circuito_padre.get("calibre_tierra")
            tuberia_padre = circuito_padre.get("tuberia_mm")
            longitud_padre = circuito_padre.get("longitud_m")
            tension_padre = circuito_padre.get("tension_v") or tension_tab
            material_padre = (circuito_padre.get("material") or "cobre").lower()
 
            # Etiquetas del interruptor según polos
            itm_1polo = itm_2polo = itm_3polo = ""
            if amperaje_padre:
                amp_int = int(float(amperaje_padre))
                if polos_padre == 1:
                    itm_1polo = f"1P-{amp_int}"
                elif polos_padre == 2:
                    itm_2polo = f"2P-{amp_int}"
                elif polos_padre == 3:
                    itm_3polo = f"3P-{amp_int}"
 
            # Calcular caída del propio alimentador (con sus calibres)
            caida_alim = None
            if alim_calc["In"] and calibre_f_padre and longitud_padre:
                caida_alim = ce.caida_tension_porcentual(
                    alim_calc["In"], longitud_padre, calibre_f_padre,
                    3, tension_padre, material_padre, fp_prom
                )
 
            # Resistencia y reactancia del calibre padre, según material (Cu o Al)
            R_padre = XL_padre = None
            if calibre_f_padre:
                cal_key = ce._normalizar_calibre(calibre_f_padre)
                if cal_key in ce.RESISTENCIA_REACTANCIA:
                    if material_padre == "aluminio":
                        R_padre = ce.RESISTENCIA_REACTANCIA[cal_key][2]
                        XL_padre = ce.RESISTENCIA_REACTANCIA[cal_key][3]
                    else:  # cobre
                        R_padre = ce.RESISTENCIA_REACTANCIA[cal_key][0]
                        XL_padre = ce.RESISTENCIA_REACTANCIA[cal_key][1]
 
            alimentador = {
                "circuito_label": "ALIMENTADOR PRINCIPAL",
                "area": "",
                "watts": alim_calc["watts"],
                "kw":    alim_calc["kw"],
                "factor_demanda": 100,
                "kw_dem": alim_calc["kw"],
                "kva":   alim_calc["kva"],
                "tension_v": tension_padre,
                "In":    alim_calc["In"],
                "Ic":    alim_calc["Ic"],
                "itm_1polo": itm_1polo,
                "itm_2polo": itm_2polo,
                "itm_3polo": itm_3polo,
                "capacidad_int_ka": ka_padre,
                "num_fases":   f"{polos_padre}F",
                "num_neutros": "1N",
                "num_tierras": "1T",
                "factor_temp":  alim_calc.get("factor_temp"),
                "factor_agrup": 1.0,
                "material":         material_padre.capitalize(),
                "material_tierra":  material_padre.capitalize(),
                "calibre_fase":   calibre_f_padre,
                "calibre_neutro": calibre_n_padre,
                "calibre_tierra": calibre_t_padre,
                "reactancia":  XL_padre,
                "resistencia": R_padre,
                "longitud_m":  longitud_padre,
                "caida_pct":   caida_alim,
                "tuberia_mm":  tuberia_padre,
                "cond_activos": ce.conductores_activos_circuito(polos_padre),
                "fase_A_w": balance.get("A"),
                "fase_B_w": balance.get("B"),
                "fase_C_w": balance.get("C"),
                "fp_prom": fp_prom,
                "balance": balance,
            }
        else:
            # Tablero sin padre eléctrico: solo mostramos los totales
            alimentador = {
                "circuito_label": "ALIMENTADOR PRINCIPAL",
                "area": "",
                "watts": alim_calc["watts"],
                "kw":    alim_calc["kw"],
                "factor_demanda": 100,
                "kw_dem": alim_calc["kw"],
                "kva":   alim_calc["kva"],
                "tension_v": alim_calc["tension_v"],
                "In":    alim_calc["In"],
                "Ic":    alim_calc["Ic"],
                "fase_A_w": balance.get("A"),
                "fase_B_w": balance.get("B"),
                "fase_C_w": balance.get("C"),
                "factor_temp":  alim_calc.get("factor_temp"),
                "factor_agrup": 1.0,
                # Tablero raíz sin padre: no hay circuito alimentador del cual
                # heredar el material. Se asume Cobre por default.
                "material":        "Cobre",
                "material_tierra": "Cobre",
                "fp_prom": fp_prom,
                "balance": balance,
            }
 
        # Ya no devolvemos total_fila por separado (era duplicado del alimentador).
        # Se devuelve None en su lugar para mantener firma del método.
        return filas, None, alimentador
 
    def _construir_fila_circuito(self, c: Dict, tension_tab: float) -> Dict:
        """Genera una fila de la tabla a partir de un circuito guardado."""
        polos = int(c.get("polos") or 1)
        inicio = c.get("espacio_inicio", 0)
        espacios = [inicio + k * 2 for k in range(polos)]
        circuito_label = "Circuito " + ",".join(str(e) for e in espacios)
 
        # Tensión por defecto si no la tiene
        if not c.get("tension_v"):
            c["tension_v"] = 127 if polos == 1 else tension_tab
 
        calc = ce.calcular_circuito_completo(c, tension_default=tension_tab)
        fase = ce.asignar_fase_secuencial(inicio, polos)
 
        # Repartir watts por fase
        fase_A_w = fase_B_w = fase_C_w = None
        watts = calc.get("watts") or 0
        if watts > 0 and fase:
            fases_circ = fase.split("-")
            por_fase = watts / len(fases_circ)
            for f_letra in fases_circ:
                f_letra = f_letra.strip().upper()
                if f_letra == "A": fase_A_w = por_fase
                elif f_letra == "B": fase_B_w = por_fase
                elif f_letra == "C": fase_C_w = por_fase
 
        # Etiquetas del interruptor por número de polos (solo se llena la que aplica)
        itm_1polo = itm_2polo = itm_3polo = ""
        amperaje_a = c.get("amperaje_a")
        if amperaje_a:
            try:
                amp_int = int(float(amperaje_a))
                if polos == 1:
                    itm_1polo = f"1P-{amp_int}"
                elif polos == 2:
                    itm_2polo = f"2P-{amp_int}"
                elif polos == 3:
                    itm_3polo = f"3P-{amp_int}"
            except (ValueError, TypeError):
                pass
 
        return {
            "circuito_label":   circuito_label,
            "area":             c.get("nombre", ""),
            "watts":            calc.get("watts"),
            "kw":               calc.get("kw"),
            "factor_demanda":   c.get("factor_demanda") or 100,
            "kw_dem":           (calc.get("kw") or 0) * ((c.get("factor_demanda") or 100) / 100.0),
            "kva":              calc.get("kva"),
            "tension_v":        calc.get("tension_v"),
            "In":               calc.get("In"),
            "Ic":               calc.get("Ic"),
            "polos":            polos,
            "amperaje_a":       c.get("amperaje_a"),
            "itm_1polo":        itm_1polo,
            "itm_2polo":        itm_2polo,
            "itm_3polo":        itm_3polo,
            "capacidad_int_ka": c.get("capacidad_int_ka"),
            "num_fases":        f"{polos}F",
            "num_neutros":      "1N" if polos != 2 else "—",
            "num_tierras":      "1T",
            "factor_temp":      calc.get("factor_temp"),
            "factor_agrup":     calc.get("factor_agrup"),
            "material":         (c.get("material") or "cobre").capitalize(),
            "material_tierra":  (c.get("material") or "cobre").capitalize(),
            "calibre_fase":     c.get("calibre_fase"),
            "calibre_neutro":   c.get("calibre_neutro"),
            "calibre_tierra":   c.get("calibre_tierra"),
            "reactancia":       calc.get("reactancia"),
            "resistencia":      calc.get("resistencia"),
            "longitud_m":       c.get("longitud_m"),
            "caida_pct":        calc.get("caida_pct"),
            "fase_asignada":    fase,
            "fase_A_w":         fase_A_w,
            "fase_B_w":         fase_B_w,
            "fase_C_w":         fase_C_w,
            "cond_activos":     calc.get("cond_activos"),
            "tuberia_mm":       c.get("tuberia_mm"),
            "tipo_carga":       c.get("tipo_carga"),
            "evaluacion":       calc.get("evaluacion"),
        }
 
    def _construir_fila_libre(self, esp: int) -> Dict:
        return {
            "circuito_label": f"Circuito {esp}",
            "area": "LIBRE",
            "tipo_carga": "libre",
        }
 
    def _parse_tension(self, tension_str) -> float:
        if tension_str is None:
            return 220.0
        try:
            return float(tension_str)
        except (ValueError, TypeError):
            import re
            m = re.search(r"(\d+(?:\.\d+)?)", str(tension_str))
            return float(m.group(1)) if m else 220.0
 
 
# ════════════════════════════════════════════════════════════════════
# WIDGET DE TABLA POR TABLERO
# ════════════════════════════════════════════════════════════════════
class WidgetTablaCuadroCargas(QWidget):
    """Widget que muestra el cuadro de cargas de UN tablero."""
 
    def __init__(self, manager: CuadroCargasManager, tablero: Dict, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.tablero = tablero
        self._construir_ui()
        self._cargar_datos()
 
    def _construir_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
 
        # Encabezado del tablero (info general)
        encabezado = QFrame()
        encabezado.setStyleSheet("""
            QFrame {
                background-color: #FEC83A;
                border: 1px solid #888;
                border-radius: 4px;
            }
            QLabel { color: black; font-weight: bold; padding: 4px; }
        """)
        h_lay = QHBoxLayout(encabezado)
        h_lay.setContentsMargins(8, 4, 8, 4)
 
        lbl_titulo = QLabel(f'TABLERO "{self.tablero.get("nombre") or self.tablero.get("id", "?")}"')
        f = lbl_titulo.font()
        f.setPointSize(11)
        f.setBold(True)
        lbl_titulo.setFont(f)
        lbl_datos = QLabel(self._descripcion_tablero())
 
        h_lay.addWidget(lbl_titulo)
        h_lay.addStretch()
        h_lay.addWidget(lbl_datos)
 
        layout.addWidget(encabezado)
 
        # Tabla
        self.tabla = QTableWidget()
        self.tabla.setStyleSheet("""
            QTableWidget {
                background: white; color: black;
                gridline-color: #AAA; font-size: 9pt;
            }
            QHeaderView::section {
                background-color: #5D7689;
                color: white;
                padding: 0px;
                border: none;
                font-weight: bold;
                font-size: 8pt;
            }
            QHeaderView::section:hover {
                background-color: #5D7689;
            }
            QHeaderView::section:pressed {
                background-color: #5D7689;
            }
            QHeaderView::section:checked {
                background-color: #5D7689;
            }
        """)
        # IMPORTANTE: instalar el HEADER PERSONALIZADO antes de poner datos.
        # Este header pinta dos zonas: grupos arriba + títulos abajo, todo en
        # el header nativo (sin filas extras dentro de la tabla, sin widgets
        # separados encima). Resultado: nunca se desalinea y permite arrastrar
        # columnas con las manijas nativas.
        header_custom = HeaderConGrupos(COLUMNAS, self.tabla)
        self.tabla.setHorizontalHeader(header_custom)
 
        self.tabla.setAlternatingRowColors(False)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
 
        # Permitir redimensionar filas con el mouse (columnas ya tienen Interactive en el header)
        self.tabla.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tabla.horizontalHeader().setVisible(True)
        self.tabla.verticalHeader().setVisible(False)
 
        # Cuando el usuario termina de redimensionar una columna, forzamos
        # un repintado completo del header para borrar cualquier sombra residual
        # que Qt haya dejado por estado pressed/active de la sección.
        self.tabla.horizontalHeader().sectionResized.connect(
            lambda *_: self.tabla.horizontalHeader().viewport().update()
        )
 
        layout.addWidget(self.tabla)
 
        # Bloque de balance abajo
        self.balance_widget = self._crear_widget_balance()
        layout.addWidget(self.balance_widget)
 
    def _descripcion_tablero(self) -> str:
        partes = []
        if self.tablero.get("ubicacion"):
            partes.append(f"Ubicación: {self.tablero['ubicacion']}")
        if self.tablero.get("num_circuitos"):
            partes.append(f"{self.tablero['num_circuitos']} espacios")
        if self.tablero.get("corriente_nominal"):
            partes.append(f"In: {self.tablero['corriente_nominal']} A")
        if self.tablero.get("tension"):
            partes.append(f"{self.tablero['tension']}V")
        if self.tablero.get("marca"):
            partes.append(self.tablero["marca"])
        return "  •  ".join(partes)
 
    def _crear_widget_balance(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet("""
            QFrame {
                background-color: #2C3E50;
                border-radius: 4px;
            }
            QLabel { color: white; padding: 6px; font-size: 9pt; }
        """)
        self.lay_balance = QHBoxLayout(w)
        self.lay_balance.setContentsMargins(8, 4, 8, 4)
        # Se llena en _cargar_datos
        return w
 
    def _cargar_datos(self):
        filas, _total, alimentador = self.manager.construir_filas_tablero(self.tablero)
        self._filas_data = filas
        self._alim_data = alimentador
 
        cols_planas = _todas_las_columnas()
        ncols = len(cols_planas)
 
        # Filas de datos: N circuitos + 1 alimentador (sin filas de header,
        # el header está en el HeaderConGrupos personalizado).
        self.tabla.setColumnCount(ncols)
        self.tabla.setRowCount(len(filas) + 1)
 
        # Anchos iniciales por columna (orientativos; el usuario los puede arrastrar)
        for i, (_, _, ancho) in enumerate(cols_planas):
            self.tabla.setColumnWidth(i, ancho)
 
        # Filas de circuitos (empiezan en row 0)
        for r, fila in enumerate(filas):
            self._llenar_fila(r, fila, es_total=False, es_alim=False)
 
        # Fila alimentador principal (última)
        self._llenar_fila(len(filas), alimentador, es_total=False, es_alim=True)
 
        # Llenar el bloque de balance abajo
        self._llenar_balance(alimentador)
 
        # Ajustar las filas de datos al contenido
        self.tabla.resizeRowsToContents()
 
        # Ajustar el ancho de cada columna al contenido. Como el header es
        # personalizado y depende de sectionSize, las celdas mergeadas de grupo
        # se reajustan SOLAS cuando las columnas cambian.
        self.tabla.resizeColumnsToContents()
 
        # Asegurar anchos mínimos definidos en COLUMNAS
        for i, (_, key, ancho_min) in enumerate(cols_planas):
            actual = self.tabla.columnWidth(i)
            if actual < ancho_min:
                self.tabla.setColumnWidth(i, ancho_min)
            # Limitar el ancho máximo de Observaciones
            if key == "observaciones_nom" and actual > 320:
                self.tabla.setColumnWidth(i, 320)
 
    def _llenar_fila(self, row: int, fila: Dict, es_total=False, es_alim=False):
        cols_planas = _todas_las_columnas()
        eval_info = fila.get("evaluacion") or {}
        estado = eval_info.get("estado", "")
        mensajes = eval_info.get("mensajes", [])
 
        # Símbolo de estado
        simbolos_estado = {"ok": "✓", "warn": "⚠", "fail": "✗"}
 
        # Color de fondo para toda la fila
        if es_alim:
            bg = COLOR_ALIM_BG
            text_color = QColor("black")
        elif es_total:
            bg = COLOR_TOTAL_BG
            text_color = QColor("black")
        elif fila.get("tipo_carga") == "libre":
            bg = COLOR_LIBRE
            text_color = QColor("#666")
        else:
            if estado == "fail":
                bg = COLOR_FAIL
            elif estado == "warn":
                bg = COLOR_WARN
            elif estado == "ok":
                bg = COLOR_OK
            else:
                bg = QColor("white")
            text_color = QColor("black")
 
        for c_idx, (titulo, key, _) in enumerate(cols_planas):
            valor = ""
            if key == "estado_simbolo":
                if not es_total and not es_alim and fila.get("tipo_carga") != "libre":
                    valor = simbolos_estado.get(estado, "")
            elif key == "observaciones_nom":
                if not es_total and not es_alim and fila.get("tipo_carga") != "libre":
                    valor = " · ".join(mensajes) if mensajes else ""
            else:
                v = fila.get(key)
                valor = self._formatear_valor(key, v)
 
            item = QTableWidgetItem(valor)
            item.setBackground(QBrush(bg))
            item.setForeground(QBrush(text_color))
            # Alineación
            if key in ("watts", "kw", "kva", "tension_v", "In", "Ic",
                      "amperaje_a", "capacidad_int_ka", "tuberia_mm",
                      "longitud_m", "caida_pct", "polos", "factor_temp",
                      "factor_agrup", "reactancia", "resistencia",
                      "fase_A_w", "fase_B_w", "fase_C_w", "cond_activos",
                      "factor_demanda", "kw_dem"):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
 
            # En blanco para libres en celdas de cálculos
            if fila.get("tipo_carga") == "libre" and key not in ("circuito_label", "area"):
                item.setText("")
 
            # Negrita para TOTAL y ALIMENTADOR
            if es_total or es_alim:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
 
            self.tabla.setItem(row, c_idx, item)
 
    def _formatear_valor(self, key: str, valor) -> str:
        if valor is None or valor == "":
            return ""
        # Numéricos con formato específico
        if key in ("watts", "kw", "kva", "kw_dem"):
            try:
                if key == "watts":
                    return f"{float(valor):.0f}"
                else:
                    return f"{float(valor):.3f}"
            except (ValueError, TypeError):
                return str(valor)
        if key == "factor_demanda":
            try:
                return f"{int(float(valor))}%"
            except (ValueError, TypeError):
                return str(valor)
        if key in ("In", "Ic", "caida_pct"):
            try:
                return f"{float(valor):.2f}"
            except (ValueError, TypeError):
                return str(valor)
        if key in ("factor_temp", "factor_agrup"):
            try:
                return f"{float(valor):.2f}"
            except (ValueError, TypeError):
                return str(valor)
        if key in ("reactancia", "resistencia"):
            try:
                return f"{float(valor):.3f}"
            except (ValueError, TypeError):
                return str(valor)
        if key in ("fase_A_w", "fase_B_w", "fase_C_w"):
            try:
                return f"{float(valor):.0f}"
            except (ValueError, TypeError):
                return str(valor)
        if key in ("amperaje_a", "tension_v", "capacidad_int_ka",
                   "tuberia_mm", "longitud_m"):
            try:
                f = float(valor)
                if f == int(f):
                    return f"{int(f)}"
                else:
                    return f"{f:.1f}"
            except (ValueError, TypeError):
                return str(valor)
        return str(valor)
 
    def _llenar_balance(self, alimentador: Dict):
        """Pone el balance de fases A/B/C en el bloque inferior."""
        # Limpiar layout previo
        while self.lay_balance.count():
            item = self.lay_balance.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
 
        balance = alimentador.get("balance", {"A": 0, "B": 0, "C": 0})
        total = alimentador.get("watts", 0)
        kw = alimentador.get("kw", 0)
        kva = alimentador.get("kva", 0)
 
        # Bloque resumen
        resumen = [
            (f"{total:.0f}", "WATTS"),
            (f"{kw:.2f}", "KWATTS"),
            (f"{kva:.2f}", "KVA"),
            (f"{balance.get('A', 0):.1f}", "FASE A"),
            (f"{balance.get('B', 0):.1f}", "FASE B"),
            (f"{balance.get('C', 0):.1f}", "FASE C"),
        ]
 
        for valor, etiqueta in resumen:
            mini = QWidget()
            v = QVBoxLayout(mini)
            v.setContentsMargins(8, 0, 8, 0)
            v.setSpacing(0)
            lbl_v = QLabel(valor)
            lbl_v.setStyleSheet("color: #FF6F69; font-weight: bold; font-size: 12pt; padding: 0;")
            lbl_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_e = QLabel(etiqueta)
            lbl_e.setStyleSheet("color: white; font-size: 8pt; padding: 0;")
            lbl_e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(lbl_v)
            v.addWidget(lbl_e)
            self.lay_balance.addWidget(mini)
 
 
# ════════════════════════════════════════════════════════════════════
# VENTANA PRINCIPAL DEL CUADRO DE CARGAS
# ════════════════════════════════════════════════════════════════════
class VentanaCuadroCargas(QMainWindow):
    """Ventana con una pestaña por cada tablero del grupo."""
 
    def __init__(self, grupo_id: int, grupo_nombre: str = "", parent=None):
        super().__init__(parent)
        self.grupo_id = grupo_id
        self.grupo_nombre = grupo_nombre
        self.setWindowTitle(f"Cuadro de cargas — {grupo_nombre or grupo_id}")
        self.resize(1200, 650)
 
        self.manager = CuadroCargasManager(self)
 
        # Toolbar
        tb = QToolBar("Herramientas")
        self.addToolBar(tb)
        act_pdf = QAction("📄 Exportar PDF", self)
        act_pdf.triggered.connect(self._exportar_pdf)
        tb.addAction(act_pdf)
 
        # Tab widget con un cuadro por tablero
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                background: #DDD; color: black; padding: 6px 14px;
                border: 1px solid #888; min-width: 80px;
            }
            QTabBar::tab:selected {
                background: #5D7689; color: white; font-weight: bold;
            }
        """)
        self.setCentralWidget(self.tabs)
 
        tableros = self.manager.tableros_del_grupo(grupo_id)
 
        if not tableros:
            w_vacio = QWidget()
            lay = QVBoxLayout(w_vacio)
            lbl = QLabel(
                "No hay tableros con circuitos guardados en este grupo.\n"
                "Captura circuitos en tus tableros para ver el cuadro de cargas."
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #666; font-size: 12pt; padding: 30px;")
            lay.addWidget(lbl)
            self.tabs.addTab(w_vacio, "Sin datos")
            return
 
        for tab in tableros:
            widget = WidgetTablaCuadroCargas(self.manager, tab)
            self.tabs.addTab(widget, f'TABLERO "{tab.get("nombre") or tab.get("id", "?")}"')
 
    def _exportar_pdf(self):
        """Exporta la pestaña actual a PDF."""
        archivo, _ = QFileDialog.getSaveFileName(
            self, "Guardar cuadro de cargas como PDF",
            f"cuadro_cargas_{self.grupo_nombre or self.grupo_id}.pdf",
            "PDF Files (*.pdf)"
        )
        if not archivo:
            return
        try:
            widget_actual = self.tabs.currentWidget()
            if widget_actual is None:
                return
            writer = QPdfWriter(archivo)
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
            writer.setPageOrientation(QPageLayout.Orientation.Landscape)
            writer.setResolution(150)
            painter = QPainter(writer)
            widget_actual.render(painter)
            painter.end()
            QMessageBox.information(self, "Listo",
                                    f"Cuadro de cargas exportado:\n{archivo}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{e}")


# ════════════════════════════════════════════════════════════════════
# Prueba independiente
# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    w = VentanaCuadroCargas(grupo_id=1, grupo_nombre="Prueba")
    w.show()
    sys.exit(app.exec())
