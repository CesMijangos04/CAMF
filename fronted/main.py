from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QSizePolicy, QFrame,
    QSplashScreen
)
from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
import sys
import os
 
# Íconos vectoriales -> pip install qtawesome
import qtawesome as qta
 
from inicio import InicioWindow                  # tu ventana de inicio 
from inventario import InventarioWindow          # tu ventana del inventario
from mantenimientos import MantenimientosWindow  # tu ventana de mantenimientos
from configuracion import ConfiguracionWindow    # tu ventana de configuración
from reportes import ReportesTab                 # tu ventana de reportes
from db_manager import create_database           # control de base de datos local
 
# ==========================================================
#  RUTAS DE RECURSOS
# ==========================================================
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(BASE_DIR, "icons")
LOGO_PATH = os.path.join(ICONS_DIR, "logo.png")   # ← ajusta el nombre real del archivo
 
# ------------ Crear base de datos si no existe ------------
db_creada = create_database()
if db_creada:
    print("🟢 Base de datos 'memoria.db' creada correctamente.")
else:
    print("📂 Base de datos ya existente.")


# ==========================================================
#  SPLASH DE ARRANQUE (Fase 4)
#  - Se muestra SOLO cuando hay migración anual pendiente.
#  - En uso diario normal (99% de las veces) no aparece; CAMF
#    arranca directo como siempre.
#  - Diseño intencionalmente simple: logo + nombre + mensaje
#    corto. Sin animación. Ver Turno 2B.2 en las notas —
#    versión con carga en background queda para Opción B
#    (splash "de verdad") cuando se decida abordarla.
# ==========================================================
class SplashArchivado(QSplashScreen):
    ANCHO = 480
    ALTO  = 320
    COLOR_FONDO      = "#1a1a1a"   # mismo negro que el header del sidebar
    COLOR_MARCA      = "#ffffff"
    COLOR_MENSAJE    = "#888888"
    LOGO_LADO        = 96          # px del logo dentro del splash

    def __init__(self, logo_path=None):
        # El pixmap base contiene SOLO fondo y logo. El texto se pinta
        # como QLabel encima del splash (después del super().__init__)
        # para aprovechar el renderizado nativo de Qt en Windows
        # (DirectWrite + subpixel AA / ClearType). QPainter.drawText
        # sobre un QPixmap en memoria solo hace grayscale AA — se ve
        # borroso porque Qt no conoce el layout de subpíxeles del
        # monitor. Con QLabel sí, y las letras salen crujientes.

        # DPR (device pixel ratio) del monitor primario. En Windows a
        # 100% es 1.0, a 125% es 1.25, a 150% es 1.5, a 200% es 2.0.
        # Creamos el pixmap base a tamaño FÍSICO (lógico × DPR) y le
        # decimos a Qt el DPR. Con eso, todas las coordenadas del
        # painter siguen en unidades lógicas (ANCHO, ALTO, LOGO_LADO)
        # pero se pintan a la densidad real de la pantalla — la app
        # se ve nítida en cualquier escalado, para cualquier usuario.
        app = QApplication.instance()
        dpr = app.primaryScreen().devicePixelRatio() if app else 1.0

        pixmap = QPixmap(int(self.ANCHO * dpr), int(self.ALTO * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(QColor(self.COLOR_FONDO))

        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            # Logo centrado horizontalmente, un poco arriba del centro
            # para dejar espacio a la marca y al mensaje debajo. El PNG
            # ya viene con las esquinas transparentes fuera del app-icon
            # redondeado — se pinta tal cual sobre el fondo del splash.
            if logo_path and os.path.exists(logo_path):
                # Escalamos el logo al tamaño FÍSICO (LOGO_LADO × DPR)
                # y le seteamos el DPR. Así Qt lo dibuja a resolución
                # real, no interpolada por Windows.
                lado_fisico = int(self.LOGO_LADO * dpr)
                logo = QPixmap(logo_path).scaled(
                    lado_fisico, lado_fisico,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                logo.setDevicePixelRatio(dpr)
                # Coordenadas de destino en unidades LÓGICAS.
                x_logo = (self.ANCHO - self.LOGO_LADO) // 2
                y_logo = 70
                painter.drawPixmap(x_logo, y_logo, logo)
        finally:
            painter.end()

        super().__init__(pixmap)

        # ─── Textos como QLabel encima del pixmap ────────────────────
        # Los QLabel son hijos del splash y se pintan directamente en
        # pantalla, no sobre un pixmap intermedio — así reciben el
        # renderizado nativo de Windows con subpixel AA. Las geometrías
        # replican exactamente las que tenían los antiguos drawText.

        # Nombre de la marca "CAMF" debajo del logo.
        self._lbl_marca = QLabel("CAMF", self)
        self._lbl_marca.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self._lbl_marca.setStyleSheet(
            f"color: {self.COLOR_MARCA}; background: transparent;"
        )
        self._lbl_marca.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_marca.setGeometry(0, 190, self.ANCHO, 32)

        # Mensaje de estado. Fijo por ahora; en la versión "de verdad"
        # (Opción B) se actualizará por etapas: respaldo → migración → rotación.
        self._lbl_mensaje = QLabel("Archivando registros históricos...", self)
        self._lbl_mensaje.setFont(QFont("Segoe UI", 10))
        self._lbl_mensaje.setStyleSheet(
            f"color: {self.COLOR_MENSAJE}; background: transparent;"
        )
        self._lbl_mensaje.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_mensaje.setGeometry(0, 240, self.ANCHO, 20)
        # Mantener el splash arriba de todo mientras dura la migración.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)


# ==========================================================
#  BOTÓN PERSONALIZADO DEL SIDEBAR
#  - Maneja estado activo/inactivo y modo colapsado
#  - Pinta una barra azul a la izquierda cuando está activo
#  - Colores tomados directo de la paleta del proyecto
# ==========================================================
class SidebarButton(QPushButton):
    def __init__(self, texto, icono_qta, parent=None):
        super().__init__(parent)
        self.texto_completo = texto
        self.icono_qta = icono_qta
        self.activo = False
        self.colapsado = False
 
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(20, 20))
 
        self._actualizar_icono()
        self._actualizar_texto()
        self._actualizar_estilo()
 
    def _actualizar_icono(self):
        # Activo: blanco. Inactivo: gris muted (#888, el mismo que usas en configuracion)
        color = "#ffffff" if self.activo else "#888888"
        self.setIcon(qta.icon(self.icono_qta, color=color))
 
    def _actualizar_texto(self):
        if self.colapsado:
            self.setText("")
            self.setToolTip(self.texto_completo)
        else:
            # Espacios para separar el ícono del texto
            self.setText(f"   {self.texto_completo}")
            self.setToolTip("")
 
    def _actualizar_estilo(self):
        if self.activo:
            # Activo: fondo #2b2b2b (el bg de botón de tu main original),
            # texto blanco bold, barrita azul de 3px a la izquierda.
            self.setStyleSheet("""
                QPushButton {
                    background-color: #2b2b2b;
                    color: #ffffff;
                    font-weight: bold;
                    font-size: 14px;
                    border: none;
                    border-left: 3px solid #0078d7;
                    text-align: left;
                    padding-left: 18px;
                }
            """)
        else:
            # Inactivo: transparente sobre el bg del sidebar (#222),
            # texto muted (#888). Hover sube al mismo #2b2b2b.
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #888888;
                    font-weight: 500;
                    font-size: 14px;
                    border: none;
                    border-left: 3px solid transparent;
                    text-align: left;
                    padding-left: 18px;
                }
                QPushButton:hover {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
            """)
 
    def setActivo(self, activo):
        self.activo = activo
        self._actualizar_icono()
        self._actualizar_estilo()
 
    def setColapsado(self, colapsado):
        self.colapsado = colapsado
        self._actualizar_texto()
 
 
# ==========================================================
#  VENTANA PRINCIPAL
# ==========================================================
class MainWindow(QMainWindow):
    ANCHO_EXPANDIDO = 220
    ANCHO_COLAPSADO = 64
 
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sistema de Mantenimiento Eléctrico")
        self.setGeometry(100, 100, 1000, 600)
 
        # Ícono de la ventana (aparece arriba a la izquierda y en la barra de tareas)
        if os.path.exists(LOGO_PATH):
            self.setWindowIcon(QIcon(LOGO_PATH))
 
        self.sidebar_colapsado = False
 
        # ------------------ Layout principal ------------------
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
 
        # ------------------ SIDEBAR ------------------
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(self.ANCHO_EXPANDIDO)
        # Fondo del sidebar: #222 (tu color original)
        self.sidebar.setStyleSheet("background-color: #222;")
 
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
 
        # ---------- Header del sidebar: logo + marca ----------
        self.header_widget = QWidget()
        self.header_widget.setFixedHeight(76)
        # Un tono más oscuro que el sidebar para anclar visualmente el logo
        self.header_widget.setStyleSheet("background-color: #1a1a1a;")
 
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(14, 8, 14, 8)
        header_layout.setSpacing(12)
 
        # Logo (imagen pequeña)
        self.logo_label = QLabel()
        self.logo_label.setFixedSize(44, 44)
        if os.path.exists(LOGO_PATH):
            # Escalado HiDPI: consultamos el DPR real del monitor
            # (100% → 1.0, 125% → 1.25, 150% → 1.5, 200% → 2.0),
            # cargamos el pixmap al tamaño FÍSICO (44 × DPR) y le
            # decimos a Qt su DPR. El QLabel sigue midiendo 44×44
            # en unidades lógicas, pero renderiza a resolución real —
            # nítido en cualquier escala de Windows.
            dpr = self.devicePixelRatioF()
            lado_fisico = int(44 * dpr)
            pixmap = QPixmap(LOGO_PATH).scaled(
                lado_fisico, lado_fisico,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            pixmap.setDevicePixelRatio(dpr)
            self.logo_label.setPixmap(pixmap)
        else:
            # Fallback si aún no está el archivo en icons/logo.png
            self.logo_label.setStyleSheet(
                "background-color: #1a1a1a; border-radius: 6px; "
                "color: #0078d7; font-size: 22px; font-weight: bold;"
            )
            self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.logo_label.setText("C")
 
        # Texto de marca (CAMF + subtítulo)
        self.marca_widget = QWidget()
        marca_layout = QVBoxLayout(self.marca_widget)
        marca_layout.setContentsMargins(0, 0, 0, 0)
        marca_layout.setSpacing(0)
 
        nombre_marca = QLabel("CAMF")
        nombre_marca.setStyleSheet(
            "color: white; font-size: 15px; font-weight: bold; background: transparent;"
        )
 
        sub_marca = QLabel("Engineering Software\n& Asset Intelligence")
        sub_marca.setStyleSheet(
            "color: #888; font-size: 10px; background: transparent;"
        )
 
        marca_layout.addWidget(nombre_marca)
        marca_layout.addWidget(sub_marca)
 
        header_layout.addWidget(self.logo_label)
        header_layout.addWidget(self.marca_widget)
        header_layout.addStretch()
 
        sidebar_layout.addWidget(self.header_widget)
 
        # ---------- Separador delgado ----------
        separador = QFrame()
        separador.setFixedHeight(1)
        separador.setStyleSheet("background-color: #2a2a2a;")
        sidebar_layout.addWidget(separador)
 
        sidebar_layout.addSpacing(8)
 
        # ---------- Botones de navegación (texto + ícono qtawesome) ----------
        botones_info = [
            ("Inicio",         "fa5s.home"),
            ("Inventario",     "fa5s.boxes"),
            ("Mantenimientos", "fa5s.tools"),
            ("Reportes",       "fa5s.chart-bar"),
            ("Configuración",  "fa5s.cog"),
        ]
 
        self.botones = []
        self.nombres_paginas = []
 
        for texto, icono in botones_info:
            btn = SidebarButton(texto, icono)
            sidebar_layout.addWidget(btn)
            self.botones.append(btn)
            self.nombres_paginas.append(texto)
 
        sidebar_layout.addStretch()
 
        # ---------- Botón colapsar / expandir ----------
        self.btn_colapsar = QPushButton()
        self.btn_colapsar.setFixedHeight(40)
        self.btn_colapsar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_colapsar.setIcon(qta.icon('fa5s.angle-double-left', color='#888'))
        self.btn_colapsar.setIconSize(QSize(14, 14))
        self.btn_colapsar.setToolTip("Contraer")
        self.btn_colapsar.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-top: 1px solid #2a2a2a;
            }
            QPushButton:hover {
                background-color: #2b2b2b;
            }
        """)
        self.btn_colapsar.clicked.connect(self.toggle_sidebar)
        sidebar_layout.addWidget(self.btn_colapsar)
 
        # ------------------ Área de contenido ------------------
        # No le pongo background-color aquí: cada ventana (Inventario,
        # Mantenimientos, Configuración) ya define el suyo.
        self.stack = QStackedWidget()
        self.paginas = {}
 
        for texto in self.nombres_paginas:
            if texto == "Inicio":
                pagina = InicioWindow()
            elif texto == "Inventario":
                pagina = InventarioWindow()
            elif texto == "Mantenimientos":
                pagina = MantenimientosWindow()
            elif texto == "Configuración":
                pagina = ConfiguracionWindow()
            elif texto == "Reportes":
                pagina = ReportesTab()  
            else:
                pagina = QWidget()
                layout_pagina = QVBoxLayout()
                layout_pagina.addWidget(QLabel(
                    f"📄 Página de {texto}",
                    alignment=Qt.AlignmentFlag.AlignCenter
                ))
                pagina.setLayout(layout_pagina)
 
            self.stack.addWidget(pagina)
            self.paginas[texto] = pagina
 
        # ------------------ Conectar botones ------------------
        for i, boton in enumerate(self.botones):
            boton.clicked.connect(lambda _, x=i: self.mostrar_pagina(x))

        # ------------------ Wire entre pestañas ------------------
        # El botón "Configuración de reportes" de la pestaña Reportes
        self.paginas["Reportes"].abrir_configuracion_solicitada.connect(
            self._ir_a_config_reportes
        )

        # ------------------ Ensamblar ------------------
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stack)
 
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)
 
        # Mostrar la página de inicio
        self.mostrar_pagina(0)
 
    # ======================================================
    #  Navegación
    # ======================================================
    def mostrar_pagina(self, index):
        """Muestra la página y resalta el botón activo."""
        self.stack.setCurrentIndex(index)
 
        for i, boton in enumerate(self.botones):
            boton.setActivo(i == index)
 
        # Si la página actual es Inventario, refrescar
        try:
            pagina_nombre = self.nombres_paginas[index]
            if pagina_nombre == "Inventario":
                self.paginas["Inventario"].mostrarInventario()
            elif pagina_nombre == "Inicio":
                self.paginas["Inicio"].actualizar()
        except Exception as e:
            print("[DEBUG mostrar_pagina] error al intentar mostrarInventario:", e)

    def _ir_a_config_reportes(self):
        """Cambia a la pestaña Configuración y abre la landing de Reportes.
        Conectado a la señal `abrir_configuracion_solicitada` de la pestaña
        Reportes (botón superior derecho 'Configuración de reportes')."""
        # Importar la constante de página dentro del método para evitar
        # import circular en tiempo de carga.
        from configuracion import PAGE_REPORTES_HOME
        idx_config = self.nombres_paginas.index("Configuración")
        self.mostrar_pagina(idx_config)
        # Algunos métodos de navegación dependen de que la página esté
        # ya visible; processEvents asegura que setCurrentIndex tomó efecto.
        QApplication.processEvents()
        self.paginas["Configuración"].navegar_a(PAGE_REPORTES_HOME)
 
    # ======================================================
    #  Colapsar / Expandir sidebar
    # ======================================================
    def toggle_sidebar(self):
        self.sidebar_colapsado = not self.sidebar_colapsado
 
        if self.sidebar_colapsado:
            self.sidebar.setFixedWidth(self.ANCHO_COLAPSADO)
            self.marca_widget.hide()
            self.btn_colapsar.setIcon(qta.icon('fa5s.angle-double-right', color='#888'))
            self.btn_colapsar.setToolTip("Expandir")
        else:
            self.sidebar.setFixedWidth(self.ANCHO_EXPANDIDO)
            self.marca_widget.show()
            self.btn_colapsar.setIcon(qta.icon('fa5s.angle-double-left', color='#888'))
            self.btn_colapsar.setToolTip("Contraer")
 
        for btn in self.botones:
            btn.setColapsado(self.sidebar_colapsado)
 
 
# ==========================================================
#  EJECUCIÓN
# ==========================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
 
    # Ícono global: lo usan también las ventanas hijas/diálogos
    if os.path.exists(LOGO_PATH):
        app.setWindowIcon(QIcon(LOGO_PATH))

    # ─────────────────────────────────────────────────────────
    #  FASE 4 — Migración anual al archivo histórico
    # ─────────────────────────────────────────────────────────
    # Se ejecuta AL ARRANCAR CAMF, antes de mostrar la ventana
    # principal. Solo corre si:
    #   (a) hay años cerrados hace >5 años elegibles, Y
    #   (b) no se corrió ya este año calendario, Y
    #   (c) no hay un fallo pendiente de un intento anterior.
    #
    # Con (c): si hubo un fallo, la notificación clickeable en
    # Inicio queda como la vía de acción del usuario. No lo
    # bombardeamos con el splash cada vez que abre CAMF si el
    # fallo se debe a algo que él debe resolver primero (disco,
    # otra instancia abierta, etc.).
    #
    # En uso diario normal (99% de las veces) este bloque no
    # muestra nada y CAMF arranca directo como siempre.
    try:
        from migracion_archivo import (
            hay_migracion_pendiente,
            hay_fallo_pendiente,
            ejecutar_migracion_anual,
        )
        if hay_migracion_pendiente() and not hay_fallo_pendiente():
            splash = SplashArchivado(LOGO_PATH)
            splash.show()
            # processEvents fuerza a Qt a pintar el splash AHORA, antes
            # de bloquear el hilo con la migración (que es SQL síncrono).
            app.processEvents()
            exito, mensaje = ejecutar_migracion_anual()
            print(f"[Fase 4] migración de arranque: exito={exito}, mensaje={mensaje}")
            splash.close()
    except Exception as e:
        # La migración es best-effort al arrancar. Si algo falla acá
        # (import roto, excepción no capturada), NO impedimos que CAMF
        # arranque. El error queda en la consola para diagnóstico y el
        # usuario puede reintentar más tarde desde la notificación.
        print(f"[Fase 4] error inesperado en migración de arranque: {e}")

    ventana = MainWindow()
    ventana.show()
    sys.exit(app.exec())

