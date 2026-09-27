# ficha_mantenimiento.py
"""
Ventana de detalle (ficha) de un mantenimiento.

Layout panel 2 columnas (mockup 2). Sidebar izquierdo compacto con datos
escaneables. Columna derecha amplia con equipos y descripción (scroll
propio cuando es larga). Header con badge de estado y franja de color.
Footer con acciones contextuales al estado.

Iconos vectoriales vía qtawesome (Font Awesome 5 Solid). En esta fase
(2) la ficha es de SOLO LECTURA; los botones de acción muestran un aviso
de "próximamente" — la implementación real es la fase 3.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QScrollArea, QSizePolicy, QMessageBox
)
from PyQt6.QtCore import Qt, QSize, QTimer, QVariantAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QPixmap

from datetime import datetime
import qtawesome as qta

from db_manager import (
    ejecutar_query,
    cancelar_mantenimiento,
    reprogramar_mantenimiento,
    cerrar_mantenimiento_pendiente,
    cerrar_mantenimiento_cancelado,
    copiar_informe_pdf,
)


# ── Configuración visual por estado ─────────────────────────────────────────
# color:     acento principal (franja inferior del header + texto del estado)
# dot:       puntito al lado del nombre del estado
# header_bg: fondo de la titlebar y el header. Cada uno es la versión muy
#            oscura (~15% luminosidad) del color del estado: da el "tinte"
#            sin saturar, integrando titlebar + header visualmente.
ESTADO_CONFIG = {
    "Programado":       {"color": "#5cb1ff", "dot": "#5cb1ff", "header_bg": "#1a2330", "badge_bg": "#2a5085"},
    "En curso":         {"color": "#f1c40f", "dot": "#f1c40f", "header_bg": "#2a2515", "badge_bg": "#5a4a15"},
    "Pendiente cierre": {"color": "#e67e22", "dot": "#e67e22", "header_bg": "#2a1f15", "badge_bg": "#5a3a1f"},
    "Cancelado":        {"color": "#e74c3c", "dot": "#e74c3c", "header_bg": "#2a1818", "badge_bg": "#5a2828"},
    "Finalizado":       {"color": "#6fc28f", "dot": "#6fc28f", "header_bg": "#1a2a1f", "badge_bg": "#2a5a3a"},
}

# Colores estándar de iconos en secciones (no dependen del estado)
COLOR_ICONO_PROGRAMA   = "#5cb1ff"  # calendario azul
COLOR_ICONO_GRUPO      = "#d4a04c"  # marker ámbar
COLOR_ICONO_RESPON     = "#6fc28f"  # persona verde
COLOR_ICONO_COSTO      = "#d4a04c"  # moneda ámbar
COLOR_ICONO_CALENDAR   = "#aaaaaa"  # nube gris
COLOR_ICONO_EQUIPOS    = "#d4a04c"  # herramienta ámbar
COLOR_ICONO_DESC       = "#aaaaaa"  # documento gris
COLOR_ICONO_TEL        = "#888888"
COLOR_ICONO_MAIL       = "#888888"


# ── Helpers de fechas ───────────────────────────────────────────────────────
def _formato_delta(delta_seconds: int, prefijo: str) -> str:
    total_min = abs(int(delta_seconds / 60))
    if total_min < 1:
        return f"{prefijo} <1 min"
    if total_min < 60:
        return f"{prefijo} {total_min} min"
    horas = total_min // 60
    if horas < 48:
        return f"{prefijo} {horas} h"
    dias = horas // 24
    return f"{prefijo} {dias} días"


def _texto_tiempo_relativo(estado_visual: str, dt_inicio, dt_fin) -> str:
    ahora = datetime.now()
    if estado_visual == "Programado":
        return _formato_delta((dt_inicio - ahora).total_seconds(), "empieza en")
    if estado_visual == "En curso":
        return _formato_delta((dt_fin - ahora).total_seconds(), "termina en")
    if estado_visual == "Pendiente cierre":
        return _formato_delta((ahora - dt_fin).total_seconds(), "terminó hace")
    if estado_visual == "Cancelado":
        return "cancelado"
    if estado_visual == "Finalizado":
        return "finalizado"
    return ""


def _formato_creado(creado_en_str: str) -> str:
    try:
        dt = datetime.strptime(creado_en_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(creado_en_str, "%Y-%m-%d %H:%M")
        except ValueError:
            return ""
    meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    return f"creado el {dt.day:02d} {meses[dt.month-1]} {dt.year} · {dt.strftime('%H:%M')}"


def _texto_chip_recurrencia(recurrencia_meses) -> str:
    """Etiqueta del chip 'CADA ...' en el header.

    Convención de valores:
        1  → "CADA MES"
        N  → "CADA N MESES"  (N > 1)
        0  → "CADA DÍA (PRUEBA)"   ← sentinela del modo de pruebas QA
        None / raro → "RECURRENTE"  (fallback defensivo)
    """
    if recurrencia_meses is None:
        return "⟳ RECURRENTE"
    try:
        m = int(recurrencia_meses)
    except (TypeError, ValueError):
        return "⟳ RECURRENTE"
    if m == 0:
        return "⟳ CADA DÍA (PRUEBA)"
    if m == 1:
        return "⟳ CADA MES"
    return f"⟳ CADA {m} MESES"


def _formato_fecha_larga(dt: datetime) -> str:
    meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    return f"{dt.day:02d} {meses[dt.month-1]} {dt.year}"


def _formato_duracion(dt_inicio: datetime, dt_fin: datetime) -> str:
    total_min = int((dt_fin - dt_inicio).total_seconds() / 60)
    if total_min < 60:
        return f"{total_min} minutos"
    horas = total_min // 60
    if horas < 24:
        return f"{horas} h" if total_min % 60 == 0 else f"{horas} h {total_min % 60} min"
    dias = horas // 24
    return f"{dias} días" if horas % 24 == 0 else f"{dias} días {horas % 24} h"


def _icon_label(icon_name: str, color: str, size: int = 14) -> QLabel:
    """Devuelve un QLabel con un icono vectorial de qtawesome."""
    lbl = QLabel()
    lbl.setPixmap(qta.icon(icon_name, color=color).pixmap(size, size))
    lbl.setFixedSize(size, size)
    lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return lbl


def _mezclar_hex(c1: str, c2: str, t: float) -> str:
    """
    Interpola dos colores hex '#rrggbb' y devuelve hex. t en [0,1].
    Usado para animar las transiciones de color cuando el estado cambia.
    """
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _styled_frame(object_name: str) -> QFrame:
    """
    Crea un QFrame configurado para que el stylesheet funcione bien:
    - Sin shape default (que dibuja borde sutil → "rectángulos negros").
    - WA_StyledBackground True para que Qt respete el background del stylesheet.
    """
    f = QFrame()
    f.setObjectName(object_name)
    f.setFrameShape(QFrame.Shape.NoFrame)
    f.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return f


# ── Diálogo principal ───────────────────────────────────────────────────────
class FichaMantenimientoDialog(QDialog):

    def __init__(self, mantenimiento_id: int, parent=None, origen_rect=None):
        super().__init__(parent)
        self.mantenimiento_id = mantenimiento_id
        self.setWindowTitle(f"Mantenimiento #{mantenimiento_id}")
        self.setMinimumSize(820, 560)
        self.resize(860, 600)

        # Frameless: quitamos la barra de título nativa del SO para que el
        # encabezado del diálogo sea de un solo diseño, integrado con el
        # color del estado. Implementamos botón X + drag manual abajo.
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        # Permite que el QDialog tenga fondo transparente; el contenido vive
        # en un main_container con border-radius, así toda la ventana
        # aparece con esquinas redondeadas en lugar del rectángulo de Windows.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._drag_offset = None  # offset entre cursor y topLeft para drag

        self.datos = None
        self.equipos = []
        self.ruta_grupo = ""

        if not self._cargar_datos():
            QMessageBox.warning(parent, "Mantenimiento",
                                f"No se pudo cargar el mantenimiento #{mantenimiento_id}.")
            # Red de seguridad: sin UI construida, exec() sobre este diálogo
            # deja la app en estado indefinido (típicamente congelamiento).
            # Programamos el cierre para el próximo ciclo del event loop —
            # así exec() retorna inmediatamente con Rejected en vez de
            # mostrar una ventana rota. QTimer ya está importado a nivel
            # de módulo (línea de imports arriba); un `from ... import
            # QTimer` local lo sombrearía como variable local y rompería
            # otros usos de QTimer en este mismo método.
            QTimer.singleShot(0, self.reject)
            return

        # Antes había aquí un único `self.setStyleSheet(self._stylesheet_base())`
        # que aplicaba TODO el styleSheet de la ficha (incluidos selectores
        # genéricos QDialog/QWidget/QLabel) al árbol completo de descendientes.
        # Eso se propagaba a cualquier QDialog hijo que se abriera desde la
        # ficha (el modal de edición y, por cascada, la lista de responsables
        # que sale del form), rompiendo su look — se veían con fondo
        # transparente sobre el theme default de Windows y daban un efecto
        # "hover permanente". Por eso primero construimos la UI y después
        # aplicamos los estilos divididos entre la ficha (solo regla con
        # objectName, no propagable) y main_container (resto, que no tiene
        # QDialog descendientes).
        self._construir_ui()
        self._set_styles_aislados()

        # Monitor de cambios de estado: si mientras la ficha está abierta
        # el mantenimiento transiciona (ej. de "Programado" a "En curso"
        # porque dieron las 8:00 AM), animamos suavemente el cambio de
        # color del header, badge, franja, dot y texto del estado, y
        # reconstruimos el footer si los botones de acción cambiaron.
        self._estado_visual_actual = self.estado_visual
        self._anim_estado = None  # se inicializa al primer cambio
        self._timer_monitor = QTimer(self)
        self._timer_monitor.timeout.connect(self._check_estado_cambio)
        self._timer_monitor.start(1000)  # 1 segundo

    # ── Monitor de estado y animación ───────────────────────────────────
    def _check_estado_cambio(self):
        """
        Llamado cada segundo. Si el estado derivado cambió desde la última
        vez, lanza la animación. Si no, solo actualiza el texto del tiempo
        relativo (que sí cambia cada segundo: "empieza en 5 min", etc).
        """
        nuevo = self.estado_visual
        if nuevo != self._estado_visual_actual:
            viejo_cfg = ESTADO_CONFIG.get(self._estado_visual_actual, ESTADO_CONFIG["Programado"])
            nuevo_cfg = ESTADO_CONFIG.get(nuevo, ESTADO_CONFIG["Programado"])
            self._estado_visual_actual = nuevo
            self._animar_cambio_estado(viejo_cfg, nuevo_cfg)
        else:
            # Solo refrescar el texto del tiempo (cambia con cada segundo)
            if hasattr(self, "_tiempo_label"):
                self._tiempo_label.setText(
                    _texto_tiempo_relativo(nuevo, self.dt_inicio, self.dt_fin)
                )

    def _animar_cambio_estado(self, viejo_cfg: dict, nuevo_cfg: dict):
        """Animación de 600 ms interpolando los colores del nuevo estado."""
        # Cancelar animación previa si seguía en curso
        if self._anim_estado is not None:
            self._anim_estado.stop()

        self._anim_estado = QVariantAnimation(self)
        self._anim_estado.setDuration(600)
        self._anim_estado.setStartValue(0.0)
        self._anim_estado.setEndValue(1.0)
        self._anim_estado.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim_estado.valueChanged.connect(
            lambda t: self._aplicar_tinte(viejo_cfg, nuevo_cfg, t)
        )
        self._anim_estado.finished.connect(self._finalizar_cambio_estado)
        self._anim_estado.start()

    def _aplicar_tinte(self, viejo: dict, nuevo: dict, t: float):
        """Aplica los colores interpolados a los widgets afectados."""
        header_bg = _mezclar_hex(viejo["header_bg"], nuevo["header_bg"], t)
        color     = _mezclar_hex(viejo["color"],     nuevo["color"],     t)
        badge_bg  = _mezclar_hex(viejo["badge_bg"],  nuevo["badge_bg"],  t)

        # Titlebar y header comparten el header_bg
        self._titlebar.setStyleSheet(
            f"#titlebar {{ background: {header_bg}; "
            f"border-top-left-radius: 10px; border-top-right-radius: 10px; }}"
        )
        self._header_frame_widget.setStyleSheet(
            f"#header_frame {{ background: {header_bg}; }}"
        )
        # Franja vibrante
        self._franja_widget.setStyleSheet(
            f"#header_franja {{ background: {color}; }}"
        )
        # Badge del número (mantenimiento_id)
        self._badge_id_label.setStyleSheet(
            f"#badge_id {{ background: {badge_bg}; color: white; "
            f"padding: 6px 12px; border-radius: 6px; "
            f"font-family: 'Consolas','Courier New',monospace; "
            f"font-weight: 500; font-size: 13px; }}"
        )
        # Texto del estado + puntito
        self._estado_text_label.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: 500; letter-spacing: 0.5px;"
        )
        self._estado_dot.setStyleSheet(
            f"background: {color}; border-radius: 5px;"
        )
        # Chip CADA N MESES: mismo esquema que el badge del ID (badge_bg
        # como fondo) pero con color primario del estado para el texto.
        # Solo lo animamos si existe (no todos los mantenimientos son recurrentes).
        if getattr(self, "_chip_recurrencia", None) is not None:
            self._chip_recurrencia.setStyleSheet(
                f"#chip_recurrencia {{ background: {badge_bg}; "
                f"color: {color}; padding: 3px 9px; "
                f"border-radius: 10px; font-size: 10px; font-weight: 600; "
                f"letter-spacing: 0.5px; }}"
            )

    def _finalizar_cambio_estado(self):
        """Al terminar la animación: actualizar textos y reconstruir footer."""
        nuevo_estado = self.estado_visual
        # Actualizar texto del estado y tiempo relativo
        self._estado_text_label.setText(nuevo_estado.upper())
        self._tiempo_label.setText(
            _texto_tiempo_relativo(nuevo_estado, self.dt_inicio, self.dt_fin)
        )
        # Reconstruir el footer porque los botones cambian con el estado
        self._reconstruir_footer()

    def _reconstruir_footer(self):
        """
        Reemplaza el footer actual por uno nuevo construido con los botones
        que aplican al estado actual. Mantiene la posición en el layout.
        """
        if not hasattr(self, "_footer_widget"):
            return
        root = self._main_container.layout()
        idx = root.indexOf(self._footer_widget)
        if idx < 0:
            return
        old = self._footer_widget
        root.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        new_footer = self._build_footer()
        root.addWidget(new_footer)

    # ── Carga de datos ──────────────────────────────────────────────────
    def _cargar_datos(self) -> bool:
        # Reset listas/cachés que dependen de la fila actual (importante
        # cuando este método se llama más de una vez en la vida de la ficha
        # — p. ej. tras editar, para no duplicar equipos).
        self.equipos = []

        # Consulta primero en la tabla operativa. Si no está ahí, cae al
        # archivo histórico (mantenimientos_archivo). Esto permite que la
        # ficha funcione uniformemente desde Programados, Finalizados y
        # Archivo histórico sin que el caller tenga que indicar la fuente.
        # El SELECT-shape debe ser IDÉNTICO en ambas queries para que
        # self.datos[N] apunte al mismo campo en ambos casos.
        SQL_SELECT_MANTENIMIENTO = """
            SELECT id, tipo_mantenimiento, urgente, fecha_inicio, fecha_fin,
                   costo, costo_moneda, descripcion,
                   responsable_tipo, responsable_id, responsable_nombre,
                   responsable_correo, responsable_telefono, estado,
                   google_event_id, calendar_sync, calendar_last_error,
                   calendar_last_sync, creado_en,
                   fecha_cierre,
                   motivo_cancelacion, retroalimentacion,
                   costo_real, costo_real_moneda, informe_pdf_path,
                   COALESCE(es_recurrente, 0), recurrencia_meses
            FROM {tabla}
            WHERE id = ?
        """

        rows = ejecutar_query(
            SQL_SELECT_MANTENIMIENTO.format(tabla="mantenimientos"),
            (self.mantenimiento_id,)
        ) or []
        # Fallback: si no está en operativa, buscar en el archivo histórico.
        # Se guarda si venía del archivo para hacer también el fallback
        # correspondiente en la query de equipos (mantenimientos_equipos_archivo).
        desde_archivo = False
        if not rows:
            rows = ejecutar_query(
                SQL_SELECT_MANTENIMIENTO.format(tabla="mantenimientos_archivo"),
                (self.mantenimiento_id,)
            ) or []
            desde_archivo = bool(rows)
        if not rows:
            return False
        self.datos = rows[0]

        # Los equipos siguen la misma lógica: primero en operativa, si no
        # hay resultados y el mantenimiento vino del archivo, buscar en
        # la tabla puente de archivo.
        pares = ejecutar_query("""
            SELECT equipo_id, equipo_tipo
            FROM mantenimientos_equipos
            WHERE mantenimiento_id = ?
        """, (self.mantenimiento_id,)) or []
        if not pares and desde_archivo:
            pares = ejecutar_query("""
                SELECT equipo_id, equipo_tipo
                FROM mantenimientos_equipos_archivo
                WHERE mantenimiento_id = ?
            """, (self.mantenimiento_id,)) or []

        # Mapeo de columnas "display" por tipo de equipo. Los transformadores
        # no tienen columna `nombre` en su tabla; en su lugar mostramos la
        # capacidad (ej. "500 kVA") para diferenciar equipos, ya que el ID
        # se muestra por separado en el chip y no tiene sentido duplicarlo.
        # Con AS mantenemos la interfaz uniforme para el resto del código.
        _cols_display = {
            'tableros':        ('nombre',    'ubicacion'),
            'transformadores': ('capacidad', 'ubicacion'),
        }
        for eq_id, eq_tipo in pares:
            cols = _cols_display.get(eq_tipo, ('nombre', 'ubicacion'))
            info = ejecutar_query(
                f"SELECT {cols[0]} AS nombre, {cols[1]} AS ubicacion "
                f"FROM {eq_tipo} WHERE id = ?",
                (eq_id,)
            )
            if info:
                nombre, ubicacion = info[0]
            else:
                nombre, ubicacion = "(no encontrado)", ""
            self.equipos.append({
                "id": eq_id, "tipo": eq_tipo,
                "nombre": nombre or "", "ubicacion": ubicacion or "",
            })

        # Grupo común vía helpers de programados (lazy import)
        from programados import (
            _cargar_jerarquia_grupos, _cargar_grupos_de_equipos,
            _grupo_comun, _ruta_grupo,
        )
        jerarquia = _cargar_jerarquia_grupos()
        grupo_por_equipo = _cargar_grupos_de_equipos()
        pares_tuple = [(e["id"], e["tipo"]) for e in self.equipos]
        grupo_id = _grupo_comun(pares_tuple, grupo_por_equipo, jerarquia)
        self.ruta_grupo = _ruta_grupo(grupo_id, jerarquia) if grupo_id else ""
        return True

    # ── Propiedades calculadas ──────────────────────────────────────────
    @property
    def dt_inicio(self) -> datetime:
        return datetime.strptime(self.datos[3], "%Y-%m-%d %H:%M")

    @property
    def dt_fin(self) -> datetime:
        return datetime.strptime(self.datos[4], "%Y-%m-%d %H:%M")

    @property
    def estado_visual(self) -> str:
        from programados import calcular_estado
        return calcular_estado(self.datos[13], self.datos[3], self.datos[4])

    @property
    def estado_cfg(self) -> dict:
        return ESTADO_CONFIG.get(self.estado_visual, ESTADO_CONFIG["Programado"])

    # ── Estilos ─────────────────────────────────────────────────────────
    def _stylesheet_base(self) -> str:
        cfg = self.estado_cfg
        return f"""
            QDialog {{ background: transparent; }}

            /* Container con border-radius: las esquinas de toda la ficha */
            QFrame#main_container {{
                background: #1e1e1e;
                border-radius: 10px;
            }}

            QWidget {{ background: transparent; }}
            QLabel {{ background: transparent; color: #ddd; }}

            /* Titlebar y header comparten el mismo color de fondo, calculado
               como una versión muy oscura del color del estado. Visualmente
               quedan integrados como una sola unidad. La titlebar respeta
               el border-radius de las esquinas superiores. */
            QFrame#titlebar {{
                background: {cfg['header_bg']};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
            QFrame#header_frame {{ background: {cfg['header_bg']}; }}

            QLabel#titlebar_text {{
                color: #aaa;
                font-size: 12px;
                font-weight: 500;
            }}
            /* Botón X minimalista: hover gris claro (no rojo invasivo) */
            QPushButton#titlebar_close {{
                background: transparent;
                border: none;
                border-radius: 0px;
                padding: 0px;
            }}
            QPushButton#titlebar_close:hover {{
                background: #3a3a3a;
            }}
            QPushButton#titlebar_close:pressed {{
                background: #2a2a2a;
            }}

            QFrame#sidebar_frame {{ background: #1a1a1a; border-right: 1px solid #2a2a2a; }}
            QFrame#content_frame {{ background: #1e1e1e; }}
            /* El footer respeta el border-radius en las esquinas inferiores */
            QFrame#footer_frame {{
                background: #181818;
                border-top: 1px solid #2a2a2a;
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
            }}
            QFrame#equipo_chip {{ background: #2a2a2a; border-radius: 4px; }}
            QFrame#descripcion_caja {{
                background: #161616;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
            }}
            QFrame#equipos_scroll_container {{
                background: transparent;
                border: 1px solid #232323;
                border-radius: 6px;
            }}

            /* Badge del número de mantenimiento: usa el color por estado */
            QLabel#badge_id {{
                background: {cfg['badge_bg']};
                color: white;
                padding: 6px 12px;
                border-radius: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-weight: 500;
                font-size: 13px;
            }}
            QLabel#tipo_titulo {{
                color: #fff;
                font-size: 16px;
                font-weight: 500;
            }}
            QLabel#creado_label, QLabel#tiempo_label {{
                color: #888;
                font-size: 11px;
            }}
            QLabel#titulo_seccion {{
                color: #666;
                font-size: 10px;
                font-weight: 500;
                letter-spacing: 1px;
            }}
            QLabel#equipo_id {{
                color: #d4a04c;
                font-family: 'Consolas', 'Courier New', monospace;
                font-weight: 500;
                font-size: 12px;
            }}
            QLabel#descripcion_texto {{
                color: #ccc;
                font-size: 12px;
                padding: 12px 14px;
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
            QPushButton[accion="primario"] {{
                background: #2a4055; border: 1px solid #2a5085;
            }}
            QPushButton[accion="primario"]:hover {{ background: #355275; }}
            QPushButton[accion="destructivo"] {{
                background: #3a2a2a; border: 1px solid #5a2a2a;
            }}
            QPushButton[accion="destructivo"]:hover {{ background: #4a3030; }}
            QPushButton[accion="prominente"] {{
                background: #5a3a1f; border: 1px solid #8a5a2f;
                font-weight: 600; padding: 9px 18px;
            }}
            QPushButton[accion="prominente"]:hover {{ background: #6f4828; }}
            QPushButton[accion="prominente_rojo"] {{
                background: #5a2828; border: 1px solid #8a3838;
                font-weight: 600; padding: 9px 18px;
            }}
            QPushButton[accion="prominente_rojo"]:hover {{ background: #722e2e; }}
            QPushButton[accion="cerrar_dialog"] {{
                background: transparent; color: #aaa; border: 1px solid #444;
            }}
            QPushButton[accion="cerrar_dialog"]:hover {{
                background: #2a2a2a; color: #ddd;
            }}

            QScrollArea, QScrollArea > QWidget > QWidget {{
                background: transparent; border: none;
            }}
            /* Scrollbar oscuro discreto que no rompe el diseño */
            QScrollBar:vertical {{
                background: #1a1a1a;
                width: 10px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #444;
                border-radius: 4px;
                min-height: 30px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{ background: #555; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                background: none; height: 0; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """


    def _set_styles_aislados(self):
        """
        Aísla los estilos para que NO se propaguen a los QDialog hijos.

        El styleSheet completo de la ficha (en _stylesheet_base) incluye
        reglas con selectores genéricos como `QDialog { background: ... }`,
        `QWidget { background: transparent }` y `QLabel { ... }`. Cuando
        ese stylesheet está aplicado al QDialog principal (la ficha), Qt
        lo propaga al árbol completo de descendientes — incluidos los
        QDialogs que se abren desde adentro (el modal de edición y, por
        cascada, la lista de responsables que sale desde el form). Eso
        rompe el look de esas ventanas hijas (se ven con fondo transparente
        sobre el theme default de Windows, dando un efecto "hover permanente").

        Solución: dividir el styleSheet en dos:

        1. Lo que aplica SOLO al QDialog de la ficha (el "background:
           transparent" necesario para que las esquinas redondeadas del
           main_container se vean): se aplica con selector específico
           QDialog#FichaMantenimientoDialog. Así no afecta a otros QDialogs.

        2. Todo lo demás (selectores genéricos QWidget/QLabel, selectores
           con objectName para titlebar, header, etc.): se aplica al
           main_container. Como main_container no tiene QDialogs hijos en
           su subárbol, los selectores genéricos solo afectan a la UI
           visible de la ficha; los QDialogs que se abran desde la ficha
           (modal de edición, etc.) NO heredan esas reglas.
        """
        # Identificar la ficha por objectName para poder usar selector
        # específico en su styleSheet (no se propaga a hijos QDialog)
        self.setObjectName("FichaMantenimientoDialog")
        self.setStyleSheet(
            "QDialog#FichaMantenimientoDialog { background: transparent; }"
        )
        # Todo el resto del styleSheet va al main_container. El selector
        # original `QDialog { background: transparent }` que estaba en
        # _stylesheet_base se vuelve no-op aquí (main_container no es
        # QDialog) — está bien, ya cubrimos ese caso arriba con el
        # selector específico.
        self._main_container.setStyleSheet(self._stylesheet_base())


    # ── Construcción UI ─────────────────────────────────────────────────
    def _construir_ui(self):
        # El QDialog en sí es transparente. Todo el contenido va en un
        # main_container que tiene border-radius — eso le da las esquinas
        # redondeadas a toda la ventana.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._main_container = QFrame()
        self._main_container.setObjectName("main_container")
        outer.addWidget(self._main_container)

        root = QVBoxLayout(self._main_container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_titlebar())
        # Guardamos referencia al header además del body, porque el header
        # muestra el tipo de mantenimiento (badge), y ese campo SÍ se puede
        # editar — antes solo refrescábamos el body, así que el cambio de
        # tipo no se veía hasta cerrar y reabrir la ficha.
        self._header_widget = self._build_header()
        root.addWidget(self._header_widget)
        # Guardamos referencias al layout root y al body para poder
        # reconstruir el body tras una edición sin cerrar la ficha.
        self._root_layout = root
        self._body_widget = self._build_body()
        root.addWidget(self._body_widget, 1)
        root.addWidget(self._build_footer())

    # ── Titlebar custom (reemplaza la barra de título nativa) ──────────
    def _build_titlebar(self) -> QWidget:
        """
        Barra superior custom. Reemplaza la barra de título nativa del SO.
        Comparte color de fondo con el header (header_bg del estado), así
        ambos se ven como una sola unidad visual.
        """
        bar = QFrame()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(32)
        self._titlebar = bar  # referencia para la animación de cambio de estado
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 0, 0)  # padding der=0 para que el botón X llegue al borde
        lay.setSpacing(8)

        # Icono pequeño de "ventana" (Tabler / FA) — sutil, opcional. Aquí
        # uso un icono de "info" pequeño que va con el contexto de ficha.
        icono = _icon_label("fa5s.clipboard-list", "#888", 13)
        lay.addWidget(icono, alignment=Qt.AlignmentFlag.AlignVCenter)

        title_lbl = QLabel(f"Mantenimiento #{self.datos[0]}")
        title_lbl.setObjectName("titlebar_text")
        lay.addWidget(title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

        lay.addStretch()

        btn_close = QPushButton()
        btn_close.setObjectName("titlebar_close")
        btn_close.setIcon(qta.icon("fa5s.times", color="#ddd"))
        btn_close.setIconSize(QSize(12, 12))
        btn_close.setFixedSize(46, 32)
        btn_close.setCursor(Qt.CursorShape.ArrowCursor)
        btn_close.clicked.connect(self.reject)
        lay.addWidget(btn_close)

        # Drag para mover la ventana arrastrando esta barra. Asignamos los
        # event handlers directamente al QFrame (sin subclasificar).
        bar.mousePressEvent = self._titlebar_press
        bar.mouseMoveEvent = self._titlebar_move
        bar.mouseReleaseEvent = self._titlebar_release
        # Doble click maximiza/restaura (comportamiento estándar de titlebars)
        bar.mouseDoubleClickEvent = self._titlebar_doubleclick
        return bar

    def _titlebar_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _titlebar_move(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_offset is not None:
            # Si la ventana está maximizada, restaurar antes de mover (estándar)
            if self.isMaximized():
                self.showNormal()
                # Recalcular el offset para que la ventana quede bajo el cursor
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def _titlebar_release(self, event):
        self._drag_offset = None

    def _titlebar_doubleclick(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()

    # ── Helper común: título de sección (icono + texto en mayúsculas) ──
    def _titulo_seccion(self, icon_name: str, color: str, texto: str) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        lay.addWidget(_icon_label(icon_name, color, 13))
        lbl = QLabel(texto)
        lbl.setObjectName("titulo_seccion")
        lay.addWidget(lbl)
        lay.addStretch()
        return wrap

    def _titulo_seccion_con_meta(self, icon_name: str, color: str, texto: str, meta: str = "") -> QWidget:
        """Igual que _titulo_seccion pero permite texto suave a la derecha (ej. 'Edif A › Piso 2')."""
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        lay.addWidget(_icon_label(icon_name, color, 13))
        lbl = QLabel(texto)
        lbl.setObjectName("titulo_seccion")
        lay.addWidget(lbl)
        if meta:
            sep = QLabel("·")
            sep.setStyleSheet("color:#444; font-size:11px;")
            lay.addWidget(sep)
            meta_lbl = QLabel(meta)
            meta_lbl.setStyleSheet("color:#888; font-size:10px; letter-spacing: 0.5px;")
            lay.addWidget(meta_lbl)
        lay.addStretch()
        return wrap

    # ── Header (contenido + franja separada del color del estado) ───────
    def _build_header(self) -> QWidget:
        cfg = self.estado_cfg
        container = QWidget()
        container_lay = QVBoxLayout(container)
        container_lay.setContentsMargins(0, 0, 0, 0)
        container_lay.setSpacing(0)

        # Contenido
        top = QFrame()
        top.setObjectName("header_frame")
        self._header_frame_widget = top  # ref para animación
        lay = QHBoxLayout(top)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(14)

        # Izquierda: badge + tipo + creado + chip URGENTE
        izq = QHBoxLayout()
        izq.setSpacing(14)
        izq.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        badge = QLabel(f"#{self.datos[0]}")
        badge.setObjectName("badge_id")
        self._badge_id_label = badge  # ref para animación
        izq.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        info_titulo = QVBoxLayout()
        info_titulo.setSpacing(2)
        lbl_tipo = QLabel(self.datos[1] or "")
        lbl_tipo.setObjectName("tipo_titulo")
        info_titulo.addWidget(lbl_tipo)
        lbl_creado = QLabel(_formato_creado(self.datos[18] or ""))
        lbl_creado.setObjectName("creado_label")
        info_titulo.addWidget(lbl_creado)
        izq.addLayout(info_titulo)

        if self.datos[2]:
            chip = QLabel("URGENTE")
            chip.setStyleSheet(
                "background: #5a2828; color: #ff8888; padding: 3px 9px; "
                "border-radius: 10px; font-size: 10px; font-weight: 600; "
                "letter-spacing: 0.5px;"
            )
            izq.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Chip CADA N MESES si el mantenimiento es parte de una serie recurrente.
        # Se pinta con los colores del estado actual (badge_bg + color primario)
        # para ir en sincronía con la paleta del header; _aplicar_tinte lo anima
        # junto con los demás elementos cuando el estado cambia.
        self._chip_recurrencia = None  # ref para animación (puede ser None)
        if len(self.datos) > 25 and self.datos[25]:
            texto_chip = _texto_chip_recurrencia(self.datos[26])
            chip_rec = QLabel(texto_chip)
            chip_rec.setObjectName("chip_recurrencia")
            chip_rec.setStyleSheet(
                f"#chip_recurrencia {{ background: {cfg['badge_bg']}; "
                f"color: {cfg['color']}; padding: 3px 9px; "
                f"border-radius: 10px; font-size: 10px; font-weight: 600; "
                f"letter-spacing: 0.5px; }}"
            )
            self._chip_recurrencia = chip_rec
            izq.addWidget(chip_rec, alignment=Qt.AlignmentFlag.AlignVCenter)

        izq.addStretch()
        lay.addLayout(izq, 1)

        # Derecha: dot + estado + tiempo relativo
        der = QVBoxLayout()
        der.setSpacing(2)
        der.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        estado_box = QHBoxLayout()
        estado_box.setSpacing(8)
        estado_box.setAlignment(Qt.AlignmentFlag.AlignRight)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background: {cfg['dot']}; border-radius: 5px;")
        self._estado_dot = dot  # ref para animación
        estado_box.addWidget(dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        estado_text = QLabel(self.estado_visual.upper())
        estado_text.setStyleSheet(
            f"color: {cfg['color']}; font-size: 13px; font-weight: 500; letter-spacing: 0.5px;"
        )
        self._estado_text_label = estado_text  # ref para animación
        estado_box.addWidget(estado_text, alignment=Qt.AlignmentFlag.AlignVCenter)
        der.addLayout(estado_box)

        lbl_tiempo = QLabel(_texto_tiempo_relativo(self.estado_visual, self.dt_inicio, self.dt_fin))
        lbl_tiempo.setObjectName("tiempo_label")
        lbl_tiempo.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._tiempo_label = lbl_tiempo  # ref para actualización
        der.addWidget(lbl_tiempo)

        lay.addLayout(der)

        # Franja inferior de 3px con el color del estado, separada del header.
        # Es un QFrame propio (no border-bottom) para evitar la sombra desigual
        # que Qt aplica cuando hay padding y un border en stylesheet.
        franja = QFrame()
        franja.setObjectName("header_franja")
        franja.setFixedHeight(3)
        franja.setStyleSheet(f"#header_franja {{ background: {cfg['color']}; }}")
        self._franja_widget = franja  # ref para animación

        container_lay.addWidget(top)
        container_lay.addWidget(franja)
        return container

    # ── Body ────────────────────────────────────────────────────────────
    def _build_body(self) -> QWidget:
        body = QWidget()
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar(), 0)
        lay.addWidget(self._build_content(), 1)
        return body

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar_frame")
        side.setFixedWidth(240)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(18)

        # Programa
        lay.addWidget(self._bloque_programa())
        # Grupo
        lay.addWidget(self._bloque_grupo())
        # Responsable
        lay.addWidget(self._bloque_responsable())
        # Costo
        lay.addWidget(self._bloque_costo())
        # Stretch para empujar Calendar al fondo
        lay.addStretch()
        # Calendar
        lay.addWidget(self._bloque_calendar())

        return side

    def _bloque_programa(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._titulo_seccion("fa5s.calendar-alt", COLOR_ICONO_PROGRAMA, "FECHA / HORA"))

        # Si el mantenimiento es de un solo día (mismo día calendario en
        # inicio y fin), mostrar una sola fecha. Si cruza días, mostrar
        # dos: una para inicio y otra para fin — relevante para que el
        # usuario vea de un vistazo que el evento es multi-día.
        if self.dt_inicio.date() == self.dt_fin.date():
            fecha_lbl = QLabel(_formato_fecha_larga(self.dt_inicio))
            fecha_lbl.setStyleSheet("color:#ddd; font-size:12px; font-weight:500;")
            lay.addWidget(fecha_lbl)
        else:
            for etiqueta_fecha, dt in [
                ("Del", self.dt_inicio),
                ("Al", self.dt_fin),
            ]:
                row = QLabel(
                    f"<span style='color:#888'>{etiqueta_fecha}:</span> "
                    f"<span style='color:#ddd; font-weight:500;'>{_formato_fecha_larga(dt)}</span>"
                )
                row.setStyleSheet("font-size:12px;")
                lay.addWidget(row)

        for etiqueta, valor in [
            ("Inicio", self.dt_inicio.strftime("%H:%M")),
            ("Fin", self.dt_fin.strftime("%H:%M")),
            ("Duración", _formato_duracion(self.dt_inicio, self.dt_fin)),
        ]:
            row = QLabel(f"<span style='color:#888'>{etiqueta}:</span> "
                         f"<span style='color:#ddd'>{valor}</span>")
            row.setStyleSheet("font-size:11px;")
            lay.addWidget(row)
        return w

    def _bloque_grupo(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._titulo_seccion("fa5s.map-marker-alt", COLOR_ICONO_GRUPO, "LUGAR"))

        if self.ruta_grupo:
            partes = [p.strip() for p in self.ruta_grupo.split("›")]
            principal = QLabel(partes[0])
            principal.setStyleSheet("color:#ddd; font-size:12px; font-weight:500;")
            lay.addWidget(principal)
            for sub in partes[1:]:
                sub_lbl = QLabel(f"› {sub}")
                sub_lbl.setStyleSheet("color:#aaa; font-size:11px; padding-left:2px;")
                lay.addWidget(sub_lbl)
        else:
            sin = QLabel("Sin agrupar")
            sin.setStyleSheet("color:#888; font-size:12px;")
            lay.addWidget(sin)
        return w

    def _bloque_responsable(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self._titulo_seccion("fa5s.user", COLOR_ICONO_RESPON, "RESPONSABLE"))

        nombre = self.datos[10] or "(sin nombre)"
        tipo = self.datos[8]
        tel = self.datos[12] or ""
        mail = self.datos[11] or ""

        nombre_lbl = QLabel(nombre)
        nombre_lbl.setStyleSheet("color:#ddd; font-size:12px; font-weight:500;")
        nombre_lbl.setWordWrap(True)
        lay.addWidget(nombre_lbl)

        if tipo == "personal":
            chip_bg, chip_fg, chip_txt = "#1f3a2a", "#6fc28f", "Personal"
        else:
            chip_bg, chip_fg, chip_txt = "#1f2a3a", "#6fa3e0", "Proveedor"
        chip = QLabel(chip_txt)
        chip.setStyleSheet(
            f"background:{chip_bg}; color:{chip_fg}; padding:1px 7px; "
            f"border-radius:3px; font-size:10px;"
        )
        chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        lay.addWidget(chip, alignment=Qt.AlignmentFlag.AlignLeft)

        if tel:
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 0)
            row.setSpacing(6)
            row.addWidget(_icon_label("fa5s.phone", COLOR_ICONO_TEL, 11))
            tel_lbl = QLabel(tel)
            tel_lbl.setStyleSheet("color:#888; font-size:11px;")
            row.addWidget(tel_lbl)
            row.addStretch()
            wrap_row = QWidget(); wrap_row.setLayout(row); lay.addWidget(wrap_row)
        if mail:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(_icon_label("fa5s.envelope", COLOR_ICONO_MAIL, 11))
            mail_lbl = QLabel(mail)
            mail_lbl.setStyleSheet("color:#888; font-size:11px;")
            mail_lbl.setWordWrap(True)
            row.addWidget(mail_lbl, 1)
            wrap_row = QWidget(); wrap_row.setLayout(row); lay.addWidget(wrap_row)
        return w

    def _bloque_costo(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self._titulo_seccion("fa5s.coins", COLOR_ICONO_COSTO, "COSTO ESTIMADO"))

        monto = self.datos[5] or 0
        moneda = self.datos[6] or "MXN"
        monto_lbl = QLabel(
            f"<span style='font-family:Consolas,monospace; color:#ddd; font-size:16px;'>"
            f"${monto:,}</span> "
            f"<span style='color:#888; font-size:11px;'>{moneda}</span>"
        )
        lay.addWidget(monto_lbl)
        return w

    def _bloque_calendar(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(4)

        # Línea sutil arriba del bloque, separándolo del resto
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#2a2a2a;")
        lay.addWidget(sep)
        lay.addSpacing(8)

        lay.addWidget(self._titulo_seccion("fa5s.cloud", COLOR_ICONO_CALENDAR, "GOOGLE CALENDAR"))

        sync = self.datos[15]
        last_sync = self.datos[17] or ""
        last_error = self.datos[16] or ""

        estado_row = QHBoxLayout()
        estado_row.setContentsMargins(0, 0, 0, 0)
        estado_row.setSpacing(6)
        if sync == 1:
            estado_row.addWidget(_icon_label("fa5s.check-circle", "#6fc28f", 11))
            txt = QLabel("Sincronizado"); txt.setStyleSheet("color:#6fc28f; font-size:11px;")
        elif last_error:
            estado_row.addWidget(_icon_label("fa5s.times-circle", "#e74c3c", 11))
            txt = QLabel("Error de sincronización"); txt.setStyleSheet("color:#e74c3c; font-size:11px;")
        else:
            estado_row.addWidget(_icon_label("fa5s.minus-circle", "#888", 11))
            txt = QLabel("Sin sincronizar"); txt.setStyleSheet("color:#888; font-size:11px;")
        estado_row.addWidget(txt)
        estado_row.addStretch()
        wrap_estado = QWidget(); wrap_estado.setLayout(estado_row); lay.addWidget(wrap_estado)

        if last_sync:
            ult = QLabel(f"Última: {last_sync}")
            ult.setStyleSheet("color:#666; font-size:10px;")
            lay.addWidget(ult)
        return w

    # ── Contenido derecho ───────────────────────────────────────────────
    def _build_content(self) -> QWidget:
        """
        Columna principal del body. TODO su contenido (bloque cierre +
        equipos + descripción) vive dentro de un QScrollArea que:
          - Limita la altura del content a la del dialog → la ventana
            ya no crece sin control con retroalimentaciones largas o
            descripciones extensas.
          - Unifica el scroll: el usuario hace scroll una sola vez sobre
            toda la columna, sin scrolls anidados (la descripción ya no
            tiene su propio scroll interno).
        """
        c = QFrame()
        c.setObjectName("content_frame")
        lay = QVBoxLayout(c)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

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

        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(18, 16, 18, 16)
        inner_lay.setSpacing(16)

        # Bloque de cierre — solo aparece cuando el mantenimiento ya está
        # cerrado (fecha_cierre IS NOT NULL). Va al inicio para que sea
        # lo primero que vea el usuario al abrir un histórico: "cómo
        # terminó esto". Si el mantenimiento aún está activo, este
        # método devuelve None y la ficha se ve normal (sin cambios).
        cierre = self._bloque_cierre()
        if cierre is not None:
            inner_lay.addWidget(cierre)

        inner_lay.addWidget(self._bloque_equipos())
        inner_lay.addWidget(self._bloque_descripcion())
        inner_lay.addStretch()

        scroll.setWidget(inner)
        lay.addWidget(scroll)
        return c

    def _bloque_equipos(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        n = len(self.equipos)
        meta = self.ruta_grupo if self.ruta_grupo else ("Mixto" if n > 1 else "")
        lay.addWidget(self._titulo_seccion_con_meta(
            "fa5s.tools", COLOR_ICONO_EQUIPOS, f"EQUIPOS ({n})", meta
        ))

        if not self.equipos:
            sin = QLabel("(sin equipos asociados)")
            sin.setStyleSheet("color:#888; font-size:12px;")
            lay.addWidget(sin)
            return w

        # Umbral: hasta UMBRAL equipos se muestran directos; pasando de eso,
        # se envuelven en un scroll area mostrando exactamente 4 chips visibles.
        UMBRAL_SCROLL = 4
        if n <= UMBRAL_SCROLL:
            for eq in self.equipos:
                lay.addWidget(self._chip_equipo(eq))
        else:
            # 4 chips justos (sin peek del siguiente). Si el usuario quiere
            # ver más, hace scroll. El scrollbar visible le indica que hay más.
            CHIP_H = 34       # altura mínima real del chip (setMinimumHeight)
            SPACING = 6
            altura_max = (UMBRAL_SCROLL * CHIP_H
                          + (UMBRAL_SCROLL - 1) * SPACING
                          + 12)  # margen interno del container (6+6)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setMaximumHeight(altura_max)
            scroll.setMinimumHeight(altura_max)

            inner = QFrame()
            inner.setObjectName("equipos_scroll_container")
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(6, 6, 6, 6)
            inner_lay.setSpacing(6)
            for eq in self.equipos:
                inner_lay.addWidget(self._chip_equipo(eq))
            inner_lay.addStretch()

            scroll.setWidget(inner)
            lay.addWidget(scroll)

        return w

    def _chip_equipo(self, eq: dict) -> QFrame:
        chip = QFrame()
        chip.setObjectName("equipo_chip")
        chip.setMinimumHeight(34)
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        id_lbl = QLabel(eq["id"])
        id_lbl.setObjectName("equipo_id")
        id_lbl.setMinimumWidth(60)
        lay.addWidget(id_lbl)

        nombre = QLabel(eq["nombre"] or "(sin nombre)")
        nombre.setStyleSheet("color:#ddd; font-size:12px;")
        lay.addWidget(nombre)

        lay.addStretch()

        if eq["ubicacion"]:
            ubic = QLabel(eq["ubicacion"])
            ubic.setStyleSheet("color:#666; font-size:11px;")
            lay.addWidget(ubic, alignment=Qt.AlignmentFlag.AlignRight)
        return chip

    def _bloque_descripcion(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self._titulo_seccion("fa5s.file-alt", COLOR_ICONO_DESC, "DESCRIPCIÓN"))

        # Sin QScrollArea propio: el scroll vive en _build_content
        # (envolviendo TODO el contenido de la columna principal). Esto
        # unifica el scroll en uno solo y evita que el bloque cierre
        # compita con la descripción por espacio vertical fijo.
        caja = QFrame()
        caja.setObjectName("descripcion_caja")
        caja_lay = QVBoxLayout(caja)
        caja_lay.setContentsMargins(0, 0, 0, 0)

        texto = self.datos[7] or "(sin descripción)"
        txt_lbl = QLabel(texto)
        txt_lbl.setObjectName("descripcion_texto")
        txt_lbl.setWordWrap(True)
        txt_lbl.setTextFormat(Qt.TextFormat.AutoText)
        txt_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        txt_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        caja_lay.addWidget(txt_lbl)

        lay.addWidget(caja)
        return w

    # ── Bloque Cierre ───────────────────────────────────────────────────
    # Aparece SOLO cuando fecha_cierre IS NOT NULL. Es el primer widget
    # de la columna principal del body (antes que Equipos / Observaciones),
    # para que el usuario vea el resumen del cierre apenas abra la ficha.
    # Diseño: borde lateral verde (Finalizado) o rojo (Cancelado),
    # ícono + tag en mayúsculas, fecha de cierre con tiempo relativo,
    # y secciones específicas según el resultado:
    #   - Finalizado: retroalimentación + costo estimado vs real (con %
    #                  de diferencia) + botón "Abrir reporte PDF".
    #   - Cancelado:  motivo de cancelación.
    def _bloque_cierre(self):
        fecha_cierre = self.datos[19] if len(self.datos) > 19 else None
        if not fecha_cierre:
            return None  # sin cierre → no se muestra el bloque

        estado_db = (self.datos[13] or "").lower()
        es_cancelado = (estado_db == "cancelado")

        if es_cancelado:
            color_borde = "#e84747"
            color_tag = "#e84747"
            icono_id = "fa5s.times-circle"
        else:
            color_borde = "#27ae60"
            color_tag = "#27ae60"
            icono_id = "fa5s.check-circle"

        box = QFrame()
        box.setObjectName("bloque_cierre")
        box.setStyleSheet(f"""
            QFrame#bloque_cierre {{
                background: #1e1e1e;
                border-left: 3px solid {color_borde};
                border-radius: 6px;
            }}
        """)

        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # ── Header del bloque: ícono + tag + fecha relativa ──
        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        header_row.setContentsMargins(0, 0, 0, 0)

        icono_lbl = QLabel()
        icono_lbl.setPixmap(qta.icon(icono_id, color=color_tag).pixmap(15, 15))
        icono_lbl.setFixedSize(15, 15)
        header_row.addWidget(icono_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

        tag_lbl = QLabel("CIERRE DEL MANTENIMIENTO")
        tag_lbl.setStyleSheet(
            f"color: {color_tag}; font-size: 11px; font-weight: 500;"
            " letter-spacing: 1px; background: transparent;"
        )
        header_row.addWidget(tag_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header_row.addStretch()
        lay.addLayout(header_row)

        fecha_str = self._formato_fecha_cierre_larga(fecha_cierre)
        relativo = self._tiempo_desde_cierre(fecha_cierre)
        texto_fecha = (
            f"Cerrado el {fecha_str} · {relativo}" if relativo
            else f"Cerrado el {fecha_str}"
        )
        fecha_lbl = QLabel(texto_fecha)
        fecha_lbl.setStyleSheet(
            "color: #888; font-size: 11px; background: transparent;"
        )
        lay.addWidget(fecha_lbl)

        # ── Contenido específico por tipo de cierre ──
        if es_cancelado:
            motivo = self.datos[20] if len(self.datos) > 20 else None
            self._cierre_seccion_texto(
                lay, "MOTIVO", motivo or "(sin motivo registrado)"
            )
        else:
            retro = self.datos[21] if len(self.datos) > 21 else None
            self._cierre_seccion_texto(
                lay, "RETROALIMENTACIÓN", retro or "(sin retroalimentación)"
            )

            # ── Sección específica por tipo de equipo ─────────────────
            # Después de la retroalimentación y antes del costo, pintamos
            # el bloque específico según el tipo de equipo del mantenimiento:
            #   - tableros: CAMBIOS AL EQUIPO (tachado + flecha + justificación)
            #   - transformadores: PRUEBAS ELÉCTRICAS con veredictos
            #     normativos + INSPECCIÓN FÍSICA + POSICIÓN DEL TAP
            # Si el mantenimiento no capturó datos de esa sección, no se
            # pinta (silencio informativo, no "sin datos").
            self._cierre_seccion_especifica_por_tipo(lay)

            self._cierre_seccion_costo(lay)
            pdf_path = self.datos[24] if len(self.datos) > 24 else None
            if pdf_path:
                self._cierre_boton_pdf(lay, pdf_path)

        return box

    def _cierre_seccion_especifica_por_tipo(self, parent_lay):
        """
        Detecta el tipo dominante del mantenimiento y delega al renderizador
        correspondiente de `widget_bloque_cierre`. Sigue la misma regla de
        detección que DialogCerrarMantenimiento: los tipos son mutuamente
        excluyentes por diseño del programador de mantenimiento.
        """
        tipos = {(e.get("tipo") or "").lower() for e in (self.equipos or [])}
        try:
            from widget_bloque_cierre import (
                render_cambios_tablero,
                render_pruebas_transformador,
            )
        except Exception as e:
            print(f"[ficha_cierre] No se pudo importar widget_bloque_cierre: {e}")
            return

        if tipos == {"tableros"}:
            render_cambios_tablero(parent_lay, self.mantenimiento_id)
        elif tipos == {"transformadores"}:
            render_pruebas_transformador(parent_lay, self.mantenimiento_id)
        # Modo genérico o mixto (no debería pasar por regla de negocio):
        # no se pinta sección específica.

    def _cierre_seccion_texto(self, parent_lay, label_text: str, content: str):
        """Helper: agrega una sección LABEL + texto al bloque cierre."""
        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)

        lbl_section = QLabel(label_text)
        lbl_section.setStyleSheet(
            "color: #666; font-size: 11px; letter-spacing: 1px;"
            " font-weight: 500; background: transparent;"
        )
        v.addWidget(lbl_section)

        lbl_content = QLabel(content)
        lbl_content.setWordWrap(True)
        lbl_content.setStyleSheet(
            "color: #ccc; font-size: 12px; background: transparent;"
        )
        v.addWidget(lbl_content)

        parent_lay.addWidget(container)

    def _cierre_seccion_costo(self, parent_lay):
        """Helper: comparativa Estimado vs Real con diferencia en %."""
        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)

        lbl_section = QLabel("COSTO")
        lbl_section.setStyleSheet(
            "color: #666; font-size: 11px; letter-spacing: 1px;"
            " font-weight: 500; background: transparent;"
        )
        v.addWidget(lbl_section)

        estimado = self.datos[5] or 0
        moneda_est = self.datos[6] or "MXN"
        real = self.datos[22] if len(self.datos) > 22 else None
        moneda_real = self.datos[23] if len(self.datos) > 23 else None
        moneda_real = moneda_real or moneda_est

        # Fila Estimado
        v.addLayout(self._cierre_fila_costo("Estimado", estimado, moneda_est))

        # Fila Real (con comparación)
        if real is not None:
            if estimado > 0:
                diff_pct = ((real - estimado) / estimado) * 100
                if abs(diff_pct) < 0.5:
                    extra, extra_color = "", "#888"
                elif diff_pct > 0:
                    extra = f"  (+{diff_pct:.1f}%)"
                    extra_color = "#e67e22"  # naranja: se pasó del estimado
                else:
                    extra = f"  ({diff_pct:.1f}%)"
                    extra_color = "#27ae60"  # verde: ahorró
            else:
                extra, extra_color = "", "#888"
            v.addLayout(self._cierre_fila_costo(
                "Real", real, moneda_real, extra, extra_color
            ))
        else:
            # Sin costo real registrado (no debería pasar en Finalizado
            # normal, pero por defensa)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            l_izq = QLabel("Real")
            l_izq.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
            row.addWidget(l_izq)
            row.addStretch()
            l_der = QLabel("—")
            l_der.setStyleSheet("color: #ccc; font-size: 12px; background: transparent;")
            row.addWidget(l_der)
            v.addLayout(row)

        parent_lay.addWidget(container)

    def _cierre_fila_costo(self, etiqueta: str, monto, moneda: str,
                           extra: str = "", extra_color: str = "#888"):
        """Construye una fila 'etiqueta-izquierda  /  monto-derecha'."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        lbl_left = QLabel(etiqueta)
        lbl_left.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
        row.addWidget(lbl_left)
        row.addStretch()

        if extra:
            lbl_right = QLabel(
                f"<span style='color:#ccc;'>${monto:,} {moneda}</span>"
                f"<span style='color:{extra_color};'>{extra}</span>"
            )
        else:
            lbl_right = QLabel(f"<span style='color:#ccc;'>${monto:,} {moneda}</span>")
        lbl_right.setStyleSheet("font-size: 12px; background: transparent;")
        lbl_right.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(lbl_right)
        return row

    def _cierre_boton_pdf(self, parent_lay, pdf_path: str):
        """Botón 'Abrir reporte PDF' alineado a la izquierda (no full-width)."""
        btn = QPushButton("  Abrir reporte PDF")
        btn.setIcon(qta.icon("fa5s.file-pdf", color="#ddd"))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: #2b2b2b; color: #ddd;
                border: 1px solid #3a3a3a; border-radius: 4px;
                padding: 6px 12px; font-size: 11px;
                text-align: left;
            }
            QPushButton:hover { background: #353535; border-color: #4a4a4a; }
        """)
        btn.clicked.connect(lambda: self._abrir_reporte_pdf(pdf_path))

        # Envolver en un HBox + stretch para que NO se estire al ancho completo
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 4, 0, 0)
        wrap.addWidget(btn)
        wrap.addStretch()
        parent_lay.addLayout(wrap)

    @staticmethod
    def _formato_fecha_cierre_larga(fc_str: str) -> str:
        """fecha_cierre ('YYYY-MM-DD HH:MM:SS' o sin segs) → '18 Jun 2026'."""
        if not fc_str:
            return ""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(fc_str, fmt)
                return _formato_fecha_larga(dt)
            except ValueError:
                continue
        return fc_str

    @staticmethod
    def _tiempo_desde_cierre(fc_str: str) -> str:
        """'Hace 3 días' / 'Hace 5 h' / 'Hace unos segundos'."""
        if not fc_str:
            return ""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(fc_str, fmt)
                delta = datetime.now() - dt
                total = int(delta.total_seconds())
                if total < 60:
                    return "Hace unos segundos"
                if total < 3600:
                    return f"Hace {total // 60} min"
                if total < 86400:
                    h = total // 3600
                    return "Hace 1 h" if h == 1 else f"Hace {h} h"
                d = total // 86400
                return "Hace 1 día" if d == 1 else f"Hace {d} días"
            except ValueError:
                continue
        return ""

    def _abrir_reporte_pdf(self, pdf_path: str):
        """Abre el PDF del cierre con el visor por defecto del sistema."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        import os
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(
                self, "Archivo no encontrado",
                f"No se pudo abrir el reporte. El archivo ya no está disponible:\n\n{pdf_path}"
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(pdf_path)))

    # ── Footer ──────────────────────────────────────────────────────────
    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footer_frame")
        self._footer_widget = footer  # ref para poder reconstruirlo al cambiar estado
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(8)

        for label, accion, callback, icon_name in self._botones_para_estado():
            btn = QPushButton(f"  {label}")  # padding pequeño para que no se pegue al icono
            btn.setProperty("accion", accion)
            if icon_name:
                color_icon = "#ffffff" if accion in ("primario", "prominente", "prominente_rojo") else "#dddddd"
                btn.setIcon(qta.icon(icon_name, color=color_icon))
                btn.setIconSize(QSize(13, 13))
            btn.clicked.connect(callback)
            lay.addWidget(btn)

        lay.addStretch()
        return footer

    def _botones_para_estado(self) -> list:
        """
        Lista de (label, tipo_accion, callback, icon_name) para el estado actual.
        En fase 2 los callbacks muestran "próximamente".
        """
        proximamente = lambda accion: lambda: QMessageBox.information(
            self,
            "Próximamente",
            f"La acción '{accion}' se implementará en la siguiente fase."
        )
        est = self.estado_visual

        # Chequeo temprano: si el mantenimiento ya tiene fecha_cierre,
        # significa que se cerró completamente (sea por completarlo desde
        # Pendiente cierre o por darle motivo desde Cancelado). Pasa a ser
        # un registro histórico de solo lectura — sin botones de acción.
        # El acceso al PDF vive dentro del bloque cierre (en el content
        # de la ficha), no en el footer — antes se duplicaba.
        fecha_cierre = self.datos[19] if len(self.datos) > 19 else None
        if fecha_cierre:
            return []  # Sin botones para mantenimientos cerrados

        if est == "Programado":
            return [
                ("Editar", "primario", self._on_editar, "fa5s.edit"),
                ("Cancelar", "destructivo", self._on_cancelar, "fa5s.times"),
                ("Reprogramar", "", self._on_reprogramar, "fa5s.calendar-day"),
                ("Re-sync Calendar", "", proximamente("Re-sync Calendar"), "fa5s.sync-alt"),
            ]
        if est == "En curso":
            return [
                ("Cancelar", "destructivo", self._on_cancelar, "fa5s.times"),
                ("Re-sync Calendar", "", proximamente("Re-sync Calendar"), "fa5s.sync-alt"),
            ]
        if est == "Pendiente cierre":
            return [
                ("Cerrar mantenimiento", "prominente", self._on_cerrar_pendiente, "fa5s.file-import"),
                ("Reprogramar", "", self._on_reprogramar, "fa5s.calendar-day"),
                ("Re-sync Calendar", "", proximamente("Re-sync Calendar"), "fa5s.sync-alt"),
            ]
        if est == "Cancelado":
            return [
                ("Cerrar mantenimiento", "prominente_rojo", self._on_cerrar_cancelado, "fa5s.file-import"),
                ("Reprogramar", "", self._on_reprogramar, "fa5s.calendar-day"),
            ]
        if est == "Finalizado":
            return [
                ("Ver reporte PDF", "", proximamente("Ver reporte PDF"), "fa5s.file-pdf"),
            ]
        return []

    # ── Handlers de acciones del footer (fase 3) ────────────────────────
    def _on_cancelar(self):
        """
        Cancela el mantenimiento (estados Programado / En curso).

        Comportamiento:
          - Mantenimiento NO recurrente → QMessageBox de confirmación estándar.
          - Mantenimiento recurrente → DialogCancelarRecurrente con dos opciones:
              * "Solo este evento": cancela + genera el siguiente inmediatamente
                (con placeholder de responsable, aparece en Notificaciones).
              * "Detener toda la serie": pone es_recurrente=0 + cancela.
                Ningún siguiente se generará.

        Tras cancelar, la ficha NO se cierra: el motivo se captura al
        'Cerrar mantenimiento' desde el estado Cancelado. La animación de
        tinte + reconstrucción del footer las dispara _check_estado_cambio
        en el próximo tick al detectar la nueva fila.
        """
        es_recurrente = len(self.datos) > 25 and bool(self.datos[25])

        if es_recurrente:
            # Flujo especial: diálogo con dos tarjetas
            eleccion = DialogCancelarRecurrente.mostrar(
                self,
                equipo_resumen=self._equipo_resumen_corto(),
                fecha_inicio_str=self.datos[3] or "",
                recurrencia_meses=self.datos[26],
            )
            if eleccion is None:
                return  # cerró el diálogo

            if eleccion == "toda_la_serie":
                # Primero apagar la bandera, luego cancelar. Si algo falla
                # entre medio, al menos la serie queda detenida y el evento
                # sigue activo — estado consistente.
                from db_manager import detener_serie_recurrente
                detener_serie_recurrente(self.mantenimiento_id)
                cancelar_mantenimiento(self.mantenimiento_id)

            elif eleccion == "solo_este":
                # Cancelar el evento actual y generar el siguiente para
                # mantener la cadencia de la serie. La generación se hace
                # con try/except para no dejar el evento cancelado a medias
                # si la creación del hijo falla.
                cancelar_mantenimiento(self.mantenimiento_id)
                try:
                    from db_manager import generar_siguiente_recurrencia
                    generar_siguiente_recurrencia(self.mantenimiento_id)
                except Exception as e:
                    print(f"[RECURRENCIA] Falla al generar siguiente post-cancelación: {e}")
        else:
            # Flujo original: confirmación simple
            confirm = QMessageBox.question(
                self,
                "Cancelar mantenimiento",
                "¿Estás seguro de cancelar este mantenimiento?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            cancelar_mantenimiento(self.mantenimiento_id)

        # Recargar datos para que self.datos[13] refleje el nuevo estado.
        # En el próximo tick del _timer_monitor, _check_estado_cambio
        # detectará la transición y disparará la animación.
        self._cargar_datos()

        # Notificar a Programados / Inicio / KPIs para que recarguen.
        from signals import app_signals
        app_signals.mantenimiento_guardado.emit()

    def _equipo_resumen_corto(self) -> str:
        """Helper para el diálogo de cancelación: '(sin equipo)', 'TG-03'
        o '4 equipos'. Usado como contexto visible en la ventana modal."""
        n = len(self.equipos)
        if n == 0:
            return "(sin equipo)"
        if n == 1:
            return self.equipos[0].get("id", "")
        return f"{n} equipos"

    def _on_reprogramar(self):
        """
        Reprograma el mantenimiento (estados Programado / Pendiente cierre / Cancelado).
        Abre el sub-diálogo DialogReprogramar precargado con las fechas actuales.
        Si el usuario acepta, hace UPDATE con las nuevas fechas y deja que
        _check_estado_cambio detecte el cambio de estado:
          - Desde Programado: si la nueva fecha es futura sigue azul; si ya
            empezó, animación a amarillo (En curso).
          - Desde Pendiente cierre: extensión del trabajo; vuelve a azul o
            amarillo según las nuevas fechas.
          - Desde Cancelado: el helper también limpia motivo_cancelacion;
            vuelve a azul/amarillo y el footer se reconstruye.
        """
        from dialogs_mantenimiento import DialogReprogramar

        resultado = DialogReprogramar.mostrar(
            self,
            self.mantenimiento_id,
            self.dt_inicio,
            self.dt_fin,
        )
        if resultado is None:
            return  # usuario canceló

        dt_inicio_nuevo, dt_fin_nuevo = resultado
        fi_str = dt_inicio_nuevo.strftime("%Y-%m-%d %H:%M")
        ff_str = dt_fin_nuevo.strftime("%Y-%m-%d %H:%M")

        reprogramar_mantenimiento(self.mantenimiento_id, fi_str, ff_str)

        # Recargar datos: las nuevas fechas + estado='programado' entran
        # en self.datos. El próximo tick de _check_estado_cambio anima.
        self._cargar_datos()

        # Notificar a la pestaña Programados.
        from signals import app_signals
        app_signals.mantenimiento_guardado.emit()

    def _on_editar(self):
        """
        Edita el mantenimiento (solo en estado Programado). Abre el
        formulario programar_nuevo en modo edición como diálogo modal.
        Solo se pueden modificar campos no-temporales: tipo, urgente,
        costo, descripción, responsable. Para fechas/horario hay que
        usar Reprogramar; para equipos hay que cancelar y crear nuevo.
        Tras el UPDATE, _refrescar_visual reconstruye el body para que
        los cambios (responsable, costo, descripción, etc.) se vean
        sin tener que cerrar y reabrir la ficha.
        """
        from programar_nuevo import ProgramarNuevoWidget

        actualizado = ProgramarNuevoWidget.editar_modal(self, self.mantenimiento_id)
        if not actualizado:
            return  # usuario canceló o cerró sin guardar

        # Recargar datos + reconstruir el body para reflejar los cambios.
        self._refrescar_visual()
        # Nota: app_signals.mantenimiento_guardado ya se emite desde
        # _actualizar_mantenimiento_editable dentro del form, así que la
        # pestaña Programados se refresca sola sin que hagamos emit aquí.

    def _refrescar_visual(self):
        """
        Recarga datos desde BD y reconstruye el header + body de la ficha
        para que cambios hechos vía Editar se reflejen en vivo.
        - El header se reconstruye porque muestra el tipo de mantenimiento
          (badge), que es editable.
        - El body se reconstruye porque tiene la mayoría de los datos.
        - El titlebar y el footer se conservan: el titlebar solo tiene
          identificador de ID (que no cambia) y el footer depende del
          estado (que tampoco cambia en una edición simple).
        """
        if not self._cargar_datos():
            return
        # Reconstruir header
        nuevo_header = self._build_header()
        self._root_layout.replaceWidget(self._header_widget, nuevo_header)
        self._header_widget.deleteLater()
        self._header_widget = nuevo_header
        # Reconstruir body
        nuevo_body = self._build_body()
        self._root_layout.replaceWidget(self._body_widget, nuevo_body)
        self._body_widget.deleteLater()
        self._body_widget = nuevo_body

    def _on_cerrar_pendiente(self):
        """
        Cierra un mantenimiento en estado 'Pendiente cierre'.

        Abre DialogCerrarMantenimiento para capturar PDF + retro + costo real.
        Dependiendo del tipo de equipo del mantenimiento, la ventana también
        pide:
            - modo 'tableros': cambios al equipo con justificación por circuito
            - modo 'transformadores': pruebas eléctricas, pruebas al aceite
              (si aplica), inspección física y posición del tap

        Al aceptar, copia el PDF a la carpeta gestionada y hace UPDATE
        atómico en BD (sobrescribe inventario si hubo cambios, inserta el
        histórico correspondiente, marca mantenimiento como finalizado).
        Si algo falla, rollback total en la BD y el mantenimiento sigue en
        'Pendiente cierre'.

        Tras cerrar correctamente, la ficha se cierra (porque ya pasó a
        Finalizados) y se notifica a las pestañas para que refresquen.
        """
        from dialogs_mantenimiento import DialogCerrarMantenimiento

        # Costo estimado + moneda van precargados como info de referencia
        costo_estimado = self.datos[5] or 0
        moneda = self.datos[6] or 'MXN'

        # Pasamos self.equipos para que el diálogo detecte el modo (tableros
        # vs transformadores) y monte la sección de captura correspondiente.
        resultado = DialogCerrarMantenimiento.mostrar(
            self, self.mantenimiento_id, costo_estimado, moneda,
            equipos=self.equipos
        )
        if resultado is None:
            return  # usuario canceló

        # 8-tupla: los 5 últimos son None según el modo del mantenimiento.
        # En modo 'tableros' se llenan updates_circuitos y cambios_equipo;
        # en modo 'transformadores' se llenan las 3 últimas. Los modos son
        # mutuamente excluyentes por diseño (programar_nuevo.py bloquea
        # mezclar tipos), así que a lo sumo un bloque tiene contenido.
        (pdf_origen, retroalimentacion, costo_real,
         updates_circuitos, cambios_equipo,
         pruebas_transformador, inspeccion_transformador, posicion_tap
         ) = resultado

        # Inyectar el nombre del responsable en cada fila de cambios_equipo,
        # que el diálogo no conoce. La ficha sí lo tiene (self.datos[9]).
        if cambios_equipo:
            responsable_nombre = (self.datos[9] if len(self.datos) > 9 else None) or None
            for c in cambios_equipo:
                if c.get("responsable") in (None, ""):
                    c["responsable"] = responsable_nombre

        # 1) Copiar el PDF a la carpeta gestionada. Si falla, avisar y NO
        # continuar con el UPDATE — no dejamos el mantenimiento a medias.
        try:
            pdf_destino = copiar_informe_pdf(self.mantenimiento_id, pdf_origen)
        except Exception as e:
            QMessageBox.critical(
                self, "Error al guardar el PDF",
                f"No se pudo copiar el archivo PDF:\n{e}\n\n"
                "El mantenimiento NO se cerró. Intenta de nuevo o verifica "
                "que el archivo de origen exista y la carpeta destino tenga "
                "permisos de escritura."
            )
            return

        # 2) UPDATE atómico: sobrescribe circuitos (si aplica) + registra
        # los 4 posibles bloques históricos (cambios, pruebas, inspección,
        # tap) + marca mantenimiento como finalizado. Todo en una sola
        # transacción. Si algo falla, rollback total.
        try:
            cerrar_mantenimiento_pendiente(
                self.mantenimiento_id,
                retroalimentacion=retroalimentacion,
                informe_pdf_path=pdf_destino,
                costo_real=costo_real,
                updates_circuitos=updates_circuitos,
                cambios_equipo=cambios_equipo,
                pruebas_transformador=pruebas_transformador,
                inspeccion_transformador=inspeccion_transformador,
                posicion_tap=posicion_tap,
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Error al cerrar el mantenimiento",
                f"No se pudo guardar el cierre en la base de datos:\n{e}\n\n"
                "Ningún cambio se aplicó — el mantenimiento sigue en Pendiente cierre."
            )
            return

        # 3) Notificar a las pestañas y cerrar la ficha
        from signals import app_signals
        app_signals.mantenimiento_guardado.emit()

        # Mensaje de éxito informativo según lo que se capturó. Se construye
        # sumando extras solo cuando hubo contenido, para no confundir con
        # "Se registraron 0 cambios" ni saturar con líneas cuando no aplica.
        n_cambios   = len(cambios_equipo) if cambios_equipo else 0
        n_pruebas   = len(pruebas_transformador) if pruebas_transformador else 0
        n_insp      = len(inspeccion_transformador) if inspeccion_transformador else 0
        n_tap       = len(posicion_tap) if posicion_tap else 0
        extras = []
        if n_cambios: extras.append(f"{n_cambios} cambio(s) al equipo")
        if n_pruebas: extras.append(f"{n_pruebas} prueba(s)")
        if n_insp:    extras.append(f"{n_insp} punto(s) de inspección")
        if n_tap:     extras.append(f"{n_tap} ajuste(s) de tap")
        msg_extra = "\nSe registraron " + ", ".join(extras) + "." if extras else ""

        QMessageBox.information(
            self, "Mantenimiento cerrado",
            "✅ El mantenimiento se cerró correctamente y pasó a Finalizados." + msg_extra
        )
        self.accept()  # cierra la ficha

    def _on_cerrar_cancelado(self):
        """
        Cierra un mantenimiento en estado 'Cancelado'. Solo captura el
        motivo de la cancelación. El estado_db sigue 'cancelado'; solo se
        llena motivo_cancelacion y fecha_cierre. Tras cerrar, el
        mantenimiento pasa a la pestaña Finalizados (que filtra por
        fecha_cierre IS NOT NULL).
        """
        from dialogs_mantenimiento import DialogCerrarCancelado

        motivo = DialogCerrarCancelado.mostrar(self, self.mantenimiento_id)
        if motivo is None:
            return  # usuario canceló

        cerrar_mantenimiento_cancelado(self.mantenimiento_id, motivo)

        from signals import app_signals
        app_signals.mantenimiento_guardado.emit()
        QMessageBox.information(
            self, "Mantenimiento cerrado",
            "✅ El mantenimiento cancelado se cerró y pasó a Finalizados."
        )
        self.accept()  # cierra la ficha



# ══════════════════════════════════════════════════════════════════════
#  Diálogo especial: cancelar mantenimiento que es parte de una serie
#  recurrente. Ofrece dos opciones tipo tarjeta clickable para que la
#  decisión sea deliberada (a diferencia del QMessageBox estándar).
# ══════════════════════════════════════════════════════════════════════

class DialogCancelarRecurrente(QDialog):
    """Modal con dos tarjetas: 'Cancelar solo este evento' o 'Cancelar y
    detener toda la serie'. El resultado se comunica al llamador vía el
    método de clase mostrar().
    """

    RESULT_SOLO_ESTE = "solo_este"
    RESULT_TODA_LA_SERIE = "toda_la_serie"

    @classmethod
    def mostrar(cls, parent, equipo_resumen: str, fecha_inicio_str: str,
                recurrencia_meses):
        """Constructor de conveniencia. Devuelve 'solo_este',
        'toda_la_serie' o None si el usuario cerró el diálogo."""
        dlg = cls(parent, equipo_resumen, fecha_inicio_str, recurrencia_meses)
        dlg.exec()
        return dlg.eleccion

    def __init__(self, parent, equipo_resumen: str, fecha_inicio_str: str,
                 recurrencia_meses):
        super().__init__(parent)
        self.eleccion = None
        self.setWindowTitle("Cancelar mantenimiento recurrente")
        self.setModal(True)
        self.setMinimumWidth(480)

        # Estilo local: no hereda del padre para asegurar look consistente.
        self.setStyleSheet("""
            QDialog { background: #2b2b2b; }
            QLabel { background: transparent; color: #e0e0e0; }
            QPushButton {
                background: #3a3a3a; color: white;
                border: none; border-radius: 6px;
                padding: 7px 16px; font-size: 12px;
            }
            QPushButton:hover { background: #505050; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        # ── Encabezado ─────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(10)
        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.exclamation-triangle",
                               color="#e8a33d").pixmap(QSize(22, 22)))
        head.addWidget(ico)
        titulo = QLabel("Cancelar mantenimiento recurrente")
        titulo.setStyleSheet("color: #e0e0e0; font-size: 15px; font-weight: 600;")
        head.addWidget(titulo)
        head.addStretch()
        root.addLayout(head)

        # ── Contexto (equipo + fecha + periodo) ───────────────────
        ctx = QLabel(self._texto_contexto(equipo_resumen, fecha_inicio_str,
                                          recurrencia_meses))
        ctx.setWordWrap(True)
        ctx.setStyleSheet(
            "color: #aaa; font-size: 12px; padding: 10px 12px; "
            "background: #1e1e1e; border-radius: 6px; "
            "border-left: 3px solid #e8a33d;"
        )
        root.addWidget(ctx)

        # ── Opción 1: solo este evento ────────────────────────────
        op1 = self._opcion_tarjeta(
            icon_name="fa5s.times",
            icon_color="#d9534f",
            titulo="Cancelar solo este evento",
            desc=("Este mantenimiento se marca como cancelado, pero la "
                  "serie continúa: se generará el siguiente evento (con "
                  "responsable pendiente por asignar)."),
            result=self.RESULT_SOLO_ESTE,
        )
        root.addWidget(op1)

        # ── Opción 2: toda la serie ───────────────────────────────
        op2 = self._opcion_tarjeta(
            icon_name="fa5s.stop-circle",
            icon_color="#d9534f",
            titulo="Cancelar y detener toda la serie",
            desc=("Se cancela este evento y no se generará ningún "
                  "siguiente. La serie recurrente queda terminada."),
            result=self.RESULT_TODA_LA_SERIE,
        )
        root.addWidget(op2)

        # ── Botón cerrar ──────────────────────────────────────────
        acciones = QHBoxLayout()
        acciones.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self.reject)
        acciones.addWidget(btn_cerrar)
        root.addLayout(acciones)

    def _texto_contexto(self, equipo, fecha_str, meses) -> str:
        """Línea corta con el contexto del mantenimiento a cancelar."""
        # Fecha bonita si viene en formato canónico
        fecha_disp = fecha_str or ""
        try:
            dt = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
            fecha_disp = dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
        # Periodo legible
        periodo = ""
        try:
            m = int(meses)
            if m == 0:
                periodo = "Se repite cada día (modo prueba)"
            elif m == 1:
                periodo = "Se repite cada mes"
            else:
                periodo = f"Se repite cada {m} meses"
        except Exception:
            periodo = "Recurrente"
        return f"{equipo} · {fecha_disp}\n{periodo}"

    def _opcion_tarjeta(self, icon_name: str, icon_color: str, titulo: str,
                        desc: str, result: str) -> QFrame:
        """Construye una tarjeta clickable que devuelve `result` al elegirla."""
        tarj = QFrame()
        tarj.setObjectName("op_tarjeta")
        tarj.setCursor(Qt.CursorShape.PointingHandCursor)
        tarj.setStyleSheet("""
            QFrame#op_tarjeta {
                background: #1e1e1e; border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
            QFrame#op_tarjeta:hover {
                border-color: #0078d7; background: #232323;
            }
        """)
        h = QHBoxLayout(tarj)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)

        ico = QLabel()
        ico.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(QSize(20, 20)))
        # setFixedSize evita que el QLabel se expanda más allá del pixmap
        # (por defecto Qt le da un sizeHint amplio que crea un hueco horizontal
        # entre el ícono y el texto). Con esto queda pegado.
        ico.setFixedSize(20, 20)
        ico.setStyleSheet("background: transparent;")
        h.addWidget(ico, alignment=Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(4)
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(
            "color: #e0e0e0; font-size: 13px; font-weight: 500; background: transparent;"
        )
        lbl_desc = QLabel(desc)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(
            "color: #888; font-size: 11px; background: transparent;"
        )
        col.addWidget(lbl_titulo)
        col.addWidget(lbl_desc)
        # stretch=1 hace que la columna del texto ocupe el ancho restante,
        # empujando ambos labels al ancho útil de la tarjeta.
        h.addLayout(col, stretch=1)

        # Click en cualquier parte de la tarjeta = elegir esta opción
        tarj.mousePressEvent = lambda ev, r=result: self._on_elegir(ev, r)
        return tarj

    def _on_elegir(self, ev, result: str):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self.eleccion = result
        self.accept()
