from PyQt6.QtCore import QObject, pyqtSignal

class AppSignals(QObject):
    mantenimiento_guardado = pyqtSignal()

app_signals = AppSignals()