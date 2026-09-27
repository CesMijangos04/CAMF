"""
card_calendario.py — Card y modal del calendario para la pestaña Inicio.

Contiene:
    CalendarioMes            — card compacta con marcadores por día
                               (misma vista que la card original de inicio.py)
                               + botón "expandir" en la esquina superior derecha
                               que emite la señal `expandir_solicitado`.

    DialogCalendarioExpandido — modal grande con vista split:
                                · panel izquierdo: calendario navegable mes a mes
                                · panel derecho:   eventos del día seleccionado

El overlay oscuro y el ciclo de vida del modal los maneja el llamador
(InicioWindow._abrir_modal_calendario), replicando el patrón que ya
existe para DialogNotificacionesExpandido. Este archivo no importa
nada de inicio.py — es auto-contenido para poder migrarse limpio
cuando llegue la reorganización total a fronted/inicio/.

Criterio de datos (DESCRIPTIVO, no accionable):
    · Se muestran TODOS los mantenimientos programados del mes,
      con o sin responsable asignado. La analogía es un calendario
      de teléfono: un cumpleaños existe aunque nadie haya "asignado"
      a alguien a felicitar.
    · La accionabilidad de "falta asignar responsable" vive en la card
      de notificaciones, no aquí.
    · Filtro por default: "Programados y vencidos". Opción alterna:
      "Incluir finalizados" (útil al navegar meses históricos).
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QScrollArea, QDialog, QPushButton, QComboBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
import qtawesome as qta
import calendar
from datetime import date, timedelta

from db_manager import connect_db


# ==========================================================
#  Paleta y constantes locales
#  Duplicadas de inicio.py para que este archivo sea
#  auto-contenido. Al hacer la migración total a fronted/inicio/
#  se colapsan a un constantes.py compartido.
# ==========================================================
COLOR_BG         = "#1e1e1e"
COLOR_CARD       = "#2b2b2b"
COLOR_BORDER     = "#2a2a2a"
COLOR_TEXT       = "#e0e0e0"
COLOR_TEXT_DIM   = "#888888"
COLOR_TEXT_FAINT = "#666666"
COLOR_OTRO_MES   = "#3a3a3a"
COLOR_ACCENT     = "#0078d7"
COLOR_ACCENT_LT  = "#4a9eff"
COLOR_DANGER     = "#d9534f"
COLOR_WARNING    = "#e8a33d"
COLOR_SUCCESS    = "#5cb85c"

# ── Colores de estado de mantenimiento ────────────────────────────
# Sincronizados con la paleta de programados.py (COLORES_ESTADO_HEX)
# para que el mismo evento se vea con el mismo color en las dos vistas:
# Inicio → Calendario y Mantenimientos → Programados. Se declaran como
# constantes separadas de COLOR_WARNING/DANGER/etc porque esos siguen
# usándose para semántica genérica (avatar de proveedor, íconos de
# error, badges) que no siempre coincide con el estado de un mantto.
#
# Nota sobre "Vencido": en programados.py el mismo estado semántico
# se llama "Pendiente cierre" y usa naranja (no rojo). Aquí lo dejamos
# con la etiqueta "Vencido" que es como Cesar lo llama en el calendario,
# pero con el mismo hex — así un mantto pendiente de cierre se ve
# idéntico en ambas vistas.
ESTADO_PROGRAMADO = "#4a90e2"   # azul suave
ESTADO_EN_CURSO   = "#f1c40f"   # amarillo brillante
ESTADO_VENCIDO    = "#e67e22"   # naranja (= "Pendiente cierre" en programados.py)
ESTADO_FINALIZADO = "#27ae60"   # verde saturado

MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]
DIAS_NOMBRE  = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DIAS_INICIAL = ["L", "M", "M", "J", "V", "S", "D"]


def _label(texto, color=COLOR_TEXT, tamaño=12, peso="normal"):
    """Helper local — mismo look que crear_label de inicio.py."""
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"""
        color: {color};
        font-size: {tamaño}px;
        font-weight: {peso};
        border: none;
        background: transparent;
    """)
    return lbl


# ==========================================================
#  Helpers de grupos (árbol jerárquico)
#  Réplicas locales de los helpers de programados.py.
#  Al hacer la migración total se colapsan a un helpers.py
#  compartido; por ahora viven aquí para mantener este archivo
#  auto-contenido y sin imports cruzados entre pestañas.
# ==========================================================
def _cargar_jerarquia_grupos(cur):
    """Devuelve {grupo_id: (nombre, padre_id)} con TODOS los grupos.

    Cargar el árbol completo en memoria una vez y resolver rutas por
    lookup es mucho más rápido que hacer una query recursiva por cada
    equipo. Como el número de grupos es chico, cabe holgado.
    """
    rows = cur.execute(
        "SELECT id, nombre, padre_id FROM grupos"
    ).fetchall()
    return {g[0]: (g[1], g[2]) for g in rows}


def _ruta_grupo(grupo_id, jerarquia):
    """Construye la cadena 'Edificio A › Piso 2' subiendo desde el
    grupo dado hasta la raíz. El separador " › " es intencional —
    misma convención que programados.py y la card de notificaciones
    para que las tres vistas se lean iguales.

    Protección anti-ciclo por si los datos vienen corruptos: si un
    grupo apunta a sí mismo (directa o indirectamente por su cadena
    de ancestros), se corta al detectarlo en vez de colgar el loop.
    """
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


# ==========================================================
#  Query compartida — días del mes con eventos por estado
#  Extraída como función a nivel de módulo para que la usen
#  tanto CalendarioMes (card compacta en Inicio) como
#  DialogCalendarioExpandido (modal grande). Antes vivía como
#  método del diálogo — ahora está aquí para que las dos vistas
#  del calendario compartan exactamente el mismo criterio.
# ==========================================================
def _obtener_dias_con_eventos_mes(año, mes, incluir_finalizados=False):
    """Devuelve cuatro sets: (programados, en_curso, vencidos, finalizados).

    Los tres primeros comparten estado='programado' en BD y se
    distinguen por comparación de las fechas del evento con hoy:

      - programado: fecha_inicio > hoy         → aún no arranca
      - en_curso:   fecha_inicio ≤ hoy ≤ fecha_fin  → está corriendo
      - vencido:    fecha_fin < hoy            → pasó su ventana
                                                 sin cerrarse

    Cada evento programado se expande a TODOS los días del mes
    que caen dentro de su rango [fecha_inicio, fecha_fin]. Un
    mantto de varios días pinta puntos en cada uno de sus días,
    no solo en el de arranque. La categoría (programado/en_curso/
    vencido) es del EVENTO, no de cada día — todos sus días
    comparten el mismo color.

    Finalizados quedan como marca puntual del día de cierre
    (fecha_cierre, con fallback a fecha_fin) — no se expanden
    porque el "finalizado" no es un estado activo de varios
    días, es un evento discreto del día que se cerró.

    Criterio DESCRIPTIVO (todos los eventos programados del mes,
    con o sin responsable). No se filtra por responsable_tipo, a
    diferencia del KPI Pendientes.
    """
    programados = set()
    en_curso    = set()
    vencidos    = set()
    finalizados = set()

    conn = connect_db(create_if_missing=False)
    if conn is None:
        return programados, en_curso, vencidos, finalizados

    try:
        cur = conn.cursor()

        primer_dia = date(año, mes, 1)
        ultimo_dia = date(año, mes, calendar.monthrange(año, mes)[1])
        primer_dia_iso = primer_dia.isoformat()
        ultimo_dia_iso = ultimo_dia.isoformat()
        hoy_iso = date.today().isoformat()

        # Programados: eventos con estado='programado' cuyo rango
        # [fecha_inicio, fecha_fin] intersecta el mes.
        rows_prog = cur.execute("""
            SELECT fecha_inicio, fecha_fin
            FROM mantenimientos
            WHERE estado = 'programado'
              AND fecha_inicio IS NOT NULL
              AND fecha_fin    IS NOT NULL
              AND date(fecha_inicio) <= date(?)
              AND date(fecha_fin)    >= date(?)
        """, (ultimo_dia_iso, primer_dia_iso)).fetchall()

        for f_ini, f_fin in rows_prog:
            f_ini_iso = f_ini[:10]
            f_fin_iso = f_fin[:10]

            # Clasificamos el evento entero según hoy. Todos sus
            # días llevan el mismo color.
            if f_fin_iso < hoy_iso:
                target = vencidos
            elif f_ini_iso > hoy_iso:
                target = programados
            else:
                target = en_curso

            try:
                dt_ini = date.fromisoformat(f_ini_iso)
                dt_fin = date.fromisoformat(f_fin_iso)
            except ValueError:
                continue

            desde = max(dt_ini, primer_dia)
            hasta = min(dt_fin, ultimo_dia)

            d = desde
            while d <= hasta:
                target.add(d.day)
                d = d + timedelta(days=1)

        if incluir_finalizados:
            # Mismo criterio que el KPI "Hechos este mes" de inicio.py:
            # fecha_cierre IS NOT NULL y en el mes consultado. Antes
            # usábamos COALESCE(fecha_cierre, fecha_fin) como fallback
            # pero eso hacía que el calendario contara manttos que el
            # KPI no cuenta (los que quedaron finalizados sin fecha_cierre
            # registrada). Alineado ahora — el usuario ve el mismo total
            # entre KPI y puntos verdes del calendario. Los manttos con
            # fecha_cierre NULL son casos raros (datos migrados o
            # incompletos) que deben investigarse aparte.
            for (f_cierre,) in cur.execute("""
                SELECT DISTINCT CAST(strftime('%d', fecha_cierre) AS INTEGER)
                FROM mantenimientos
                WHERE estado = 'finalizado'
                  AND fecha_cierre IS NOT NULL
                  AND strftime('%Y-%m', fecha_cierre) = ?
            """, (f"{año:04d}-{mes:02d}",)).fetchall():
                if f_cierre:
                    finalizados.add(f_cierre)

    except Exception as e:
        print(f"[Calendario] error al obtener días con eventos: {e}")
    finally:
        conn.close()

    return programados, en_curso, vencidos, finalizados


# ==========================================================
#  CARD COMPACTA DEL MES
# ==========================================================
class CalendarioMes(QFrame):
    """Vista de mes (sin interacción sobre las celdas) con marcadores:
        - punto azul = mantenimiento programado
        - punto rojo = mantenimiento vencido
        - fondo azul tenue = hoy

    Cambios vs. la versión original de inicio.py:
        1) Botón "expandir" en la esquina superior derecha (siempre visible,
           a diferencia del de notificaciones que se oculta cuando no hay
           items: el calendario sirve para navegar meses aunque el mes
           actual no tenga eventos).
        2) Señal `expandir_solicitado` que el padre (InicioWindow) conecta
           a su método que instancia overlay + DialogCalendarioExpandido.
           El calendario no sabe nada del overlay ni del diálogo —
           mismo patrón desacoplado que ya usan las notificaciones.
    """

    expandir_solicitado = pyqtSignal()

    def __init__(self, año=None, mes=None,
                 dias_programados=None, dias_en_curso=None,
                 dias_vencidos=None, parent=None):
        super().__init__(parent)
        hoy = date.today()
        self.año = año if año is not None else hoy.year
        self.mes = mes if mes is not None else hoy.month
        self.dia_hoy = hoy.day if (self.año == hoy.year and self.mes == hoy.month) else None

        # Si no nos pasaron los sets desde afuera, los consultamos
        # nosotros mismos con la función de módulo. Es el caso normal
        # ahora — inicio.py ya no pre-calcula estos datos y confía en
        # que la card se autoabastece. Se mantienen los parámetros
        # opcionales por compatibilidad y por si alguna vista futura
        # quiere pre-cargar los datos por su cuenta.
        if dias_programados is None and dias_en_curso is None and dias_vencidos is None:
            prog, encur, venc, _fin = _obtener_dias_con_eventos_mes(
                self.año, self.mes, incluir_finalizados=False
            )
            self.programados = prog
            self.en_curso    = encur
            self.vencidos    = venc
        else:
            self.programados = set(dias_programados or [])
            self.en_curso    = set(dias_en_curso or [])
            self.vencidos    = set(dias_vencidos or [])

        self.setObjectName("calCard")
        self.setStyleSheet(f"""
            QFrame#calCard {{
                background-color: {COLOR_CARD};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # ─── Encabezado: mes + botón expandir ───
        # Sin leyenda de colores en la card compacta. El usuario ve
        # los puntos como "algo pasa ese día" y expande la card para
        # aprender qué significa cada color — la leyenda vive en el
        # modal expandido, que además tiene el filtro de finalizados.
        # Así se libera espacio horizontal para el título y el botón.
        encab = QHBoxLayout()
        encab.setContentsMargins(0, 0, 0, 0)
        encab.setSpacing(6)

        encab.addWidget(_label(
            f"{MESES_ES[self.mes]} {self.año}",
            color=COLOR_TEXT, tamaño=14, peso="600"
        ))
        encab.addStretch()

        btn_expandir = QPushButton()
        btn_expandir.setIcon(qta.icon("fa5s.expand-alt", color=COLOR_TEXT_DIM))
        btn_expandir.setIconSize(QSize(14, 14))
        btn_expandir.setFixedSize(26, 26)
        btn_expandir.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_expandir.setToolTip("Ver calendario completo")
        btn_expandir.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 0;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.05);
            }
        """)
        btn_expandir.clicked.connect(self.expandir_solicitado)
        encab.addWidget(btn_expandir)

        layout.addLayout(encab)

        # ─── Grilla del mes ───
        grid = QGridLayout()
        grid.setSpacing(3)
        for i in range(7):
            grid.setColumnStretch(i, 1)

        for i, letra in enumerate(DIAS_INICIAL):
            lbl = _label(letra, color=COLOR_TEXT_FAINT, tamaño=10)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(lbl, 0, i)

        for r, c, dia, es_actual in self._iterar_celdas():
            es_hoy = (self.dia_hoy is not None and dia == self.dia_hoy and es_actual)
            es_finde = c >= 5
            programado = es_actual and dia in self.programados
            en_curso   = es_actual and dia in self.en_curso
            vencido    = es_actual and dia in self.vencidos
            celda = self._crear_celda(
                dia, hoy=es_hoy, finde=es_finde,
                otro_mes=not es_actual,
                programado=programado, en_curso=en_curso, vencido=vencido
            )
            grid.addWidget(celda, r + 1, c)

        layout.addLayout(grid)

    def _iterar_celdas(self):
        calendar.setfirstweekday(calendar.MONDAY)
        semanas = calendar.monthcalendar(self.año, self.mes)

        if self.mes == 1:
            mes_ant, año_ant = 12, self.año - 1
        else:
            mes_ant, año_ant = self.mes - 1, self.año
        ultimo_dia_anterior = calendar.monthrange(año_ant, mes_ant)[1]

        zeros_inicio = 0
        for d in semanas[0]:
            if d == 0:
                zeros_inicio += 1
            else:
                break

        dia_prox = 1
        for r, semana in enumerate(semanas):
            for c, d in enumerate(semana):
                if d == 0:
                    if r == 0 and c < zeros_inicio:
                        dia = ultimo_dia_anterior - (zeros_inicio - c - 1)
                        yield (r, c, dia, False)
                    else:
                        yield (r, c, dia_prox, False)
                        dia_prox += 1
                else:
                    yield (r, c, d, True)

    def _leyenda(self, texto, color):
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        h = QHBoxLayout(cont)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(5)
        punto = QLabel()
        punto.setFixedSize(6, 6)
        punto.setStyleSheet(f"background-color: {color}; border-radius: 3px; border: none;")
        h.addWidget(punto)
        h.addWidget(_label(texto, color=COLOR_TEXT_DIM, tamaño=11))
        return cont

    def _crear_celda(self, dia, hoy=False, finde=False, otro_mes=False,
                     programado=False, en_curso=False, vencido=False):
        celda = QFrame()
        celda.setObjectName("calCell")

        if hoy:
            bg, color, peso = "rgba(0, 120, 215, 0.20)", COLOR_ACCENT, "bold"
        elif otro_mes:
            bg, color, peso = "transparent", COLOR_OTRO_MES, "normal"
        elif finde:
            bg, color, peso = "transparent", COLOR_TEXT_FAINT, "normal"
        else:
            bg, color, peso = "transparent", COLOR_TEXT, "normal"

        celda.setStyleSheet(f"""
            QFrame#calCell {{
                background-color: {bg};
                border-radius: 4px;
                border: none;
            }}
        """)
        celda.setMinimumHeight(38)

        v = QVBoxLayout(celda)
        v.setContentsMargins(0, 5, 0, 5)
        v.setSpacing(2)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = _label(str(dia), color=color, tamaño=12, peso=peso)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(lbl)

        # Puntos indicadores — hasta 3 apilados horizontalmente en
        # orden de gravedad visual: vencido → en curso → programado.
        # No se pintan finalizados en la card compacta (esos son
        # historia, sin urgencia; se ven solo en el modal con filtro).
        cont_punto = QWidget()
        cont_punto.setFixedHeight(6)
        cont_punto.setStyleSheet("background: transparent; border: none;")
        hp = QHBoxLayout(cont_punto)
        hp.setContentsMargins(0, 0, 0, 0)
        hp.setSpacing(2)
        hp.addStretch()
        if vencido:
            hp.addWidget(self._punto(ESTADO_VENCIDO))
        if en_curso:
            hp.addWidget(self._punto(ESTADO_EN_CURSO))
        if programado:
            hp.addWidget(self._punto(ESTADO_PROGRAMADO))
        hp.addStretch()
        v.addWidget(cont_punto)

        return celda

    def _punto(self, color):
        p = QLabel()
        p.setFixedSize(5, 5)
        p.setStyleSheet(f"background-color: {color}; border-radius: 2px; border: none;")
        return p


# ==========================================================
#  DIÁLOGO EXPANDIDO
# ==========================================================
class DialogCalendarioExpandido(QDialog):
    """Modal grande con vista split calendario / eventos del día.

    - Al abrir: día seleccionado = hoy. Si hoy no tiene eventos, el
      panel derecho muestra estado vacío pero el calendario resalta hoy.
    - Navegación de mes con chevrones. Al cambiar de mes, si el día
      seleccionado no existe en el nuevo mes (ej. 31 en febrero) se
      baja al último día del mes.
    - Click en una celda → selecciona ese día y refresca el panel
      derecho con sus eventos.
    - Click en una card de evento → abre FichaMantenimientoDialog.

    El overlay lo maneja el llamador (InicioWindow), mismo patrón
    que DialogNotificacionesExpandido — este diálogo no sabe nada
    del overlay.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calendario")
        self.setModal(True)
        self.setMinimumSize(880, 580)

        hoy = date.today()
        self._año = hoy.year
        self._mes = hoy.month
        self._dia_seleccionado = hoy.day
        self._dias_programados = set()
        self._dias_en_curso    = set()
        self._dias_vencidos    = set()
        self._dias_finalizados = set()
        # Modo de la grilla del panel izquierdo: "dias" (calendario
        # tradicional) o "meses" (grid 4×3 con los 12 meses del año,
        # estilo Windows Calendar). Click en el título "Julio 2026"
        # alterna entre los dos. Los chevrones ← → cambian de
        # comportamiento según el modo: en "dias" navegan mes a mes,
        # en "meses" navegan año a año — así el usuario puede saltar
        # a Marzo 2027 en dos clicks (título + año siguiente + mes)
        # en vez de nueve chevron-siguientes.
        self._modo_vista = "dias"

        # QSS base — mismo tratamiento que DialogNotificacionesExpandido:
        # sin custom drop-down/down-arrow en el QComboBox para que Qt use
        # el chevron nativo de Windows 11 (los SVG data-URIs no renderizan
        # bien en PyQt6 6.9.1).
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_CARD};
                color: {COLOR_TEXT};
            }}
            QComboBox {{
                background: {COLOR_BG};
                color: {COLOR_TEXT};
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
                min-height: 22px;
                min-width: 220px;
            }}
            QComboBox:hover {{
                border: 1px solid {COLOR_ACCENT};
            }}
            QComboBox QAbstractItemView {{
                background: {COLOR_BG};
                color: {COLOR_TEXT};
                border: 1px solid #3a3a3a;
                selection-background-color: {COLOR_ACCENT};
                selection-color: white;
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
        """)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        # ─── Header: ícono + título + filtro ───
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        ico_head = QLabel()
        ico_head.setPixmap(qta.icon("fa5s.calendar-alt", color=COLOR_ACCENT_LT).pixmap(QSize(24, 24)))
        ico_head.setStyleSheet("background: transparent;")
        header.addWidget(ico_head)

        header.addWidget(
            _label("Calendario", color=COLOR_TEXT, tamaño=16, peso="bold"),
            stretch=1
        )

        self.combo_filtro = QComboBox()
        self.combo_filtro.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_filtro.addItem("Programados y vencidos", userData="prog_venc")
        self.combo_filtro.addItem("Incluir finalizados",    userData="con_final")
        self.combo_filtro.currentIndexChanged.connect(self._on_filtro_cambiado)
        header.addWidget(self.combo_filtro)

        v.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {COLOR_BORDER}; border: none; max-height: 1px;")
        v.addWidget(sep)

        # ─── Cuerpo: split view ───
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(14)

        self.panel_cal = self._crear_panel_calendario()
        self.panel_cal.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.panel_ev = self._crear_panel_eventos()
        self.panel_ev.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # 55/45 aprox — el calendario necesita más aire para las celdas
        # cuadradas; el panel de eventos vive en scroll y aguanta menos ancho.
        cuerpo.addWidget(self.panel_cal, stretch=11)
        cuerpo.addWidget(self.panel_ev,  stretch=9)
        v.addLayout(cuerpo, stretch=1)

        # Carga inicial
        self._recargar_datos_mes()

    # ------------------------------------------------------
    #  Panel izquierdo: calendario navegable
    # ------------------------------------------------------
    def _crear_panel_calendario(self):
        panel = QFrame()
        panel.setObjectName("panelCal")
        panel.setStyleSheet(f"""
            QFrame#panelCal {{
                background-color: {COLOR_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
        """)
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        # Navegación de mes
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(6)

        self.btn_mes_ant = QPushButton()
        self.btn_mes_ant.setIcon(qta.icon("fa5s.chevron-left", color=COLOR_TEXT_DIM))
        self.btn_mes_ant.setIconSize(QSize(14, 14))
        self.btn_mes_ant.setFixedSize(28, 28)
        self.btn_mes_ant.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mes_ant.setStyleSheet(self._qss_boton_chevron())
        self.btn_mes_ant.clicked.connect(self._mes_anterior)
        nav.addWidget(self.btn_mes_ant)

        # Título del mes/año — clickable. En modo "dias" muestra
        # "Julio 2026", en modo "meses" solo "2026". Cursor pointer
        # y hover discreto para telegrafiar que es interactivo.
        # Se implementa como QPushButton para tener hover y click
        # sin manejar mousePressEvent a mano.
        self.lbl_mes = QPushButton("")
        self.lbl_mes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_mes.setStyleSheet(f"""
            QPushButton {{
                color: {COLOR_TEXT};
                font-size: 14px;
                font-weight: 600;
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                text-align: center;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.05);
            }}
        """)
        self.lbl_mes.clicked.connect(self._toggle_modo_vista)
        nav.addWidget(self.lbl_mes, stretch=1)

        self.btn_mes_sig = QPushButton()
        self.btn_mes_sig.setIcon(qta.icon("fa5s.chevron-right", color=COLOR_TEXT_DIM))
        self.btn_mes_sig.setIconSize(QSize(14, 14))
        self.btn_mes_sig.setFixedSize(28, 28)
        self.btn_mes_sig.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mes_sig.setStyleSheet(self._qss_boton_chevron())
        self.btn_mes_sig.clicked.connect(self._mes_siguiente)
        nav.addWidget(self.btn_mes_sig)

        v.addLayout(nav)

        # Contenedor de la grilla (se reconstruye al cambiar mes/día
        # seleccionado). Sacar la grilla a su propio widget hijo permite
        # tirarla completa y volverla a construir sin afectar la nav
        # ni la leyenda.
        self.cont_grid = QWidget()
        self.cont_grid.setStyleSheet("background: transparent;")
        self.lay_grid = QVBoxLayout(self.cont_grid)
        self.lay_grid.setContentsMargins(0, 0, 0, 0)
        self.lay_grid.setSpacing(0)
        v.addWidget(self.cont_grid, stretch=1)

        # Leyenda al pie
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background: {COLOR_BORDER}; border: none; max-height: 1px;")
        v.addWidget(sep2)

        leg = QHBoxLayout()
        leg.setContentsMargins(0, 4, 0, 0)
        leg.setSpacing(14)
        leg.addWidget(self._leyenda("Programado", ESTADO_PROGRAMADO))
        leg.addWidget(self._leyenda("En curso",   ESTADO_EN_CURSO))
        leg.addWidget(self._leyenda("Vencido",    ESTADO_VENCIDO))
        # La leyenda de finalizados solo aparece cuando el filtro los incluye.
        self.leyenda_final = self._leyenda("Finalizado", ESTADO_FINALIZADO)
        self.leyenda_final.setVisible(False)
        leg.addWidget(self.leyenda_final)
        leg.addStretch()
        v.addLayout(leg)

        return panel

    # ------------------------------------------------------
    #  Panel derecho: eventos del día seleccionado
    # ------------------------------------------------------
    def _crear_panel_eventos(self):
        panel = QFrame()
        panel.setObjectName("panelEv")
        panel.setStyleSheet(f"""
            QFrame#panelEv {{
                background-color: {COLOR_BG};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
        """)
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)

        self.lbl_dia_semana = _label("", color=COLOR_TEXT_DIM, tamaño=13)
        v.addWidget(self.lbl_dia_semana)

        self.lbl_dia_fecha = _label("", color=COLOR_TEXT, tamaño=16, peso="600")
        v.addWidget(self.lbl_dia_fecha)

        v.addSpacing(4)

        # Scroll de eventos. Misma configuración que el scroll de
        # notificaciones en la card compacta de inicio.py: overlay
        # thin sobre fondo transparente.
        self.scroll_ev = QScrollArea()
        self.scroll_ev.setWidgetResizable(True)
        self.scroll_ev.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_ev.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_ev.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.25);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0; background: transparent; border: none;
            }
        """)

        self.cont_ev = QWidget()
        self.cont_ev.setStyleSheet("background: transparent;")
        self.lay_ev = QVBoxLayout(self.cont_ev)
        self.lay_ev.setContentsMargins(0, 0, 0, 0)
        self.lay_ev.setSpacing(8)

        self.scroll_ev.setWidget(self.cont_ev)
        v.addWidget(self.scroll_ev, stretch=1)

        return panel

    # ------------------------------------------------------
    #  Helpers visuales
    # ------------------------------------------------------
    def _qss_boton_chevron(self):
        return """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 0;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.05);
            }
        """

    def _leyenda(self, texto, color):
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        h = QHBoxLayout(cont)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(5)
        punto = QLabel()
        punto.setFixedSize(6, 6)
        punto.setStyleSheet(f"background-color: {color}; border-radius: 3px; border: none;")
        h.addWidget(punto)
        h.addWidget(_label(texto, color=COLOR_TEXT_DIM, tamaño=11))
        return cont

    # ------------------------------------------------------
    #  Navegación de mes
    # ------------------------------------------------------
    def _mes_anterior(self):
        # En vista meses, el chevron ← navega al año anterior.
        # No hace falta recargar datos porque la vista meses no
        # pinta puntos (solo nombres de meses).
        if self._modo_vista == "meses":
            self._año -= 1
            self._reconstruir_grilla()
            return
        if self._mes == 1:
            self._mes = 12
            self._año -= 1
        else:
            self._mes -= 1
        self._ajustar_dia_seleccionado()
        self._recargar_datos_mes()

    def _mes_siguiente(self):
        # En vista meses, el chevron → navega al año siguiente.
        if self._modo_vista == "meses":
            self._año += 1
            self._reconstruir_grilla()
            return
        if self._mes == 12:
            self._mes = 1
            self._año += 1
        else:
            self._mes += 1
        self._ajustar_dia_seleccionado()
        self._recargar_datos_mes()

    def _ajustar_dia_seleccionado(self):
        """Si el día seleccionado no existe en el nuevo mes (ej. 31 en
        febrero → 28/29), lo baja al último día del mes. Así el usuario
        no se queda con un día "fantasma" seleccionado que no aparece
        en la grilla."""
        ultimo = calendar.monthrange(self._año, self._mes)[1]
        if self._dia_seleccionado > ultimo:
            self._dia_seleccionado = ultimo

    def _on_filtro_cambiado(self):
        incluir_final = (self.combo_filtro.currentData() == "con_final")
        self.leyenda_final.setVisible(incluir_final)
        self._recargar_datos_mes()

    # ------------------------------------------------------
    #  Recarga de datos
    # ------------------------------------------------------
    def _recargar_datos_mes(self):
        """Consulta la BD, actualiza los sets de días con eventos del
        mes actual, y repinta la grilla + el panel del día seleccionado."""
        incluir_final = (self.combo_filtro.currentData() == "con_final")
        (self._dias_programados,
         self._dias_en_curso,
         self._dias_vencidos,
         self._dias_finalizados) = _obtener_dias_con_eventos_mes(
            self._año, self._mes, incluir_final
        )
        self._reconstruir_grilla()
        self._recargar_eventos_dia()

    def _recargar_eventos_dia(self):
        """Refresca solo el panel derecho — se llama al hacer click en
        una celda sin necesidad de repintar la grilla completa."""
        hoy = date.today()
        try:
            fecha_sel = date(self._año, self._mes, self._dia_seleccionado)
        except ValueError:
            fecha_sel = hoy
            self._dia_seleccionado = hoy.day

        self.lbl_dia_semana.setText(DIAS_NOMBRE[fecha_sel.weekday()])

        incluir_final = (self.combo_filtro.currentData() == "con_final")
        eventos = self._obtener_eventos_del_dia(fecha_sel, incluir_final)

        n = len(eventos)
        if n == 0:
            contador = ""
        elif n == 1:
            contador = " · 1 evento"
        else:
            contador = f" · {n} eventos"
        self.lbl_dia_fecha.setText(
            f"{fecha_sel.day} de {MESES_ES[fecha_sel.month].lower()}{contador}"
        )

        # Limpiar layout con hide() antes de deleteLater() para evitar
        # flicker (mismo patrón que finalizados.py y programados.py).
        while self.lay_ev.count() > 0:
            item = self.lay_ev.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

        if not eventos:
            self.lay_ev.addWidget(self._estado_vacio_dia())
            self.lay_ev.addStretch()
            return

        for ev in eventos:
            self.lay_ev.addWidget(self._crear_card_evento(ev))
        self.lay_ev.addStretch()

    def _estado_vacio_dia(self):
        vacio = QFrame()
        vacio.setStyleSheet("background: transparent; border: none;")
        vv = QVBoxLayout(vacio)
        vv.setContentsMargins(0, 40, 0, 12)
        vv.setSpacing(8)
        vv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.calendar-day", color=COLOR_TEXT_FAINT).pixmap(QSize(32, 32)))
        ico.setStyleSheet("background: transparent; border: none;")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = _label("Sin eventos programados este día",
                     color=COLOR_TEXT_FAINT, tamaño=12)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vv.addWidget(ico)
        vv.addWidget(lbl)
        return vacio

    # ------------------------------------------------------
    #  Reconstrucción de la grilla del calendario
    # ------------------------------------------------------
    def _reconstruir_grilla(self):
        """Dispatcher: limpia el contenedor y llama al reconstructor
        del modo activo. También actualiza el título del panel — en
        modo días muestra 'Julio 2026', en modo meses solo '2026'."""
        while self.lay_grid.count() > 0:
            item = self.lay_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

        if self._modo_vista == "meses":
            self.lbl_mes.setText(str(self._año))
            self._reconstruir_grilla_meses()
        else:
            self.lbl_mes.setText(f"{MESES_ES[self._mes]} {self._año}")
            self._reconstruir_grilla_dias()

    def _reconstruir_grilla_dias(self):
        hoy = date.today()
        dia_hoy = hoy.day if (self._año == hoy.year and self._mes == hoy.month) else None

        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        grid = QGridLayout(cont)
        grid.setSpacing(3)
        grid.setContentsMargins(0, 0, 0, 0)
        for i in range(7):
            grid.setColumnStretch(i, 1)

        for i, letra in enumerate(DIAS_INICIAL):
            lbl = _label(letra, color=COLOR_TEXT_FAINT, tamaño=10)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(lbl, 0, i)

        for r, c, dia, es_actual in self._iterar_celdas():
            es_hoy = (dia_hoy is not None and dia == dia_hoy and es_actual)
            es_finde = c >= 5
            programado = es_actual and dia in self._dias_programados
            en_curso   = es_actual and dia in self._dias_en_curso
            vencido    = es_actual and dia in self._dias_vencidos
            finalizado = es_actual and dia in self._dias_finalizados
            seleccionado = (es_actual and dia == self._dia_seleccionado)

            celda = self._crear_celda_clickable(
                dia, es_actual=es_actual,
                hoy=es_hoy, finde=es_finde,
                seleccionado=seleccionado,
                programado=programado, en_curso=en_curso,
                vencido=vencido, finalizado=finalizado
            )
            grid.addWidget(celda, r + 1, c)

        self.lay_grid.addWidget(cont)

    def _reconstruir_grilla_meses(self):
        """Vista alterna: grid 4×3 con los 12 meses del año actual.
        Click en un mes → vuelve a vista días en ese mes/año.
        Los chevrones ← → del header navegan años en este modo.

        Estilo estilo Windows Calendar — el "mes actualmente
        seleccionado" (self._mes) se resalta con fondo azul lleno,
        y el "mes de hoy" (si estamos en el año actual) con borde
        azul sin fondo. Cuando ambos coinciden gana "seleccionado"
        y no se ve el borde — misma prioridad que en la vista día."""
        hoy = date.today()
        mes_hoy = hoy.month if self._año == hoy.year else None

        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        grid = QGridLayout(cont)
        grid.setSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)
        for i in range(3):
            grid.setColumnStretch(i, 1)
        for r in range(4):
            grid.setRowStretch(r, 1)

        for mes in range(1, 13):
            r = (mes - 1) // 3
            c = (mes - 1) % 3
            es_mes_hoy       = (mes_hoy is not None and mes == mes_hoy)
            es_seleccionado  = (mes == self._mes)
            celda = self._crear_celda_mes(
                mes, es_mes_hoy=es_mes_hoy, seleccionado=es_seleccionado
            )
            grid.addWidget(celda, r, c)

        self.lay_grid.addWidget(cont)

    def _crear_celda_mes(self, mes, es_mes_hoy=False, seleccionado=False):
        # Mismos criterios visuales que _crear_celda_clickable (día):
        # seleccionado gana con fondo azul lleno, mes_hoy con borde
        # sin fondo. border 1px solid transparente por default para
        # evitar shift al pintar/despintar outline.
        borde_color = "transparent"
        if seleccionado:
            bg, color, peso = "rgba(0, 120, 215, 0.30)", COLOR_ACCENT_LT, "bold"
        elif es_mes_hoy:
            bg, color, peso = "transparent", COLOR_ACCENT, "bold"
            borde_color = COLOR_ACCENT
        else:
            bg, color, peso = "transparent", COLOR_TEXT, "500"

        celda = QFrame()
        celda.setObjectName("mesCell")
        celda.setStyleSheet(f"""
            QFrame#mesCell {{
                background-color: {bg};
                border-radius: 6px;
                border: 1px solid {borde_color};
            }}
            QFrame#mesCell:hover {{
                background-color: rgba(255, 255, 255, 0.05);
            }}
        """)
        celda.setMinimumHeight(60)
        celda.setCursor(Qt.CursorShape.PointingHandCursor)
        celda.mousePressEvent = lambda ev, m=mes: self._on_click_mes(ev, m)

        v = QVBoxLayout(celda)
        v.setContentsMargins(0, 0, 0, 0)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = _label(MESES_ES[mes], color=color, tamaño=13, peso=peso)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(lbl)

        return celda

    def _on_click_mes(self, ev, mes):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self._mes = mes
        self._ajustar_dia_seleccionado()
        self._modo_vista = "dias"
        # Al aterrizar en un mes, recargamos datos (query + reconstruir
        # + refrescar panel del día seleccionado). Es exactamente el
        # flujo que ya usaba _mes_anterior/_siguiente en modo días.
        self._recargar_datos_mes()

    def _toggle_modo_vista(self):
        """Alterna entre vista día y vista meses. Se conecta al click
        del título del panel (self.lbl_mes)."""
        if self._modo_vista == "dias":
            self._modo_vista = "meses"
            # No hace falta consultar la BD — la vista meses no
            # muestra puntos, solo los 12 nombres del año self._año.
            self._reconstruir_grilla()
        else:
            self._modo_vista = "dias"
            self._recargar_datos_mes()

    def _iterar_celdas(self):
        calendar.setfirstweekday(calendar.MONDAY)
        semanas = calendar.monthcalendar(self._año, self._mes)

        if self._mes == 1:
            mes_ant, año_ant = 12, self._año - 1
        else:
            mes_ant, año_ant = self._mes - 1, self._año
        ultimo_dia_anterior = calendar.monthrange(año_ant, mes_ant)[1]

        zeros_inicio = 0
        for d in semanas[0]:
            if d == 0:
                zeros_inicio += 1
            else:
                break

        dia_prox = 1
        for r, semana in enumerate(semanas):
            for c, d in enumerate(semana):
                if d == 0:
                    if r == 0 and c < zeros_inicio:
                        dia = ultimo_dia_anterior - (zeros_inicio - c - 1)
                        yield (r, c, dia, False)
                    else:
                        yield (r, c, dia_prox, False)
                        dia_prox += 1
                else:
                    yield (r, c, d, True)

    def _crear_celda_clickable(self, dia, es_actual=True,
                                hoy=False, finde=False, seleccionado=False,
                                programado=False, en_curso=False,
                                vencido=False, finalizado=False):
        celda = QFrame()
        celda.setObjectName("calCellExp")

        # Estado visual, en tres capas independientes: fondo, color de
        # texto, y borde. La prioridad es:
        #   seleccionado (fondo azul lleno, dominante) >
        #   hoy (borde azul sin fondo, outline estilo Windows 11) >
        #   otro_mes / finde / normal (sin adorno)
        #
        # Cuando un día es hoy Y seleccionado al mismo tiempo (default
        # al abrir el modal), predomina "seleccionado" — el fondo lleno
        # tapa cualquier borde. Al hacer click en otro día, ese pasa a
        # ser el seleccionado y "hoy" recupera su outline.
        #
        # Truco de layout: TODAS las celdas llevan `border: 1px solid`,
        # con color transparente por default. Así solo cambia el color
        # del borde para "hoy" y no se corren de tamaño las demás
        # celdas al pintar/despintar el outline.
        borde_color = "transparent"
        if seleccionado:
            bg, color, peso = "rgba(0, 120, 215, 0.30)", COLOR_ACCENT_LT, "bold"
        elif hoy:
            bg, color, peso = "transparent", COLOR_ACCENT, "bold"
            borde_color = COLOR_ACCENT
        elif not es_actual:
            bg, color, peso = "transparent", COLOR_OTRO_MES, "normal"
        elif finde:
            bg, color, peso = "transparent", COLOR_TEXT_FAINT, "normal"
        else:
            bg, color, peso = "transparent", COLOR_TEXT, "normal"

        celda.setStyleSheet(f"""
            QFrame#calCellExp {{
                background-color: {bg};
                border-radius: 4px;
                border: 1px solid {borde_color};
            }}
            QFrame#calCellExp:hover {{
                background-color: rgba(255, 255, 255, 0.05);
            }}
        """)
        celda.setMinimumHeight(46)

        if es_actual:
            celda.setCursor(Qt.CursorShape.PointingHandCursor)
            celda.mousePressEvent = lambda ev, d=dia: self._on_click_dia(ev, d)

        v = QVBoxLayout(celda)
        v.setContentsMargins(0, 6, 0, 6)
        v.setSpacing(3)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = _label(str(dia), color=color, tamaño=13, peso=peso)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(lbl)

        # Puntos indicadores. Un mismo día puede tener varios tipos
        # (ej. un mantto vencido + otro programado en el mismo día).
        # Se pintan todos los que apliquen, en orden de gravedad
        # visual: rojo (vencido) → ámbar (en curso) → azul (programado)
        # → verde (finalizado).
        cont_punto = QWidget()
        cont_punto.setFixedHeight(7)
        cont_punto.setStyleSheet("background: transparent; border: none;")
        hp = QHBoxLayout(cont_punto)
        hp.setContentsMargins(0, 0, 0, 0)
        hp.setSpacing(3)
        hp.addStretch()
        if vencido:
            hp.addWidget(self._punto(ESTADO_VENCIDO))
        if en_curso:
            hp.addWidget(self._punto(ESTADO_EN_CURSO))
        if programado:
            hp.addWidget(self._punto(ESTADO_PROGRAMADO))
        if finalizado:
            hp.addWidget(self._punto(ESTADO_FINALIZADO))
        hp.addStretch()
        v.addWidget(cont_punto)

        return celda

    def _punto(self, color):
        p = QLabel()
        p.setFixedSize(5, 5)
        p.setStyleSheet(f"background-color: {color}; border-radius: 2px; border: none;")
        return p

    def _on_click_dia(self, ev, dia):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self._dia_seleccionado = dia
        # Reconstruimos la grilla completa para mover el resaltado del
        # día seleccionado. Costo bajo (42 celdas). Luego repintamos
        # el panel derecho con los eventos del nuevo día.
        self._reconstruir_grilla()
        self._recargar_eventos_dia()

    # ------------------------------------------------------
    #  Cards de evento (panel derecho)
    # ------------------------------------------------------
    def _crear_card_evento(self, ev):
        """Card clickable de un evento del día:
          [equipo]                     [pill hora]
          tipo · ubicación
          [avatar] Responsable    [badge tipo]

        Click en cualquier parte de la card → FichaMantenimientoDialog.
        """
        mant_id = ev["id"]
        estado = ev.get("estado", "programado")
        es_vencido  = ev.get("es_vencido",  False)
        es_en_curso = ev.get("es_en_curso", False)

        # Color del border-left según estado del evento.
        # Prioridad: vencido > finalizado > en curso > programado.
        # (Vencido y en curso son mutuamente excluyentes por
        # construcción en _obtener_eventos_del_dia, pero el orden
        # explícito documenta la intención.)
        if es_vencido:
            color_borde = ESTADO_VENCIDO
        elif estado == "finalizado":
            color_borde = ESTADO_FINALIZADO
        elif es_en_curso:
            color_borde = ESTADO_EN_CURSO
        else:
            color_borde = ESTADO_PROGRAMADO

        card = QFrame()
        card.setObjectName("cardEvento")
        card.setStyleSheet(f"""
            QFrame#cardEvento {{
                background-color: {COLOR_CARD};
                border: 1px solid {COLOR_BORDER};
                border-left: 3px solid {color_borde};
                border-radius: 6px;
            }}
            QFrame#cardEvento:hover {{
                background-color: #333333;
            }}
        """)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.mousePressEvent = lambda e, mid=mant_id: self._on_click_evento(e, mid)

        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(5)

        # Línea 1: equipo + #id + pill de hora.
        # El #id sale en gris tenue justo después del nombre del equipo
        # como en un tracker de tickets — permite distinguir de un
        # vistazo si dos entradas de la lista son el mismo mantto sin
        # tener que abrir cada ficha. Es idempotente con la ficha:
        # ambos usan la misma columna mantenimientos.id como fuente.
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(_label(
            ev.get("equipo_titulo") or "Mantenimiento",
            color=COLOR_TEXT, tamaño=13, peso="500"
        ))
        top.addWidget(_label(
            f"#{ev['id']}",
            color=COLOR_TEXT_FAINT, tamaño=11
        ))
        top.addStretch()

        hora = ev.get("hora", "")
        if hora:
            pill = QLabel(hora)
            pill.setStyleSheet(f"""
                background-color: rgba(0, 120, 215, 0.18);
                color: {COLOR_ACCENT_LT};
                font-size: 10px;
                font-weight: 500;
                padding: 2px 8px;
                border-radius: 4px;
                border: none;
            """)
            top.addWidget(pill)
        v.addLayout(top)

        # Línea 2: grupo › subgrupo · ubicación · tipo de mantto.
        # `grupo_ruta` trae sus propios separadores ' › ' internos entre
        # niveles del árbol de grupos (misma convención que
        # programados.py). El ' · ' separa "categorías" distintas:
        # ruta jerárquica de grupos, ubicación física del equipo y
        # tipo de mantenimiento. Cada parte se omite si viene vacía
        # para no pintar separadores huérfanos.
        sub_partes = []
        if ev.get("grupo_ruta"):
            sub_partes.append(ev["grupo_ruta"])
        if ev.get("ubicacion"):
            sub_partes.append(ev["ubicacion"])
        if ev.get("tipo_mantenimiento"):
            sub_partes.append(ev["tipo_mantenimiento"])
        if sub_partes:
            v.addWidget(_label(" · ".join(sub_partes),
                               color=COLOR_TEXT_DIM, tamaño=11))

        # Línea 3: responsable
        v.addLayout(self._fila_responsable(ev))

        return card

    def _fila_responsable(self, ev):
        h = QHBoxLayout()
        h.setContentsMargins(0, 3, 0, 0)
        h.setSpacing(6)

        resp_tipo = (ev.get("responsable_tipo") or "").lower()
        resp_nombre = ev.get("responsable_nombre") or ""

        avatar = QLabel()
        avatar.setFixedSize(20, 20)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Tres estados de responsable con tratamiento visual distinto:
        #   pendiente / vacío → avatar gris + "Sin asignar"
        #   externo/proveedor → ícono de edificio ámbar + nombre
        #   interno           → iniciales sobre círculo azul + nombre
        if resp_tipo == "pendiente" or not resp_tipo:
            avatar.setPixmap(
                qta.icon("fa5s.user-slash", color=COLOR_TEXT_FAINT).pixmap(QSize(12, 12))
            )
            avatar.setStyleSheet("""
                background-color: rgba(136, 136, 136, 0.15);
                border-radius: 10px;
            """)
            nombre_mostrar = "Sin asignar"
            color_nombre = COLOR_TEXT_FAINT
            badge_texto = ""
        elif resp_tipo in ("externo", "proveedor"):
            avatar.setPixmap(
                qta.icon("fa5s.building", color=COLOR_WARNING).pixmap(QSize(12, 12))
            )
            avatar.setStyleSheet("""
                background-color: rgba(232, 163, 61, 0.20);
                border-radius: 10px;
            """)
            nombre_mostrar = resp_nombre or "Proveedor"
            color_nombre = "#b0b0b0"
            badge_texto = "Proveedor"
        else:
            iniciales = self._iniciales(resp_nombre)
            avatar.setText(iniciales)
            avatar.setStyleSheet(f"""
                background-color: rgba(74, 158, 255, 0.20);
                color: {COLOR_ACCENT_LT};
                font-size: 9px;
                font-weight: 600;
                border-radius: 10px;
            """)
            nombre_mostrar = resp_nombre or "Interno"
            color_nombre = "#b0b0b0"
            badge_texto = "Interno"

        h.addWidget(avatar)
        h.addWidget(_label(nombre_mostrar, color=color_nombre, tamaño=11))
        h.addStretch()
        if badge_texto:
            h.addWidget(_label(badge_texto, color=COLOR_TEXT_FAINT, tamaño=10))

        return h

    def _iniciales(self, nombre):
        """Hasta 2 iniciales del nombre. Fallback '?' si viene vacío."""
        if not nombre:
            return "?"
        partes = [p for p in nombre.strip().split() if p]
        if not partes:
            return "?"
        if len(partes) == 1:
            return partes[0][:2].upper()
        return (partes[0][0] + partes[-1][0]).upper()

    def _on_click_evento(self, ev, mant_id):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        try:
            from ficha_mantenimiento import FichaMantenimientoDialog
            FichaMantenimientoDialog(mant_id, self).exec()
        except Exception as e:
            print(f"[Calendario] no se pudo abrir la ficha del mantto {mant_id}: {e}")

    # ------------------------------------------------------
    #  Queries a la BD (auto-contenidas)
    #
    #  Cuando se haga el refactor del data layer, estas funciones
    #  se moverán a db_manager.py como obtener_dias_con_eventos()
    #  y obtener_eventos_del_dia(). Por ahora viven aquí para
    #  no tocar db_manager.
    # ------------------------------------------------------
    def _obtener_eventos_del_dia(self, fecha, incluir_finalizados=False):
        """Lista de eventos que caen en `fecha` (objeto date).

        Un evento cae en el día si:
          - Es programado y fecha_inicio <= día <= fecha_fin
            (cubre mantenimientos de 1 día y de rango largo).
          - O es finalizado y su fecha_cierre (o fecha_fin como
            fallback) es ese día.

        Cada evento devuelve además `grupo_ruta` (cadena tipo
        'Edificio A › Piso 2' resuelta desde tableros.grupo_id vía
        la jerarquía de grupos) y `es_en_curso` (bool que distingue
        los programados activos del día para pintarlos ámbar en vez
        de azul).
        """
        eventos = []
        conn = connect_db(create_if_missing=False)
        if conn is None:
            return eventos

        try:
            cur = conn.cursor()
            fecha_str = fecha.isoformat()

            # Detección dinámica de columnas: responsable_nombre puede
            # existir o no en la tabla dependiendo de la versión del
            # esquema. Si falta, mostramos solo el tipo de responsable.
            cols = [r[1] for r in cur.execute(
                "PRAGMA table_info(mantenimientos)"
            ).fetchall()]
            tiene_resp_nombre = 'responsable_nombre' in cols
            sel_resp = ", m.responsable_nombre" if tiene_resp_nombre \
                       else ", NULL as responsable_nombre"

            if incluir_finalizados:
                estados_where = "m.estado IN ('programado', 'finalizado')"
            else:
                estados_where = "m.estado = 'programado'"

            query = f"""
                SELECT m.id, m.tipo_mantenimiento, m.fecha_inicio, m.fecha_fin,
                       m.responsable_tipo{sel_resp}, m.estado,
                       COUNT(me.id) AS n_eq,
                       MIN(me.equipo_id)   AS primer_eq_id,
                       MIN(me.equipo_tipo) AS primer_eq_tipo
                FROM mantenimientos m
                LEFT JOIN mantenimientos_equipos me ON me.mantenimiento_id = m.id
                WHERE {estados_where}
                  AND (
                        (date(m.fecha_inicio) <= date(?) AND date(m.fecha_fin) >= date(?))
                        OR (m.estado = 'finalizado'
                            AND m.fecha_cierre IS NOT NULL
                            AND date(m.fecha_cierre) = date(?))
                      )
                GROUP BY m.id
                ORDER BY m.fecha_inicio
            """

            filas = cur.execute(
                query, (fecha_str, fecha_str, fecha_str)
            ).fetchall()

            # Cargamos la jerarquía de grupos una sola vez antes del
            # loop — así cada evento resuelve su ruta por lookup en
            # memoria en vez de otra query recursiva.
            jerarquia = _cargar_jerarquia_grupos(cur)

            hoy_str = date.today().isoformat()

            for fila in filas:
                (mid, tipo_m, f_ini, f_fin, resp_tipo, resp_nombre,
                 estado, n_eq, eq_id, eq_tipo) = fila

                titulo, ubicacion, grupo_ruta = self._titulo_y_sub(
                    cur, jerarquia, n_eq, eq_id, eq_tipo, tipo_m
                )

                # Hora extraída del formato "YYYY-MM-DD HH:MM" o
                # "YYYY-MM-DD HH:MM:SS". Si viene solo la fecha
                # (sin hora), queda cadena vacía y la pill no se pinta.
                hora = ""
                if f_ini and len(f_ini) >= 16:
                    hora = f_ini[11:16]

                # Los tres subestados de un mantto "programado" son
                # mutuamente excluyentes (los definen las fechas vs
                # hoy). Los evaluamos en el orden de prioridad visual
                # para el border-left de la card:
                #   vencido → en curso → programado a futuro
                es_vencido = (
                    estado == 'programado'
                    and f_fin and f_fin[:10] < hoy_str
                )
                es_en_curso = (
                    estado == 'programado'
                    and not es_vencido
                    and f_ini and f_fin
                    and f_ini[:10] <= hoy_str <= f_fin[:10]
                )

                eventos.append({
                    "id":                  mid,
                    "equipo_titulo":       titulo,
                    "ubicacion":           ubicacion,
                    "grupo_ruta":          grupo_ruta,
                    "hora":                hora,
                    "tipo_mantenimiento":  tipo_m or "",
                    "responsable_tipo":    resp_tipo or "",
                    "responsable_nombre":  resp_nombre or "",
                    "estado":              estado,
                    "es_vencido":          es_vencido,
                    "es_en_curso":         es_en_curso,
                })

        except Exception as e:
            print(f"[Calendario] error al obtener eventos del día: {e}")
        finally:
            conn.close()

        return eventos

    def _titulo_y_sub(self, cur, jerarquia, n_equipos, equipo_id, equipo_tipo, tipo_mantenimiento):
        """Devuelve (titulo, ubicacion, grupo_ruta) para la card del evento.

        Casos:
          - 1 equipo:  título = nombre del equipo,
                       subtítulo = su ubicación, ruta = jerarquía de grupos
          - N equipos: título = tipo de mantto,
                       subtítulo = 'N equipos', ruta = "" (no aplica un
                       grupo único cuando hay varios equipos posiblemente
                       de grupos distintos)
          - 0/None:    fallback al tipo de mantto sin subtítulo ni ruta
        """
        if not n_equipos or equipo_id is None:
            return (tipo_mantenimiento or "Mantenimiento", "", "")

        if n_equipos > 1:
            return (tipo_mantenimiento or "Mantenimiento",
                    f"{n_equipos} equipos", "")

        return self._detalle_equipo(cur, jerarquia, equipo_id, equipo_tipo)

    def _detalle_equipo(self, cur, jerarquia, equipo_id, equipo_tipo):
        """Resuelve (nombre_visible, ubicación, ruta_grupo) de un equipo.

        `ubicacion` viene del texto libre del propio equipo (tableros
        lo tiene NOT NULL; transformadores puede ser NULL).
        `ruta_grupo` se arma subiendo por el árbol de grupos hasta
        la raíz — misma convención que programados.py.
        """
        try:
            if equipo_tipo == "tableros":
                row = cur.execute(
                    "SELECT nombre, ubicacion, grupo_id FROM tableros WHERE id = ?",
                    (equipo_id,)
                ).fetchone()
                if row is None:
                    return (f"Tablero {equipo_id}", "", "")
                nombre, ubicacion, grupo_id = row
                ruta = _ruta_grupo(grupo_id, jerarquia)
                if nombre:
                    return (str(nombre), str(ubicacion or ""), ruta)
                return (f"Tablero {equipo_id}", str(ubicacion or ""), ruta)

            if equipo_tipo == "transformadores":
                row = cur.execute(
                    "SELECT ubicacion, grupo_id FROM transformadores WHERE id = ?",
                    (equipo_id,)
                ).fetchone()
                if row is None:
                    return (f"Transformador {equipo_id}", "", "")
                ubic, grupo_id = row
                ruta = _ruta_grupo(grupo_id, jerarquia)
                return (f"Transformador {equipo_id}", str(ubic or ""), ruta)
        except Exception as e:
            print(f"[Calendario] aviso al resolver equipo {equipo_tipo}/{equipo_id}: {e}")

        return (str(equipo_id), "", "")
