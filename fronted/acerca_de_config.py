# acerca_de_config.py
"""
Página "Acerca de" — carátula del programa con info de versión y sistema.

Diseño tipo Windows 11 Settings:
  [icono] Sistema de Mantenimiento Eléctrico
          Versión X · Build Y
          Tagline

  INFORMACIÓN DEL SISTEMA
  Versión de la app                 1.0
  Python                            3.x.x
  PyQt6                             6.9.x
  Qt                                6.9.x
  Sistema operativo                 Windows 11

  [ Copiar información del sistema ]
"""

import sys
import platform

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QApplication, QMessageBox
)
from PyQt6.QtCore import Qt, QT_VERSION_STR, PYQT_VERSION_STR, QSize
import qtawesome as qta


# ── Constantes editables cuando saques una nueva versión ─────────────────────
APP_VERSION = "1.0"
APP_BUILD   = "2026.06"
APP_NOMBRE  = "Sistema de Mantenimiento Eléctrico"
APP_TAGLINE = "Gestión de equipos, mantenimientos y responsables"


def _info_sistema() -> dict[str, str]:
    """Devuelve un dict con los datos que se muestran/copian al portapapeles."""
    py = sys.version_info
    return {
        "Versión de la app":  APP_VERSION,
        "Python":             f"{py.major}.{py.minor}.{py.micro}",
        "PyQt6":              PYQT_VERSION_STR,
        "Qt":                 QT_VERSION_STR,
        "Sistema operativo":  f"{platform.system()} {platform.release()}",
    }


def _make_app_icon(size: int = 64) -> QFrame:
    """Cuadrado con gradiente verde-azulado y rayo (símbolo eléctrico) al centro."""
    frame = QFrame()
    frame.setFixedSize(size, size)
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    frame.setStyleSheet(f"""
        QFrame {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #1d4a3a, stop:1 #0a2a3a);
            border-radius: {size // 6}px;
        }}
    """)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ico = QLabel()
    ico.setPixmap(qta.icon("fa5s.bolt", color="#5ce0a8").pixmap(int(size * 0.5), int(size * 0.5)))
    ico.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    lay.addWidget(ico)
    return frame


def _make_info_row(label: str, value: str) -> QFrame:
    """Fila informativa: label a la izquierda, valor a la derecha."""
    row = QFrame()
    row.setObjectName("info_row")
    row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    row.setMinimumHeight(50)
    row.setStyleSheet("""
        QFrame#info_row {
            background: #2b2b2b;
            border-radius: 8px;
        }
        QLabel#info_label {
            color: white; font-size: 14px; background: transparent;
        }
        QLabel#info_value {
            color: #aaa; font-size: 14px; background: transparent;
        }
    """)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(12)

    lbl_l = QLabel(label)
    lbl_l.setObjectName("info_label")
    lay.addWidget(lbl_l)

    lay.addStretch()

    lbl_r = QLabel(value)
    lbl_r.setObjectName("info_value")
    lbl_r.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(lbl_r)
    return row


class AcercaDePage(QWidget):
    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        # self queda SIN setStyleSheet para no propagar estilos a diálogos hijos.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(_SCROLLBAR_QSS)
        outer.addWidget(scroll, 1)

        contenido = QWidget()
        contenido.setStyleSheet(_PAGE_QSS)
        scroll.setWidget(contenido)

        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.setSpacing(18)

        # ── Tarjeta superior: icono + nombre + versión + tagline ─────────
        card = QHBoxLayout()
        card.setSpacing(16)
        card.addWidget(_make_app_icon(64), alignment=Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        text_box.setContentsMargins(0, 2, 0, 0)

        lbl_nombre = QLabel(APP_NOMBRE)
        lbl_nombre.setObjectName("app_nombre")
        text_box.addWidget(lbl_nombre)

        lbl_version = QLabel(f"Versión {APP_VERSION} · Build {APP_BUILD}")
        lbl_version.setObjectName("app_version")
        text_box.addWidget(lbl_version)

        lbl_tagline = QLabel(APP_TAGLINE)
        lbl_tagline.setObjectName("app_tagline")
        text_box.addWidget(lbl_tagline)

        card.addLayout(text_box, 1)
        lay.addLayout(card)
        lay.addSpacing(6)

        # ── Sección "INFORMACIÓN DEL SISTEMA" ────────────────────────────
        cab = QLabel("INFORMACIÓN DEL SISTEMA")
        cab.setObjectName("section_header")
        lay.addWidget(cab)

        self._info = _info_sistema()
        for label, value in self._info.items():
            lay.addWidget(_make_info_row(label, value))

        # ── Botón Copiar ─────────────────────────────────────────────────
        lay.addSpacing(6)
        btn_copy = QPushButton("  Copiar información del sistema")
        btn_copy.setObjectName("btn_copiar")
        btn_copy.setIcon(qta.icon("fa5s.copy", color="#ddd"))
        btn_copy.setIconSize(QSize(14, 14))
        btn_copy.setMinimumHeight(40)
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(self._copiar_info)
        lay.addWidget(btn_copy, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addStretch()

    def _copiar_info(self):
        """Copia todos los pares label: valor al portapapeles."""
        texto = "\n".join(f"{k}: {v}" for k, v in self._info.items())
        QApplication.clipboard().setText(texto)
        QMessageBox.information(
            self, "Copiado",
            "Información del sistema copiada al portapapeles."
        )


# ── Estilos ──────────────────────────────────────────────────────────────────
_PAGE_QSS = """
    QLabel#app_nombre {
        color: white; font-size: 18px; font-weight: 500; background: transparent;
    }
    QLabel#app_version {
        color: #888; font-size: 12px; background: transparent;
    }
    QLabel#app_tagline {
        color: #999; font-size: 12px; background: transparent;
    }
    QLabel#section_header {
        color: #666; font-size: 10px; font-weight: 500;
        letter-spacing: 1px; background: transparent;
    }
    QPushButton#btn_copiar {
        background: #2b2b2b;
        color: white;
        border: 1px solid #3a3a3a;
        border-radius: 6px;
        padding: 8px 18px;
        font-size: 13px;
    }
    QPushButton#btn_copiar:hover {
        background: #353535;
        border: 1px solid #0078d7;
    }
"""

_SCROLLBAR_QSS = """
    QScrollArea, QScrollArea > QWidget > QWidget {
        background: transparent; border: none;
    }
    QScrollBar:vertical {
        background: #1a1a1a; width: 10px; margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #444; border-radius: 4px;
        min-height: 30px; margin: 2px;
    }
    QScrollBar::handle:vertical:hover { background: #555; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        background: none; height: 0; border: none;
    }
"""
