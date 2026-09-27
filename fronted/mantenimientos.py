import sys
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QTabWidget)
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt

from programar_nuevo import ProgramarNuevoWidget
from programados import ProgramadosWidget
from finalizados import FinalizadosWidget

class MantenimientosWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mantenimientos")
        self.resize(1000, 700)
        self.set_dark_style()
        self.init_ui()
        self.actualizarColorPestania()  # Aplica el estilo de pestañas como Inventario

    def set_dark_style(self):
        """Estilo general consistente con Inventario"""
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: white; font-family: Segoe UI; }
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

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#121212"))
        palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2a2a2a"))
        palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Button, QColor("#3a3a3a"))
        palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        self.setPalette(palette)

    def init_ui(self):
        layout = QVBoxLayout()
        self.tabs = QTabWidget()

        # Crear las tres pestañas
        self.tab_programar = ProgramarNuevoWidget()
        self.tab_programados = ProgramadosWidget()
        self.tab_finalizados = FinalizadosWidget()

        # Añadir las pestañas al QTabWidget
        self.tabs.addTab(self.tab_programar, "Nuevo")
        self.tabs.addTab(self.tab_programados, "Programados")
        self.tabs.addTab(self.tab_finalizados, "Finalizados")

        layout.addWidget(self.tabs)
        self.setLayout(layout)

    def actualizarColorPestania(self):
        """Estilo de pestañas idéntico al Inventario"""
        estilo = """
            QTabWidget::pane {
                border: none;
                background: #1e1e1e;
            }
            QTabBar::tab {
                background: #2a2a2a;
                color: white;
                padding: 8px 14px;
                border: none;
                border-top: 3px solid transparent;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                border-top: 3px solid #0078d7; /* Azul igual al main */
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background: #333333;
            }
        """
        self.tabs.setStyleSheet(estilo)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = MantenimientosWindow()
    ventana.show()
    sys.exit(app.exec())
