"""
Paquete notificaciones — bandeja de notificaciones de CAMF.

Este __init__.py re-exporta la API pública del orquestador para que
`inicio.py` (y cualquier otro consumidor) siga haciendo el mismo import
que antes del refactor:

    from notificaciones import obtener_notificaciones_activas

La lógica real vive en `notificaciones/notificaciones.py` (el
orquestador) y cada tipo específico vive en su propio archivo dentro
del paquete.
"""
from .notificaciones import obtener_notificaciones_activas

__all__ = ["obtener_notificaciones_activas"]
