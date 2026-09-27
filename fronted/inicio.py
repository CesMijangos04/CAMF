"""
inicio.py — Pestaña Inicio del Sistema de Mantenimiento Eléctrico CAMF

Panorama del sistema: KPIs operativos, calendario, próximos mantenimientos,
mantenimientos vencidos, composición del inventario y tip educativo.

Esta pestaña es PURAMENTE INFORMATIVA: sin atajos a otras pestañas (eso
lo hace el sidebar). Su rol es sintetizar información dispersa en
Inventario, Mantenimientos y Reportes.

Datos: TODOS provienen de memoria.db en tiempo real. Cada vez que el
usuario abre la pestaña, MainWindow.mostrar_pagina() llama a
`InicioWindow.actualizar()` y se reconstruye el contenido con queries
frescas a la base de datos.

Estados de mantenimiento usados (según db_manager.py):
    'programado'  → activo, no vencido si fecha_fin >= hoy
    'programado'  + fecha_fin < hoy → vencido (pendiente de cierre)
    'finalizado'  → cerrado con PDF (cuenta como "hecho este mes")
    'cancelado'   → no se cuenta en KPIs operativos
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QScrollArea, QLayout,
    QDialog, QPushButton, QTextEdit, QApplication, QSizePolicy,
    QComboBox
)
from PyQt6.QtCore import Qt, QSize, QEvent, pyqtSignal
import qtawesome as qta
import random
from datetime import date, datetime

from db_manager import connect_db
from notificaciones import obtener_notificaciones_activas
from card_calendario import CalendarioMes, DialogCalendarioExpandido


# ==========================================================
#  PALETA DE COLORES (consistente con main.py / configuracion.py)
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

# Nombres en español (evita problemas con locale del sistema)
MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]
DIAS_NOMBRE  = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DIAS_INICIAL = ["L", "M", "M", "J", "V", "S", "D"]


# ==========================================================
#  TIPS DE LA NOM (rotan al azar al abrir la pestaña)
#
#  TODO: ampliar a 30-50 tips, verificar los artículos exactos contra
#  la versión vigente de la NOM, y eventualmente migrar a una tabla
#  en memoria.db para que sean editables desde Configuración.
# ==========================================================
TIPS_NOM = [
    {
        "texto": "Las instalaciones eléctricas en lugares de trabajo deben revisarse "
                 "al menos una vez al año por personal calificado.",
        "ref":   "NOM-001-SEDE-2012",
    },
    {
        "texto": "Frente a tableros eléctricos debe mantenerse un espacio libre de "
                 "trabajo de al menos 1.0 m, sin obstáculos, para operación segura.",
        "ref":   "NOM-001-SEDE-2012, art. 110-26",
    },
    {
        "texto": "Todo equipo eléctrico debe contar con un sistema de puesta a tierra "
                 "continuo y permanente, verificado periódicamente con un megóhmetro.",
        "ref":   "NOM-001-SEDE-2012, art. 250",
    },
    {
        "texto": "En transformadores de potencia, se recomienda termografía cada "
                 "6 meses y análisis fisicoquímico del aceite al menos una vez al año.",
        "ref":   "Buenas prácticas de mantenimiento eléctrico",
    },
    {
        "texto": "La caída de tensión en circuitos derivados no debe exceder 3%, "
                 "y la suma de alimentador + derivado no debe pasar de 5%.",
        "ref":   "NOM-001-SEDE-2012, art. 215",
    },
    {
        "texto": "Los conductores de puesta a tierra deben ser de color verde "
                 "o verde con franjas amarillas, sin excepción.",
        "ref":   "NOM-001-SEDE-2012, art. 200/250",
    },
    {
        "texto": "Los breakers termomagnéticos deben operarse manualmente al menos "
                 "una vez al año para evitar que se traben por falta de uso.",
        "ref":   "Buenas prácticas — fabricantes (Schneider, Siemens, ABB)",
    },
]


# ==========================================================
#  Helpers de saludo y fecha
# ==========================================================
def saludo_por_hora():
    h = datetime.now().hour
    if h < 12:
        return "Buenos días"
    if h < 19:
        return "Buenas tardes"
    return "Buenas noches"


def fecha_legible(hoy=None):
    hoy = hoy or date.today()
    return f"{DIAS_NOMBRE[hoy.weekday()]} {hoy.day} de {MESES_ES[hoy.month].lower()}"


def fecha_corta(fecha_str):
    """'2026-06-24 08:00' → '24 jun'."""
    if not fecha_str:
        return ""
    try:
        dt = datetime.strptime(fecha_str[:10], "%Y-%m-%d").date()
        return f"{dt.day} {MESES_ES[dt.month][:3].lower()}"
    except Exception:
        return fecha_str[:10]


# ==========================================================
#  Helpers visuales
# ==========================================================
def crear_label(texto, color=COLOR_TEXT, tamaño=12, peso="normal", transparent=True):
    lbl = QLabel(texto)
    bg = "background: transparent;" if transparent else ""
    lbl.setStyleSheet(f"""
        color: {color};
        font-size: {tamaño}px;
        font-weight: {peso};
        border: none;
        {bg}
    """)
    return lbl


def crear_badge(texto, tipo="med"):
    """Tipos: high, med, low, crit, warn, urgente."""
    estilos = {
        "high":    ("rgba(232, 163, 61, 0.15)", COLOR_WARNING),
        "med":     ("rgba(0, 120, 215, 0.18)",  COLOR_ACCENT_LT),
        "low":     ("rgba(136, 136, 136, 0.15)", "#aaaaaa"),
        "crit":    ("rgba(217, 83, 79, 0.15)",  COLOR_DANGER),
        "warn":    ("rgba(232, 163, 61, 0.15)", COLOR_WARNING),
        "urgente": ("rgba(217, 83, 79, 0.20)",  COLOR_DANGER),
    }
    bg, color = estilos.get(tipo, estilos["low"])
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"""
        background-color: {bg};
        color: {color};
        font-size: 10px;
        font-weight: 500;
        padding: 2px 8px;
        border-radius: 4px;
        border: none;
    """)
    return lbl


def crear_tarjeta(objeto_id):
    """Devuelve (QFrame, QVBoxLayout) con estilo de tarjeta. El objeto_id
    aisla el QSS para que no se herede a los hijos."""
    card = QFrame()
    card.setObjectName(objeto_id)
    card.setStyleSheet(f"""
        QFrame#{objeto_id} {{
            background-color: {COLOR_CARD};
            border: 1px solid {COLOR_BORDER};
            border-radius: 8px;
        }}
    """)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(0)
    return card, layout


def crear_titulo_tarjeta(texto, icono_qta=None, color_icono=None):
    cont = QWidget()
    cont.setStyleSheet("background: transparent;")
    h = QHBoxLayout(cont)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)

    if icono_qta:
        lbl_ic = QLabel()
        col = color_icono or COLOR_TEXT
        lbl_ic.setPixmap(qta.icon(icono_qta, color=col).pixmap(QSize(16, 16)))
        lbl_ic.setStyleSheet("background: transparent; border: none;")
        h.addWidget(lbl_ic)

    h.addWidget(crear_label(texto, color=COLOR_TEXT, tamaño=14, peso="600"))
    h.addStretch()
    return cont


def crear_fila_lista(titulo, sub, color_sub, derecha_widgets, es_ultima=False):
    """Fila de lista: titulo+subtitulo a la izquierda, widgets a la derecha."""
    fila = QFrame()
    fila.setObjectName("filaLista")
    borde = "border: none;" if es_ultima else f"border-bottom: 1px solid {COLOR_BORDER};"
    fila.setStyleSheet(f"QFrame#filaLista {{ background: transparent; {borde} border-radius: 0; }}")

    h = QHBoxLayout(fila)
    h.setContentsMargins(0, 9, 0, 9)
    h.setSpacing(8)

    izq = QWidget()
    izq.setStyleSheet("background: transparent;")
    v = QVBoxLayout(izq)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    v.addWidget(crear_label(titulo, color=COLOR_TEXT, tamaño=13, peso="500"))
    if sub:
        v.addWidget(crear_label(sub, color=color_sub, tamaño=11))
    h.addWidget(izq, stretch=1)

    for w in derecha_widgets:
        h.addWidget(w)

    return fila


def crear_fila_vacia(mensaje):
    """Mensaje de placeholder cuando una lista no tiene resultados."""
    lbl = crear_label(mensaje, color=COLOR_TEXT_FAINT, tamaño=12)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cont = QFrame()
    cont.setStyleSheet("background: transparent; border: none;")
    h = QHBoxLayout(cont)
    h.setContentsMargins(0, 16, 0, 16)
    h.addWidget(lbl)
    return cont


def limpiar_layout(layout):
    """Borra recursivamente todos los items de un layout. Útil para
    reconstruir secciones al refrescar."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
            continue
        sub = item.layout()
        if sub is not None:
            limpiar_layout(sub)


# ==========================================================
#  TARJETA DE KPI
# ==========================================================
class KpiCard(QFrame):
    def __init__(self, icono_qta, etiqueta, valor, subtexto, danger=False, parent=None):
        super().__init__(parent)

        if danger:
            bg, border = "rgba(217, 83, 79, 0.08)", "rgba(217, 83, 79, 0.30)"
            c_lbl = c_val = c_sub = c_ic = COLOR_DANGER
        else:
            bg, border = COLOR_CARD, COLOR_BORDER
            c_lbl, c_ic = COLOR_TEXT_DIM, COLOR_TEXT_DIM
            c_val = COLOR_TEXT
            c_sub = COLOR_TEXT_FAINT

        self.setObjectName("kpiCard")
        self.setStyleSheet(f"""
            QFrame#kpiCard {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        fila = QHBoxLayout()
        fila.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(qta.icon(icono_qta, color=c_ic).pixmap(QSize(14, 14)))
        ic.setStyleSheet("background: transparent; border: none;")
        fila.addWidget(ic)
        fila.addWidget(crear_label(etiqueta, color=c_lbl, tamaño=12))
        fila.addStretch()
        layout.addLayout(fila)

        layout.addWidget(crear_label(str(valor), color=c_val, tamaño=26, peso="600"))
        layout.addWidget(crear_label(subtexto, color=c_sub, tamaño=11))


# ==========================================================
#  VENTANA DE INICIO
# ==========================================================
class InicioWindow(QWidget):
    """Pestaña Inicio: panorama del sistema CAMF, datos en tiempo real."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            InicioWindow {{ background-color: {COLOR_BG}; }}
            QWidget {{ font-family: 'Segoe UI', Arial, sans-serif; }}
        """)

        # Layout raíz con scroll
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {COLOR_BG}; border: none; }}
            QScrollBar:vertical {{
                background: {COLOR_BG}; width: 10px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #444; border-radius: 5px; min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)

        self._contenedor = QWidget()
        self._contenedor.setStyleSheet(f"background-color: {COLOR_BG};")

        self._lay_contenido = QVBoxLayout(self._contenedor)
        self._lay_contenido.setContentsMargins(28, 26, 28, 26)
        self._lay_contenido.setSpacing(14)

        scroll.setWidget(self._contenedor)
        root.addWidget(scroll)

        # Primera construcción
        self._datos = self._obtener_datos()
        self._construir_contenido()

        # Refresh automático cuando algo cambia en mantenimientos (asignación
        # de responsable desde la ficha, cierre de un evento que genera el
        # siguiente, etc). Igual que Programados.
        try:
            from signals import app_signals
            app_signals.mantenimiento_guardado.connect(self.actualizar)
        except Exception:
            # Si signals.py no existe / no tiene la señal, no rompemos.
            pass

    # ------------------------------------------------------
    #  Refrescar — llamado desde main.py al cambiar de pestaña
    # ------------------------------------------------------
    def actualizar(self):
        """Re-consulta la BD y reconstruye el contenido completo."""
        self._datos = self._obtener_datos()
        limpiar_layout(self._lay_contenido)
        self._construir_contenido()

    def _construir_contenido(self):
        self._lay_contenido.addWidget(self._crear_encabezado())
        self._lay_contenido.addLayout(self._crear_fila_kpis())
        self._lay_contenido.addLayout(self._crear_fila_calendario_notificaciones())
        self._lay_contenido.addLayout(self._crear_fila_criticos_estado())
        self._lay_contenido.addWidget(self._crear_sabias_que())
        self._lay_contenido.addStretch()

    # ------------------------------------------------------
    #  DATOS — queries reales a memoria.db
    # ------------------------------------------------------
    def _obtener_datos(self):
        """Hace todas las queries necesarias en una sola conexión.
        Si la BD no existe o falla algo, devuelve estructura con ceros."""
        datos = self._datos_vacios()

        conn = connect_db(create_if_missing=False)
        if conn is None:
            return datos

        try:
            cur = conn.cursor()

            # ===== KPIs =====
            n_tableros = cur.execute("SELECT COUNT(*) FROM tableros").fetchone()[0]
            n_transformadores = cur.execute("SELECT COUNT(*) FROM transformadores").fetchone()[0]
            datos["kpis"]["equipos_totales"] = n_tableros + n_transformadores

            datos["kpis"]["pendientes"] = cur.execute("""
                SELECT COUNT(*) FROM mantenimientos
                WHERE estado = 'programado'
                  AND responsable_tipo != 'pendiente'
                  AND date(fecha_inicio) BETWEEN date('now','localtime')
                                            AND date('now','localtime','+30 days')
            """).fetchone()[0]

            datos["kpis"]["vencidos"] = cur.execute("""
                SELECT COUNT(*) FROM mantenimientos
                WHERE estado = 'programado'
                  AND responsable_tipo != 'pendiente'
                  AND date(fecha_fin) < date('now','localtime')
            """).fetchone()[0]

            datos["kpis"]["hechos_mes"] = cur.execute("""
                SELECT COUNT(*) FROM mantenimientos
                WHERE estado = 'finalizado'
                  AND fecha_cierre IS NOT NULL
                  AND date(fecha_cierre) >= date('now','localtime','start of month')
                  AND date(fecha_cierre) <  date('now','localtime','start of month','+1 month')
            """).fetchone()[0]

            # ===== Calendario (mes actual) =====
            datos["calendario"]["programados"] = [
                r[0] for r in cur.execute("""
                    SELECT DISTINCT CAST(strftime('%d', fecha_inicio) AS INTEGER)
                    FROM mantenimientos
                    WHERE estado = 'programado'
                      AND responsable_tipo != 'pendiente'
                      AND strftime('%Y-%m', fecha_inicio) = strftime('%Y-%m', 'now','localtime')
                      AND date(fecha_fin) >= date('now','localtime')
                """).fetchall()
            ]
            datos["calendario"]["vencidos"] = [
                r[0] for r in cur.execute("""
                    SELECT DISTINCT CAST(strftime('%d', fecha_fin) AS INTEGER)
                    FROM mantenimientos
                    WHERE estado = 'programado'
                      AND responsable_tipo != 'pendiente'
                      AND strftime('%Y-%m', fecha_fin) = strftime('%Y-%m', 'now','localtime')
                      AND date(fecha_fin) < date('now','localtime')
                """).fetchall()
            ]

            # ===== Notificaciones =====
            # Se delega a notificaciones.py para que el cálculo viva en un
            # módulo dedicado y crezca a futuro (próximos vencimientos UVIE,
            # equipos sin mantto, etc) sin engordar este archivo.
            datos["notificaciones"] = obtener_notificaciones_activas()

            # ===== Equipos críticos (mantenimientos vencidos) =====
            filas_crit = cur.execute("""
                SELECT m.id, m.tipo_mantenimiento, m.fecha_fin,
                       CAST(julianday('now','localtime') - julianday(m.fecha_fin) AS INTEGER) AS dias,
                       COUNT(me.id)        AS n_eq,
                       MIN(me.equipo_id)   AS primer_eq_id,
                       MIN(me.equipo_tipo) AS primer_eq_tipo
                FROM mantenimientos m
                LEFT JOIN mantenimientos_equipos me ON me.mantenimiento_id = m.id
                WHERE m.estado = 'programado'
                  AND date(m.fecha_fin) < date('now','localtime')
                GROUP BY m.id
                ORDER BY dias DESC
                LIMIT 5
            """).fetchall()

            for mid, tipo_m, ffin, dias, n_eq, eq_id, eq_tipo in filas_crit:
                titulo, _ = self._titulo_y_sub(cur, n_eq, eq_id, eq_tipo, tipo_m)
                dias = max(dias or 0, 0)
                plural = "s" if dias != 1 else ""
                datos["criticos"].append({
                    "titulo":    titulo,
                    "subtitulo": f"Vencido hace {dias} día{plural}",
                    "dias":      dias,
                })

            # ===== Estado del sistema =====
            datos["inventario"].append(("Tableros",        n_tableros))
            datos["inventario"].append(("Transformadores", n_transformadores))

            # Circuitos (la tabla puede no existir en BDs muy viejas)
            try:
                n_circ = cur.execute("SELECT COUNT(*) FROM circuitos").fetchone()[0]
                datos["inventario"].append(("Circuitos", n_circ))
                n_no_nom = cur.execute(
                    "SELECT COUNT(*) FROM circuitos WHERE cumple_nom = 0"
                ).fetchone()[0]
                datos["circuitos_total"]  = n_circ
                datos["circuitos_no_nom"] = n_no_nom
            except Exception as e:
                print(f"[Inicio] aviso al consultar circuitos: {e}")

            # ===== Tip "Sabías que" =====
            if TIPS_NOM:
                idx = random.randint(0, len(TIPS_NOM) - 1)
                datos["sabias"] = {
                    "texto":      TIPS_NOM[idx]["texto"],
                    "referencia": TIPS_NOM[idx]["ref"],
                    "indice":     idx + 1,
                    "total":      len(TIPS_NOM),
                }

        except Exception as e:
            print(f"[Inicio] error al obtener datos: {e}")
        finally:
            conn.close()

        return datos

    def _datos_vacios(self):
        return {
            "kpis": {
                "equipos_totales": 0,
                "pendientes":      0,
                "vencidos":        0,
                "hechos_mes":      0,
            },
            "calendario":    {"programados": [], "vencidos": []},
            "notificaciones": [],
            "criticos":       [],
            "inventario": [],
            "circuitos_total":  0,
            "circuitos_no_nom": 0,
            "sabias": {
                "texto":      TIPS_NOM[0]["texto"] if TIPS_NOM else "",
                "referencia": TIPS_NOM[0]["ref"]   if TIPS_NOM else "",
                "indice":     1,
                "total":      len(TIPS_NOM),
            },
        }

    def _titulo_y_sub(self, cur, n_equipos, equipo_id, equipo_tipo, tipo_mantenimiento):
        """Devuelve (titulo, subtitulo) para una fila de mantenimiento.

        - 1 equipo: titulo = nombre/id del equipo, subtitulo = ubicación
        - N equipos: titulo = tipo de mantenimiento, subtitulo = 'N equipos'
        - Sin equipos: titulo = tipo de mantenimiento, subtitulo = ''
        """
        if n_equipos is None or n_equipos == 0 or equipo_id is None:
            return (tipo_mantenimiento or "Mantenimiento", "")

        if n_equipos > 1:
            return (tipo_mantenimiento or "Mantenimiento", f"{n_equipos} equipos")

        # n_equipos == 1
        nombre, ubicacion = self._detalle_equipo(cur, equipo_id, equipo_tipo)
        return (nombre, ubicacion)

    def _detalle_equipo(self, cur, equipo_id, equipo_tipo):
        """Resuelve nombre visible y ubicación a partir del equipo_id/tipo."""
        try:
            if equipo_tipo == "tableros":
                row = cur.execute(
                    "SELECT nombre, ubicacion FROM tableros WHERE id = ?",
                    (equipo_id,)
                ).fetchone()
                if row is None:
                    return (f"Tablero {equipo_id}", "")
                nombre, ubicacion = row
                if nombre:
                    return (str(nombre), str(ubicacion or ""))
                return (f"Tablero {equipo_id}", str(ubicacion or ""))

            if equipo_tipo == "transformadores":
                row = cur.execute(
                    "SELECT ubicacion FROM transformadores WHERE id = ?",
                    (equipo_id,)
                ).fetchone()
                if row is None:
                    return (f"Transformador {equipo_id}", "")
                return (f"Transformador {equipo_id}", str(row[0] or ""))

        except Exception as e:
            print(f"[Inicio] aviso al resolver equipo {equipo_tipo}/{equipo_id}: {e}")

        return (str(equipo_id), "")

    # ------------------------------------------------------
    #  SECCIONES VISUALES
    # ------------------------------------------------------
    def _crear_encabezado(self):
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        v = QVBoxLayout(cont)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        # Sin login todavía: saludo genérico, sin nombre.
        # TODO: cuando exista login, mostrar el nombre del usuario.
        v.addWidget(crear_label(
            saludo_por_hora(), color=COLOR_TEXT, tamaño=22, peso="600"
        ))

        # Subtítulo: solo fecha por ahora.
        # TODO: cuando exista la pestaña Proyecto y haya proyecto activo,
        # concatenar " · proyecto activo: <nombre>".
        v.addWidget(crear_label(
            fecha_legible(), color=COLOR_TEXT_DIM, tamaño=13
        ))
        return cont

    def _crear_fila_kpis(self):
        h = QHBoxLayout()
        # Márgenes explícitos a 0 para que este QHBoxLayout tenga el mismo
        # ancho efectivo que las QGridLayout de las otras dos filas.
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)
        k = self._datos["kpis"]

        # Subtítulos contextuales según el número
        sub_equipos = "Tableros + transformadores"
        sub_pend    = "Próximos 30 días"
        sub_venc    = "Requiere atención" if k["vencidos"] > 0 else "Sin pendientes"
        sub_hechos  = "Cerrados este mes"

        # Todas las cards con:
        #   - stretch=1 → todas exigen el mismo espacio.
        #   - sizePolicy Ignored horizontal → Qt IGNORA el sizeHint natural
        #     y les da un ancho matemáticamente igual, sin importar el
        #     texto interno. Sin esto, el sizeHint dominaba y "Requiere
        #     atención" hacía que esa card fuera más ancha que las demás.
        cards = [
            KpiCard("fa5s.bolt",                 "Equipos totales", k["equipos_totales"], sub_equipos),
            KpiCard("fa5s.calendar",             "Pendientes",      k["pendientes"],      sub_pend),
            KpiCard("fa5s.exclamation-triangle", "Vencidos",        k["vencidos"],        sub_venc, danger=(k["vencidos"] > 0)),
            KpiCard("fa5s.clipboard-check",      "Hechos este mes", k["hechos_mes"],      sub_hechos),
        ]
        for card in cards:
            card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            h.addWidget(card, stretch=1)
        return h

    def _crear_fila_calendario_notificaciones(self):
        # QGridLayout con columnStretch(0,1) y columnStretch(1,1), combinado
        # con sizePolicy Ignored horizontal en ambos widgets, garantiza que
        # ambas columnas ocupen EXACTAMENTE el 50% del ancho disponible,
        # sin importar el contenido interno de cada una. Sin el sizePolicy
        # Ignored, Qt respeta el sizeHint natural de cada widget y una
        # notificación con pill "Reintentar →" hace que la columna de
        # notificaciones sea más ancha que la del calendario.
        grid = QGridLayout()
        grid.setSpacing(14)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Card compacta del calendario. Ya no le pasamos los sets
        # de días programados/vencidos: la card los consulta sola
        # con _obtener_dias_con_eventos_mes de card_calendario.py.
        # Así toda la lógica de "qué es descriptivo" vive en un solo
        # lugar y coincide entre card compacta y modal expandido.
        # (Nota: self._datos["calendario"] queda como código muerto
        # que se puede limpiar en una sesión futura de refactor.)
        cal = CalendarioMes()
        cal.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # Botón "expandir" (esquina superior derecha de la card) →
        # abre el modal grande con vista split. Mismo patrón que
        # el botón expandir de la card de notificaciones.
        cal.expandir_solicitado.connect(self._abrir_modal_calendario)

        notif = self._crear_notificaciones()
        notif.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        # El calendario define el "tamaño de referencia" vertical de esta
        # fila — es lo que mide la card de notificaciones cuando está en
        # el estado vacío (palomita verde). Sin un tope superior explícito,
        # el sizePolicy Preferred deja que ambas cards se estiren cuando
        # el layout externo tiene espacio de sobra (fila de KPIs pequeña,
        # ventana alta), y el calendario acaba con huecos en el medio.
        # Fijamos maximumHeight en ambas cards al sizeHint del calendario:
        # así conservan siempre el tamaño natural del vacío, y las
        # notificaciones que no caben se ven por scroll interno de la
        # card + el botón "expandir" que abre el modal grande.
        alto_ref = cal.sizeHint().height()
        cal.setMaximumHeight(alto_ref)
        notif.setMaximumHeight(alto_ref)

        grid.addWidget(cal, 0, 0)
        grid.addWidget(notif, 0, 1)
        return grid

    def _crear_notificaciones(self):
        """Tarjeta de notificaciones que requieren acción. Hoy: asignar
        responsable a hijos auto-generados por series recurrentes. A
        futuro: UVIE por vencer, equipos sin mantto, etc — todos se
        calculan en notificaciones.py y aparecen aquí sin modificar este
        método (cada notif viene como dict con titulo/subtitulo/fecha).

        Cada fila es clickable: al hacer click se abre la FichaMantenimiento
        del mantto referido (cuando aplica). Tras guardar cambios desde la
        ficha, el signal mantenimiento_guardado refresca Inicio y la
        notificación desaparece automáticamente si la acción se completó.
        """
        card, layout = crear_tarjeta("cardNotificaciones")
        n_items = len(self._datos["notificaciones"])
        titulo_txt = f"Notificaciones ({n_items})" if n_items else "Notificaciones"
        color_icono = COLOR_WARNING if n_items else COLOR_TEXT_DIM

        # Header construido manualmente (en vez de crear_titulo_tarjeta)
        # para anclar el botón "expandir" a la derecha. La firma actual
        # del helper no permite widgets después del título, y queremos
        # mantener ese helper intacto porque lo usan otras cards.
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        h_head = QHBoxLayout(header)
        h_head.setContentsMargins(0, 0, 0, 0)
        h_head.setSpacing(6)

        lbl_ic = QLabel()
        lbl_ic.setPixmap(
            qta.icon("fa5s.bell", color=color_icono).pixmap(QSize(16, 16))
        )
        lbl_ic.setStyleSheet("background: transparent; border: none;")
        h_head.addWidget(lbl_ic)
        h_head.addWidget(crear_label(titulo_txt, color=COLOR_TEXT,
                                     tamaño=14, peso="600"))
        h_head.addStretch()

        # Botón "expandir": solo aparece cuando hay al menos 1 notif.
        # Es una herramienta de ayuda para ver listas largas con más
        # aire — abre un modal grande con la lista completa y filtro.
        # Cuando no hay notifs, no lo mostramos: expandir un estado
        # vacío sería confuso y el "todo en orden" ya se ve de un vistazo.
        if n_items:
            btn_expandir = QPushButton()
            btn_expandir.setIcon(qta.icon("fa5s.expand-alt", color=COLOR_TEXT_DIM))
            btn_expandir.setIconSize(QSize(14, 14))
            btn_expandir.setFixedSize(26, 26)
            btn_expandir.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_expandir.setToolTip("Ver todas las notificaciones")
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
            btn_expandir.clicked.connect(self._abrir_modal_notificaciones)
            h_head.addWidget(btn_expandir)

        layout.addWidget(header)
        layout.addSpacing(4)

        if not n_items:
            # Estado vacío delegado al helper — el mismo widget se usa
            # dentro del modal expandido cuando el filtro deja la lista
            # vacía, para que las dos vistas se vean consistentes.
            layout.addStretch()
            layout.addWidget(self._crear_estado_vacio_notif())
            layout.addStretch()
            return card

        # Las filas viven dentro de un QScrollArea interno para que la
        # card mantenga su tamaño natural (dictado por el calendario
        # hermano del QGridLayout). Sin esto, N filas empujan el
        # sizeHint vertical de la card, el grid respeta ese hint por
        # el sizePolicy(Ignored, Preferred), y el calendario a la
        # izquierda queda aplastado.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Scrollbar delgado tipo "overlay" — consistente con el look
        # oscuro del proyecto. Fondo transparente para que se lea sobre
        # la card oscura sin marcos.
        scroll.setStyleSheet("""
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
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0; background: transparent; border: none;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        cont_filas = QWidget()
        cont_filas.setStyleSheet("background: transparent;")
        v_filas = QVBoxLayout(cont_filas)
        v_filas.setContentsMargins(0, 0, 0, 0)
        v_filas.setSpacing(0)

        for i, notif in enumerate(self._datos["notificaciones"]):
            es_ultima = (i == n_items - 1)
            fila = self._crear_fila_notificacion(notif, es_ultima)
            v_filas.addWidget(fila)
        # Empuja el contenido hacia arriba cuando hay pocas filas
        # (evita centrado vertical del scroll cuando cabe todo).
        v_filas.addStretch()

        scroll.setWidget(cont_filas)
        layout.addWidget(scroll, stretch=1)
        return card

    def _crear_estado_vacio_notif(self, mensaje="Sin notificaciones pendientes"):
        """Widget del estado vacío de notificaciones: palomita verde
        centrada + leyenda. Compartido entre la card compacta de Inicio
        y el modal expandido — ambos muestran exactamente lo mismo
        cuando no hay nada que atender."""
        vacio = QFrame()
        vacio.setStyleSheet("background: transparent; border: none;")
        vv = QVBoxLayout(vacio)
        vv.setContentsMargins(0, 12, 0, 12)
        vv.setSpacing(6)
        vv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico_ok = QLabel()
        ico_ok.setPixmap(
            qta.icon("fa5s.check-circle", color="#4a7f3d").pixmap(QSize(28, 28))
        )
        ico_ok.setStyleSheet("background: transparent; border: none;")
        ico_ok.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_vacio = crear_label(mensaje, color=COLOR_TEXT_FAINT, tamaño=12)
        lbl_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vv.addWidget(ico_ok)
        vv.addWidget(lbl_vacio)
        return vacio

    def _crear_fila_notificacion(self, notif, es_ultima, generoso=False):
        """Fila clickable de notificación, layout propuesta C:
          [ícono]  equipo · fecha           [Asignar →]
                   grupo › ubicación · tipo

        Datos vienen estructurados desde notificaciones.py — aquí solo
        decidimos cómo presentarlos. Click → ejecuta la acción asociada
        (por ahora la única es 'asignar_responsable').

        `generoso=True` se usa desde el modal expandido: márgenes,
        íconos y textos ligeramente mayores para aprovechar el espacio.
        `generoso=False` (default) conserva el layout denso original
        de la card compacta — cero regresión visual."""
        mant_id = notif.get("mantenimiento_id")
        accion = notif.get("accion_tipo")

        fila = QFrame()
        fila.setObjectName("filaNotif")
        borde = "border: none;" if es_ultima else f"border-bottom: 1px solid {COLOR_BORDER};"
        fila.setStyleSheet(
            f"QFrame#filaNotif {{ background: transparent; {borde} border-radius: 4px; }}"
            f"QFrame#filaNotif:hover {{ background: rgba(255,255,255,0.03); }}"
        )
        if mant_id is not None and accion:
            fila.setCursor(Qt.CursorShape.PointingHandCursor)
            fila.mousePressEvent = lambda ev, mid=mant_id, acc=accion: self._on_click_notif(ev, mid, acc)

        h = QHBoxLayout(fila)
        # Padding vertical compacto por default; más generoso cuando
        # la fila vive dentro del modal expandido.
        if generoso:
            h.setContentsMargins(10, 12, 10, 12)
            h.setSpacing(14)
        else:
            h.setContentsMargins(4, 6, 4, 6)
            h.setSpacing(10)

        # Ícono según tipo. Cada nuevo tipo define su ícono qtawesome +
        # color en este mapa. Fallback discreto si viene un tipo
        # inesperado (no romper la UI si notificaciones.py agrega algo
        # que inicio.py aún no conoce).
        tipo_notif = notif.get("tipo", "")
        mapa_iconos = {
            "responsable_pendiente": ("fa5s.user-clock",           COLOR_WARNING),
            "archivado_exito":       ("fa5s.archive",              COLOR_ACCENT_LT),
            "archivado_fallo":       ("fa5s.exclamation-triangle", COLOR_DANGER),
        }
        icono_qta, color_icono = mapa_iconos.get(
            tipo_notif, ("fa5s.bell", COLOR_TEXT_DIM)
        )
        ico = QLabel()
        ico_size = 22 if generoso else 18
        ico.setPixmap(qta.icon(icono_qta, color=color_icono).pixmap(QSize(ico_size, ico_size)))
        ico.setStyleSheet("background: transparent; border: none;")
        h.addWidget(ico)

        # Centro: dos líneas de texto
        centro = QWidget()
        centro.setStyleSheet("background: transparent;")
        v = QVBoxLayout(centro)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)

        equipo_resumen = notif.get("equipo_resumen", "")
        fecha_disp     = notif.get("fecha_display", "")
        grupo_ruta     = notif.get("grupo_ruta", "")
        tipo_mantto    = notif.get("tipo_mantto", "")

        # Línea 1: equipo · fecha (prominente)
        if equipo_resumen and fecha_disp:
            linea1 = f"{equipo_resumen} · {fecha_disp}"
        else:
            linea1 = equipo_resumen or fecha_disp or "Mantenimiento"
        v.addWidget(crear_label(linea1, color=COLOR_TEXT,
                                tamaño=(14 if generoso else 13), peso="500"))

        # Línea 2: grupo › ubicación · tipo (contexto)
        partes = []
        if grupo_ruta:
            partes.append(grupo_ruta)
        if tipo_mantto:
            partes.append(tipo_mantto)
        if partes:
            v.addWidget(crear_label(" · ".join(partes), color=COLOR_TEXT_DIM,
                                    tamaño=(12 if generoso else 11)))

        h.addWidget(centro, stretch=1)

        # Pill CTA (derecha). Texto + color se mapean por accion_tipo.
        # Cada acción tiene su intención visual: warning para asignar,
        # neutro para marcar como leído, danger para reintentar.
        mapa_ctas = {
            "asignar_responsable":            ("Asignar →",    COLOR_WARNING),
            "marcar_archivado_exito_leido":   ("Marcar leído", COLOR_TEXT_DIM),
            "reintentar_archivado":           ("Reintentar →", COLOR_DANGER),
        }
        cta_texto, cta_color = mapa_ctas.get(
            accion, ("Ver →", COLOR_TEXT_DIM)
        )
        # Convertimos el color hex a rgba para el fondo tintado suave.
        # (Los colores del proyecto son todos hex de 7 caracteres.)
        try:
            r = int(cta_color[1:3], 16)
            g = int(cta_color[3:5], 16)
            b = int(cta_color[5:7], 16)
            cta_bg = f"rgba({r}, {g}, {b}, 0.15)"
            cta_border = f"rgba({r}, {g}, {b}, 0.3)"
        except (ValueError, IndexError):
            cta_bg = "rgba(255, 255, 255, 0.05)"
            cta_border = "rgba(255, 255, 255, 0.1)"

        cta = QLabel(cta_texto)
        cta_pad  = "6px 12px" if generoso else "4px 10px"
        cta_size = "11px" if generoso else "10px"
        cta.setStyleSheet(f"""
            background-color: {cta_bg};
            color: {cta_color};
            font-size: {cta_size};
            font-weight: 500;
            padding: {cta_pad};
            border: 1px solid {cta_border};
            border-radius: 10px;
        """)
        h.addWidget(cta)

        return fila

    def _on_click_notif(self, ev, mant_id, accion):
        """Maneja el click en una notificación según su acción.

        Acciones soportadas:
          - 'asignar_responsable': abre ListaResponsablesDialog para elegir
            responsable y persistir la asignación. La notificación
            desaparece sola cuando se emite mantenimiento_guardado.
          - 'marcar_archivado_exito_leido': borra los flags de metadata
            de la notificación de éxito. Refresca Inicio para que
            desaparezca visualmente.
          - 'reintentar_archivado': abre DialogReintentarArchivado con
            el mensaje técnico del último fallo y un botón para
            reintentar la migración anual. Si el reintento tiene éxito,
            los flags de fallo se borran y la notificación desaparece.
          - Otras: fallback abre la ficha del mantto por su ID.
        Si el usuario cierra el diálogo sin elegir, no pasa nada."""
        if ev.button() != Qt.MouseButton.LeftButton:
            return

        if accion == "asignar_responsable":
            self._abrir_selector_responsable(mant_id)
            return

        if accion == "marcar_archivado_exito_leido":
            try:
                from migracion_archivo import marcar_notificacion_exito_leida
                marcar_notificacion_exito_leida()
                # Refrescar Inicio para que la notificación desaparezca
                # de la card sin que el usuario tenga que hacer nada más.
                self.actualizar()
            except Exception as e:
                print(f"[Inicio] error al marcar archivado exito leído: {e}")
            return

        if accion == "reintentar_archivado":
            try:
                dlg = DialogReintentarArchivado(self)
                dlg.exec()
                # El diálogo maneja el reintento internamente y actualiza
                # los flags de metadata. Refrescamos Inicio para que la
                # notificación refleje el nuevo estado (desaparecida si
                # tuvo éxito, o con nuevo mensaje si falló de nuevo).
                self.actualizar()
            except Exception as e:
                print(f"[Inicio] error al abrir diálogo de reintento: {e}")
            return

        # Acciones futuras: por defecto, abrir la ficha del mantto
        try:
            from ficha_mantenimiento import FichaMantenimientoDialog
            FichaMantenimientoDialog(mant_id, self).exec()
        except Exception as e:
            print(f"[Inicio] no se pudo abrir la ficha del mantto {mant_id}: {e}")

    def _abrir_modal_notificaciones(self):
        """Abre el diálogo modal grande con la lista completa de
        notificaciones. Se acompaña de un overlay oscuro sobre la
        ventana principal para dar énfasis visual — clic fuera del
        modal (sobre el overlay) también cierra.

        Al terminar refrescamos Inicio: dentro del modal el usuario
        pudo asignar responsables, marcar leído o reintentar el
        archivado, y todas esas acciones cambian el set de notifs
        pendientes."""
        overlay = _OverlayOscuro(self.window())
        overlay.show()
        overlay.raise_()

        dlg = DialogNotificacionesExpandido(self)
        overlay.clicked.connect(dlg.reject)
        try:
            dlg.exec()
        finally:
            overlay.deleteLater()
            self.actualizar()

    def _abrir_modal_calendario(self):
        """Abre el diálogo modal grande con el calendario navegable +
        panel de eventos del día. Mismo patrón desacoplado que
        _abrir_modal_notificaciones: overlay oscuro sobre la ventana
        principal, clic fuera cierra, refresh al terminar.

        El refresh final cubre el caso en el que el usuario, desde
        una card de evento del modal, abrió la ficha del mantto y
        cambió su estado (por ejemplo cerró un evento). Al volver
        a Inicio, la card compacta debe reflejar el nuevo set de
        días con puntos."""
        overlay = _OverlayOscuro(self.window())
        overlay.show()
        overlay.raise_()

        dlg = DialogCalendarioExpandido(self)
        overlay.clicked.connect(dlg.reject)
        try:
            dlg.exec()
        finally:
            overlay.deleteLater()
            self.actualizar()

    def _abrir_selector_responsable(self, mant_id):
        """Flujo rápido: ListaResponsablesDialog → UPDATE → signal."""
        try:
            from lista_responsables import ListaResponsablesDialog
        except Exception as e:
            print(f"[Inicio] ListaResponsablesDialog no disponible: {e}")
            return

        # Mismo patrón que programar_nuevo.py: parent=self y guardar el diálogo
        # como atributo de instancia. Usar variable local hace que el GC pueda
        # liberar el diálogo antes de tiempo y renderizar mal la tabla.
        self.dialogo_responsables = ListaResponsablesDialog(self)

        # Replicar el estilo base de MantenimientosWindow. Cuando el diálogo
        # se abre desde Programar nuevo, hereda naturalmente ese CSS (pestañas
        # de mantenimientos + botón, entrada, combo consistentes con la app).
        # InicioWindow NO tiene esos selectores genéricos, así que el diálogo
        # se veía con el estilo nativo de Windows (scrollbar gruesa gris,
        # pestañas con look distinto). Este CSS iguala el aspecto.
        self.dialogo_responsables.setStyleSheet("""
            QWidget { background-color: #121212; color: white; font-family: 'Segoe UI'; }
            QLineEdit, QComboBox, QTextEdit, QDateEdit {
                background-color: #1e1e1e; color: white;
                border: 1px solid #444; border-radius: 5px;
            }
            QPushButton {
                background-color: #3a3a3a; color: white;
                border-radius: 8px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #505050; }
        """)

        self.dialogo_responsables.responsable_asignado.connect(
            lambda data, mid=mant_id: self._aplicar_responsable(mid, data)
        )
        self.dialogo_responsables.exec()

    def _aplicar_responsable(self, mant_id, data):
        """Persiste el responsable elegido y dispara refresh global."""
        if not data or not data.get("tipo"):
            # El usuario "quitó" responsable o no eligió nada — no hacemos nada
            return
        try:
            from db_manager import asignar_responsable_mantenimiento
            ok = asignar_responsable_mantenimiento(mant_id, data)
            if not ok:
                print(f"[Inicio] no se pudo asignar responsable a mant {mant_id}")
                return
        except Exception as e:
            print(f"[Inicio] error al asignar responsable: {e}")
            return

        # Signal global: Programados / Finalizados / KPIs de Inicio se
        # refrescan solos. Inicio también, porque en __init__ conectamos
        # mantenimiento_guardado → self.actualizar. No llamamos self.actualizar()
        # directo para evitar refrescar dos veces la misma pantalla.
        try:
            from signals import app_signals
            app_signals.mantenimiento_guardado.emit()
        except Exception:
            # Si signals.py no existe, refresh manual como fallback
            self.actualizar()

    def _crear_fila_criticos_estado(self):
        # Mismo tratamiento que _crear_fila_calendario_notificaciones:
        # QGridLayout con columnStretch iguales + sizePolicy Ignored
        # horizontal en ambos widgets garantiza columnas de exactamente
        # 50% de ancho, sin depender del contenido interno.
        grid = QGridLayout()
        grid.setSpacing(14)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        criticos = self._crear_equipos_criticos()
        criticos.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        estado = self._crear_estado_sistema()
        estado.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        grid.addWidget(criticos, 0, 0)
        grid.addWidget(estado,   0, 1)
        return grid

    def _crear_equipos_criticos(self):
        card, layout = crear_tarjeta("cardCriticos")
        color_icono_titulo = COLOR_DANGER if self._datos["criticos"] else COLOR_TEXT_DIM
        layout.addWidget(crear_titulo_tarjeta(
            "Mantenimientos vencidos",
            icono_qta="fa5s.exclamation-triangle",
            color_icono=color_icono_titulo,
        ))
        layout.addSpacing(4)

        items = self._datos["criticos"]
        if not items:
            layout.addWidget(crear_fila_vacia("Sin mantenimientos vencidos. 👌"))
            return card

        for i, it in enumerate(items):
            tipo_badge = "crit" if it["dias"] >= 7 else "warn"
            texto_badge = f"{it['dias']} d" if it["dias"] != 1 else "1 d"
            badge = crear_badge(texto_badge, tipo_badge)
            color_sub = COLOR_DANGER if it["dias"] >= 7 else COLOR_WARNING

            es_ultima = (i == len(items) - 1)
            fila = crear_fila_lista(
                it["titulo"], it["subtitulo"], color_sub,
                derecha_widgets=[badge],
                es_ultima=es_ultima,
            )
            layout.addWidget(fila)
        return card

    def _crear_estado_sistema(self):
        card, layout = crear_tarjeta("cardEstado")
        layout.addWidget(crear_titulo_tarjeta("Estado del sistema"))
        layout.addSpacing(8)

        if not self._datos["inventario"]:
            layout.addWidget(crear_fila_vacia("Sin equipos registrados todavía."))
            return card

        for label, valor in self._datos["inventario"]:
            self._fila_etiqueta_valor(layout, label, str(valor))

        # Aviso de circuitos que no cumplen NOM (si los hay)
        n_no_nom = self._datos.get("circuitos_no_nom", 0)
        n_total  = self._datos.get("circuitos_total", 0)
        if n_total > 0:
            layout.addSpacing(6)
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background-color: {COLOR_BORDER}; border: none;")
            layout.addWidget(sep)
            layout.addSpacing(10)

            if n_no_nom > 0:
                self._fila_etiqueta_valor(
                    layout, "Circuitos no cumplen NOM",
                    str(n_no_nom), color_valor=COLOR_WARNING,
                )
            else:
                self._fila_etiqueta_valor(
                    layout, "Cumplimiento NOM",
                    "100%", color_valor=COLOR_ACCENT_LT,
                )
        return card

    def _fila_etiqueta_valor(self, layout_padre, etiqueta, valor, color_valor=None):
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 3, 0, 3)
        fila.addWidget(crear_label(etiqueta, color=COLOR_TEXT_DIM, tamaño=12))
        fila.addStretch()
        fila.addWidget(crear_label(
            valor, color=color_valor or COLOR_TEXT,
            tamaño=12, peso="500",
        ))
        layout_padre.addLayout(fila)

    def _crear_sabias_que(self):
        cont = QFrame()
        cont.setObjectName("sabiasCard")
        cont.setStyleSheet(f"""
            QFrame#sabiasCard {{
                background-color: rgba(0, 120, 215, 0.08);
                border: 1px solid rgba(0, 120, 215, 0.25);
                border-radius: 8px;
            }}
        """)

        h = QHBoxLayout(cont)
        h.setContentsMargins(18, 14, 18, 14)
        h.setSpacing(14)

        ic = QLabel()
        ic.setPixmap(qta.icon("fa5s.lightbulb", color=COLOR_ACCENT_LT).pixmap(QSize(20, 20)))
        ic.setStyleSheet("background: transparent; border: none;")
        ic.setAlignment(Qt.AlignmentFlag.AlignTop)
        h.addWidget(ic)

        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent;")
        v = QVBoxLayout(cuerpo)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        v.addWidget(crear_label("Sabías que…", color=COLOR_ACCENT_LT, tamaño=11, peso="600"))

        s = self._datos["sabias"]
        tip_html = (
            f'<span style="color: #c0d8f0;">{s["texto"]}</span> '
            f'<span style="color: rgba(192, 216, 240, 0.6);">— {s["referencia"]}</span>'
        )
        tip = QLabel(tip_html)
        tip.setStyleSheet("font-size: 13px; background: transparent; border: none;")
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(tip)

        h.addWidget(cuerpo, stretch=1)

        contador = crear_label(
            f"{s['indice']} de {s['total']}",
            color="rgba(74, 158, 255, 0.7)", tamaño=10,
        )
        contador.setAlignment(Qt.AlignmentFlag.AlignTop)
        h.addWidget(contador)
        return cont


# ══════════════════════════════════════════════════════════════════════
#  DIÁLOGO DE REINTENTO DEL ARCHIVADO (Fase 4)
# ══════════════════════════════════════════════════════════════════════

class DialogReintentarArchivado(QDialog):
    """
    Diálogo modal que se abre al hacer clic en la notificación de
    "archivado falló". Muestra el mensaje técnico del error y ofrece
    un botón para reintentar la migración.

    Estados posibles del diálogo:
      1. Inicial: muestra error + botones [Cancelar] [Reintentar].
      2. Al pulsar Reintentar: el botón se desactiva y su texto cambia
         a "Reintentando...". Se ejecuta migracion_archivo.reintentar_migracion().
      3. Si el reintento tuvo éxito: mensaje de éxito y solo botón [Cerrar].
      4. Si el reintento volvió a fallar: se actualiza el mensaje de error
         con el nuevo detalle y se reactiva el botón para probar otra vez.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("No se completó el archivado")
        self.setModal(True)
        self.setMinimumWidth(520)
        # Stylesheet consistente con ficha_mantenimiento.py: define un
        # look base para QPushButton y variantes por property("accion").
        # Así los botones lucen igual que en el resto de la app en vez
        # de "genéricos bonitos".
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_CARD};
                color: {COLOR_TEXT};
            }}
            QPushButton {{
                background: #2a2a2a;
                color: #fff;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background: #353535; }}
            QPushButton:disabled {{
                background: #1a1a1a;
                color: #555;
                border-color: #2a2a2a;
            }}
            QPushButton[accion="primario"] {{
                background: #2a4055; border: 1px solid #2a5085;
            }}
            QPushButton[accion="primario"]:hover {{ background: #355275; }}
            QPushButton[accion="primario"]:disabled {{
                background: #1a2530; border-color: #223045; color: #556;
            }}
            QPushButton[accion="cerrar_dialog"] {{
                background: transparent; color: #aaa; border: 1px solid #444;
            }}
            QPushButton[accion="cerrar_dialog"]:hover {{
                background: #2a2a2a; color: #ddd;
            }}
        """)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        # Encabezado con ícono + título. Guardamos referencias para poder
        # transformar el estado a "éxito" cuando el reintento sale bien.
        # Ícono a 22px (no 28) para no dominar visualmente y quedar
        # proporcional al tamaño del título de al lado.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        self.ico_header = QLabel()
        self.ico_header.setPixmap(
            qta.icon("fa5s.exclamation-triangle", color=COLOR_DANGER)
               .pixmap(QSize(22, 22))
        )
        self.ico_header.setStyleSheet("background: transparent;")
        header.addWidget(self.ico_header)

        self.lbl_titulo = crear_label(
            "No se completó el archivado",
            color=COLOR_TEXT, tamaño=15, peso="bold"
        )
        header.addWidget(self.lbl_titulo, stretch=1)
        v.addLayout(header)

        # Descripción breve
        self.lbl_descripcion = crear_label(
            "Ocurrió un error al mover los mantenimientos viejos al "
            "archivo histórico. La base de datos no fue modificada. "
            "Puedes reintentar ahora.",
            color=COLOR_TEXT_DIM, tamaño=12
        )
        self.lbl_descripcion.setWordWrap(True)
        v.addWidget(self.lbl_descripcion)

        # Área de detalle técnico (solo lectura, seleccionable, scrolleable)
        self.txt_error = QTextEdit()
        self.txt_error.setReadOnly(True)
        self.txt_error.setMaximumHeight(120)
        self.txt_error.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLOR_BG};
                color: {COLOR_TEXT_DIM};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                padding: 8px;
            }}
        """)
        v.addWidget(self.txt_error)

        # Cargar mensaje inicial desde metadata.
        self._cargar_mensaje_error()

        # Botones. Un solo botón "Reintentar" — el usuario cancela con
        # la X de la barra de título, no hace falta un botón redundante.
        # Si cierra sin reintentar, el flag de fallo persiste y la
        # notificación sigue en Inicio (el usuario "aplazó" la acción).
        botones_h = QHBoxLayout()
        botones_h.addStretch()

        self.btn_reintentar = QPushButton("Reintentar")
        self.btn_reintentar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reintentar.setProperty("accion", "primario")
        self.btn_reintentar.clicked.connect(self._on_reintentar)
        botones_h.addWidget(self.btn_reintentar)

        v.addLayout(botones_h)

    def _cargar_mensaje_error(self):
        """Lee el mensaje técnico actual desde metadata y lo muestra."""
        try:
            from migracion_archivo import obtener_mensaje_fallo
            self.txt_error.setPlainText(
                obtener_mensaje_fallo() or "(sin detalles técnicos)"
            )
        except Exception as e:
            self.txt_error.setPlainText(f"(error al leer detalles: {e})")

    def _on_reintentar(self):
        """Ejecuta el reintento con feedback visual. Actualiza el estado
        del diálogo según el resultado."""
        # Fase "en progreso": deshabilitar y cambiar texto.
        self.btn_reintentar.setEnabled(False)
        self.btn_reintentar.setText("Reintentando...")
        QApplication.processEvents()  # que la UI muestre el cambio ya.

        try:
            from migracion_archivo import reintentar_migracion
            exito, mensaje = reintentar_migracion()
        except Exception as e:
            exito, mensaje = False, f"Excepción inesperada: {e}"

        if exito:
            self._mostrar_estado_exito(mensaje)
        else:
            self._mostrar_estado_fallo_nuevo(mensaje)

    def _mostrar_estado_exito(self, mensaje: str):
        """Transforma el diálogo al estado 'ya se completó'. El usuario
        cierra con la X de la barra de título — no hay botón Cerrar
        redundante. El flag de fallo ya fue borrado por reintentar_migracion()."""
        # Cambiar título de ventana.
        self.setWindowTitle("Archivado completado")

        # Actualizar el header prominente del diálogo: ícono verde de
        # check + título "Archivado completado". Sin esto, el título
        # rojo "No se completó" seguiría en pantalla contradiciendo el
        # mensaje de éxito de abajo.
        self.ico_header.setPixmap(
            qta.icon("fa5s.check-circle", color=COLOR_SUCCESS)
               .pixmap(QSize(22, 22))
        )
        self.lbl_titulo.setText("Archivado completado")

        # Actualizar descripción y detalle.
        self.lbl_descripcion.setText(
            "El archivado se completó correctamente. "
            "Puedes cerrar esta ventana."
        )
        self.txt_error.setPlainText(mensaje or "Migración completada.")

        # Ocultar Reintentar — ya no aplica. La X cierra el diálogo.
        self.btn_reintentar.hide()

    def _mostrar_estado_fallo_nuevo(self, mensaje: str):
        """Actualiza el mensaje de error y reactiva el botón para
        probar otra vez."""
        self.txt_error.setPlainText(mensaje or "(sin detalles adicionales)")
        self.btn_reintentar.setEnabled(True)
        self.btn_reintentar.setText("Reintentar")

# ============================================================
#  OVERLAY OSCURO REUTILIZABLE PARA MODALES EXPANDIDOS
# ============================================================
class _OverlayOscuro(QWidget):
    """Widget semi-transparente que oscurece el fondo detrás de un
    modal. Se ancla al top-level widget y se redimensiona
    automáticamente cuando la ventana principal cambia de tamaño.

    Al hacer clic sobre él, emite la señal `clicked` — el diálogo
    asociado puede conectarla a su propio `reject()` para cerrar
    con "clic fuera".

    Uso típico:
        overlay = _OverlayOscuro(self.window())
        overlay.show()
        overlay.raise_()
        dlg = MiDialogo(self)
        overlay.clicked.connect(dlg.reject)
        try:
            dlg.exec()
        finally:
            overlay.deleteLater()
    """
    clicked = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 140);")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Filtro en el parent para seguir cualquier resize de la ventana
        # principal (maximizar, restaurar, snap a mitad de pantalla).
        parent.installEventFilter(self)
        self._ajustar_geometria()

    def _ajustar_geometria(self):
        p = self.parent()
        if p is not None:
            self.setGeometry(p.rect())

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Type.Resize:
            self._ajustar_geometria()
        return False

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


# ============================================================
#  DIÁLOGO EXPANDIDO DE NOTIFICACIONES
# ============================================================
class DialogNotificacionesExpandido(QDialog):
    """Diálogo modal grande con la lista completa de notificaciones.

    Sirve cuando la card compacta del Inicio se queda corta (muchas
    notifs, ventana en tamaño pequeño). Muestra las mismas filas con
    más aire y agrega un dropdown de filtro por tipo.

    Reutiliza `_crear_fila_notificacion(..., generoso=True)` del
    InicioWindow padre — mismo look, mismo comportamiento, misma
    lógica de click. Cuando el filtro deja la lista vacía, muestra
    el mismo estado vacío que la card compacta.
    """

    def __init__(self, inicio_window):
        super().__init__(inicio_window)
        self._inicio = inicio_window
        self.setWindowTitle("Notificaciones")
        self.setModal(True)
        self.setMinimumSize(680, 500)

        # Mismo QSS base que DialogReintentarArchivado + estilos para
        # el QComboBox de filtro (consistente con archivo_historico.py:
        # sin custom drop-down/down-arrow para que Qt use el chevron
        # nativo de Windows 11, que sí renderiza bien).
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
                min-width: 200px;
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

        # ─── Header: ícono grande + título + stretch + dropdown filtro ───
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        n_items = len(self._inicio._datos["notificaciones"])
        col_head = COLOR_WARNING if n_items else COLOR_TEXT_DIM

        ico_head = QLabel()
        ico_head.setPixmap(qta.icon("fa5s.bell", color=col_head).pixmap(QSize(24, 24)))
        ico_head.setStyleSheet("background: transparent;")
        header.addWidget(ico_head)

        titulo_txt = f"Notificaciones ({n_items})" if n_items else "Notificaciones"
        self.lbl_titulo = crear_label(titulo_txt, color=COLOR_TEXT, tamaño=16, peso="bold")
        header.addWidget(self.lbl_titulo, stretch=1)

        # Dropdown de filtro. El userData de cada opción se lee en
        # _reconstruir_lista() para decidir qué notifs incluir.
        self.combo_filtro = QComboBox()
        self.combo_filtro.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_filtro.addItem("Todas", userData="todas")
        self.combo_filtro.addItem("Responsables pendientes", userData="responsable_pendiente")
        self.combo_filtro.addItem("Archivado", userData="archivado")
        self.combo_filtro.currentIndexChanged.connect(self._reconstruir_lista)
        header.addWidget(self.combo_filtro)

        v.addLayout(header)

        # Línea separadora tenue debajo del header.
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {COLOR_BORDER}; border: none; max-height: 1px;")
        v.addWidget(sep)

        # ─── Cuerpo: scroll area con las filas ───
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cont_filas = QWidget()
        self.cont_filas.setStyleSheet("background: transparent;")
        self.layout_filas = QVBoxLayout(self.cont_filas)
        self.layout_filas.setContentsMargins(0, 0, 0, 0)
        self.layout_filas.setSpacing(0)

        self.scroll.setWidget(self.cont_filas)
        v.addWidget(self.scroll, stretch=1)

        # Llenar la lista inicial — filtro por defecto es "Todas".
        self._reconstruir_lista()

    def _limpiar_layout(self):
        """Vacía completamente el layout de filas antes de repintarlo.
        Usamos hide() antes de deleteLater() para evitar el flicker
        que teníamos en finalizados.py y programados.py con
        setParent(None)."""
        while self.layout_filas.count() > 0:
            item = self.layout_filas.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def _reconstruir_lista(self):
        """Filtra las notifs según el dropdown y repinta el contenedor.
        Si el filtro deja la lista vacía, muestra el mismo estado vacío
        que la card de Inicio — consistencia visual entre las dos
        vistas."""
        self._limpiar_layout()

        criterio = self.combo_filtro.currentData()
        todas = self._inicio._datos["notificaciones"]

        if criterio == "responsable_pendiente":
            filtradas = [n for n in todas if n.get("tipo") == "responsable_pendiente"]
        elif criterio == "archivado":
            filtradas = [n for n in todas
                         if n.get("tipo") in ("archivado_exito", "archivado_fallo")]
        else:  # "todas" o fallback
            filtradas = list(todas)

        if not filtradas:
            # Palomita verde centrada + leyenda, igual que la card.
            self.layout_filas.addStretch()
            self.layout_filas.addWidget(self._inicio._crear_estado_vacio_notif())
            self.layout_filas.addStretch()
            return

        n = len(filtradas)
        for i, notif in enumerate(filtradas):
            es_ultima = (i == n - 1)
            fila = self._inicio._crear_fila_notificacion(notif, es_ultima, generoso=True)
            self.layout_filas.addWidget(fila)
        # Empuja el contenido hacia arriba (evita centrado vertical
        # cuando hay pocas filas).
        self.layout_filas.addStretch()
