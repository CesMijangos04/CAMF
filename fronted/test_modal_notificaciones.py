"""
test_modal_notificaciones.py — Prueba temporal del modal expandido
                               de notificaciones (Fase 4).

Ejecutar desde el directorio del proyecto (donde vive main.py):
    python test_modal_notificaciones.py

Levanta la aplicación COMPLETA (main.py con toda su ventana:
sidebar, pestañas, header) con notificaciones FALSAS inyectadas en
memoria — solo el módulo `notificaciones` queda intervenido.

Sirve para:
  · Ver cómo se ve la card compacta con el badge "Notificaciones (N)"
    cuando N es grande, DENTRO del layout real de Inicio (con
    calendario, KPIs, críticos, etc).
  · Verificar que la card conserva su tamaño natural aun con muchas
    filas — deben aparecer como scroll interno, no empujar el layout.
  · Ver el botón expandir habilitado; abrir el modal grande; probar
    los 3 filtros del dropdown; verificar el overlay oscuro y cierre
    por clic fuera.
  · Verificar que el modal se redimensiona bien al maximizar/minimizar
    la ventana principal.

NO modifica la base de datos ni ningún archivo del proyecto. Todo el
resto del programa va con datos REALES de tu BD — solo la lista de
notificaciones está intervenida.

IMPORTANTE — no hagas clic en las filas fake:
  Los mantenimiento_id son inventados (99001, 99002, …). Si haces
  clic en una fila de "responsable_pendiente", se abrirá
  ListaResponsablesDialog contra un ID que no existe y no persistirá.
  Esta es una prueba visual únicamente.

Para cerrar la prueba: cierra la ventana. Nada persiste.
"""
import sys
import os
import runpy

# ────────────────────────────────────────────────────────────
#  Aseguramos que Python encuentra los módulos del proyecto
# ────────────────────────────────────────────────────────────
# El script debe vivir en la misma carpeta que main.py e inicio.py.
_este_dir = os.path.dirname(os.path.abspath(__file__))
if _este_dir not in sys.path:
    sys.path.insert(0, _este_dir)


# ────────────────────────────────────────────────────────────
#  Generador de notificaciones falsas
# ────────────────────────────────────────────────────────────
def _generar_notifs_fake(n_responsable: int = 25,
                         incluir_exito: bool = True,
                         incluir_fallo: bool = True):
    """Devuelve una lista mezclada de notifs con la MISMA estructura
    de dict que usan los archivos reales del paquete notificaciones/.
    Los mantenimiento_id arrancan en 99000 para no colisionar con IDs
    reales de la BD."""
    edificios = [
        "UPAEP › Edificio K",
        "UPAEP › Edificio Central",
        "Grupo Modelo › Planta 1",
        "Volkswagen › Nave A",
        "Puebla Corp › Torre Ejecutiva",
    ]
    tipos_mantto = ["Preventivo recurrente", "Preventivo anual",
                    "Correctivo programado"]

    fake = []

    # Responsables pendientes (la mayoría)
    for i in range(1, n_responsable + 1):
        dia = 5 + (i % 25)  # días distribuidos a lo largo del mes
        hora = 8 + (i % 4) * 2
        fake.append({
            "tipo": "responsable_pendiente",
            "mantenimiento_id": 99000 + i,
            "equipo_resumen": f"TAB{i:03d}" if i % 3 else f"{i % 5 + 2} equipos",
            "grupo_ruta": edificios[i % len(edificios)],
            "tipo_mantto": tipos_mantto[i % len(tipos_mantto)],
            "fecha_orden": f"2026-07-{dia:02d} {hora:02d}:00",
            "fecha_display": f"{dia}/jul {hora}:00",
            "accion_tipo": "asignar_responsable",
        })

    # Archivado éxito
    if incluir_exito:
        fake.append({
            "tipo": "archivado_exito",
            "mantenimiento_id": None,
            "equipo_resumen": "245 mantenimientos",
            "grupo_ruta": "",
            "tipo_mantto": "Archivado histórico",
            "fecha_orden": "2026-01-01 00:00",
            "fecha_display": "Año(s) 2022",
            "accion_tipo": "marcar_archivado_exito_leido",
        })

    # Archivado fallo
    if incluir_fallo:
        fake.append({
            "tipo": "archivado_fallo",
            "mantenimiento_id": None,
            "equipo_resumen": "Migración pendiente",
            "grupo_ruta": "",
            "tipo_mantto": "Archivado histórico",
            "fecha_orden": "2026-01-01 00:01",
            "fecha_display": "Ver detalles",
            "accion_tipo": "reintentar_archivado",
        })

    # Ordenar como lo hace notificaciones.py (por fecha_orden asc)
    fake.sort(key=lambda n: n.get("fecha_orden", ""))
    return fake


# ────────────────────────────────────────────────────────────
#  Monkey-patch: aplicar ANTES de importar inicio o main
# ────────────────────────────────────────────────────────────
# Importamos SOLO el paquete `notificaciones` (no `inicio`, no `main`).
# Sustituimos la función pública. Cuando después main.py importe
# inicio.py y éste haga `from notificaciones import
# obtener_notificaciones_activas`, Python copia la referencia YA
# sustituida — no hay que patchear inicio.py.
import notificaciones as _notif_pkg

def _fake_activas():
    return _generar_notifs_fake(
        n_responsable=25,
        incluir_exito=True,
        incluir_fallo=True,
    )

_notif_pkg.obtener_notificaciones_activas = _fake_activas


# ────────────────────────────────────────────────────────────
#  Banner informativo
# ────────────────────────────────────────────────────────────
print("=" * 60)
print("PRUEBA DEL MODAL DE NOTIFICACIONES — dentro de main.py")
print("=" * 60)
print("Notificaciones inyectadas: 27")
print("  · 25 de tipo 'responsable_pendiente'")
print("  ·  1 de tipo 'archivado_exito'")
print("  ·  1 de tipo 'archivado_fallo'")
print()
print("Qué probar:")
print("  1. Ve a la pestaña Inicio — la card de Notificaciones debe")
print("     conservar su tamaño y mostrar scroll INTERNO con las 27.")
print("  2. El calendario a la izquierda debe verse normal, sin")
print("     aplastarse.")
print("  3. Clic en el botón expandir -> overlay oscuro + modal grande.")
print("  4. En el modal, probar el dropdown de filtro:")
print("       - Todas                    -> 27 filas")
print("       - Responsables pendientes  -> 25 filas")
print("       - Archivado                ->  2 filas")
print("  5. Clic sobre el overlay (fuera del modal) -> cierra.")
print("  6. Maximizar la ventana con el modal abierto - el overlay se")
print("     ajusta.")
print()
print("Cerrar la ventana principal para terminar la prueba.")
print("=" * 60)


# ────────────────────────────────────────────────────────────
#  Lanzar main.py como si fuera el punto de entrada normal
# ────────────────────────────────────────────────────────────
# runpy.run_path ejecuta el archivo con run_name="__main__" — se
# comporta idéntico a `python main.py`, pero conservando el
# monkey-patch que aplicamos arriba. main.py crea su QApplication,
# muestra el splash de archivado (si aplica) y levanta la ventana
# principal completa con sidebar, header y pestañas.
runpy.run_path(os.path.join(_este_dir, "main.py"), run_name="__main__")
