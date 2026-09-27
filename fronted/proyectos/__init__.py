"""
Módulo Proyectos de CAMF.

Diseño eléctrico asistido para baja tensión: captura de plano
arquitectónico, delimitación de espacios, colocación de simbología
eléctrica, propuesta automática de agrupación y trayectorias según
NOM-001-SEDE, cuadro de cargas, unifilar y documentación.

Estructura interna prevista:
    ventana_proyectos.py     — listado principal de proyectos (esta fase)
    wizard_nuevo_proyecto.py — asistente de 4 pasos (siguiente fase)
    espacio_trabajo.py       — vista del proyecto abierto
    canvas_plano.py          — canvas con plano de fondo tipo DIALux
    paleta_simbolos.py       — barra de simbología eléctrica
    motor_agrupacion.py      — propuesta automática de circuitos
    datos_proyecto.py        — modelo en RAM (después SQLite)
"""
