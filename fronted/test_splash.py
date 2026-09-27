"""
test_splash.py — Ver el splash aislado

Ejecuta desde la carpeta del proyecto:

    python test_splash.py

Muestra el splash de arranque durante 3 segundos y termina.
No ejecuta ninguna migración, no toca la base de datos.
Solo sirve para ver cómo se ve el splash visualmente.

Cuando termines de ajustar el splash, borra este archivo — no es
código de producción.
"""
import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Importar SplashArchivado y LOGO_PATH desde main.py
from main import SplashArchivado, LOGO_PATH


def main():
    app = QApplication(sys.argv)

    splash = SplashArchivado(LOGO_PATH)
    splash.show()

    # Cierra el splash y sale de la app después de 3 segundos.
    QTimer.singleShot(3000, splash.close)
    QTimer.singleShot(3100, app.quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
