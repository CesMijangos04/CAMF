import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QFileDialog,
    QLabel, QScrollArea, QFrame, QSpacerItem, QSizePolicy, QMessageBox, QToolTip
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from pdf_utils import generar_pdf_tablero

TOTAL_SLOTS = 42
SLOT_HEIGHT = 30
SLOT_WIDTH = 92
SPACING = 6
HEADER_SPACE = 55
NUMERO_WIDTH = 24  # espacio para número y alertas

class SlotVacio(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedSize(SLOT_WIDTH, SLOT_HEIGHT)
        self.setStyleSheet("""
            QFrame {
                background-color: #ECECEC;
                border: 1px dashed #9A9A9A;
                border-radius: 4px;
            }
        """)

class BreakerVisual(QFrame):
    def __init__(self, amperaje, fases):
        super().__init__()
        self.setFixedSize(
            SLOT_WIDTH,
            SLOT_HEIGHT * fases + SPACING * (fases - 1)
        )
        self.setStyleSheet("""
            QFrame {
                background-color: #2A2A2A;
                border: 1px solid #111;
                border-radius: 4px;
            }
        """)
        lbl_amp = QLabel(f"{amperaje} A")
        lbl_amp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_amp.setFont(QFont("Arial", 11))
        lbl_amp.setStyleSheet("color: white;")

        palanca = QFrame()
        palanca.setFixedSize(6, 18)
        palanca.setStyleSheet("""
            QFrame {
                background-color: #555;
                border-radius: 2px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.addStretch()
        layout.addWidget(lbl_amp, stretch=1)
        layout.addStretch()
        layout.addWidget(palanca, alignment=Qt.AlignmentFlag.AlignVCenter)

class VistaTableroWidget(QWidget):
    def __init__(self, circuitos, num_circuitos, tablero_data, total_slots=TOTAL_SLOTS):
        super().__init__()
        self.circuitos = circuitos
        self.num_circuitos = num_circuitos
        self.tablero_data = tablero_data
        self.setWindowTitle("Tablero Eléctrico")
        self.setMinimumSize(460, 740)
        self.setStyleSheet("background-color: #8C8C8C;")

        main = QVBoxLayout(self)
        main.setContentsMargins(26, 16, 26, 16)

        carcaza = QFrame()
        carcaza.setStyleSheet("""
            QFrame {
                background-color: #B8B8B8;
                border: 2px solid #777;
                border-radius: 12px;
            }
        """)
        carcaza_layout = QVBoxLayout(carcaza)
        carcaza_layout.setContentsMargins(26, 18, 26, 22)

        header_placeholder = QFrame()
        header_placeholder.setFixedHeight(HEADER_SPACE)
        header_placeholder.setStyleSheet("""
            QFrame {
                background-color: #CFCFCF;
                border: 1px solid #AAA;
                border-radius: 6px;
            }
        """)

        marco = QFrame()
        marco.setStyleSheet("""
            QFrame {
                background-color: #DDDDDD;
                border: 1px solid #AAA;
                border-radius: 6px;
            }
        """)
        marco_layout = QVBoxLayout(marco)
        marco_layout.setContentsMargins(12, 12, 12, 12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        area = QWidget()
        area_layout = QHBoxLayout(area)
        area_layout.setSpacing(10)

        # Columnas de slots/breakers
        col_izq = QVBoxLayout()
        col_der = QVBoxLayout()
        col_izq.setSpacing(SPACING)
        col_der.setSpacing(SPACING)

        # Columnas de números afuera
        num_col_izq = QVBoxLayout()
        num_col_der = QVBoxLayout()
        num_col_izq.setSpacing(SPACING)
        num_col_der.setSpacing(SPACING)

        # Espacios visibles reales
        slots_visibles = num_circuitos

        demo_breakers_izq = {}
        demo_breakers_der = {}
        usados = set()

        for data in circuitos:
            if not data:
                continue

            inicio = data.get('espacio_inicio')
            if inicio is None:
                continue

            if inicio % 2 == 1:
                # izquierda
                demo_breakers_izq[inicio] = data
            else:
                # derecha
                demo_breakers_der[inicio] = data

        # Columna izquierda
        i = 1
        while i <= TOTAL_SLOTS:
            if i in demo_breakers_izq:
                circuito = demo_breakers_izq[i]
                amp = int(circuito['amperaje_a'])
                fases = int(circuito['polos'])
                espacios = [i + (k * 2) for k in range(fases)]
                breaker = BreakerVisual(amp, fases)
                nombre = circuito.get('nombre', "Sin nombre")
                breaker.setToolTip(
                    f"<span style='color:black;'>"
                    f"<b>Circuito:</b> {nombre} <br>"
                    f"<b>Amperaje:</b> {amp} A<br>"
                    f"<b>Fases:</b> {fases}<br>"
                    f"<b>Espacios:</b> {', '.join(map(str, espacios))}"
                    f"</span>"
                )
                col_izq.addWidget(breaker)

                lbl_num = QLabel(str(i))
                lbl_num.setFont(QFont("Arial", 8))
                lbl_num.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
                lbl_num.setFixedHeight(SLOT_HEIGHT * fases + SPACING * (fases - 1))
                lbl_num.setFixedWidth(NUMERO_WIDTH)
                lbl_num.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                num_col_izq.addWidget(lbl_num)

                usados.update(range(i, i + fases * 2, 2))
                i += 2 * fases
            else:
                if i <= slots_visibles:
                    slot = SlotVacio()
                    slot.setToolTip(
                        f"<span style='color:black;'>"
                        f"<b>Espacio {i}</b><br>"
                        "Disponible"
                        f"</span>"
                    )
                    col_izq.addWidget(slot)

                    lbl_num = QLabel(str(i))
                    lbl_num.setFont(QFont("Arial", 8))
                    lbl_num.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
                    lbl_num.setFixedHeight(SLOT_HEIGHT)
                    lbl_num.setFixedWidth(NUMERO_WIDTH)
                    lbl_num.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                    num_col_izq.addWidget(lbl_num)
                else:
                    col_izq.addItem(QSpacerItem(
                        1, SLOT_HEIGHT,
                        QSizePolicy.Policy.Fixed,
                        QSizePolicy.Policy.Fixed
                    ))
                    num_col_izq.addItem(QSpacerItem(
                        NUMERO_WIDTH, SLOT_HEIGHT,
                        QSizePolicy.Policy.Fixed,
                        QSizePolicy.Policy.Fixed
                    ))
                i += 2

        # Columna derecha
        i = 2
        while i <= TOTAL_SLOTS:
            if i in demo_breakers_der:
                circuito = demo_breakers_der[i]
                amp = int(circuito['amperaje_a'])
                fases = int(circuito['polos'])
                espacios = [i + (k * 2) for k in range(fases)]
                breaker = BreakerVisual(amp, fases)
                nombre = circuito.get('nombre', "Sin nombre")
                breaker.setToolTip(
                    f"<span style='color:black;'>"
                    f"<b>Circuito:</b> {nombre} <br>"
                    f"<b>Amperaje:</b> {amp} A<br>"
                    f"<b>Fases:</b> {fases}<br>"
                    f"<b>Espacios:</b> {', '.join(map(str, espacios))}"
                    f"</span>"
                )
                col_der.addWidget(breaker)
                lbl_num = QLabel(str(i))
                lbl_num.setFont(QFont("Arial", 8))
                lbl_num.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                lbl_num.setFixedHeight(SLOT_HEIGHT * fases + SPACING * (fases - 1))
                lbl_num.setFixedWidth(NUMERO_WIDTH)
                lbl_num.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                num_col_der.addWidget(lbl_num)

                i += 2 * fases
                continue

            if i <= slots_visibles:
                slot = SlotVacio()
                slot.setToolTip(
                    f"<span style='color:black;'>"
                    f"<b>Espacio {i}</b><br>"
                    "Disponible"
                    f"</span>"
                )
                col_der.addWidget(slot)

                lbl_num = QLabel(str(i))
                lbl_num.setFont(QFont("Arial", 8))
                lbl_num.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                lbl_num.setFixedHeight(SLOT_HEIGHT)
                lbl_num.setFixedWidth(NUMERO_WIDTH)
                lbl_num.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                num_col_der.addWidget(lbl_num)
            else:
                col_der.addItem(QSpacerItem(
                    1, SLOT_HEIGHT,
                    QSizePolicy.Policy.Fixed,
                    QSizePolicy.Policy.Fixed
                ))
                num_col_der.addItem(QSpacerItem(
                    NUMERO_WIDTH, SLOT_HEIGHT,
                    QSizePolicy.Policy.Fixed,
                    QSizePolicy.Policy.Fixed
                ))
            i += 2

        # Combinar números y columnas de slots
        container_izq = QHBoxLayout()
        container_izq.addLayout(num_col_izq)
        container_izq.addLayout(col_izq)

        container_der = QHBoxLayout()
        container_der.addLayout(col_der)
        container_der.addLayout(num_col_der)

        area_layout.addLayout(container_izq)
        area_layout.addLayout(container_der)

        scroll.setWidget(area)
        marco_layout.addWidget(scroll)

        header = self.crearEncabezado()
        carcaza_layout.addWidget(header)
        carcaza_layout.addSpacing(10)
        carcaza_layout.addWidget(marco)

        btn_layout = QHBoxLayout()
        btn_imprimir = QPushButton("Imprimir")
        btn_imprimir.setFixedSize(80, 28)
        btn_imprimir.setStyleSheet("""
            QPushButton {
                background-color: #0078d7;
                color: white;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0094ff; }
        """)
        btn_imprimir.clicked.connect(self.imprimir_tablero)

        # Layout horizontal para colocarlo en inferior derecho
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()  # empuja el botón a la derecha
        btn_layout.addWidget(btn_imprimir)
        
        carcaza_layout.addLayout(btn_layout)

        main.addWidget(carcaza)

    def crearEncabezado(self):
            contenedor = QFrame()
            contenedor.setFixedHeight(70)
            contenedor.setStyleSheet("""
                QFrame {
                    background-color: #CFCFCF;
                    border: 1px solid #AAA;
                    border-radius: 6px;
                }
            """)

            layout = QGridLayout(contenedor)
            layout.setContentsMargins(10, 6, 10, 6)
            layout.setHorizontalSpacing(20)

            lbl_id = QLabel(self.tablero_data["id"])
            lbl_ubic = QLabel(self.tablero_data["ubicacion"])
            lbl_tension = QLabel(f"V: {self.tablero_data['tension']} V")
            lbl_corriente = QLabel(f"I: {self.tablero_data['corriente']} A")
            lbl_marca = QLabel(self.tablero_data["marca"])
            lbl_tipo = QLabel(self.tablero_data["tipo"])

            for lbl in [lbl_id, lbl_ubic, lbl_tension, lbl_corriente, lbl_marca, lbl_tipo]:
                lbl.setFont(QFont("Arial", 8))
                lbl.setStyleSheet("""
                    QLabel {
                        color: #000000;
                        background: transparent;
                        border: none;
                        padding: 0px;
                    }
                """)

            layout.addWidget(lbl_id,        0, 0)
            layout.addWidget(lbl_ubic,      0, 1)
            layout.addWidget(lbl_tension,   1, 0)
            layout.addWidget(lbl_corriente, 1, 1)
            layout.addWidget(lbl_marca,     0, 2)
            layout.addWidget(lbl_tipo,      1, 2)

            return contenedor
    
    def imprimir_tablero(self):
        # Abrir diálogo para elegir ruta y nombre del archivo
        archivo, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar PDF del tablero",
            f"{self.tablero_data['id']}_directorio.pdf",
            "PDF Files (*.pdf)"
        )
        if not archivo:
            return  # si cancela, no hace nada

        # Llamar a la función que genera el PDF
        try:
            generar_pdf_tablero(
                archivo,
                self.tablero_data,
                self.circuitos,        # lista de circuitos tal como se usa en la UI
                self.num_circuitos     # número total de circuitos visibles
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Ocurrió un error al generar el PDF:\n{str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = VistaTableroWidget()
    w.show()
    sys.exit(app.exec())
