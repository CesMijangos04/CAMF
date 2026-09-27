from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QScrollArea, QSizePolicy, QMenu
)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QAction
from datetime import datetime
import qtawesome as qta

#from signals import AppSignals
from db_manager import ejecutar_query

# ===================== LÓGICA (IGUAL) =====================
def calcular_estado(estado_db, fecha_inicio_iso, fecha_fin_iso):
    """
    Devuelve el estado "derivado" del mantenimiento para mostrar en la UI.

    El campo persistente 'estado' en BD puede ser: 'programado', 'cancelado',
    'finalizado'. A partir de él + las fechas calculamos el estado visual:

      - Cancelado     → estado_db == 'cancelado'
      - Finalizado    → estado_db == 'finalizado'
      - Programado    → estado_db == 'programado' y aún no inicia
      - En curso      → estado_db == 'programado' y estamos dentro de la ventana
      - Pendiente cierre → estado_db == 'programado' y el tiempo ya pasó
    """
    if estado_db == "cancelado":
        return "Cancelado"
    if estado_db == "finalizado":
        return "Finalizado"

    ahora = datetime.now()
    inicio = datetime.strptime(fecha_inicio_iso, "%Y-%m-%d %H:%M")
    fin = datetime.strptime(fecha_fin_iso, "%Y-%m-%d %H:%M")

    if ahora < inicio:
        return "Programado"
    elif inicio <= ahora <= fin:
        return "En curso"
    else:
        return "Pendiente cierre"
    
def obtener_mantenimientos():
    """
    Cada fila devuelta es un mantenimiento con todos sus campos relevantes
    + una lista parseable de equipos: 'id1:tipo1|id2:tipo2|...'.
    """
    return ejecutar_query("""
        SELECT
            m.id,
            m.tipo_mantenimiento,
            m.urgente,
            m.fecha_inicio,
            m.fecha_fin,
            m.costo,
            m.costo_moneda,
            m.responsable_nombre,
            m.estado,
            GROUP_CONCAT(me.equipo_id || ':' || me.equipo_tipo, '|') AS equipos_lista
        FROM mantenimientos m
        LEFT JOIN mantenimientos_equipos me ON me.mantenimiento_id = m.id
        WHERE m.fecha_cierre IS NULL
          AND m.responsable_tipo != 'pendiente'
        GROUP BY m.id
        ORDER BY m.fecha_inicio ASC
    """)


# ── Helpers de grupos para columna "Equipos · Grupo común" ──────────────────
def _cargar_jerarquia_grupos():
    """Devuelve {grupo_id: (nombre, padre_id)} para todos los grupos."""
    rows = ejecutar_query("SELECT id, nombre, padre_id FROM grupos") or []
    return {g[0]: (g[1], g[2]) for g in rows}


def _cargar_grupos_de_equipos():
    """Devuelve {(equipo_id, tabla): grupo_id} consultando tableros y transformadores."""
    d = {}
    for tabla in ("tableros", "transformadores"):
        rows = ejecutar_query(f"SELECT id, grupo_id FROM {tabla}") or []
        for eq_id, grupo_id in rows:
            d[(eq_id, tabla)] = grupo_id
    return d


def _ancestros(grupo_id, jerarquia):
    """Lista de IDs desde el grupo hasta la raíz (incluye el grupo mismo)."""
    out = []
    actual = grupo_id
    visitados = set()  # protección anti-ciclo por si hay datos corruptos
    while actual is not None and actual in jerarquia and actual not in visitados:
        visitados.add(actual)
        out.append(actual)
        actual = jerarquia[actual][1]
    return out


def _ruta_grupo(grupo_id, jerarquia):
    """Cadena 'Edificio A › Piso 2' desde la raíz hasta el grupo dado."""
    if grupo_id is None or grupo_id not in jerarquia:
        return ""
    partes = []
    actual = grupo_id
    visitados = set()
    while actual is not None and actual in jerarquia and actual not in visitados:
        visitados.add(actual)
        partes.append(jerarquia[actual][0])
        actual = jerarquia[actual][1]
    return " › ".join(reversed(partes))


def _grupo_comun(equipos, grupo_por_equipo, jerarquia):
    """
    Devuelve el grupo común más específico para una lista de equipos.

    Casos:
    - Todos en el mismo subgrupo → ese subgrupo.
    - En subgrupos distintos pero con ancestro común → ese ancestro.
    - Algún equipo sin grupo, o sin ancestro común → None (= "Mixto" o "Sin grupo").
    """
    if not equipos:
        return None
    listas = []
    for eq_id, eq_tipo in equipos:
        grupo = grupo_por_equipo.get((eq_id, eq_tipo))
        if grupo is None:
            return None  # algún equipo sin grupo → no hay común
        listas.append(_ancestros(grupo, jerarquia))
    # Recorremos del más profundo al más cercano a raíz en la primera lista,
    # devolvemos el primero que esté en todas las demás.
    for g in listas[0]:
        if all(g in lista for lista in listas[1:]):
            return g
    return None


def _formato_equipos(equipos_lista_str, grupo_por_equipo, jerarquia):
    """
    Construye el texto de la columna "Equipos".

    - 0 equipos      → "—"
    - 1-3 equipos    → "TG-01, TG-02 · Edificio A › Piso 2"
    - 4+ equipos     → "5 equipos · Edificio A"
    - Sin grupo común → "... · Sin agrupar" o "... · Mixto"
    """
    if not equipos_lista_str:
        return "—"

    equipos = []
    for par in equipos_lista_str.split("|"):
        if ":" in par:
            eq_id, eq_tipo = par.split(":", 1)
            equipos.append((eq_id, eq_tipo))

    if not equipos:
        return "—"

    n = len(equipos)
    if n <= 3:
        ids = ", ".join(eq_id for eq_id, _ in equipos)
        cabeza = ids
    else:
        cabeza = f"{n} equipos"

    # Sufijo del grupo común
    grupo_id = _grupo_comun(equipos, grupo_por_equipo, jerarquia)
    if grupo_id is not None:
        ruta = _ruta_grupo(grupo_id, jerarquia)
        return f"{cabeza} · {ruta}" if ruta else cabeza

    # Determinar si todos no tienen grupo, o si es mezcla
    sin_grupo = sum(1 for eq in equipos if grupo_por_equipo.get(eq) is None)
    if sin_grupo == n:
        return f"{cabeza} · Sin agrupar"
    return f"{cabeza} · Mixto"



# ── Colores en HEX, paralelo a COLORES_ESTADO (que es QColor para los
#    delegates antiguos). Los nuevos widgets usan styleSheet en CSS-like
#    QSS, donde es más cómodo trabajar con strings hex.
COLORES_ESTADO_HEX = {
    "Programado":       "#4a90e2",
    "En curso":         "#f1c40f",
    "Pendiente cierre": "#e67e22",
    "Cancelado":        "#e84747",
    "Finalizado":       "#27ae60",
}


def _formato_equipos_dos_lineas(equipos_lista_str, grupo_por_equipo, jerarquia):
    """
    Versión de _formato_equipos pensada para las cards: en lugar de juntar
    todo con un separador ` · ` en una sola línea, devuelve la tupla
    (linea1, linea2, linea2_es_estado) donde:

        - linea1: IDs (si hay ≤3) o "N equipos" (si hay 4+)
        - linea2: ruta del grupo común, o "Mixto" / "Sin agrupar"
        - linea2_es_estado: True si linea2 es "Mixto"/"Sin agrupar"
                            (para mostrarla en itálica + más tenue)

    De esta forma cada card SIEMPRE ocupa 2 líneas exactas en la columna
    Equipos, sin importar la cantidad de equipos.
    """
    if not equipos_lista_str:
        return ("—", "", False)

    equipos = []
    for par in equipos_lista_str.split("|"):
        if ":" in par:
            eq_id, eq_tipo = par.split(":", 1)
            equipos.append((eq_id, eq_tipo))

    if not equipos:
        return ("—", "", False)

    n = len(equipos)
    if n <= 3:
        linea1 = ", ".join(eq_id for eq_id, _ in equipos)
    else:
        linea1 = f"{n} equipos"

    grupo_id = _grupo_comun(equipos, grupo_por_equipo, jerarquia)
    if grupo_id is not None:
        ruta = _ruta_grupo(grupo_id, jerarquia)
        return (linea1, ruta or "", False)

    sin_grupo = sum(1 for eq in equipos if grupo_por_equipo.get(eq) is None)
    if sin_grupo == n:
        return (linea1, "Sin agrupar", True)
    return (linea1, "Mixto", True)


# ══════════════════════════════════════════════════════════════════════
#  HELPERS PARA LAS CARDS
# ══════════════════════════════════════════════════════════════════════

class ElideLabel(QLabel):
    """
    QLabel que automáticamente trunca su texto con elipsis ('...') cuando
    no cabe en el ancho disponible. Necesario porque QLabel nativo NO hace
    elide — si el texto excede el ancho, lo recorta sin avisar visualmente
    al usuario.

    Mantiene el texto completo internamente (_full_text) y solo aplica el
    elide al pintar. Cuando cambia el ancho del widget (resizeEvent), se
    re-calcula el texto truncado.
    """
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text or ""
        self._mode = Qt.TextElideMode.ElideRight
        # Necesario para que el widget pueda achicarse en layouts; sino se
        # planta en su sizeHint y empuja al resto.
        self.setMinimumWidth(0)
        super().setText(self._full_text)

    def setText(self, text):
        self._full_text = text or ""
        self._update_elide()

    def text(self):
        return self._full_text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self):
        fm = self.fontMetrics()
        # Restar un pequeño margen para que la elipsis no quede pegada al borde
        ancho_disponible = max(0, self.width() - 2)
        elided = fm.elidedText(self._full_text, self._mode, ancho_disponible)
        super().setText(elided)


class BalancedWrapLabel(QLabel):
    """
    QLabel para nombres de personas: cuando el texto no cabe en 1 línea
    en el ancho disponible, lo parte en 2 líneas BALANCEADAS (lo más
    iguales posible en ancho).

    Por qué no usar setWordWrap(True): el wrap nativo de Qt parte al
    primer punto donde no cabe la palabra siguiente. Para "Cesar Andres
    Mijangos Flores" con ancho 153px → mete "Cesar Andres Mijangos" en
    línea 1 (cabe en 145px) y deja "Flores" solo en línea 2. Resultado:
    línea 1 llega casi al borde derecho → visualmente la columna parece
    "llena" y el contenido empujado a la derecha.

    Lo que hace BalancedWrapLabel: prueba TODOS los puntos de corte
    posibles entre palabras y elige el que produce 2 líneas con el menor
    delta de ancho entre ellas. Para el mismo nombre y ancho, devuelve
    "Cesar Andres" / "Mijangos Flores" (líneas más iguales) → el ancho
    efectivo es ~110px en lugar de 145px → Responsable se ve más
    compacto y mejor centrado.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text or ""
        self._updating = False
        self.setMinimumWidth(0)
        super().setText(self._full_text)

    def setText(self, text):
        self._full_text = text or ""
        self._update_wrap()

    def text(self):
        return self._full_text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._updating:
            self._update_wrap()

    def _update_wrap(self):
        # Flag para evitar loops de resize: cambiar el texto puede
        # disparar otro resizeEvent → potencialmente loop infinito.
        if self._updating:
            return
        self._updating = True
        try:
            available = max(0, self.width() - 2)
            if available <= 0:
                super().setText(self._full_text)
                return
            fm = self.fontMetrics()
            full_width = fm.horizontalAdvance(self._full_text)

            # Margen de seguridad para evitar que el texto quede pegado al
            # borde derecho de la columna. Si el texto ocupa más del 90%
            # del ancho disponible, hacer wrap aunque técnicamente cupiera
            # en 1 línea — el usuario percibe ese caso como "pegado a la
            # siguiente columna" visualmente, especialmente en ventanas
            # con sidebar expandida + ventana minimizada (donde el ancho
            # de cada columna es justo el suficiente para el contenido).
            umbral = int(available * 0.90)

            if full_width <= umbral:
                # Cabe holgado en 1 línea, sin wrap
                super().setText(self._full_text)
                return
            # Necesita wrap: buscar el punto de corte óptimo
            partido = self._wrap_balanced(self._full_text, available, fm)
            super().setText(partido)
        finally:
            self._updating = False

    @staticmethod
    def _wrap_balanced(text, max_width, fm):
        """
        Devuelve el texto partido en 2 líneas con `\\n` en el punto que
        minimiza la diferencia de ancho entre ambas líneas. Si ninguna
        partición logra que ambas líneas quepan en max_width, elige la
        opción con menor desbordamiento.
        """
        palabras = text.split()
        if len(palabras) < 2:
            return text

        mejor_corte = -1
        mejor_score = float("inf")

        for corte in range(1, len(palabras)):
            linea1 = " ".join(palabras[:corte])
            linea2 = " ".join(palabras[corte:])
            ancho1 = fm.horizontalAdvance(linea1)
            ancho2 = fm.horizontalAdvance(linea2)
            # Penalizar fuerte el desbordamiento (cada px sobre max_width
            # pesa 10x el desbalance entre líneas).
            penal = 0
            if ancho1 > max_width:
                penal += (ancho1 - max_width) * 10
            if ancho2 > max_width:
                penal += (ancho2 - max_width) * 10
            score = abs(ancho1 - ancho2) + penal
            if score < mejor_score:
                mejor_score = score
                mejor_corte = corte

        if mejor_corte < 0:
            return text

        linea1 = " ".join(palabras[:mejor_corte])
        linea2 = " ".join(palabras[mejor_corte:])
        return f"{linea1}\n{linea2}"


def _formato_delta_humano(delta) -> str:
    """
    Convierte un timedelta en texto humano corto: '5 min', '3 h', '1 día',
    '12 días'. Para deltas negativos toma el valor absoluto (el caller
    decide si decir 'en X' o 'hace X').
    """
    total_segundos = abs(int(delta.total_seconds()))
    if total_segundos < 60:
        return "menos de 1 min"
    if total_segundos < 3600:
        return f"{total_segundos // 60} min"
    if total_segundos < 86400:
        horas = total_segundos // 3600
        return "1 h" if horas == 1 else f"{horas} h"
    dias = total_segundos // 86400
    return "1 día" if dias == 1 else f"{dias} días"


def _texto_tiempo_relativo(estado_visual: str, fi_str: str, ff_str: str) -> str:
    """
    Devuelve la línea de contexto que se muestra debajo del horario en
    cada card, similar a la que tiene la ficha de mantenimiento. Ejemplos:

        En curso         → "Termina en 3 días"
        Programado       → "Empieza en 5 días"
        Pendiente cierre → "Terminó hace 2 días"
        Cancelado        → "" (no se muestra; el color rojo ya basta)
        Finalizado       → "" (no aplica en esta pestaña)
    """
    try:
        ahora = datetime.now()
        fi = datetime.strptime(fi_str, "%Y-%m-%d %H:%M")
        ff = datetime.strptime(ff_str, "%Y-%m-%d %H:%M")
    except Exception:
        return ""

    if estado_visual == "En curso":
        delta = ff - ahora
        if delta.total_seconds() > 0:
            return f"Termina en {_formato_delta_humano(delta)}"
        return ""
    if estado_visual == "Programado":
        delta = fi - ahora
        if delta.total_seconds() > 0:
            return f"Empieza en {_formato_delta_humano(delta)}"
        return ""
    if estado_visual == "Pendiente cierre":
        delta = ahora - ff
        return f"Terminó hace {_formato_delta_humano(delta)}"
    return ""


# ══════════════════════════════════════════════════════════════════════
#  CARD DE MANTENIMIENTO
# ══════════════════════════════════════════════════════════════════════

class MantenimientoCard(QFrame):
    """
    Widget compacto que representa un mantenimiento en la lista. Reemplaza
    al sistema de QTableView + delegates de la versión anterior.

    Estructura visual (5 columnas, 2 líneas máximo):

        [Tipo (+⚠)]   [Equipos]               [Responsable]   [Inicio]      [Horario]
        100 px        flexible (2 líneas)     150 px          [Fin] 160 px  130 px

    Diseño:
        - Franja lateral izquierda del color del estado (border-left 3 px).
        - Fondo gris oscuro normal, tinte rojo si urgente.
        - Hover: levanta el fondo un tono.
        - Doble click → emite double_clicked(mant_id).
        - Click derecho → emite menu_solicitado(mant_id, pos_global).
    """

    double_clicked = pyqtSignal(int)
    menu_solicitado = pyqtSignal(int, QPoint)

    def __init__(self, datos, equipos_lineas, parent=None):
        """
        Args:
            datos: tupla del SELECT de obtener_mantenimientos() (ya
                   enriquecida con el formato de equipos en posición 10).
                   Índices clave:
                     [0] id, [1] tipo_mantenimiento, [2] urgente,
                     [3] fecha_inicio, [4] fecha_fin, [5] costo,
                     [7] responsable_nombre, [8] estado_db
            equipos_lineas: tupla (linea1, linea2, linea2_es_estado)
                            calculada previamente por
                            _formato_equipos_dos_lineas.
        """
        super().__init__(parent)
        self._mantenimiento_id = datos[0]
        self._datos = datos
        self._equipos_lineas = equipos_lineas
        self._estado_visual = calcular_estado(datos[8], datos[3], datos[4])
        self._urgente = bool(datos[2])

        self.setObjectName("card_mantenimiento")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.setMinimumHeight(56)

        self._aplicar_estilo()
        self._construir_ui()

    def _aplicar_estilo(self):
        color_estado = COLORES_ESTADO_HEX.get(self._estado_visual, "#888888")
        # Tinte rojo cuando urgente — coexiste con la franja del estado
        # para no perder la información de "en qué estado está".
        if self._urgente:
            bg, bg_hover = "#2a1818", "#341c1c"
        else:
            bg, bg_hover = "#1e1e1e", "#252525"
        self.setStyleSheet(f"""
            QFrame#card_mantenimiento {{
                background: {bg};
                border-radius: 6px;
                border-left: 3px solid {color_estado};
            }}
            QFrame#card_mantenimiento:hover {{
                background: {bg_hover};
            }}
        """)

    def _construir_ui(self):
        """
        Layout HORIZONTAL responsivo con stretch + minimumWidth.

        Los mins son lo más bajos que se puede para que en ventanas
        chicas todo quepa sin que el card se salga del scrollarea:
            - Tipo:        stretch 1, min 100px
            - Equipos:     stretch 2, min 130px (suficiente para
                                                 "UPAEP › Edificio K";
                                                 IDs más largos se
                                                 truncan con elipsis en
                                                 ventanas muy chicas)
            - Responsable: stretch 3, min 120px (con BalancedWrapLabel
                                                 el nombre se parte en
                                                 2 líneas balanceadas
                                                 cuando no cabe en 1.
                                                 Min 120 le permite a
                                                 "Mijangos Flores"
                                                 caber en la línea más
                                                 ancha del wrap)
            - Inicio/Fin:  stretch 2, min 130px (cabe "Fin: 30/09/2026"
                                                 que es ~120px)
            - Horario:     stretch 2, min 110px

        Por qué stretch 3 para Responsable nivela los huecos en max:
        Para que la distancia (hueco + spacing) entre cada par de
        columnas vecinas sea uniforme, cada columna necesita un ancho
        = contenido + k (constante). Como Responsable tiene contenido
        ~60px más largo que Equipos/Fechas, necesita ~60px más de
        ancho. Subir su stretch de 2 a 3 le da esos extras en max
        donde el contenido cabe en 1 línea.

        Por qué BalancedWrapLabel para Responsable en min:
        El wrap nativo de Qt parte "Cesar Andres Mijangos" + "Flores"
        (línea 1 casi al borde, línea 2 corta). BalancedWrapLabel
        encuentra el corte óptimo: "Cesar Andres" + "Mijangos Flores"
        — líneas más iguales, ancho efectivo menor → Responsable se
        ve más compacto y no parece pegado a Fechas.

        Total mins ≈ 590 + spacing 56 + padding card 28 = 674 → cabe
        en ventana ~800px (con sidebar ~130 + márgenes ~30).
        """
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(14)

        # ── Columna 1: Tipo (+ ícono ⚠ si urgente) ──
        col_tipo = self._build_tipo()
        col_tipo.setMinimumWidth(100)
        lay.addWidget(col_tipo, 1)

        # ── Columna 2: Equipos (2 líneas) ──
        col_eq = self._build_equipos()
        col_eq.setMinimumWidth(130)
        lay.addWidget(col_eq, 2)

        # ── Columna 3: Responsable ──
        col_resp = self._build_responsable()
        col_resp.setMinimumWidth(120)
        lay.addWidget(col_resp, 3)

        # ── Columna 4: Inicio / Fin (solo fechas, sin hora) ──
        col_fechas = self._build_fechas()
        col_fechas.setMinimumWidth(130)
        lay.addWidget(col_fechas, 2)

        # ── Columna 5: Horario + tiempo relativo ──
        col_hor = self._build_horario()
        col_hor.setMinimumWidth(110)
        lay.addWidget(col_hor, 2)

    def _build_tipo(self) -> QWidget:
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(5)

        lbl = QLabel(self._datos[1] or "—")
        lbl.setStyleSheet(
            "color: white; font-size: 12px; font-weight: 500; background: transparent;"
        )
        h.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

        if self._urgente:
            icono = QLabel()
            icono.setPixmap(
                qta.icon("fa5s.exclamation-triangle", color="#ff6b6b").pixmap(11, 11)
            )
            icono.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            h.addWidget(icono, alignment=Qt.AlignmentFlag.AlignVCenter)

        h.addStretch()
        return w

    def _build_equipos(self) -> QWidget:
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)

        linea1, linea2, linea2_es_estado = self._equipos_lineas

        lbl1 = ElideLabel(linea1)
        lbl1.setStyleSheet("color: white; font-size: 11px; background: transparent;")
        v.addWidget(lbl1)

        lbl2 = ElideLabel(linea2)
        if linea2_es_estado:
            lbl2.setStyleSheet(
                "color: #888; font-size: 10px; font-style: italic;"
                " background: transparent;"
            )
        else:
            lbl2.setStyleSheet(
                "color: #888; font-size: 10px; background: transparent;"
            )
        v.addWidget(lbl2)

        return w

    def _build_responsable(self) -> QWidget:
        """
        Responsable usa BalancedWrapLabel: si el nombre no cabe en 1 línea,
        se parte en 2 líneas BALANCEADAS (no como el wrap nativo de Qt que
        deja "Cesar Andres Mijangos" + "Flores" pegando la línea 1 al borde
        derecho, sino "Cesar Andres" + "Mijangos Flores" que reduce el
        ancho efectivo de la columna y hace que Responsable se vea más
        compacto/centrado).
        """
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        lbl = BalancedWrapLabel(self._datos[7] or "—")
        lbl.setStyleSheet("color: #ccc; font-size: 11px; background: transparent;")
        lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        v.addWidget(lbl)
        return w

    def _build_fechas(self) -> QWidget:
        """
        Columna Inicio / Fin: SOLO fechas (con año), sin hora. La hora va
        en la columna Horario para no duplicar la información.
        """
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)

        fi_txt = self._formato_fecha(self._datos[3])
        ff_txt = self._formato_fecha(self._datos[4])

        lbl_inicio = QLabel(
            f"<span style='color:#888;'>Inicio:</span> "
            f"<span style='color:#ccc;'>{fi_txt}</span>"
        )
        lbl_inicio.setStyleSheet("font-size: 11px; background: transparent;")
        lbl_inicio.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(lbl_inicio)

        lbl_fin = QLabel(
            f"<span style='color:#888;'>Fin:</span> "
            f"<span style='color:#ccc;'>{ff_txt}</span>"
        )
        lbl_fin.setStyleSheet("font-size: 11px; background: transparent;")
        lbl_fin.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(lbl_fin)

        return w

    def _build_horario(self) -> QWidget:
        """
        Horario (HH:MM - HH:MM) + línea de tiempo relativo debajo en
        gris tenue. Misma idea que la ficha de mantenimiento: "Termina
        en 3 días", "Empieza en 5 días", "Terminó hace 2 h".
        """
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)

        hi = self._extraer_hora(self._datos[3])
        hf = self._extraer_hora(self._datos[4])
        lbl_hor = QLabel(f"{hi} - {hf}")
        lbl_hor.setStyleSheet("color: #ccc; font-size: 11px; background: transparent;")
        v.addWidget(lbl_hor)

        # Tiempo relativo (solo si aplica; para Cancelado no se muestra).
        # Uso ElideLabel para que si la ventana es chica y "Empieza en
        # 102 días" no cabe entero, se trunque con elipsis en lugar de
        # cortarse sin avisar al usuario.
        texto_rel = _texto_tiempo_relativo(
            self._estado_visual, self._datos[3], self._datos[4]
        )
        if texto_rel:
            lbl_rel = ElideLabel(texto_rel)
            lbl_rel.setStyleSheet(
                "color: #888; font-size: 10px; background: transparent;"
            )
            v.addWidget(lbl_rel)

        return w

    @staticmethod
    def _formato_fecha(iso_str) -> str:
        """'2026-06-23 09:00' → '23/06/2026' (sin hora — esa va aparte)."""
        if not iso_str:
            return "—"
        try:
            dt = datetime.strptime(iso_str, "%Y-%m-%d %H:%M")
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return str(iso_str)

    @staticmethod
    def _extraer_hora(iso_str) -> str:
        """Saca HH:MM del string ISO."""
        if not iso_str or " " not in iso_str:
            return "--:--"
        hora = iso_str.split(" ", 1)[1]
        return hora[:5]

    # ── Eventos ────────────────────────────────────────────────────────
    def mouseDoubleClickEvent(self, event):
        """
        Doble click → abre la ficha de detalle.

        IMPORTANTE: la emisión de double_clicked se difiere con
        QTimer.singleShot(0, ...). Razón: el slot conectado abre la ficha
        de mantenimiento con dialog.exec(), que bloquea hasta que se
        cierre. Durante ese exec(), el event loop sigue corriendo y otras
        señales (en particular app_signals.mantenimiento_guardado, que se
        emite cuando el usuario edita/cierra desde la propia ficha) pueden
        ejecutar recargar_datos → _limpiar_contenido → DESTRUIR esta card.
        Al volver de exec() y de mouseDoubleClickEvent, Qt intenta hacer
        post-procesamiento sobre el widget eliminado y crashea con
        'RuntimeError: wrapped C/C++ object has been deleted'.

        Diferir con singleShot(0) deja que mouseDoubleClickEvent termine
        de procesarse antes de que se ejecute el slot, eliminando la
        ventana de oportunidad para el crash.
        """
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            mant_id = self._mantenimiento_id
            QTimer.singleShot(0, lambda: self._safe_emit_double_click(mant_id))

    def _safe_emit_double_click(self, mant_id):
        """Emite double_clicked tolerando que self haya sido destruido
        entre el doble click y este tick del event loop (improbable
        porque singleShot(0) corre antes del próximo tick de los timers,
        pero defensivo por si acaso)."""
        try:
            self.double_clicked.emit(mant_id)
        except RuntimeError:
            # Self fue destruido. Ya no podemos hacer nada — el callback
            # ya no aplica y no hay que abrir nada.
            pass

    def _on_context_menu(self, pos: QPoint):
        """
        Click derecho → mismo patrón que doble click: diferir la emisión.
        El menú contextual abre un QMenu con exec(), igual que la ficha,
        y los slots de sus acciones pueden destruir esta card.
        """
        mant_id = self._mantenimiento_id
        pos_global = self.mapToGlobal(pos)
        QTimer.singleShot(
            0, lambda: self._safe_emit_menu(mant_id, pos_global)
        )

    def _safe_emit_menu(self, mant_id, pos_global):
        """Emite menu_solicitado tolerando self destruido."""
        try:
            self.menu_solicitado.emit(mant_id, pos_global)
        except RuntimeError:
            pass


# ══════════════════════════════════════════════════════════════════════
#  HEADER DE SECCIÓN (En curso · 2, Programado · 12, …)
# ══════════════════════════════════════════════════════════════════════

def _build_seccion_header(estado: str, count: int) -> QWidget:
    """
    Header tenue de cada sección de estado: un punto del color del estado
    + el nombre del estado en MAYÚSCULAS + el contador.
    Solo se usa en modo "Todos" (en vista filtrada por un estado los
    headers son redundantes).
    """
    color = COLORES_ESTADO_HEX.get(estado, "#888")

    w = QWidget()
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 10, 0, 4)
    h.setSpacing(6)

    punto = QLabel()
    punto.setFixedSize(6, 6)
    punto.setStyleSheet(f"background: {color}; border-radius: 3px;")
    h.addWidget(punto, alignment=Qt.AlignmentFlag.AlignVCenter)

    lbl = QLabel(f"{estado.upper()} · {count}")
    lbl.setStyleSheet(
        f"color: {color}; font-size: 10px; font-weight: 500;"
        f" letter-spacing: 1px; background: transparent;"
    )
    h.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
    h.addStretch()

    return w


# ══════════════════════════════════════════════════════════════════════
#  WIDGET PRINCIPAL — ProgramadosWidget
# ══════════════════════════════════════════════════════════════════════

class ProgramadosWidget(QWidget):
    """
    Pestaña "Programados". Reemplaza al QTableView + delegates por una
    lista de MantenimientoCard agrupada por estado, con buscador y filtros
    tipo pills.

    Refresh:
      - timer_visual (1 s): recalcula estados (puede mover una card entre
        secciones si cruzó la frontera "En curso ↔ Pendiente cierre").
      - timer_bd (60 s): vuelve a leer BD por si otro flujo agregó/cambió
        mantenimientos.
      - Señal app_signals.mantenimiento_guardado: recarga inmediata al
        guardar desde "Nuevo" o cuando se edita/cierra.
    """

    def __init__(self):
        super().__init__()
        # Estado interno
        self._datos_crudos = []           # tuplas crudas de obtener_mantenimientos
        self._jerarquia = {}              # id_grupo → grupo dict
        self._grupo_por_equipo = {}       # (eq_id, eq_tipo) → grupo_id
        self._filtro_activo = "todos"
        self._texto_busqueda = ""
        self._ultimos_estados = None

        # Debounce del buscador: evita re-renderizar la vista completa por
        # cada tecla. Cuando el usuario escribe o borra rápido (o mantiene
        # backspace), el timer se reinicia con cada textChanged y solo
        # dispara _render() 150 ms después de la última tecla. Umbral por
        # debajo del cual la UI se percibe instantánea al usuario.
        self._debounce_busqueda = QTimer(self)
        self._debounce_busqueda.setSingleShot(True)
        self._debounce_busqueda.setInterval(150)
        self._debounce_busqueda.timeout.connect(self._render)

        self.init_ui()

        # Refresh visual cada 1 s (sin tocar BD): detecta transiciones de
        # estado por puro paso del tiempo (En curso → Pendiente cierre).
        self._timer_visual = QTimer(self)
        self._timer_visual.timeout.connect(self._tick_visual)
        self._timer_visual.start(1000)

        # Refresh real desde BD cada 60 s: rescata cambios hechos desde
        # otras pestañas o procesos.
        self._timer_bd = QTimer(self)
        self._timer_bd.timeout.connect(self.recargar_datos)
        self._timer_bd.start(60000)

        # Señal global de "se guardó algo" → recarga inmediata
        try:
            from signals import app_signals
            app_signals.mantenimiento_guardado.connect(self.recargar_datos)
        except Exception:
            # Si signals.py no existe / no tiene la señal, no rompemos
            pass

    # ===================== CONSTRUCCIÓN UI =====================
    def init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(10)

        lay.addWidget(self._build_header())
        lay.addWidget(self._build_buscador_y_pills())
        lay.addWidget(self._build_scrollarea(), 1)

        self.recargar_datos()

    def _build_header(self) -> QWidget:
        """Header con ícono qtawesome + título + subtítulo (sin contador
        suelto — el contador total ya vive en la pill 'Todos · N')."""
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        titulo_row = QHBoxLayout()
        titulo_row.setSpacing(10)
        titulo_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        icono = QLabel()
        icono.setPixmap(qta.icon("fa5s.calendar-alt", color="#ddd").pixmap(22, 22))
        icono.setFixedSize(22, 22)
        titulo_row.addWidget(icono, alignment=Qt.AlignmentFlag.AlignVCenter)

        titulo = QLabel("Mantenimientos programados")
        titulo.setStyleSheet(
            "color: white; font-size: 22px; font-weight: 500; background: transparent;"
        )
        titulo_row.addWidget(titulo, alignment=Qt.AlignmentFlag.AlignVCenter)
        titulo_row.addStretch()
        v.addLayout(titulo_row)

        subtitulo = QLabel("Eventos próximos, en curso y pendientes de cierre")
        subtitulo.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
        subtitulo.setContentsMargins(32, 0, 0, 0)
        v.addWidget(subtitulo)

        return container

    def _build_buscador_y_pills(self) -> QWidget:
        """Barra horizontal: buscador a la izquierda + pills a la derecha."""
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 6, 0, 4)
        h.setSpacing(8)

        # Buscador
        self.input_busqueda = QLineEdit()
        self.input_busqueda.setPlaceholderText("Buscar equipo, responsable…")
        self.input_busqueda.setFixedHeight(30)
        self.input_busqueda.setMinimumWidth(220)
        self.input_busqueda.setMaximumWidth(280)
        self.input_busqueda.setStyleSheet("""
            QLineEdit {
                background: #2b2b2b; color: #ddd; border: 1px solid #333;
                border-radius: 6px; padding: 4px 10px; font-size: 11px;
            }
            QLineEdit:focus { border: 1px solid #0078d7; }
        """)
        self.input_busqueda.textChanged.connect(self._on_busqueda_changed)
        h.addWidget(self.input_busqueda)

        # Pills
        self._pills = {}
        estados_visibles = [
            ("todos", "Todos"),
            ("En curso", "En curso"),
            ("Programado", "Programado"),
            ("Pendiente cierre", "Pendiente cierre"),
            ("Cancelado", "Cancelado"),
        ]
        for key, label in estados_visibles:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._pill_style(activo=(key == "todos")))
            btn.clicked.connect(lambda checked=False, k=key: self._cambiar_filtro(k))
            h.addWidget(btn)
            self._pills[key] = btn

        h.addStretch()
        return container

    def _build_scrollarea(self) -> QScrollArea:
        """ScrollArea con un QWidget contenedor que se reconstruye en cada
        render. Las cards y los headers de sección viven aquí dentro."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: transparent; width: 10px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #444; border-radius: 4px;
                min-height: 30px; margin: 2px;
            }
            QScrollBar::handle:vertical:hover { background: #555; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                background: none; height: 0; border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        # Widget contenedor + layout dinámico. _render() llama a
        # _limpiar_contenido() y vuelve a poblar.
        self._contenido = QWidget()
        self._contenido_lay = QVBoxLayout(self._contenido)
        self._contenido_lay.setContentsMargins(0, 0, 8, 0)  # margen derecho para no tapar scrollbar
        self._contenido_lay.setSpacing(4)
        self._contenido_lay.addStretch()  # stretch al final, empuja todo arriba

        scroll.setWidget(self._contenido)
        return scroll

    # ===================== ESTILOS DE PILLS =====================
    def _pill_style(self, activo: bool) -> str:
        if activo:
            return """
                QPushButton {
                    background: #0078d7; color: white; border: none;
                    padding: 5px 12px; border-radius: 12px;
                    font-size: 11px; font-weight: 500;
                }
                QPushButton:hover { background: #0094ff; }
            """
        return """
            QPushButton {
                background: #2b2b2b; color: #aaa; border: none;
                padding: 5px 12px; border-radius: 12px; font-size: 11px;
            }
            QPushButton:hover { background: #353535; color: #ccc; }
        """

    # ===================== EVENTOS DE FILTRO / BÚSQUEDA =====================
    def _cambiar_filtro(self, key: str):
        if key == self._filtro_activo:
            return
        self._filtro_activo = key
        for k, btn in self._pills.items():
            btn.setStyleSheet(self._pill_style(activo=(k == key)))
        self._render()

    def _on_busqueda_changed(self, texto: str):
        # Actualizar el texto de búsqueda inmediatamente, pero disparar
        # el render con debounce. start() reinicia el timer si ya estaba
        # corriendo — así, si el usuario sigue tecleando, no se ejecutan
        # renders intermedios (solo el final, 150 ms después de la última
        # tecla). Ver __init__ para el detalle del timer.
        self._texto_busqueda = texto.strip().lower()
        self._debounce_busqueda.start()

    # ===================== TIMERS =====================
    def _tick_visual(self):
        """Cada 1 s: si algún estado cambió por paso del tiempo, re-render."""
        if not self._datos_crudos:
            return
        estados_actuales = tuple(
            calcular_estado(m[8], m[3], m[4]) for m in self._datos_crudos
        )
        if estados_actuales != self._ultimos_estados:
            self._ultimos_estados = estados_actuales
            self._render()

    # ===================== CARGA / REFRESH =====================
    def recargar_datos(self):
        """Recarga datos desde BD + jerarquía de grupos."""
        self._datos_crudos = obtener_mantenimientos() or []
        self._jerarquia = _cargar_jerarquia_grupos()
        self._grupo_por_equipo = _cargar_grupos_de_equipos()
        self._ultimos_estados = None
        self._render()

    def _render(self):
        """
        Núcleo del rendering. NO toca BD. Pasos:
            1. Pre-calcular tupla (datos, equipos_lineas, estado, texto_busqueda)
               para cada mantenimiento.
            2. Calcular contadores de cada estado SOBRE EL TOTAL (antes de
               filtrar) para que las pills siempre muestren reales.
            3. Aplicar filtro de búsqueda (si hay texto).
            4. Aplicar filtro de pill (si no es "todos").
            5. Ordenar por prioridad de estado + fecha_inicio.
            6. Limpiar contenido del scrollarea.
            7. Construir headers de sección + cards.
                - En modo "todos": agrupado por estado con headers.
                - En modo filtrado: lista plana.
        """
        # ── 1. Pre-cálculo enriquecido ──
        items = []
        for m in self._datos_crudos:
            equipos_raw = m[9] if len(m) > 9 else None
            equipos_lineas = _formato_equipos_dos_lineas(
                equipos_raw, self._grupo_por_equipo, self._jerarquia
            )
            estado = calcular_estado(m[8], m[3], m[4])
            # Texto búsqueda concatena los campos donde se permite buscar
            texto_busq = " ".join([
                str(equipos_lineas[0] or ""),
                str(equipos_lineas[1] or ""),
                str(m[7] or ""),  # responsable
                str(m[1] or ""),  # tipo
            ]).lower()
            items.append({
                "datos": m,
                "equipos_lineas": equipos_lineas,
                "estado": estado,
                "texto_busq": texto_busq,
            })

        # ── 2. Contadores por estado (sobre el dataset completo) ──
        contadores = {
            "En curso": 0, "Programado": 0,
            "Pendiente cierre": 0, "Cancelado": 0,
        }
        for it in items:
            if it["estado"] in contadores:
                contadores[it["estado"]] += 1
        total = sum(contadores.values())
        self._actualizar_etiquetas_pills(contadores, total)

        # ── 3. Filtro de búsqueda ──
        if self._texto_busqueda:
            items = [
                it for it in items if self._texto_busqueda in it["texto_busq"]
            ]

        # ── 4. Filtro de pill ──
        if self._filtro_activo != "todos":
            items = [it for it in items if it["estado"] == self._filtro_activo]

        # ── 5. Ordenar ──
        prioridad_estado = {
            "En curso": 0,
            "Programado": 1,
            "Pendiente cierre": 2,
            "Cancelado": 3,
            "Finalizado": 4,
        }
        def clave(it):
            try:
                fi = datetime.strptime(it["datos"][3], "%Y-%m-%d %H:%M")
            except Exception:
                fi = datetime.max
            return (prioridad_estado.get(it["estado"], 99), fi)
        items.sort(key=clave)

        # ── 6. Limpiar y reconstruir ──
        self._limpiar_contenido()

        if not items:
            self._mostrar_estado_vacio()
            return

        if self._filtro_activo == "todos":
            self._render_agrupado(items, contadores)
        else:
            self._render_plano(items)

    def _render_agrupado(self, items, contadores):
        """En modo 'Todos': insertar headers por estado + cards."""
        ultimo_estado = None
        for it in items:
            if it["estado"] != ultimo_estado:
                # Insertar header de sección
                header = _build_seccion_header(
                    it["estado"], contadores.get(it["estado"], 0)
                )
                self._contenido_lay.insertWidget(
                    self._contenido_lay.count() - 1, header
                )
                ultimo_estado = it["estado"]
            self._insertar_card(it)

    def _render_plano(self, items):
        """Vista filtrada por un estado: solo cards, sin headers."""
        for it in items:
            self._insertar_card(it)

    def _insertar_card(self, it):
        card = MantenimientoCard(it["datos"], it["equipos_lineas"])
        card.double_clicked.connect(self._abrir_ficha)
        card.menu_solicitado.connect(self._mostrar_menu_contextual)
        # Insertar JUSTO ANTES del stretch (último widget del layout)
        self._contenido_lay.insertWidget(self._contenido_lay.count() - 1, card)

    def _mostrar_estado_vacio(self):
        """Mensaje cuando no hay resultados (búsqueda sin match, etc)."""
        msg = QLabel("Sin resultados.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(
            "color: #666; font-size: 12px; font-style: italic;"
            " background: transparent; padding: 40px 0;"
        )
        self._contenido_lay.insertWidget(self._contenido_lay.count() - 1, msg)

    def _limpiar_contenido(self):
        """Borra TODOS los widgets del contenido excepto el stretch final."""
        # El último item del layout es el stretch (addStretch), que es un
        # spacer item, no un widget. Lo dejamos. Los demás los eliminamos.
        while self._contenido_lay.count() > 1:
            item = self._contenido_lay.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                # NOTA: hide() en vez de setParent(None). En Windows,
                # setParent(None) promueve el widget a ventana top-level
                # durante el ciclo del event loop hasta que deleteLater()
                # lo destruye, produciendo un parpadeo de ventana huérfana
                # con el icono de python.exe. Con muchos registros y
                # renders frecuentes (buscador por tecla), esto genera una
                # tormenta de ventanas parpadeantes. hide() oculta el
                # widget antes de que pueda pintarse como top-level.
                w.hide()
                w.deleteLater()

    def _actualizar_etiquetas_pills(self, contadores, total):
        """Refresca el texto de cada pill con su contador."""
        self._pills["todos"].setText(f"Todos · {total}")
        for key in ("En curso", "Programado", "Pendiente cierre", "Cancelado"):
            self._pills[key].setText(f"{key} · {contadores[key]}")

    # ===================== ACCIONES (doble click / menú) =====================
    def _abrir_ficha(self, mant_id: int):
        from ficha_mantenimiento import FichaMantenimientoDialog
        dialog = FichaMantenimientoDialog(mant_id, self)
        dialog.exec()

    def _mostrar_menu_contextual(self, mant_id: int, pos_global: QPoint):
        menu = QMenu(self)
        act_ver = menu.addAction("Ver detalle")
        accion = menu.exec(pos_global)
        if accion == act_ver:
            self._abrir_ficha(mant_id)
