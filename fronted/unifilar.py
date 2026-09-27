# unifilar.py
"""
Diagrama unifilar con enfoque de "cajas por tablero" + conexiones limpias.
 
Características:
  - Cada tablero se dibuja como una caja con marco y título destacado.
  - Las conexiones padre→hijo son líneas ortogonales (vertical + horizontal + vertical).
  - El árbol completo se dibuja en una sola hoja virtual con zoom/pan.
  - Espacios libres se muestran como en el unifilar real (círculo abierto + "LIBRE").
  - Cargas se dibujan con símbolos diferenciados (motor, tablero hijo, carga genérica, etc.).
"""
 
from typing import Optional, Dict, Any, List, Tuple
from PyQt6.QtWidgets import (
    QMainWindow, QGraphicsScene, QGraphicsView, QGraphicsItemGroup,
    QGraphicsLineItem, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsPathItem, QGraphicsTextItem, QToolBar, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QFontMetrics, QPainterPath,
    QPageLayout, QPageSize, QAction, QPdfWriter
)
 
from db_manager import connect_db
from calculos_electricos import calcular_circuito_completo
 
 
# ════════════════════════════════════════════════════════════════════
# CONFIG DE DIBUJO
# ════════════════════════════════════════════════════════════════════
COL_W            = 110      # ancho asignado a cada circuito derivado
ALTO_HEADER      = 60       # alto del encabezado de cada caja
PADDING_CAJA     = 30       # padding lateral interno de la caja
SEPARACION_HIJOS = 60       # separación horizontal entre hijos
NIVEL_GAP        = 160      # separación vertical entre niveles del árbol
ESCALON_BUS_B    = 18       # diferencia de altura entre cables del bus padre→hijos
 
# Pens y colores
PEN_LINE       = QPen(QColor("#000"), 1.3)
PEN_THIN       = QPen(QColor("#000"), 0.7)
PEN_DASH       = QPen(QColor("#000"), 1.0, Qt.PenStyle.DashLine)
PEN_BARRA      = QPen(QColor("#000"), 2.2)
PEN_CONEXION   = QPen(QColor("#000"), 1.5)
PEN_CAJA       = QPen(QColor("#333"), 1.2, Qt.PenStyle.DashLine)
PEN_HEADER     = QPen(QColor("#333"), 1.5)
COLOR_HEADER   = QColor("#E8EDF3")
COLOR_CAJA_BG  = QColor("#FFFFFF")
COLOR_TEXTO    = QColor("#000000")
COLOR_TEXTO_GRIS = QColor("#555555")
 
 
def make_text(scene, contenido: str, font, x: float, y: float,
              color=None, center_x=False) -> "QGraphicsTextItem":
    """
    Crea un QGraphicsTextItem con color de texto FORZADO a negro por default.
    Esto evita que el tema oscuro del sistema deje texto invisible sobre fondo claro.
    Si center_x=True, x se interpreta como centro horizontal del texto.
    """
    t = QGraphicsTextItem(contenido)
    t.setFont(font)
    t.setDefaultTextColor(color if color is not None else COLOR_TEXTO)
    if center_x:
        # Usar QFontMetrics para medir el ancho del texto SIN inicializar un
        # QPainter "fantasma" sobre el item antes de estar en la scene.
        # boundingRect() en items no agregados a scene a veces dispara
        # "QPainter::begin: engine == 0" en consola.
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(contenido)
        t.setPos(x - tw / 2, y)
    else:
        t.setPos(x, y)
    scene.addItem(t)
    return t
 
 
def _envolver_nombre(nombre: str, max_chars_por_linea: int = 14) -> List[str]:
    """
    Divide un nombre en varias líneas si es más largo que max_chars_por_linea.
    Parte por palabras (no por mitad de palabra). Si una sola palabra es más
    larga que el ancho, la deja en su propia línea sin recortar.
    """
    if not nombre:
        return [""]
    palabras = nombre.split()
    lineas = []
    actual = ""
    for p in palabras:
        if not actual:
            actual = p
        elif len(actual) + 1 + len(p) <= max_chars_por_linea:
            actual += " " + p
        else:
            lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas if lineas else [nombre]
 
 
def make_text_multilinea(scene, contenido: str, font, x_centro: float, y: float,
                         max_chars: int = 14, color=None) -> int:
    """
    Dibuja un texto envuelto en varias líneas, centrado horizontalmente.
    Devuelve la cantidad de líneas dibujadas.
    """
    lineas = _envolver_nombre(contenido, max_chars)
    for i, ln in enumerate(lineas):
        make_text(scene, ln, font, x_centro, y + i * 11,
                  color=color, center_x=True)
    return len(lineas)
 
# Fuentes
FONT_SMALL  = QFont("Arial", 7)
FONT_XSMALL = QFont("Arial", 6)
FONT_NORMAL = QFont("Arial", 8)
FONT_BOLD   = QFont("Arial", 8, QFont.Weight.Bold)
FONT_HEAD   = QFont("Arial", 13, QFont.Weight.Bold)
FONT_SUBHEAD = QFont("Arial", 9)
 
# Coordenadas verticales dentro de la caja del tablero (relativas a y_top)
Y_PPAL_LBL   = ALTO_HEADER + 14
Y_PPAL_SIM   = ALTO_HEADER + 50
Y_BARRA      = ALTO_HEADER + 95
Y_NUM_ESP    = Y_BARRA + 8
Y_INT_DER    = Y_BARRA + 55

# Tabla de información de cada circuito (columna fija de etiquetas + valores horizontales)
# 9 filas: Cal. F, Cal. N, Cal. T, Tubería, L, In, Ic, %e, Voltaje
# Las unidades (m, A, V) ahora van en el valor, no en la etiqueta.
ETIQUETAS_TABLA = [
    ("Cal. Fase",    "calibre_fase"),
    ("Cal. Neutro",  "calibre_neutro"),
    ("Cal. Tierra",  "calibre_tierra"),
    ("Tubería",      "tuberia"),
    ("Longitud",     "longitud"),
    ("In",           "In"),
    ("Ic",           "Ic"),
    ("%e",           "caida"),
    ("Voltaje",      "voltaje"),
]
Y_TABLA_INICIO = Y_INT_DER + 25      # primera fila después del breaker
ALTO_FILA      = 12                  # alto de cada fila tabular
ANCHO_ETIQUETAS = 80                 # ancho de la columna fija de etiquetas (a la izquierda)
Y_TABLA_FIN    = Y_TABLA_INICIO + len(ETIQUETAS_TABLA) * ALTO_FILA

Y_LOAD_SIM   = Y_TABLA_FIN + 18      # el símbolo va debajo de la tabla
Y_LOAD_TXT   = Y_LOAD_SIM + 28
ALTO_CAJA    = Y_LOAD_TXT + 90   # +90 para dar espacio a nombres en 2-3 líneas
 
 
# ════════════════════════════════════════════════════════════════════
# UNIFILAR MANAGER
# ════════════════════════════════════════════════════════════════════
class UnifilarManager:
    def __init__(self, parent=None):
        self.parent = parent
 
    def construir_arbol_grupo(self, grupo_id: int, solo_directos: bool = True) -> List[Dict]:
        """
        Construye el árbol del unifilar para un grupo.
        - solo_directos=True (default): solo usa tableros/transformadores que
          pertenezcan DIRECTAMENTE al grupo (no a subgrupos).
        - solo_directos=False: incluye subgrupos también.
        """
        ids_grupos = [grupo_id] if solo_directos else self._subarbol_grupo(grupo_id)
        if not ids_grupos:
            return []
 
        raices = []
        tableros_visitados = set()
 
        transformadores = self._transformadores_del_grupo(ids_grupos)
        for trafo in transformadores:
            nodo_trafo = self._nodo_transformador(trafo)
            if trafo.get("tablero_alimentado_id"):
                t_hijo = self._cargar_tablero(trafo["tablero_alimentado_id"])
                if t_hijo:
                    nodo_tab = self._nodo_tablero_recursivo(
                        t_hijo, circuito_padre=None,
                        tableros_visitados=tableros_visitados
                    )
                    nodo_trafo["hijos"].append(nodo_tab)
            raices.append(nodo_trafo)
 
        tableros_raiz = self._tableros_raiz_del_grupo(ids_grupos, tableros_visitados)
        for t in tableros_raiz:
            nodo = self._nodo_tablero_recursivo(
                t, circuito_padre=None,
                tableros_visitados=tableros_visitados
            )
            raices.append(nodo)
 
        return raices
 
    def grupo_tiene_unifilar(self, grupo_id: int, solo_directos: bool = True) -> bool:
        """
        ¿El grupo tiene tableros o transformadores que mostrar en el unifilar?

        - solo_directos=True (default): solo cuenta los que pertenecen
          DIRECTAMENTE a este grupo. Esto evita que el botón aparezca en
          grupos padre que solo contienen subgrupos.
        - solo_directos=False: incluye subgrupos también.
        """
        ids_grupos = [grupo_id] if solo_directos else self._subarbol_grupo(grupo_id)
        if not ids_grupos:
            return False
        conn = connect_db()
        if conn is None:
            return False
        cur = conn.cursor()
        placeholders = ",".join("?" * len(ids_grupos))
        cur.execute(f"SELECT COUNT(*) FROM tableros WHERE grupo_id IN ({placeholders})",
                    ids_grupos)
        n_tab = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM transformadores WHERE grupo_id IN ({placeholders})",
                    ids_grupos)
        n_trf = cur.fetchone()[0]
        conn.close()
        return (n_tab + n_trf) > 0
 
    def _subarbol_grupo(self, grupo_id: int) -> List[int]:
        if grupo_id is None:
            return []
        conn = connect_db()
        if conn is None:
            return []
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
        ids = [r[0] for r in cur.fetchall()]
        conn.close()
        return ids
 
    def _transformadores_del_grupo(self, ids_grupos: List[int]) -> List[Dict]:
        conn = connect_db()
        if conn is None:
            return []
        cur = conn.cursor()
        placeholders = ",".join("?" * len(ids_grupos))
        cur.execute(f"""
            SELECT id, ubicacion, capacidad, tension, fecha, marca, enfriamiento,
                   fases, conexion, tipo, grupo_id, tablero_alimentado_id
            FROM transformadores WHERE grupo_id IN ({placeholders}) ORDER BY id
        """, ids_grupos)
        cols = [d[0] for d in cur.description]
        result = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return result
 
    def _tableros_raiz_del_grupo(self, ids_grupos: List[int],
                                 ya_visitados: set) -> List[Dict]:
        conn = connect_db()
        if conn is None:
            return []
        cur = conn.cursor()
        placeholders = ",".join("?" * len(ids_grupos))
        cur.execute(f"""
            SELECT id, nombre, ubicacion, corriente_nominal, tension, tipo, num_circuitos,
                   marca, fecha_instalacion, comentarios, grupo_id
            FROM tableros
            WHERE grupo_id IN ({placeholders})
              AND id NOT IN (SELECT tablero_hijo_id FROM circuitos
                             WHERE tablero_hijo_id IS NOT NULL)
              AND id NOT IN (SELECT tablero_alimentado_id FROM transformadores
                             WHERE tablero_alimentado_id IS NOT NULL)
            ORDER BY id
        """, ids_grupos)
        cols = [d[0] for d in cur.description]
        result = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            if d["id"] not in ya_visitados:
                result.append(d)
        conn.close()
        return result
 
    def _cargar_tablero(self, tablero_id: str) -> Optional[Dict]:
        conn = connect_db()
        if conn is None:
            return None
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nombre, ubicacion, corriente_nominal, tension, tipo, num_circuitos,
                   marca, fecha_instalacion, comentarios, grupo_id
            FROM tableros WHERE id = ?
        """, (tablero_id,))
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        conn.close()
        return dict(zip(cols, row)) if row else None
 
    def _circuitos_del_tablero(self, tablero_id: str) -> List[Dict]:
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
        result = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return result
 
    def _nodo_transformador(self, trafo: Dict) -> Dict:
        return {"tipo": "transformador", "id": trafo["id"], "datos": trafo,
                "circuito_padre": None, "circuitos": [], "hijos": []}
 
    def _nodo_tablero_recursivo(self, tablero: Dict,
                                 circuito_padre: Optional[Dict],
                                 tableros_visitados: set) -> Dict:
        if tablero["id"] in tableros_visitados:
            return {"tipo": "tablero", "id": tablero["id"], "datos": tablero,
                    "circuito_padre": circuito_padre, "circuitos": [], "hijos": []}
        tableros_visitados.add(tablero["id"])
 
        circuitos = self._circuitos_del_tablero(tablero["id"])
        nodo = {"tipo": "tablero", "id": tablero["id"], "datos": tablero,
                "circuito_padre": circuito_padre, "circuitos": circuitos, "hijos": []}
 
        for c in circuitos:
            if c.get("tipo_carga") == "tablero" and c.get("tablero_hijo_id"):
                t_hijo = self._cargar_tablero(c["tablero_hijo_id"])
                if t_hijo:
                    sub_nodo = self._nodo_tablero_recursivo(
                        t_hijo, circuito_padre=c,
                        tableros_visitados=tableros_visitados
                    )
                    nodo["hijos"].append(sub_nodo)
        return nodo

    def construir_arbol_tablero(self, tablero_id) -> List[Dict]:
        """
        Construye el árbol del unifilar arrancando de un tablero específico,
        sin mostrar su tablero padre.
 
        Reutiliza la misma lógica recursiva que construir_arbol_grupo, pero
        con un único punto de entrada en lugar de iterar las raíces del grupo.
        """
        tablero = self._cargar_tablero(tablero_id)
        if not tablero:
            return []
        grupo_id = tablero.get("grupo_id")
        if grupo_id is None:
            return []
 
        # Construir el árbol completo del grupo (reutiliza lógica existente)
        arbol_grupo = self.construir_arbol_grupo(grupo_id)
 
        # Buscar recursivamente el nodo del tablero objetivo dentro del árbol
        def _buscar(nodos):
            for n in nodos:
                if n.get("tipo") == "tablero" and n.get("id") == tablero_id:
                    return n
                sub = _buscar(n.get("hijos", []))
                if sub:
                    return sub
            return None
 
        nodo = _buscar(arbol_grupo)
        if not nodo:
            return []
 
        # Cortar el descenso: los tableros hijos solo aparecerán como símbolo
        # en la columna del circuito que los alimenta, sin expandir.
        nodo["hijos"] = []
        return [nodo]
 
# ════════════════════════════════════════════════════════════════════
# CÁLCULOS
# ════════════════════════════════════════════════════════════════════
def calcular_totales_tablero(circuitos: List[Dict], tension_v: float = 220) -> Dict:
    suma_w = 0.0
    suma_fp = 0.0
    n_con_fp = 0
    for c in circuitos:
        w = c.get("carga_w") or 0
        if w:
            suma_w += float(w)
        fp = c.get("factor_potencia")
        if fp:
            suma_fp += float(fp)
            n_con_fp += 1
    fp_prom = (suma_fp / n_con_fp) if n_con_fp else 0.85
 
    try:
        v = float(tension_v) if tension_v else 220
    except (ValueError, TypeError):
        v = 220
    if v > 0 and fp_prom > 0:
        i_aprox = suma_w / (1.7320508 * v * fp_prom) if suma_w else 0
    else:
        i_aprox = 0
    kw = suma_w / 1000.0
    return {"kw_inst": kw, "a_inst": i_aprox, "v": v, "fp": fp_prom,
            "kw_dem": kw, "a_dem": i_aprox}
 
 
def _parse_tension_numerica(tension_str) -> float:
    if tension_str is None:
        return 220.0
    try:
        return float(tension_str)
    except (ValueError, TypeError):
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", str(tension_str))
        return float(m.group(1)) if m else 220.0
 
 
# ════════════════════════════════════════════════════════════════════
# SÍMBOLOS
# ════════════════════════════════════════════════════════════════════
def simbolo_interruptor(scene, x, y, polos, amperaje, ka=None, tooltip=None):
    grupo = QGraphicsItemGroup()

    # Arco abierto a la DERECHA (C invertida tipo símbolo NOM).
    # Va desde el punto superior, se curva hacia la derecha,
    # y vuelve al punto inferior. Sin palanca, sin marcas internas
    # (siguiendo el estilo de la referencia profesional).
    path = QPainterPath()
    path.moveTo(x, y - 10)
    path.quadTo(x + 14, y, x, y + 10)
    arco = QGraphicsPathItem(path)
    arco.setPen(PEN_LINE)
    arco.setParentItem(grupo)

    polos_n = int(polos) if polos else 1
    amp_n = int(amperaje) if amperaje else 0
    txt_amp = QGraphicsTextItem(f"{polos_n}×{amp_n}A")
    txt_amp.setFont(FONT_NORMAL)
    txt_amp.setDefaultTextColor(COLOR_TEXTO)
    txt_amp.setPos(x + 18, y - 13)
    txt_amp.setParentItem(grupo)

    if ka:
        txt_ka = QGraphicsTextItem(f"{int(ka)}kA")
        txt_ka.setFont(FONT_SMALL)
        txt_ka.setDefaultTextColor(COLOR_TEXTO)
        txt_ka.setPos(x + 18, y - 1)
        txt_ka.setParentItem(grupo)

    if tooltip:
        grupo.setToolTip(tooltip)

    scene.addItem(grupo)
    return grupo
 
 
def simbolo_tablero_hijo(scene, x, y):
    """Rectángulo con líneas horizontales internas (representa los carriles
    del tablero). Sin tachado, estilo NOM profesional."""
    grupo = QGraphicsItemGroup()
    # Rectángulo principal
    rect = QGraphicsRectItem(x - 11, y, 22, 22)
    rect.setPen(PEN_LINE)
    rect.setBrush(QBrush(Qt.GlobalColor.white))
    rect.setParentItem(grupo)
    # 3 líneas horizontales internas (carriles)
    for i in range(3):
        yi = y + 6 + i * 5
        l = QGraphicsLineItem(x - 8, yi, x + 8, yi)
        l.setPen(PEN_THIN)
        l.setParentItem(grupo)
    scene.addItem(grupo)
    return grupo
 
 
def simbolo_motor(scene, x, y):
    grupo = QGraphicsItemGroup()
    circ = QGraphicsEllipseItem(x - 11, y, 22, 22)
    circ.setPen(PEN_LINE)
    circ.setBrush(QBrush(Qt.GlobalColor.white))
    circ.setParentItem(grupo)
    txt = QGraphicsTextItem("M")
    txt.setFont(FONT_BOLD)
    txt.setDefaultTextColor(COLOR_TEXTO)
    fm = QFontMetrics(FONT_BOLD)
    tw = fm.horizontalAdvance("M")
    th = fm.height()
    txt.setPos(x - tw / 2, y + 11 - th / 2)
    txt.setParentItem(grupo)
    scene.addItem(grupo)
    return grupo
 
 
def simbolo_elevador(scene, x, y):
    """Rectángulo con doble flecha vertical (sube/baja) dibujada con polígonos
    para evitar problemas de renderizado del caracter Unicode."""
    grupo = QGraphicsItemGroup()
    # Rectángulo principal
    rect = QGraphicsRectItem(x - 12, y, 24, 28)
    rect.setPen(PEN_LINE)
    rect.setBrush(QBrush(Qt.GlobalColor.white))
    rect.setParentItem(grupo)

    # Línea vertical central
    linea = QGraphicsLineItem(x, y + 5, x, y + 23)
    linea.setPen(PEN_LINE)
    linea.setParentItem(grupo)

    # Flecha hacia arriba (triángulo apuntando arriba)
    flecha_up = QPainterPath()
    flecha_up.moveTo(x, y + 3)
    flecha_up.lineTo(x - 3, y + 8)
    flecha_up.lineTo(x + 3, y + 8)
    flecha_up.closeSubpath()
    item_up = QGraphicsPathItem(flecha_up)
    item_up.setPen(PEN_LINE)
    item_up.setBrush(QBrush(QColor("#000000")))
    item_up.setParentItem(grupo)

    # Flecha hacia abajo (triángulo apuntando abajo)
    flecha_dn = QPainterPath()
    flecha_dn.moveTo(x, y + 25)
    flecha_dn.lineTo(x - 3, y + 20)
    flecha_dn.lineTo(x + 3, y + 20)
    flecha_dn.closeSubpath()
    item_dn = QGraphicsPathItem(flecha_dn)
    item_dn.setPen(PEN_LINE)
    item_dn.setBrush(QBrush(QColor("#000000")))
    item_dn.setParentItem(grupo)

    scene.addItem(grupo)
    return grupo
 
 
def simbolo_carga_generica(scene, x, y, letra=""):
    """Círculo con X dentro. Para contactos, alumbrado y cargas no específicas.
    La letra es opcional (no se muestra por default, el círculo con X es suficiente)."""
    grupo = QGraphicsItemGroup()
    # Círculo principal
    circ = QGraphicsEllipseItem(x - 10, y, 20, 20)
    circ.setPen(PEN_LINE)
    circ.setBrush(QBrush(Qt.GlobalColor.white))
    circ.setParentItem(grupo)
    # X interna
    l1 = QGraphicsLineItem(x - 6, y + 4, x + 6, y + 16)
    l1.setPen(PEN_LINE)
    l1.setParentItem(grupo)
    l2 = QGraphicsLineItem(x + 6, y + 4, x - 6, y + 16)
    l2.setPen(PEN_LINE)
    l2.setParentItem(grupo)
    # Letra opcional (rara vez se usa, queda preparado por compatibilidad)
    if letra:
        txt = QGraphicsTextItem(letra)
        txt.setFont(FONT_SMALL)
        txt.setDefaultTextColor(COLOR_TEXTO)
        fm = QFontMetrics(FONT_SMALL)
        tw = fm.horizontalAdvance(letra)
        txt.setPos(x - tw / 2, y + 22)
        txt.setParentItem(grupo)
    scene.addItem(grupo)
    return grupo


def simbolo_aire_acondicionado(scene, x, y):
    """Triángulo invertido con base (símbolo genérico de AC).
    Más adelante se dividirá en 4 subtipos: minisplit, condensadora,
    manejadora, chiller — por ahora genérico."""
    grupo = QGraphicsItemGroup()
    # Triángulo
    path = QPainterPath()
    path.moveTo(x, y)
    path.lineTo(x - 12, y + 22)
    path.lineTo(x + 12, y + 22)
    path.closeSubpath()
    item = QGraphicsPathItem(path)
    item.setPen(PEN_LINE)
    item.setBrush(QBrush(Qt.GlobalColor.white))
    item.setParentItem(grupo)
    # Base rectangular bajo el triángulo
    base = QGraphicsRectItem(x - 13, y + 22, 26, 4)
    base.setPen(PEN_LINE)
    base.setBrush(QBrush(Qt.GlobalColor.white))
    base.setParentItem(grupo)
    scene.addItem(grupo)
    return grupo
 
 
def simbolo_libre(scene, x, y):
    circ = QGraphicsEllipseItem(x - 4, y - 4, 8, 8)
    circ.setPen(PEN_LINE)
    circ.setBrush(QBrush(Qt.GlobalColor.white))
    scene.addItem(circ)
    return circ
 
 
def simbolo_transformador(scene, x, y, datos):
    """Dos círculos entrelazados horizontalmente (primario y secundario).
    Estilo NOM clásico para transformadores."""
    grupo = QGraphicsItemGroup()
    r = 12
    # Círculo izquierdo (primario)
    c1 = QGraphicsEllipseItem(x - r - 6, y - r, 2*r, 2*r)
    c1.setPen(PEN_LINE)
    c1.setBrush(QBrush(Qt.GlobalColor.white))
    c1.setParentItem(grupo)
    # Círculo derecho (secundario), ligeramente superpuesto
    c2 = QGraphicsEllipseItem(x - r + 6, y - r, 2*r, 2*r)
    c2.setPen(PEN_LINE)
    c2.setBrush(QBrush(Qt.GlobalColor.white))
    c2.setParentItem(grupo)

    tt = (f"<b>Transformador {datos.get('id', '')}</b><br>"
          f"Capacidad: {datos.get('capacidad', '?')}<br>"
          f"Tensión: {datos.get('tension', '?')}<br>"
          f"Conexión: {datos.get('conexion', '?')}<br>"
          f"Marca: {datos.get('marca', '?')}")
    grupo.setToolTip(tt)
    scene.addItem(grupo)
    return grupo
 
 
def _tooltip_circuito(c):
    partes = [f"<b>{c.get('nombre', 'Sin nombre')}</b>"]
    if c.get("amperaje_a"):
        partes.append(f"Interruptor: {int(c['polos'])}×{int(c['amperaje_a'])} A")
    if c.get("capacidad_int_ka"):
        partes.append(f"Capacidad: {int(c['capacidad_int_ka'])} kA")
    if c.get("calibre_fase"):
        partes.append(f"Cable F: {c['calibre_fase']}")
    if c.get("calibre_neutro"):
        partes.append(f"Cable N: {c['calibre_neutro']}")
    if c.get("calibre_tierra"):
        partes.append(f"Cable T: {c['calibre_tierra']}")
    if c.get("tuberia_mm"):
        partes.append(f"Tubería: {c['tuberia_mm']} mm")
    if c.get("longitud_m"):
        partes.append(f"Longitud: {c['longitud_m']} m")
    if c.get("carga_w"):
        partes.append(f"Carga: {c['carga_w']} W")
    if c.get("factor_potencia"):
        partes.append(f"FP: {c['factor_potencia']}")
    return "<br>".join(partes)
 
 
# ════════════════════════════════════════════════════════════════════
# DIBUJADOR
# ════════════════════════════════════════════════════════════════════
class DibujadorUnifilar:
    def __init__(self, scene: QGraphicsScene):
        self.scene = scene
        self._anclas = {}
 
    def dibujar_raices(self, raices: List[Dict]):
        x_actual = 0
        for raiz in raices:
            ancho = self._ancho_subarbol(raiz)
            cx = x_actual + ancho / 2
            self._dibujar_nodo(raiz, cx, 0)
            x_actual += ancho + 100
 
    def _ancho_caja(self, nodo: Dict) -> float:
        if nodo["tipo"] == "transformador":
            return 220
 
        circuitos = nodo.get("circuitos", [])
        # Cada circuito ocupa UNA columna (sin importar polos).
        # Cada espacio libre individual también ocupa UNA columna.
        num_circuitos = len(circuitos)
 
        total_esp = self._total_espacios(nodo)
        if total_esp > 0:
            espacios_ocupados = set()
            for c in circuitos:
                inicio = c.get("espacio_inicio", 0)
                polos = c.get("polos", 1)
                for k in range(polos):
                    espacios_ocupados.add(inicio + k * 2)
            num_libres = sum(1 for e in range(1, total_esp + 1)
                            if e not in espacios_ocupados)
        else:
            num_libres = 0
 
        total_cols = max(num_circuitos + num_libres, 3)
        ancho_int = total_cols * COL_W
        # 2*padding interior + ANCHO_ETIQUETAS (columna fija de etiquetas a la
        # izquierda) + 130 (bloque de totales a la derecha)
        return ancho_int + 2 * PADDING_CAJA + ANCHO_ETIQUETAS + 130
 
    def _ancho_subarbol(self, nodo: Dict) -> float:
        ancho_propio = self._ancho_caja(nodo)
        if not nodo["hijos"]:
            return ancho_propio
        ancho_hijos = sum(self._ancho_subarbol(h) for h in nodo["hijos"])
        ancho_hijos += SEPARACION_HIJOS * (len(nodo["hijos"]) - 1)
        return max(ancho_propio, ancho_hijos)
 
    def _total_espacios(self, nodo: Dict) -> int:
        try:
            return int(nodo["datos"].get("num_circuitos") or 0)
        except (ValueError, TypeError):
            return 0
 
    def _dibujar_nodo(self, nodo: Dict, cx: float, y_top: float):
        if nodo["tipo"] == "transformador":
            self._dibujar_caja_transformador(nodo, cx, y_top)
            if nodo["hijos"]:
                hijo = nodo["hijos"][0]
                cx_hijo = cx
                y_hijo = y_top + 120
                self._dibujar_nodo(hijo, cx_hijo, y_hijo)
                self._linea_conexion(cx, y_top + 90, cx_hijo, y_hijo)
        else:
            self._dibujar_caja_tablero(nodo, cx, y_top)
            if nodo["hijos"]:
                anchos_hijos = [self._ancho_subarbol(h) for h in nodo["hijos"]]
                total_h = sum(anchos_hijos) + SEPARACION_HIJOS * (len(anchos_hijos) - 1)
                x_h_actual = cx - total_h / 2
                y_hijos = y_top + ALTO_CAJA + NIVEL_GAP

                # Para escalonar el bus padre→hijos con patrón "V invertida":
                # los hijos centrales tienen tramo horizontal más bajo (cerca de
                # los hijos), los hijos de los extremos tienen tramo horizontal
                # más alto (cerca del padre). Esto separa visualmente los cables.
                n_hijos = len(nodo["hijos"])
                y_horizontal_base = y_top + ALTO_CAJA + 40   # base del bus
                # Distancia de cada hijo al centro (0 = centro, máximo = extremo)
                centro_idx = (n_hijos - 1) / 2.0

                for i, (hijo, ancho_h) in enumerate(zip(nodo["hijos"], anchos_hijos)):
                    cx_h = x_h_actual + ancho_h / 2
                    self._dibujar_nodo(hijo, cx_h, y_hijos)

                    # Distancia al centro (en posiciones). Más lejos = más arriba.
                    dist_centro = abs(i - centro_idx)
                    y_horizontal_i = y_horizontal_base - dist_centro * ESCALON_BUS_B

                    circ_padre = hijo.get("circuito_padre")
                    punto_origen = self._punto_salida_circuito(
                        nodo["id"], circ_padre, cx, y_top
                    )
                    if punto_origen:
                        self._linea_conexion(
                            punto_origen[0], punto_origen[1],
                            cx_h, y_hijos,
                            y_horizontal=y_horizontal_i
                        )
                    x_h_actual += ancho_h + SEPARACION_HIJOS
    def _dibujar_caja_transformador(self, nodo: Dict, cx: float, y_top: float):
        datos = nodo["datos"]
        ancho = self._ancho_caja(nodo)
        x_izq = cx - ancho / 2
 
        caja = QGraphicsRectItem(x_izq, y_top, ancho, 100)
        caja.setPen(PEN_CAJA)
        caja.setBrush(QBrush(COLOR_CAJA_BG))
        self.scene.addItem(caja)
 
        header = QGraphicsRectItem(x_izq, y_top, ancho, 28)
        header.setPen(PEN_HEADER)
        header.setBrush(QBrush(COLOR_HEADER))
        self.scene.addItem(header)
 
        make_text(self.scene, f"⚡ TRANSFORMADOR {datos.get('id', '')}",
                  FONT_HEAD, cx, y_top + 4, center_x=True)
 
        simbolo_transformador(self.scene, cx, y_top + 50, datos)
        info = f"{datos.get('capacidad', '?')} • {datos.get('tension', '?')} • {datos.get('conexion', '?')}"
        make_text(self.scene, info, FONT_NORMAL, cx, y_top + 82, center_x=True)
 
    def _dibujar_caja_tablero(self, nodo: Dict, cx: float, y_top: float):
        datos = nodo["datos"]
        circuitos = nodo.get("circuitos", [])
        circuito_padre = nodo.get("circuito_padre")
        circuitos_ord = sorted(circuitos, key=lambda c: c.get("espacio_inicio", 0))
 
        # Calcular espacios libres (los espacios físicos que no están ocupados)
        total_esp = self._total_espacios(nodo)
        espacios_ocupados = set()
        for c in circuitos_ord:
            inicio = c.get("espacio_inicio", 0)
            polos = c.get("polos", 1)
            for k in range(polos):
                espacios_ocupados.add(inicio + k * 2)
        espacios_libres = []
        if total_esp > 0:
            espacios_libres = [e for e in range(1, total_esp + 1)
                              if e not in espacios_ocupados]
 
        # Cada circuito = 1 columna; cada espacio libre = 1 columna
        num_circuitos = len(circuitos_ord)
        num_libres = len(espacios_libres)
        total_cols = max(num_circuitos + num_libres, 3)
 
        ancho_int = total_cols * COL_W
        ancho = ancho_int + 2 * PADDING_CAJA + ANCHO_ETIQUETAS + 130
        x_izq = cx - ancho / 2
 
        # Marco
        caja = QGraphicsRectItem(x_izq, y_top, ancho, ALTO_CAJA)
        caja.setPen(PEN_CAJA)
        caja.setBrush(QBrush(COLOR_CAJA_BG))
        self.scene.addItem(caja)
 
        # Header
        header = QGraphicsRectItem(x_izq, y_top, ancho, ALTO_HEADER)
        header.setPen(PEN_HEADER)
        header.setBrush(QBrush(COLOR_HEADER))
        self.scene.addItem(header)
 
        # Título: prioriza el nombre amigable, cae al ID si no hay
        nombre_tab = datos.get("nombre") or datos.get("id", "?")
        make_text(self.scene, f'TABLERO "{nombre_tab}"', FONT_HEAD, cx, y_top + 6,
                  center_x=True)
 
        # Sub-encabezado
        sub = self._linea_descripcion_tablero(datos)
        make_text(self.scene, sub, FONT_SUBHEAD, cx, y_top + 26, center_x=True)
 
        # Etiqueta "VIENE DE..."
        if circuito_padre:
            esp_padre = circuito_padre.get("espacio_inicio", "?")
            polos_padre = circuito_padre.get("polos", 1)
            espacios_str = ",".join(
                str(esp_padre + k * 2) for k in range(polos_padre)
            )
            make_text(self.scene, f"VIENE DE: Esp. {espacios_str}",
                      FONT_SMALL, x_izq + 8, y_top + 44,
                      color=COLOR_TEXTO_GRIS)
 
        # Interruptor principal (si tiene padre)
        if circuito_padre:
            # Etiqueta a un costado (izquierda del símbolo) para que no se
            # atraviese con la línea vertical que viene desde el encabezado.
            make_text(self.scene, "ITM PRINCIPAL", FONT_SMALL,
                      cx - 80, y_top + Y_PPAL_SIM - 4)

            # Línea vertical desde el borde inferior del encabezado hasta la
            # parte superior del breaker (arco empieza en Y_PPAL_SIM - 10).
            l_top = QGraphicsLineItem(
                cx, y_top + ALTO_HEADER,
                cx, y_top + Y_PPAL_SIM - 10
            )
            l_top.setPen(PEN_LINE)
            self.scene.addItem(l_top)

            simbolo_interruptor(
                self.scene, cx, y_top + Y_PPAL_SIM,
                polos=circuito_padre.get("polos") or 3,
                amperaje=circuito_padre.get("amperaje_a") or 0,
                ka=circuito_padre.get("capacidad_int_ka"),
                tooltip=_tooltip_circuito(circuito_padre)
            )
            l_ppal = QGraphicsLineItem(
                cx, y_top + Y_PPAL_SIM + 12,
                cx, y_top + Y_BARRA
            )
            l_ppal.setPen(PEN_LINE)
            self.scene.addItem(l_ppal)
 
        # Barra horizontal
        x_first = x_izq + PADDING_CAJA + ANCHO_ETIQUETAS + COL_W / 2
        x_last  = x_first + (total_cols - 1) * COL_W
        barra = QGraphicsLineItem(x_first, y_top + Y_BARRA,
                                  x_last, y_top + Y_BARRA)
        barra.setPen(PEN_BARRA)
        self.scene.addItem(barra)
 
        # ── DIBUJAR COLUMNAS ──────────────────────────────────────────
        # 1. Una columna por cada circuito real (en orden de espacio_inicio)
        # 2. Después, una columna por cada espacio libre

        # Voltaje del tablero como referencia (los circuitos heredan este valor
        # si no tienen tension_v capturado individual).
        tension_v_tab = _parse_tension_numerica(datos.get("tension"))

        puntos_salida = {}
 
        # Primero los circuitos
        for i, c in enumerate(circuitos_ord):
            x_col = x_first + i * COL_W
 
            # Etiqueta de espacios físicos arriba de la columna (ej. "1,3,5" o "7")
            polos = int(c.get("polos") or 1)
            inicio = c.get("espacio_inicio", 0)
            espacios_str = ",".join(str(inicio + k * 2) for k in range(polos))
            # Al lado derecho de la línea vertical, no centrado sobre ella.
            # Prefijo "C-" para indicar que son números de circuito.
            make_text(self.scene, f"C-{espacios_str}", FONT_XSMALL,
                      x_col + 6, y_top + Y_NUM_ESP)
 
            # Línea de la barra al interruptor
            l = QGraphicsLineItem(x_col, y_top + Y_BARRA,
                                   x_col, y_top + Y_INT_DER - 12)
            l.setPen(PEN_LINE)
            self.scene.addItem(l)
 
            # Dibujar interruptor + cables + carga + nombre
            # Pasamos el voltaje del tablero como fallback: si el circuito no
            # tiene tension_v capturado, hereda el del tablero.
            self._dibujar_columna_circuito(c, x_col, y_top,
                                            tension_tablero=tension_v_tab)
 
            # Punto de salida para la conexión a un eventual tablero hijo.
            # Va DEBAJO del nombre del tablero (Y_LOAD_TXT + offset suficiente
            # para 2-3 líneas de nombre) para que el cable no atraviese el texto.
            puntos_salida[id(c)] = (x_col, y_top + Y_LOAD_TXT + 50)
 
        # Después los espacios libres
        for j, esp_libre in enumerate(espacios_libres):
            x_col = x_first + (num_circuitos + j) * COL_W
 
            # Número del espacio arriba (a la derecha de la línea)
            make_text(self.scene, f"C-{esp_libre}", FONT_XSMALL,
                      x_col + 6, y_top + Y_NUM_ESP)
 
            # Línea desde la barra hasta el círculo
            l = QGraphicsLineItem(x_col, y_top + Y_BARRA,
                                   x_col, y_top + Y_LOAD_SIM)
            l.setPen(PEN_LINE)
            self.scene.addItem(l)
 
            simbolo_libre(self.scene, x_col, y_top + Y_LOAD_SIM + 4)
            make_text(self.scene, "LIBRE", FONT_SMALL,
                      x_col, y_top + Y_LOAD_TXT, center_x=True)
 
        self._anclas[nodo["id"]] = {
            "cx": cx,
            "y_top": y_top,
            "puntos_salida": puntos_salida,
        }

        # Columna fija de etiquetas (Cal. Fase, Cal. Neutro, In, Ic, %e, ...)
        # Se dibuja UNA SOLA VEZ a la izquierda del primer circuito.
        # Los valores de cada circuito se alinean a estas filas.
        x_etiquetas = x_izq + PADDING_CAJA + 25
        for k, (etiqueta, _clave) in enumerate(ETIQUETAS_TABLA):
            y_fila = y_top + Y_TABLA_INICIO + k * ALTO_FILA
            make_text(self.scene, etiqueta, FONT_SMALL,
                      x_etiquetas, y_fila, color=COLOR_TEXTO)

        # Bloque de totales
        tension_v = _parse_tension_numerica(datos.get("tension"))
        totales = calcular_totales_tablero(circuitos_ord, tension_v)
        x_tot = x_izq + ancho - 125
        y_tot = y_top + ALTO_HEADER + 25
        make_text(self.scene, "CARGA INSTALADA", FONT_BOLD, x_tot, y_tot)
        lineas = [
            f"{totales['kw_inst']:.3f} kW",
            f"{totales['a_inst']:.2f} A",
            f"{int(totales['v'])} V",
            f"FP {totales['fp']:.2f}",
            "─" * 14,
            f"FD: 100%",
            f"Dem: {totales['kw_dem']:.3f} kW",
        ]
        for k, ln in enumerate(lineas):
            make_text(self.scene, ln, FONT_NORMAL, x_tot, y_tot + 14 + k * 12)
 
    def _dibujar_columna_circuito(self, c: Dict, x: float, y_top: float,
                                   tension_tablero: float = None):
        """
        Dibuja el interruptor + cables + carga + nombre del circuito en su
        columna individual. La línea desde la barra hasta el interruptor ya
        fue dibujada por _dibujar_caja_tablero.
        tension_tablero: voltaje del tablero al que pertenece este circuito,
        usado como fallback si el circuito no tiene tension_v capturado.
        """
        polos = int(c.get("polos") or 1)
        amperaje = c.get("amperaje_a") or 0
        ka = c.get("capacidad_int_ka")
 
        # Interruptor
        simbolo_interruptor(
            self.scene, x, y_top + Y_INT_DER,
            polos=polos, amperaje=amperaje, ka=ka,
            tooltip=_tooltip_circuito(c)
        )
 
        # Línea del interruptor al símbolo de carga
        l = QGraphicsLineItem(x, y_top + Y_INT_DER + 12,
                              x, y_top + Y_LOAD_SIM - 2)
        l.setPen(PEN_LINE)
        self.scene.addItem(l)

        # Valores de este circuito alineados a la tabla común (filas horizontales).
        # Las etiquetas (Cal. Fase, In, %e, etc.) se dibujan UNA SOLA VEZ a la
        # izquierda del tablero, no aquí. Aquí solo van los VALORES de cada
        # circuito, alineados a cada fila correspondiente.
        try:
            calc = calcular_circuito_completo(c) if c.get("carga_w") else {}
        except Exception:
            calc = {}

        # Abreviatura del material: "Cu" o "Al"
        material = (c.get("material") or "cobre").lower()
        mat_abrev = "Al" if material == "aluminio" else "Cu"

        # Formato para calibres: "1 F - 6 AWG Cu" (polos + calibre + material)
        # Para tierra se usa "des" indicando que es desnudo: "1 T - 6 des Cu"
        def _fmt_calibre(calibre, polos_count, sufijo, desnudo=False):
            if not calibre:
                return "—"
            # Para tierra desnuda: "1 T - 6 des Cu"
            if desnudo:
                # Quitar "AWG" si está presente, agregar "des"
                calibre_limpio = calibre.replace(" AWG", "").replace(" KCM", "")
                return f"{polos_count} {sufijo} - {calibre_limpio} des {mat_abrev}"
            return f"{polos_count} {sufijo} - {calibre} {mat_abrev}"

        # Regla del cuadro de cargas: bifásicos (polos == 2) NO llevan neutro
        polos_n = int(c.get("polos") or 1)
        if polos_n == 2:
            calibre_n_display = "—"
        else:
            calibre_n_display = _fmt_calibre(c.get("calibre_neutro"), 1, "N")

        # Voltaje a mostrar: misma regla que aplica cuadro_cargas.py:
        #   - Si el circuito tiene tension_v capturado → usar ese
        #   - Si no, y es monofásico (1P) → 127 V (fase a neutro)
        #   - Si no, y es bifásico o trifásico (2P/3P) → voltaje del tablero
        if c.get("tension_v"):
            voltaje_str = f"{c['tension_v']} V"
        elif tension_tablero:
            if polos_n == 1:
                voltaje_str = "127 V"
            else:
                voltaje_str = f"{int(tension_tablero)} V"
        else:
            voltaje_str = "—"

        valores = {
            "calibre_fase":   _fmt_calibre(c.get("calibre_fase"),   polos_n, "F"),
            "calibre_neutro": calibre_n_display,
            "calibre_tierra": _fmt_calibre(c.get("calibre_tierra"), 1, "T", desnudo=True),
            "tuberia":        f"{c['tuberia_mm']} mm" if c.get("tuberia_mm") else "—",
            "longitud":       f"{c['longitud_m']} m" if c.get("longitud_m") else "—",
            "In":             f"{calc.get('In'):.2f} A" if calc.get('In') else "—",
            "Ic":             f"{calc.get('Ic'):.2f} A" if calc.get('Ic') else "—",
            "caida":          f"{calc.get('caida_pct'):.2f} %" if calc.get('caida_pct') is not None else "—",
            "voltaje":        voltaje_str,
        }
        for k, (_etiqueta, clave) in enumerate(ETIQUETAS_TABLA):
            valor = valores.get(clave, "—")
            y_fila = y_top + Y_TABLA_INICIO + k * ALTO_FILA
            # Texto a la DERECHA de la línea vertical del circuito (no centrado
            # sobre ella, para que no se atraviese con la línea).
            make_text(self.scene, str(valor), FONT_SMALL,
                      x + 6, y_fila)

        # Símbolo de carga
        tipo = c.get("tipo_carga", "carga")
        if tipo == "tablero":
            simbolo_tablero_hijo(self.scene, x, y_top + Y_LOAD_SIM)
        elif tipo == "motor":
            simbolo_motor(self.scene, x, y_top + Y_LOAD_SIM)
        elif tipo == "elevador":
            simbolo_elevador(self.scene, x, y_top + Y_LOAD_SIM)
        elif tipo == "aa":
            simbolo_aire_acondicionado(self.scene, x, y_top + Y_LOAD_SIM)
        elif tipo == "bomba_incendio":
            simbolo_carga_generica(self.scene, x, y_top + Y_LOAD_SIM, letra="BCI")
        elif tipo == "transformador":
            simbolo_transformador(self.scene, x, y_top + Y_LOAD_SIM + 12, c)
        else:
            simbolo_carga_generica(self.scene, x, y_top + Y_LOAD_SIM)
 
        # Nombre debajo, envuelto en líneas si es muy largo
        nombre = c.get("nombre", "Sin nombre")
        n_lineas = make_text_multilinea(self.scene, nombre, FONT_BOLD,
                                         x, y_top + Y_LOAD_TXT, max_chars=13)

        # Potencia debajo del nombre (en W). Se coloca JUSTO DESPUÉS de la última
        # línea del nombre (sin importar cuántas líneas use), para que no se
        # encime con nombres largos ni quede separado en nombres cortos.
        # Cada línea del nombre = 11 px de alto, +6 de padding.
        if c.get("carga_w"):
            potencia_str = f"{int(c['carga_w'])} W"
            y_potencia = y_top + Y_LOAD_TXT + n_lineas * 11 + 6
            make_text(self.scene, potencia_str, FONT_SMALL,
                      x, y_potencia, center_x=True)
 
    def _linea_descripcion_tablero(self, datos: Dict) -> str:
        partes = []
        if datos.get("num_circuitos"):
            partes.append(f"{datos['num_circuitos']} espacios")
        if datos.get("corriente_nominal"):
            partes.append(f"In: {datos['corriente_nominal']} A")
        if datos.get("tension"):
            partes.append(f"{datos['tension']} V")
        if datos.get("marca"):
            partes.append(datos['marca'])
        if datos.get("ubicacion"):
            partes.append(datos['ubicacion'])
        return " • ".join(partes)
 
    def _agrupar_consecutivos(self, lista: List[int]) -> List[str]:
        if not lista:
            return []
        lista = sorted(lista)
        grupos = []
        inicio = lista[0]
        anterior = lista[0]
        for e in lista[1:]:
            if e == anterior + 1:
                anterior = e
            else:
                grupos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
                inicio = e
                anterior = e
        grupos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
        return grupos
 
    def _punto_salida_circuito(self, tablero_padre_id, circuito,
                                cx_padre, y_top_padre):
        ancla = self._anclas.get(tablero_padre_id)
        if ancla and circuito and id(circuito) in ancla["puntos_salida"]:
            return ancla["puntos_salida"][id(circuito)]
        return (cx_padre, y_top_padre + ALTO_CAJA)
 
    def _linea_conexion(self, x_top, y_top_origen, x_bottom, y_bottom_destino,
                        y_horizontal=None):
        # y_horizontal: altura del tramo horizontal. Si no se especifica, se usa
        # el punto medio entre origen y destino (comportamiento original).
        # Se usa para escalonar las conexiones del bus padre→hijos a distintas
        # alturas y que se distingan visualmente.
        if y_horizontal is None:
            y_horizontal = (y_top_origen + y_bottom_destino) / 2
        l1 = QGraphicsLineItem(x_top, y_top_origen, x_top, y_horizontal)
        l1.setPen(PEN_CONEXION)
        self.scene.addItem(l1)
        l2 = QGraphicsLineItem(x_top, y_horizontal, x_bottom, y_horizontal)
        l2.setPen(PEN_CONEXION)
        self.scene.addItem(l2)
        l3 = QGraphicsLineItem(x_bottom, y_horizontal, x_bottom, y_bottom_destino)
        l3.setPen(PEN_CONEXION)
        self.scene.addItem(l3)
 
 
# ════════════════════════════════════════════════════════════════════
# VISTA Y VENTANA
# ════════════════════════════════════════════════════════════════════
class UnifilarView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom = 0
 
    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        delta = 1 if event.angleDelta().y() > 0 else -1
        nuevo = self._zoom + delta
        if -10 <= nuevo <= 20:
            self.scale(factor, factor)
            self._zoom = nuevo
 
 
class VentanaUnifilar(QMainWindow):
    def __init__(self, grupo_id: int = None, grupo_nombre: str = "",
                 tablero_id=None, tablero_nombre: str = "", parent=None):
        super().__init__(parent)
        self.grupo_id = grupo_id
        self.grupo_nombre = grupo_nombre
        self.tablero_id = tablero_id
        self.tablero_nombre = tablero_nombre

        # Tamaño inicial razonable. Si la pantalla del usuario es más chica
        # que el tamaño solicitado, se adapta automáticamente a la pantalla
        # disponible (90% del área útil). Mismo patrón que cuadro de cargas.
        from PyQt6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            ancho = min(1200, int(geo.width() * 0.9))
            alto = min(700, int(geo.height() * 0.9))
            self.resize(ancho, alto)
        else:
            self.resize(1200, 700)
 
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QBrush(QColor("#FAFAFA")))
 
        manager = UnifilarManager(self)
        if tablero_id is not None:
            # Modo tablero individual: solo este tablero y sus descendientes
            raices = manager.construir_arbol_tablero(tablero_id)
            self.setWindowTitle(
                f"Diagrama unifilar — {tablero_nombre or tablero_id}"
            )
            mensaje_vacio = "Este tablero no tiene datos para mostrar en el unifilar."
        else:
            # Modo grupo: comportamiento histórico, intacto
            raices = manager.construir_arbol_grupo(grupo_id)
            self.setWindowTitle(
                f"Diagrama unifilar — {grupo_nombre or grupo_id}"
            )
            mensaje_vacio = "No hay tableros ni transformadores con datos en este grupo."
 
        if not raices:
            self.scene.addText(mensaje_vacio, QFont("Arial", 12))
        else:
            dibujador = DibujadorUnifilar(self.scene)
            dibujador.dibujar_raices(raices)
 
        rect = self.scene.itemsBoundingRect().adjusted(-100, -80, 100, 80)
        self.scene.setSceneRect(rect)
 
        self.view = UnifilarView(self.scene)
        self.setCentralWidget(self.view)
 
        tb = QToolBar("Herramientas")
        self.addToolBar(tb)
 
        act_fit = QAction("Ajustar", self)
        act_fit.triggered.connect(self.ajustar_vista)
        tb.addAction(act_fit)
 
        act_in = QAction("Zoom +", self)
        act_in.triggered.connect(lambda: self.view.scale(1.2, 1.2))
        tb.addAction(act_in)
 
        act_out = QAction("Zoom -", self)
        act_out.triggered.connect(lambda: self.view.scale(1/1.2, 1/1.2))
        tb.addAction(act_out)
 
        tb.addSeparator()
 
        act_pdf = QAction("Exportar PDF", self)
        act_pdf.triggered.connect(self.exportar_pdf)
        tb.addAction(act_pdf)
 
        # IMPORTANTE: postergar fitInView hasta que el viewport esté inicializado.
        # Si se llama en el constructor (antes de que la ventana se muestre),
        # Qt intenta usar el paint engine que aún no existe y dispara
        # "QPainter::begin: engine == 0, type: 3" en consola.
        QTimer.singleShot(0, self.ajustar_vista)
 
    def ajustar_vista(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
 
    def exportar_pdf(self):
        # Elegir nombre por defecto según el modo de la ventana
        if self.tablero_id is not None:
            nombre_default = f"unifilar_tablero_{self.tablero_nombre or self.tablero_id}"
        else:
            nombre_default = f"unifilar_{self.grupo_nombre or self.grupo_id}"
        archivo, _ = QFileDialog.getSaveFileName(
            self, "Guardar unifilar como PDF",
            f"{nombre_default}.pdf",
            "PDF Files (*.pdf)"
        )
        if not archivo:
            return
        try:
            writer = QPdfWriter(archivo)
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
            writer.setPageOrientation(QPageLayout.Orientation.Landscape)
            writer.setResolution(300)
            painter = QPainter(writer)
            self.scene.render(painter)
            painter.end()
            QMessageBox.information(self, "Listo", f"Unifilar exportado:\n{archivo}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el PDF:\n{e}")
 
 
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = VentanaUnifilar(grupo_id=1, grupo_nombre="Prueba")
    w.show()
    sys.exit(app.exec())