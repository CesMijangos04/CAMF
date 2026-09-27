"""
Pestaña Finalizados — historial de mantenimientos cerrados.

A diferencia de Programados (eventos activos, dinámicos), Finalizados es
una vista histórica de eventos cerrados (estado='finalizado' o
estado='cancelado' con fecha_cierre llena). Por eso:

  - Filtro de query: WHERE fecha_cierre IS NOT NULL.
  - Sin agrupación por estado: lista plana ordenada por fecha_cierre DESC
    (lo más recientemente cerrado va arriba).
  - Sin timers periódicos: el histórico no cambia solo. Refresca por señal
    cuando alguien cierra un mantenimiento desde otra pestaña/ficha.
  - Pills: Todos / Finalizado / Cancelado (los dos posibles estados
    finales de un mantenimiento cerrado).
  - En la columna derecha, en vez de "Horario + tiempo relativo del
    futuro", se muestra "Cerrado: dd/mm/yyyy" + "Hace X días".

Se reusa muchísimo de programados.py (la card, los helpers de elide y
formato de equipos, los colores) — Finalizados es esencialmente una
copia con cambios chicos pero significativos.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QScrollArea, QMenu, QDialog
)
from PyQt6.QtCore import Qt, QPoint, QTimer, QSize
from datetime import datetime
import qtawesome as qta

from db_manager import ejecutar_query
from programados import (
    calcular_estado,
    _cargar_jerarquia_grupos,
    _cargar_grupos_de_equipos,
    _formato_equipos_dos_lineas,
    _formato_delta_humano,
    _build_seccion_header,
    MantenimientoCard,
    COLORES_ESTADO_HEX,
)


# ══════════════════════════════════════════════════════════════════════
#  CARGA DE DATOS
# ══════════════════════════════════════════════════════════════════════

def obtener_mantenimientos_finalizados(anio: int | None = None):
    """
    Igual SELECT que obtener_mantenimientos() de programados, con dos
    diferencias clave:
      - WHERE m.fecha_cierre IS NOT NULL (en vez de IS NULL).
      - Columna 10: m.fecha_cierre (necesaria para mostrar "Cerrado: …").
      - ORDER BY m.fecha_cierre DESC (más reciente arriba).

    Parámetro opcional `anio`:
      - Si es None (default): trae TODOS los años (comportamiento clásico,
        usado hoy para construir los pills de año dinámicamente).
      - Si es un entero (ej. 2026): filtra a SQL para traer SOLO ese año.
        Puerta abierta para futuras optimizaciones (Fase 3/4) — cuando la
        BD tenga miles de registros, evitar traer el histórico completo
        a memoria cada vez que se cambia de cápsula anual.
    """
    if anio is not None:
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
                GROUP_CONCAT(me.equipo_id || ':' || me.equipo_tipo, '|') AS equipos_lista,
                m.fecha_cierre
            FROM mantenimientos m
            LEFT JOIN mantenimientos_equipos me ON me.mantenimiento_id = m.id
            WHERE m.fecha_cierre IS NOT NULL
              AND CAST(strftime('%Y', m.fecha_cierre) AS INTEGER) = ?
            GROUP BY m.id
            ORDER BY m.fecha_cierre DESC
        """, (anio,))

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
            GROUP_CONCAT(me.equipo_id || ':' || me.equipo_tipo, '|') AS equipos_lista,
            m.fecha_cierre
        FROM mantenimientos m
        LEFT JOIN mantenimientos_equipos me ON me.mantenimiento_id = m.id
        WHERE m.fecha_cierre IS NOT NULL
        GROUP BY m.id
        ORDER BY m.fecha_cierre DESC
    """)


# ══════════════════════════════════════════════════════════════════════
#  CARD ESPECIALIZADA — FinalizadoCard
# ══════════════════════════════════════════════════════════════════════

class FinalizadoCard(MantenimientoCard):
    """
    Subclase de MantenimientoCard que solo cambia la columna 5: en vez de
    'Horario + tiempo relativo del futuro' (Empieza/Termina en X días),
    muestra 'Cerrado: dd/mm/yyyy' + 'Hace X días'.

    El resto (franja lateral del color del estado, tinte rojo si urgente,
    distribución de columnas, doble click → ficha, menú contextual) se
    hereda intacto.
    """

    def __init__(self, datos, equipos_lineas, parent=None):
        # IMPORTANTE: asignar antes del super().__init__ porque el padre
        # llama a _construir_ui() → _build_horario() → necesita
        # self._fecha_cierre.
        self._fecha_cierre = datos[10] if len(datos) > 10 else None
        super().__init__(datos, equipos_lineas, parent=parent)

    def _build_horario(self):
        """
        Override: en Finalizados la columna 5 es 'Cerrado: <fecha>' +
        'Hace <N días>'. No tiene sentido mostrar horario operativo de un
        evento que ya pasó.
        """
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)

        fc_txt = self._formato_fecha_cierre(self._fecha_cierre)
        lbl_cierre = QLabel(
            f"<span style='color:#888;'>Cerrado:</span> "
            f"<span style='color:#ccc;'>{fc_txt}</span>"
        )
        lbl_cierre.setStyleSheet("font-size: 11px; background: transparent;")
        lbl_cierre.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(lbl_cierre)

        texto_relativo = self._texto_hace_cuanto(self._fecha_cierre)
        if texto_relativo:
            lbl_rel = QLabel(texto_relativo)
            lbl_rel.setStyleSheet(
                "color: #888; font-size: 10px; background: transparent;"
            )
            v.addWidget(lbl_rel)

        return w

    @staticmethod
    def _formato_fecha_cierre(fc_str) -> str:
        """
        fecha_cierre se guarda como 'YYYY-MM-DD HH:MM:SS' (con segundos),
        a diferencia de fecha_inicio/fin que son 'YYYY-MM-DD HH:MM'.
        Devolvemos solo 'dd/mm/yyyy'.
        """
        if not fc_str:
            return "—"
        # Probar primero el formato con segundos, luego el de sin
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(fc_str, fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
        return str(fc_str)

    @staticmethod
    def _texto_hace_cuanto(fc_str) -> str:
        """Convierte fecha_cierre en 'Hace 3 días' / 'Hace 5 h' / etc."""
        if not fc_str:
            return ""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                fc = datetime.strptime(fc_str, fmt)
                delta = datetime.now() - fc
                if delta.total_seconds() < 60:
                    return "Hace unos segundos"
                return f"Hace {_formato_delta_humano(delta)}"
            except ValueError:
                continue
        return ""


# ══════════════════════════════════════════════════════════════════════
#  WIDGET PRINCIPAL — FinalizadosWidget
# ══════════════════════════════════════════════════════════════════════

class FinalizadosWidget(QWidget):
    """
    Pestaña Finalizados. Espejo de ProgramadosWidget con tres diferencias:
        1. Carga distinta (obtener_mantenimientos_finalizados).
        2. Pills: Todos / Finalizado / Cancelado (no las 4 de Programados).
        3. Sin agrupación visual ni timers periódicos (el histórico es
           estático, no transiciona por paso del tiempo).

    Igualito en lo demás: header con ícono + título + subtítulo, barra de
    buscador + pills, QScrollArea con cards, doble click → ficha de
    mantenimiento (la misma que Programados; eventualmente será una ficha
    de cierre dedicada, pero eso es otra tanda).
    """

    def __init__(self):
        super().__init__()
        self._datos_crudos = []
        self._jerarquia = {}
        self._grupo_por_equipo = {}
        self._filtro_activo = "todos"
        self._filtro_anio = "todos"
        self._texto_busqueda = ""
        # Refs internas para el filtro por año (se rellena dinámicamente
        # en _refrescar_pills_anio cada vez que cargan datos).
        self._pills_anio = {}
        self._anios_layout = None  # QHBoxLayout, asignado en _build_buscador_y_pills

        # === Estado del pool de cards (Fase 2) ==================
        # Las cards viven en memoria persistente mientras el usuario está
        # dentro de la misma cápsula anual. Filtrar (buscar / pill de
        # estado) NO destruye ni crea cards — solo aplica show()/hide().
        # El pool se destruye completo solo cuando el usuario cambia de
        # cápsula anual (ej. de "Todos"=2026 a la cápsula "2025"). Un
        # cierre nuevo llegando por signal agrega UNA card al pool sin
        # tocar las demás.
        self._cards_por_id = {}         # dict[int mant_id, FinalizadoCard]
        self._headers_seccion = {}      # dict["Finalizado"/"Cancelado", QWidget]
        self._contadores_estado = {"Finalizado": 0, "Cancelado": 0}
        self._anio_del_pool = None      # int año actualmente cargado en el pool
        self._msg_vacio = None          # QLabel persistente para estado vacío

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

        # Sin timer periódico: el histórico no cambia solo. Solo recarga
        # cuando alguien cierra un mantenimiento desde otra pestaña.
        try:
            from signals import app_signals
            app_signals.mantenimiento_guardado.connect(self.recargar_datos)
        except Exception:
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
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        titulo_row = QHBoxLayout()
        titulo_row.setSpacing(10)
        titulo_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # fa5s.archive sugiere histórico de mejor manera que check-circle
        icono = QLabel()
        icono.setPixmap(qta.icon("fa5s.archive", color="#ddd").pixmap(22, 22))
        icono.setFixedSize(22, 22)
        titulo_row.addWidget(icono, alignment=Qt.AlignmentFlag.AlignVCenter)

        titulo = QLabel("Mantenimientos finalizados")
        titulo.setStyleSheet(
            "color: white; font-size: 22px; font-weight: 500;"
            " background: transparent;"
        )
        titulo_row.addWidget(titulo, alignment=Qt.AlignmentFlag.AlignVCenter)
        titulo_row.addStretch()

        # Botón "Archivo histórico" (Fase 4). Se abre un diálogo de
        # selección de año/mes, y solo entonces se carga la vista real.
        # Deshabilitado por defecto; se habilita en recargar_datos() si
        # la tabla mantenimientos_archivo tiene contenido.
        # Diferenciación visual sin cambio de color del ícono:
        #   - Deshabilitado: opacidad reducida + borde muy tenue.
        #   - Habilitado:    opacidad plena + borde visible + hover.
        self.btn_archivo = QPushButton()
        self.btn_archivo.setIcon(qta.icon("fa5s.archive", color="#aaaaaa"))
        self.btn_archivo.setIconSize(QSize(16, 16))
        self.btn_archivo.setFixedSize(32, 32)
        self.btn_archivo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_archivo.setToolTip("Archivo histórico")
        self.btn_archivo.setStyleSheet("""
            QPushButton {
                background: #2a2a2a;
                border: 1px solid #444;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #353535;
                border: 1px solid #555;
            }
            QPushButton:disabled {
                background: transparent;
                border: 1px solid #262626;
            }
        """)
        # Opacidad para el estado deshabilitado. QGraphicsOpacityEffect
        # aplica opacidad a nivel de widget completo (ícono + fondo +
        # borde), lo cual da el efecto de "apagado" que se quiere sin
        # tocar el color del ícono. Se activa/desactiva en
        # _actualizar_boton_archivo() según el estado.
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        self._efecto_opacidad_archivo = QGraphicsOpacityEffect(self.btn_archivo)
        self.btn_archivo.setGraphicsEffect(self._efecto_opacidad_archivo)

        self.btn_archivo.setEnabled(False)
        self.btn_archivo.clicked.connect(self._abrir_archivo_historico)
        titulo_row.addWidget(self.btn_archivo, alignment=Qt.AlignmentFlag.AlignVCenter)

        v.addLayout(titulo_row)

        subtitulo = QLabel(
            "Historial de mantenimientos cerrados (completados y cancelados)"
        )
        subtitulo.setStyleSheet(
            "color: #888; font-size: 12px; background: transparent;"
        )
        subtitulo.setContentsMargins(32, 0, 0, 0)
        v.addWidget(subtitulo)

        return container

    def _build_buscador_y_pills(self) -> QWidget:
        """
        Contenedor vertical con DOS filas de filtros:
            Fila 1: Buscador + pills de estado (Todos, Finalizado, Cancelado)
            Fila 2: 'Año' + pills dinámicos (Todos, 2026, 2025, …)

        La fila de año se reconstruye en cada recargar_datos() porque
        depende de qué años haya en BD: solo se muestran años con
        cierres registrados.
        """
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 6, 0, 4)
        v.setSpacing(8)

        # ── Fila 1: Buscador + pills de estado ──
        v.addWidget(self._build_fila_estado())

        # ── Separador sutil entre las dos filas de filtros ──
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2a2a2a; border: none;")
        v.addWidget(sep)

        # ── Fila 2: Filtro por año (dinámico) ──
        v.addWidget(self._build_fila_anios_skeleton())

        return container

    def _build_fila_estado(self) -> QWidget:
        """Fila 1: buscador + pills de estado."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

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

        self._pills = {}
        estados_visibles = [
            ("todos", "Todos"),
            ("Finalizado", "Finalizado"),
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
        return w

    def _build_fila_anios_skeleton(self) -> QWidget:
        """
        Fila 2 vacía: solo el label 'Año' + un stretch al final. Los
        botones de los años se insertan en _refrescar_pills_anio() porque
        se calculan desde los datos cargados (dinámicos).
        """
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 0, 0, 0)
        h.setSpacing(6)

        lbl = QLabel("Año")
        lbl.setStyleSheet("color: #666; font-size: 11px; letter-spacing: 0.5px;")
        h.addWidget(lbl)

        # Stretch final desde el inicio. Los pills se insertan entre el
        # label "Año" y este stretch (posiciones 1..N).
        h.addStretch()

        # Guardamos referencia al layout para poder rellenarlo después.
        self._anios_layout = h
        return w

    def _refrescar_pills_anio(self):
        """
        Reconstruye los pills de año basándose en los datos actuales.
        Llamado desde recargar_datos(). Lógica:
          - Cuenta cierres por año a partir de fecha_cierre.
          - Crea pill "Todos · N_total".
          - Crea pill "AÑO · N" por cada año con cierres, ordenado del
            más reciente al más viejo.
          - Si el año que estaba activo (self._filtro_anio) ya no tiene
            cierres (caso borde si se borrara un mantenimiento), vuelve
            a "todos".
        """
        # Limpiar pills viejos del layout (entre label "Año" en pos 0 y
        # el stretch al final). Iteramos hasta que solo queden 2 items:
        # el label y el stretch.
        while self._anios_layout.count() > 2:
            item = self._anios_layout.takeAt(1)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                # NOTA: hide() en vez de setParent(None). En Windows,
                # setParent(None) promueve el widget a ventana top-level
                # durante el ciclo del event loop hasta que deleteLater()
                # lo destruye, produciendo un parpadeo de ventana huérfana
                # con el icono de python.exe. hide() lo oculta antes de
                # que pueda pintarse como top-level.
                w.hide()
                w.deleteLater()
        self._pills_anio.clear()

        # Contar cierres por año
        counts = {}
        for m in self._datos_crudos:
            anio = self._anio_de_fecha_cierre(m)
            if anio is not None:
                counts[anio] = counts.get(anio, 0) + 1
        total = sum(counts.values())

        # Insertar nuevos pills (justo antes del stretch en posición N-1).
        # Inserción en orden: Todos, año más reciente, ..., año más viejo.
        #
        # NOTA (Fase 1): "Todos" ahora representa "año en curso", no la
        # historia completa. Su contador refleja únicamente los cierres
        # del año actual. Los años pasados viven en sus propias cápsulas
        # (los pills numéricos "2025", "2024", etc.). Cuando el año pase
        # (ej. 1 de enero de 2027), "Todos" pasará automáticamente a
        # mostrar 2027 y 2026 pasará a ser una cápsula más.
        anio_actual = datetime.now().year
        anios_ordenados = sorted(counts.keys(), reverse=True)
        pills_a_crear = [("todos", f"Todos · {counts.get(anio_actual, 0)}")]
        for anio in anios_ordenados:
            pills_a_crear.append((str(anio), f"{anio} · {counts[anio]}"))

        # Si el filtro activo ya no existe (año sin cierres), reset
        if self._filtro_anio != "todos" and self._filtro_anio not in {p[0] for p in pills_a_crear}:
            self._filtro_anio = "todos"

        for key, label in pills_a_crear:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._pill_anio_style(activo=(key == self._filtro_anio)))
            btn.clicked.connect(lambda checked=False, k=key: self._cambiar_filtro_anio(k))
            # Insertar antes del stretch (en posición count-1)
            self._anios_layout.insertWidget(self._anios_layout.count() - 1, btn)
            self._pills_anio[key] = btn

    @staticmethod
    def _anio_de_fecha_cierre(datos_tupla) -> int | None:
        """Saca el año (int) de la columna fecha_cierre (índice 10).
        Tolera los dos formatos en que puede venir el string."""
        fc = datos_tupla[10] if len(datos_tupla) > 10 else None
        if not fc:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(fc, fmt).year
            except ValueError:
                continue
        return None

    def _build_scrollarea(self) -> QScrollArea:
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

        self._contenido = QWidget()
        self._contenido_lay = QVBoxLayout(self._contenido)
        self._contenido_lay.setContentsMargins(0, 0, 8, 0)
        self._contenido_lay.setSpacing(4)
        self._contenido_lay.addStretch()

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

    def _pill_anio_style(self, activo: bool) -> str:
        """
        Estilo de pill del filtro por año. Más sutil que los pills de
        estado (que tienen mayor jerarquía visual) — fondo transparente
        + borde fino. El activo se distingue con fondo + borde más
        oscuros + texto blanco.
        """
        if activo:
            return """
                QPushButton {
                    background: #2b2b2b; color: #fff;
                    border: 1px solid #555; border-radius: 10px;
                    padding: 2px 10px; font-size: 11px;
                }
                QPushButton:hover { background: #353535; }
            """
        return """
            QPushButton {
                background: transparent; color: #888;
                border: 1px solid #2f2f2f; border-radius: 10px;
                padding: 2px 10px; font-size: 11px;
            }
            QPushButton:hover { color: #ccc; border-color: #444; }
        """

    # ===================== EVENTOS DE FILTRO / BÚSQUEDA =====================
    def _cambiar_filtro(self, key: str):
        if key == self._filtro_activo:
            return
        self._filtro_activo = key
        for k, btn in self._pills.items():
            btn.setStyleSheet(self._pill_style(activo=(k == key)))
        self._render()

    def _cambiar_filtro_anio(self, key: str):
        """Cambia el filtro por año y rerenderiza. key es 'todos' o el
        año como string ('2026', '2025', …)."""
        if key == self._filtro_anio:
            return
        self._filtro_anio = key
        for k, btn in self._pills_anio.items():
            btn.setStyleSheet(self._pill_anio_style(activo=(k == key)))
        self._render()

    def _on_busqueda_changed(self, texto: str):
        # Actualizar el texto de búsqueda inmediatamente, pero disparar
        # el render con debounce. start() reinicia el timer si ya estaba
        # corriendo — así, si el usuario sigue tecleando, no se ejecutan
        # renders intermedios (solo el final, 150 ms después de la última
        # tecla). Ver __init__ para el detalle del timer.
        self._texto_busqueda = texto.strip().lower()
        self._debounce_busqueda.start()

    # ===================== CARGA / REFRESH =====================
    def recargar_datos(self):
        self._datos_crudos = obtener_mantenimientos_finalizados() or []
        self._jerarquia = _cargar_jerarquia_grupos()
        self._grupo_por_equipo = _cargar_grupos_de_equipos()
        # Reconstruir los pills de año (los años disponibles dependen de
        # los datos cargados, no son fijos).
        self._refrescar_pills_anio()
        # Habilitar el botón de archivo histórico solo si hay contenido
        # en la tabla mantenimientos_archivo. Chequeo barato: contar años
        # disponibles (query rápido, un solo SELECT DISTINCT con GROUP BY).
        self._actualizar_boton_archivo()
        self._render()

    def _actualizar_boton_archivo(self):
        """Habilita/deshabilita el botón 'Archivo histórico' según la
        tabla mantenimientos_archivo tenga contenido. Se llama desde
        recargar_datos(). Ícono con color fijo — la diferenciación visual
        entre enabled/disabled la da la opacidad (efecto) y el estilo
        (fondo + borde vía QSS con :disabled). Ver el bloque del botón
        en _crear_encabezado()."""
        try:
            from db_manager import obtener_anios_disponibles_en_archivo
            hay_archivo = len(obtener_anios_disponibles_en_archivo()) > 0
        except Exception:
            hay_archivo = False
        self.btn_archivo.setEnabled(hay_archivo)
        # Opacidad: 1.0 cuando hay contenido, 0.35 cuando no. Efecto
        # visible de "apagado" que apoya al QSS :disabled.
        self._efecto_opacidad_archivo.setOpacity(1.0 if hay_archivo else 0.35)

    def _abrir_archivo_historico(self):
        """Flujo completo del botón 'Archivo histórico':
             1. Abrir DialogSeleccionArchivo con año/mes.
             2. Si el usuario acepta, abrir VentanaArchivoHistorico con
                los datos filtrados.
             3. Si desde la ventana se pide 'Cambiar filtro', volver al
                paso 1 con un nuevo diálogo.
             4. Si se cierra la ventana normalmente o se cancela el
                diálogo, salir del flujo.
        El loop while permite el ida-y-vuelta selector ↔ ventana sin
        recursión (que sería frágil con exec() modales anidados)."""
        try:
            from archivo_historico import (
                DialogSeleccionArchivo,
                VentanaArchivoHistorico,
                RESULTADO_CAMBIAR_FILTRO,
            )
        except Exception as e:
            print(f"[Finalizados] no se pudo cargar archivo_historico: {e}")
            return

        while True:
            dlg = DialogSeleccionArchivo(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                break  # el usuario canceló el selector
            ventana = VentanaArchivoHistorico(
                dlg.anio_elegido, dlg.mes_elegido, self
            )
            resultado = ventana.exec()
            if resultado != RESULTADO_CAMBIAR_FILTRO:
                break  # cerró la ventana normalmente

    def _render(self):
        """
        Pipeline (Fase 2 — recycling de widgets):

            1. Enriquecer datos_crudos con equipos_lineas + estado +
               texto buscable + año de cierre.
            2. Determinar año objetivo:
                 - "Todos" → año en curso.
                 - Un año específico → ese año.
            3. Filtrar items al año objetivo (universo del pool).
            4. Actualizar contadores del pill de estado.
            5. Sincronizar el pool con el universo del año:
                 - Si cambió la cápsula (año distinto al pool actual):
                   destruir el pool completo y construirlo desde cero
                   con las cards del nuevo año.
                 - Si es el mismo año pero llegaron cierres nuevos por
                   signal: agregar solo esas cards nuevas al pool sin
                   tocar las demás.
                 - Si no hay cambios en los datos: no se toca el pool.
            6. Aplicar filtros visuales sobre el pool: show()/hide()
               según búsqueda + pill de estado. Cero destrucción / cero
               creación.

        Costo:
            - Al abrir o cambiar de cápsula: O(N) creación (una vez).
            - Al buscar / cambiar pill de estado: O(N) show/hide, MUY
              barato — es lo que da la fluidez percibida.
            - Al llegar un cierre nuevo: O(1) creación de una card.
        """
        # === Paso 1: enriquecer datos ===
        items = []
        for m in self._datos_crudos:
            equipos_raw = m[9] if len(m) > 9 else None
            equipos_lineas = _formato_equipos_dos_lineas(
                equipos_raw, self._grupo_por_equipo, self._jerarquia
            )
            estado = calcular_estado(m[8], m[3], m[4])
            anio_cierre = self._anio_de_fecha_cierre(m)
            texto_busq = " ".join([
                str(equipos_lineas[0] or ""),
                str(equipos_lineas[1] or ""),
                str(m[7] or ""),
                str(m[1] or ""),
            ]).lower()
            items.append({
                "id": m[0],
                "datos": m,
                "equipos_lineas": equipos_lineas,
                "estado": estado,
                "anio_cierre": anio_cierre,
                "texto_busq": texto_busq,
            })

        # === Paso 2: determinar año objetivo ===
        anio_actual = datetime.now().year
        if self._filtro_anio == "todos":
            anio_objetivo = anio_actual
        else:
            try:
                anio_objetivo = int(self._filtro_anio)
            except (ValueError, TypeError):
                anio_objetivo = anio_actual

        # === Paso 3: filtrar al año objetivo ===
        items_del_anio = [it for it in items if it["anio_cierre"] == anio_objetivo]

        # === Paso 4: actualizar contadores de pill de estado ===
        contadores = {"Finalizado": 0, "Cancelado": 0}
        for it in items_del_anio:
            if it["estado"] in contadores:
                contadores[it["estado"]] += 1
        total_anio = sum(contadores.values())
        self._actualizar_etiquetas_pills(contadores, total_anio)
        self._contadores_estado = contadores

        # === Paso 5: sincronizar el pool con el universo del año ===
        if self._anio_del_pool != anio_objetivo:
            # Cambio de cápsula: destruir pool viejo y construir el nuevo.
            self._limpiar_pool_completo()
            self._construir_pool(items_del_anio)
            self._anio_del_pool = anio_objetivo
        else:
            # Mismo año en el pool: detectar diffs incrementales.
            ids_en_pool = set(self._cards_por_id.keys())
            ids_en_datos = {it["id"] for it in items_del_anio}
            ids_nuevos = ids_en_datos - ids_en_pool
            ids_removidos = ids_en_pool - ids_en_datos
            if ids_nuevos:
                # Cierre nuevo llegó por signal — agregar solo eso.
                nuevos = [it for it in items_del_anio if it["id"] in ids_nuevos]
                for it in nuevos:
                    self._agregar_card_al_pool(it)
            if ids_removidos:
                # Defensivo. Los finalizados son inmutables por diseño
                # (ver ficha_mantenimiento.py: sin botones cuando hay
                # fecha_cierre); si aparece un id fuera, probablemente
                # es un borrado directo en BD. Se maneja quitándolo.
                for mant_id in ids_removidos:
                    self._quitar_card_del_pool(mant_id)

        # === Paso 6: aplicar filtros visuales ===
        self._aplicar_filtros_visuales(items_del_anio)

    def _construir_pool(self, items_del_anio):
        """
        Construye el pool completo de cards + headers para el año activo.
        Se llama SOLO al cambiar de cápsula anual (o al primer render).

        Estructura fija del layout resultante:
            [Header FINALIZADO]
            [card_fin_1, card_fin_2, ..., card_fin_N] (por fecha DESC)
            [Header CANCELADO]
            [card_can_1, card_can_2, ..., card_can_M] (por fecha DESC)
            [stretch]

        Este orden es fijo por diseño: siempre existe en el layout aunque
        el usuario filtre por un estado específico (en ese caso se ocultan
        los headers y las cards del otro estado con hide(), pero no se
        reordena nada).
        """
        # Separar por estado, preservando orden (fecha DESC ya viene de SQL).
        por_estado = {"Finalizado": [], "Cancelado": []}
        for it in items_del_anio:
            if it["estado"] in por_estado:
                por_estado[it["estado"]].append(it)

        # Insertar en orden: Finalizado header + sus cards → Cancelado header + sus cards.
        for estado in ("Finalizado", "Cancelado"):
            header = _build_seccion_header(estado, self._contadores_estado.get(estado, 0))
            self._headers_seccion[estado] = header
            self._contenido_lay.insertWidget(
                self._contenido_lay.count() - 1, header
            )
            for it in por_estado[estado]:
                card = self._crear_card(it)
                self._cards_por_id[it["id"]] = card
                self._contenido_lay.insertWidget(
                    self._contenido_lay.count() - 1, card
                )

    def _crear_card(self, it):
        """Fábrica de FinalizadoCard: crea, conecta signals, retorna."""
        card = FinalizadoCard(it["datos"], it["equipos_lineas"])
        card.double_clicked.connect(self._abrir_ficha)
        card.menu_solicitado.connect(self._mostrar_menu_contextual)
        # Guardar refs a metadata útil directamente en la card para el
        # filtrado visual (evita re-calcular en cada _aplicar_filtros).
        card._estado_finalizado = it["estado"]
        card._texto_busq = it["texto_busq"]
        return card

    def _agregar_card_al_pool(self, it):
        """
        Agrega UNA card al pool sin tocar las demás. Se usa cuando llega
        un cierre nuevo vía signal mantenimiento_guardado.

        Como el SELECT viene ordenado por fecha_cierre DESC y esta card
        acaba de cerrarse ahorita, debe ir arriba de todo el grupo de su
        estado (la más reciente). Se inserta justo después del header del
        estado correspondiente.
        """
        card = self._crear_card(it)
        self._cards_por_id[it["id"]] = card

        header = self._headers_seccion.get(it["estado"])
        if header is None:
            # No debería pasar (los headers se crean siempre en
            # _construir_pool), pero por defensa: si falta el header, la
            # metemos al final antes del stretch.
            self._contenido_lay.insertWidget(
                self._contenido_lay.count() - 1, card
            )
        else:
            # Insertar justo después del header del estado.
            idx_header = self._contenido_lay.indexOf(header)
            self._contenido_lay.insertWidget(idx_header + 1, card)

        # Actualizar contador del header.
        self._contadores_estado[it["estado"]] = self._contadores_estado.get(
            it["estado"], 0
        ) + 1

    def _quitar_card_del_pool(self, mant_id: int):
        """Destruye UNA card del pool. Defensivo — normalmente no se usa."""
        card = self._cards_por_id.pop(mant_id, None)
        if card is None:
            return
        estado = getattr(card, "_estado_finalizado", None)
        if estado in self._contadores_estado:
            self._contadores_estado[estado] = max(
                0, self._contadores_estado[estado] - 1
            )
        card.hide()
        card.deleteLater()

    def _aplicar_filtros_visuales(self, items_del_anio):
        """
        Recorre el pool y aplica show()/hide() según los filtros activos.
        Esta función se llama en CADA _render(): es el corazón de la
        fluidez, porque no crea ni destruye widgets.

        Reglas:
            - Card visible si: (pill de estado la incluye) Y (búsqueda
              coincide o está vacía).
            - Header visible si: modo pill "todos" activo Y hay al
              menos una card visible de ese estado. En modo pill de
              estado específico, TODOS los headers se ocultan (vista
              plana).
            - Mensaje vacío visible si: cero cards visibles en total.
        """
        modo_agrupado = (self._filtro_activo == "todos")
        visibles_por_estado = {"Finalizado": 0, "Cancelado": 0}

        for it in items_del_anio:
            card = self._cards_por_id.get(it["id"])
            if card is None:
                continue

            # Filtro 1: pill de estado.
            pasa_estado = (
                self._filtro_activo == "todos"
                or it["estado"] == self._filtro_activo
            )
            # Filtro 2: búsqueda.
            pasa_busqueda = (
                not self._texto_busqueda
                or self._texto_busqueda in it["texto_busq"]
            )

            if pasa_estado and pasa_busqueda:
                card.show()
                if it["estado"] in visibles_por_estado:
                    visibles_por_estado[it["estado"]] += 1
            else:
                card.hide()

        # Actualizar headers (visibilidad + contadores).
        # En modo plano (pill de estado específico), TODOS los headers
        # se ocultan; en modo agrupado, se muestran si su sección tiene
        # al menos una card visible.
        for estado in ("Finalizado", "Cancelado"):
            header = self._headers_seccion.get(estado)
            if header is None:
                continue
            if modo_agrupado and visibles_por_estado.get(estado, 0) > 0:
                # Actualizar el contador dentro del header. El header
                # muestra el total del estado (no el filtrado por
                # búsqueda), igual comportamiento que Fase 1.
                self._set_texto_contador_header(
                    header, estado, self._contadores_estado.get(estado, 0)
                )
                header.show()
            else:
                header.hide()

        # Manejar el mensaje de estado vacío.
        total_visibles = sum(visibles_por_estado.values())
        self._actualizar_msg_vacio(total_visibles == 0)

    def _set_texto_contador_header(self, header, estado, contador):
        """
        Actualiza el texto de contador dentro de un header. El header es
        un QWidget que contiene un layout con labels; buscamos el label
        que tiene el patrón "<estado> · N" y lo actualizamos.
        """
        for lbl in header.findChildren(QLabel):
            texto = lbl.text() or ""
            if texto.startswith(estado.upper()) or texto.startswith(estado):
                lbl.setText(f"{estado.upper()} · {contador}")
                return

    def _actualizar_msg_vacio(self, mostrar: bool):
        """
        Muestra u oculta el label persistente de estado vacío con el
        texto contextual según el filtro. El label se crea perezosamente
        la primera vez que hace falta.
        """
        if not mostrar:
            if self._msg_vacio is not None:
                self._msg_vacio.hide()
            return

        # Determinar texto contextual.
        anio_actual = datetime.now().year
        if self._texto_busqueda or self._filtro_activo != "todos":
            texto = "Sin resultados para los filtros actuales."
        elif self._filtro_anio != "todos":
            texto = f"Sin mantenimientos cerrados en {self._filtro_anio}."
        else:
            texto = f"Sin mantenimientos cerrados en {anio_actual} todavía."

        if self._msg_vacio is None:
            self._msg_vacio = QLabel(texto)
            self._msg_vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._msg_vacio.setStyleSheet(
                "color: #666; font-size: 12px; font-style: italic;"
                " background: transparent; padding: 40px 0;"
            )
            self._contenido_lay.insertWidget(
                self._contenido_lay.count() - 1, self._msg_vacio
            )
        else:
            self._msg_vacio.setText(texto)
            self._msg_vacio.show()

    def _limpiar_pool_completo(self):
        """
        Destruye TODAS las cards y headers del pool. Solo se llama al
        cambiar de cápsula anual (o al recargar_datos desde cero, ej.
        primera carga). Vacía _cards_por_id y _headers_seccion.

        El mensaje de estado vacío (_msg_vacio) NO se destruye — es
        persistente entre cápsulas, solo se oculta/muestra con
        _actualizar_msg_vacio.

        IMPORTANTE: NO toca self._contadores_estado. Ese dict es
        calculado y asignado por _render() JUSTO ANTES de llamar a este
        método (paso 4 → paso 5). Si acá lo reseteamos a ceros, los
        headers que _construir_pool crea inmediatamente después usarían
        esos ceros en vez de los conteos reales — que era el bug que
        hacía que "FINALIZADO · 0" y "CANCELADO · 0" aparecieran en la
        primera carga aunque los pills sí mostraran los conteos
        correctos (los pills se actualizan desde la variable local
        `contadores` en _render, no desde el atributo).
        """
        for card in self._cards_por_id.values():
            # NOTA: hide() antes de deleteLater() por la misma razón que
            # en Fase 1 (ver comentario extenso en _refrescar_pills_anio):
            # setParent(None) o dejar el widget visible durante el ciclo
            # de destrucción produce ventanas top-level parpadeantes en
            # Windows.
            card.hide()
            card.deleteLater()
        for header in self._headers_seccion.values():
            header.hide()
            header.deleteLater()
        self._cards_por_id.clear()
        self._headers_seccion.clear()

    def _actualizar_etiquetas_pills(self, contadores, total):
        self._pills["todos"].setText(f"Todos · {total}")
        for key in ("Finalizado", "Cancelado"):
            self._pills[key].setText(f"{key} · {contadores[key]}")

    # ===================== ACCIONES (doble click / menú) =====================
    def _abrir_ficha(self, mant_id: int):
        """
        Provisional: abre la misma FichaMantenimientoDialog que usa
        Programados. La ficha actual ya tiene chequeo temprano en
        _botones_para_estado: si fecha_cierre IS NOT NULL, solo aparece
        'Ver reporte PDF' (Finalizado) o ningún botón (Cancelado-cerrado).
        Cuando se haga la ficha de cierre dedicada se cambiará aquí.
        """
        from ficha_mantenimiento import FichaMantenimientoDialog
        dialog = FichaMantenimientoDialog(mant_id, self)
        dialog.exec()

    def _mostrar_menu_contextual(self, mant_id: int, pos_global: QPoint):
        menu = QMenu(self)
        act_ver = menu.addAction("Ver detalle")
        accion = menu.exec(pos_global)
        if accion == act_ver:
            self._abrir_ficha(mant_id)
