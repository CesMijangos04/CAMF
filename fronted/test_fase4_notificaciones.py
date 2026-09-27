"""
test_fase4_notificaciones.py — Simulador de flags para probar Turno 2B.1

Ejecuta este archivo desde la carpeta del proyecto:

    python test_fase4_notificaciones.py

Menú interactivo que te permite:
  1. Simular notificación de éxito (245 mantenimientos, año 2022).
  2. Simular notificación de fallo (con mensaje de error de ejemplo).
  3. Limpiar TODOS los flags de archivado (dejar limpio).
  4. Ver el estado actual de los flags.

Después de setear un flag, ABRE CAMF, ve al Inicio, y observa la
notificación en la card correspondiente. Interactúa con ella:

  - Éxito: clic en "Marcar leído" → la notificación desaparece.
  - Fallo: clic en la notificación → abre el diálogo con el error →
    presiona "Reintentar" → como no hay años elegibles con umbral 5,
    el reintento retorna éxito trivial y la notificación desaparece.

Cuando termines de probar, usa la opción 3 para limpiar todo.
"""
from db_manager import metadata_get, metadata_set, metadata_delete


CLAVES_ARCHIVADO = [
    "notif_archivo_exito_cantidad",
    "notif_archivo_exito_anio",
    "notif_archivo_fallo_msg",
    "ultima_migracion_archivo",  # sin esto, hay_migracion_pendiente() cree
                                  # que ya se corrió este año y el splash no
                                  # aparece aunque haya años elegibles.
]

MENSAJE_FALLO_EJEMPLO = (
    "Error durante la migración: "
    "sqlite3.OperationalError: database is locked. "
    "Otra instancia de CAMF puede tener la base abierta. "
    "Cierra todas las instancias y reintenta."
)


def simular_exito():
    metadata_set("notif_archivo_exito_cantidad", "245")
    metadata_set("notif_archivo_exito_anio", "2022")
    print("\n✓ Flag de éxito seteado. Abre CAMF → Inicio para verlo.")
    print("  Deberías ver una notificación azul con ícono de archivo.")
    print("  Al hacer clic en 'Marcar leído', debería desaparecer.\n")


def simular_fallo():
    metadata_set("notif_archivo_fallo_msg", MENSAJE_FALLO_EJEMPLO)
    print("\n✓ Flag de fallo seteado. Abre CAMF → Inicio para verlo.")
    print("  Deberías ver una notificación roja con triángulo de exclamación.")
    print("  Al hacer clic, se abre el diálogo con el error y botón Reintentar.")
    print("  Como no hay años elegibles con umbral 5, el reintento va a")
    print("  retornar éxito trivial y la notificación va a desaparecer.\n")


def limpiar():
    for k in CLAVES_ARCHIVADO:
        metadata_delete(k)
    print("\n✓ Todos los flags de archivado limpiados.\n")


def ver_estado():
    print("\nEstado actual de los flags de archivado:")
    for k in CLAVES_ARCHIVADO:
        v = metadata_get(k)
        estado = f"'{v}'" if v else "(no seteado)"
        print(f"  {k}: {estado}")
    print()


def main():
    print("╔" + "═" * 66 + "╗")
    print("║  Simulador de notificaciones — Turno 2B.1 (Fase 4)            ║")
    print("╚" + "═" * 66 + "╝")

    while True:
        print("Opciones:")
        print("  1) Simular notificación de éxito")
        print("  2) Simular notificación de fallo")
        print("  3) Limpiar TODOS los flags de archivado")
        print("  4) Ver estado actual")
        print("  5) Salir")

        opcion = input("\n  Elige: ").strip()
        if opcion == "1":
            simular_exito()
        elif opcion == "2":
            simular_fallo()
        elif opcion == "3":
            limpiar()
        elif opcion == "4":
            ver_estado()
        elif opcion == "5":
            print("\n  Hasta luego.\n")
            break
        else:
            print("\n  Opción no válida.\n")


if __name__ == "__main__":
    main()
