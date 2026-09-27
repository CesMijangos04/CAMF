import os
import shutil
import sqlite3
import calendar
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

DB_NAME = "memoria.db"

def get_db_path() -> str:
    """Ruta donde guardaremos la DB local (AppData\\Local\\CAMF\\memoria.db en Windows)."""
    base_dir = os.path.join(os.getenv('LOCALAPPDATA', os.getcwd()), "CAMF")
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, DB_NAME)

def db_exists() -> bool:
    path = get_db_path()
    return os.path.exists(path)

def create_database():
    """Crea el archivo de DB y las tablas base inmediatamente.

    Retorna True solo si el archivo .db se creó ahora (primera vez).
    Retorna False si ya existía.

    En AMBOS casos ejecuta crear_tablas() para asegurar que el esquema
    esté al día. crear_tablas() usa `CREATE TABLE IF NOT EXISTS` en cada
    definición, así que es idempotente y seguro llamarlo en cada arranque
    de CAMF. Esto permite agregar tablas nuevas al esquema (ej. Fase 4:
    metadata_sistema, mantenimientos_archivo) sin romper BDs existentes.
    """
    db_path = get_db_path()
    created = not os.path.exists(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    crear_tablas(cursor)
    conn.commit()
    conn.close()

    return created

def crear_tablas(cursor):
    """Crea todas las tablas si no existen. Diseñada para arrancar limpio."""
 
    # ── Grupos (árbol ilimitado con padre_id) ──────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grupos (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre    TEXT    NOT NULL,
            padre_id  INTEGER REFERENCES grupos(id) ON DELETE SET NULL,
            creado_en TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── Tableros ───────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tableros (
            id                TEXT PRIMARY KEY,
            nombre            TEXT,
            ubicacion         TEXT NOT NULL,
            corriente_nominal TEXT,
            tension           TEXT,
            tipo              TEXT,
            num_circuitos     INTEGER,
            marca             TEXT,
            fecha_instalacion TEXT,
            comentarios       TEXT,
            grupo_id          INTEGER REFERENCES grupos(id) ON DELETE SET NULL
        )
    """)

    # ── Transformadores ────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transformadores (
            id          TEXT PRIMARY KEY,
            ubicacion   TEXT,
            capacidad   TEXT,
            tension     TEXT,
            fecha       TEXT,
            marca       TEXT,
            enfriamiento TEXT,
            fases       TEXT,
            conexion    TEXT,
            tipo        TEXT,
            grupo_id    INTEGER REFERENCES grupos(id) ON DELETE SET NULL,
            tablero_alimentado_id TEXT REFERENCES tableros(id) ON DELETE SET NULL
        )
    """)

    # ── Circuitos ──────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS circuitos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tablero_id      TEXT NOT NULL REFERENCES tableros(id) ON DELETE CASCADE,
            espacio_inicio  INTEGER NOT NULL,
            polos           INTEGER NOT NULL,
 
            tipo_carga      TEXT NOT NULL,
              -- 'carga' | 'tablero' | 'motor' | 'elevador'
              -- | 'aa' | 'bomba_incendio' | 'transformador' | 'libre'
 
            nombre          TEXT,
            descripcion     TEXT,
 
            -- Protección
            amperaje_a       REAL,
            capacidad_int_ka REAL,
 
            -- Conductores
            calibre_fase    TEXT,
            calibre_neutro  TEXT,
            calibre_tierra  TEXT,
            num_fase        INTEGER,
            material        TEXT DEFAULT 'cobre',
            aislamiento     TEXT,
            tuberia_mm      REAL,
            longitud_m      REAL,
            caida_pct       REAL,
 
            -- Eléctricos
            fase_asignada   TEXT,
            carga_w         REAL,
            factor_potencia REAL,
            factor_demanda  REAL,
            tension_v       REAL,
            corriente_a     REAL,
 
            -- Relación con hijos
            tablero_hijo_id        TEXT REFERENCES tableros(id) ON DELETE SET NULL,
            transformador_hijo_id  TEXT REFERENCES transformadores(id) ON DELETE SET NULL,
 
            -- Datos específicos por tipo (HP, arranque, etc.) en JSON
            datos_especificos TEXT,
 
            -- Metadata
            origen_datos    TEXT DEFAULT 'inventario',
            cumple_nom      INTEGER DEFAULT 1,
            observaciones   TEXT,
 
            UNIQUE(tablero_id, espacio_inicio)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_circuitos_tablero ON circuitos(tablero_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_circuitos_hijo ON circuitos(tablero_hijo_id)")

    # ── Personal ───────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS personal (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            id_personal TEXT UNIQUE,
            nombre     TEXT NOT NULL,
            ap_paterno TEXT NOT NULL,
            ap_materno TEXT NOT NULL,
            telefono   TEXT NOT NULL,
            correo     TEXT NOT NULL,
            puesto     TEXT NOT NULL
        )
    """)
 
    # ── Proveedores ────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS proveedores (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            id_proveedor TEXT UNIQUE,
            empresa      TEXT NOT NULL,
            telefono     TEXT NOT NULL,
            correo       TEXT NOT NULL,
            contactos_json TEXT
        )
    """)

    # ── Mantenimientos ─────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mantenimientos (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_mantenimiento   TEXT NOT NULL,
            urgente              INTEGER DEFAULT 0,
            fecha_inicio         TEXT NOT NULL,
            fecha_fin            TEXT NOT NULL,
            costo                INTEGER DEFAULT 0,
            costo_moneda         TEXT DEFAULT 'MXN',
            descripcion          TEXT NOT NULL,
            responsable_tipo     TEXT NOT NULL,
            responsable_id       TEXT NOT NULL,
            responsable_nombre   TEXT NOT NULL,
            responsable_correo   TEXT,
            responsable_telefono TEXT,
            estado               TEXT DEFAULT 'programado',
            motivo_cancelacion   TEXT,

            -- ================= CIERRE DEL MANTENIMIENTO =================
            -- Se llenan al ejecutar "Cerrar mantenimiento" desde la ficha:
            --   * Desde Pendiente cierre: PDF + retro + costo real, estado='finalizado'
            --   * Desde Cancelado:        solo motivo (en motivo_cancelacion), estado='cancelado'
            -- Si fecha_cierre IS NOT NULL, el mantenimiento vive en la pestaña Finalizados.
            fecha_cierre         TEXT,
            costo_real           INTEGER,
            costo_real_moneda    TEXT,
            retroalimentacion    TEXT,
            informe_pdf_path     TEXT,

            -- ================= GOOGLE CALENDAR =================
            google_event_id      TEXT,
            calendar_sync        INTEGER DEFAULT 0,
            calendar_last_error  TEXT,
            calendar_last_sync   TEXT,

            -- ================= RECURRENCIA =================
            -- Solo aplica a Preventivos. Al cerrar (Finalizado) un
            -- mantenimiento con es_recurrente=1, db_manager genera la siguiente
            -- instancia con +recurrencia_meses sobre fecha_inicio, conservando
            -- duración. El hijo nace con responsable placeholder
            -- ('pendiente'/'0'/'(por asignar)') y estado='programado'; la query
            -- de Programados lo filtra fuera hasta que se le asigne responsable.
            es_recurrente            INTEGER DEFAULT 0,
            recurrencia_meses        INTEGER,
            dias_aviso_responsable   INTEGER DEFAULT 7,
            mantenimiento_padre_id   INTEGER REFERENCES mantenimientos(id) ON DELETE SET NULL,
            serie_id                 INTEGER,

            creado_en            TEXT NOT NULL
        )
    """)

    # ── Mantenimientos ↔ Equipos (tabla puente N:M) ────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mantenimientos_equipos (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            mantenimiento_id  INTEGER NOT NULL REFERENCES mantenimientos(id) ON DELETE CASCADE,
            equipo_id         TEXT NOT NULL,
            equipo_tipo       TEXT NOT NULL  -- 'tableros' | 'transformadores'
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_me_mantenimiento ON mantenimientos_equipos(mantenimiento_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_me_equipo ON mantenimientos_equipos(equipo_id, equipo_tipo)")

    # ── Cambios al equipo registrados en el cierre ─────────────────────────
    # Log de auditoría de modificaciones que un mantenimiento aplicó a los
    # datos de inventario. Se llena cuando el ingeniero, al cerrar un
    # mantenimiento de tableros, edita algún campo de un circuito (calibre,
    # ITM, material, etc.). La tabla `circuitos` SÍ se sobreescribe con el
    # valor nuevo (el inventario refleja la realidad al día); esta tabla
    # guarda el "antes" para poder mostrarlo en la ficha del mantenimiento
    # cerrado y en los reportes de auditoría.
    #
    # Diseño: una fila por (mantenimiento_id, equipo_id, campo). Si en un
    # mismo cierre se cambian dos campos del mismo circuito, se generan dos
    # filas. Permite justificación distinta por campo y consulta granular
    # (ej. "todos los cambios de calibre_fase del año").
    #
    # `equipo_tipo` es genérico para admitir a futuro cambios en otros tipos
    # de equipo (transformadores, motores) sin migrar el schema. Hoy solo se
    # llena con 'circuitos'.
    #
    # `tablero_id` es información derivable (JOIN a circuitos), pero se
    # congela aquí en el momento del cambio para blindar la auditoría: si el
    # circuito luego se muda de tablero, el cambio sigue perteneciendo al
    # tablero original.
    #
    # `justificacion` es NOT NULL: la regla del producto es que todo cambio
    # debe venir con motivo. La UI lo hace obligatorio; este constraint es
    # el respaldo a nivel BD.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cambios_equipo (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            mantenimiento_id  INTEGER NOT NULL
                              REFERENCES mantenimientos(id) ON DELETE CASCADE,
            equipo_tipo       TEXT NOT NULL,        -- 'circuitos' (por ahora)
            equipo_id         TEXT NOT NULL,        -- id del circuito modificado
            tablero_id        TEXT,                 -- congelado al momento del cambio
            campo             TEXT NOT NULL,        -- 'calibre_fase', 'amperaje_a', etc.
            valor_anterior    TEXT,                 -- guardado como TEXT para universalizar
            valor_nuevo       TEXT NOT NULL,
            justificacion     TEXT NOT NULL,
            responsable       TEXT,                 -- nombre del responsable del mantenimiento
            creado_en         TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cambios_equipo_mant    ON cambios_equipo(mantenimiento_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cambios_equipo_tablero ON cambios_equipo(tablero_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cambios_equipo_equipo  ON cambios_equipo(equipo_tipo, equipo_id)")

    # ── Pruebas eléctricas del transformador registradas en el cierre ─────
    # Una fila por prueba capturada durante el cierre de un mantenimiento
    # sobre un transformador. `prueba_codigo` coincide con las constantes
    # de `evaluacion_transformador.py` (res_aisl_at_tierra, ttr_error_pct,
    # etc.), lo que permite consultar el histórico y re-evaluar contra
    # umbrales normativos actualizados sin migrar datos.
    #
    # `estado` = 'capturada' cuando el ingeniero registró un valor;
    # `estado` = 'no_ejecutada' si marcó la prueba como no realizada (valor
    # queda NULL, observacion recomendada como motivo).
    #
    # `veredicto` NO se guarda: se calcula on-demand en la vista finalizada
    # llamando al motor `evaluar_prueba(codigo, valor)`. Ventaja: si se
    # ajusta un umbral normativo, los registros históricos se re-evalúan
    # automáticamente sin migración.
    #
    # `transformador_id` es TEXT sin FK, por la misma razón que en
    # `cambios_equipo`: sobrevive al retiro/borrado del equipo, la
    # trazabilidad histórica permanece.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pruebas_transformador (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            mantenimiento_id  INTEGER NOT NULL
                              REFERENCES mantenimientos(id) ON DELETE CASCADE,
            transformador_id  TEXT NOT NULL,
            prueba_codigo     TEXT NOT NULL,     -- ver evaluacion_transformador.py
            valor             REAL,               -- NULL si estado='no_ejecutada'
            unidad            TEXT,               -- copiada del catálogo (histórica)
            estado            TEXT NOT NULL,      -- 'capturada' | 'no_ejecutada'
            observacion       TEXT,               -- nota o motivo (nullable)
            creado_en         TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pruebas_trafo_mant     ON pruebas_transformador(mantenimiento_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pruebas_trafo_trafo    ON pruebas_transformador(transformador_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pruebas_trafo_codigo   ON pruebas_transformador(prueba_codigo)")

    # ── Inspección física del transformador ───────────────────────────────
    # Puntos de inspección visual/mecánica que el ingeniero verifica en el
    # cierre: nivel de aceite, silica gel, bushings, tanque, radiadores,
    # aterrizaje, protecciones (Buchholz), apriete de conexiones, etc.
    #
    # `punto` es una clave estable (ej. 'nivel_aceite', 'silica_gel'). La
    # convención de códigos vive en el widget de captura para no acoplar
    # este schema a nombres UI.
    #
    # `estado` incluye 'no_revisado' explícito para diferenciar entre "el
    # ingeniero decidió no revisar" y "el ingeniero no ha llegado a este
    # punto todavía". Al guardar el cierre, los puntos vacíos NO generan
    # fila (misma regla que cambios_equipo: sin acción, sin registro).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inspeccion_transformador (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            mantenimiento_id  INTEGER NOT NULL
                              REFERENCES mantenimientos(id) ON DELETE CASCADE,
            transformador_id  TEXT NOT NULL,
            punto             TEXT NOT NULL,     -- 'nivel_aceite', 'silica_gel', ...
            estado            TEXT NOT NULL,     -- 'ok' | 'atencion' | 'falla' | 'na' | 'no_revisado'
            observacion       TEXT,
            creado_en         TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_insp_trafo_mant   ON inspeccion_transformador(mantenimiento_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_insp_trafo_trafo  ON inspeccion_transformador(transformador_id)")

    # ── Posición del cambiador de derivaciones (tap) ──────────────────────
    # Registra el estado del tap ANTES y DESPUÉS del mantenimiento. Se
    # inserta solo si el ingeniero capturó ambos valores. Si son distintos,
    # `justificacion` es obligatoria (regla de UI).
    #
    # El tap no vive en el inventario `transformadores` porque no es un
    # atributo del equipo — es un ajuste operativo que cambia entre
    # mantenimientos. Aquí queda su historial completo, útil para saber
    # cuándo alguien lo movió y por qué (auditoría UVIE).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posicion_tap_transformador (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            mantenimiento_id  INTEGER NOT NULL
                              REFERENCES mantenimientos(id) ON DELETE CASCADE,
            transformador_id  TEXT NOT NULL,
            posicion_antes    INTEGER NOT NULL,
            posicion_despues  INTEGER NOT NULL,
            justificacion     TEXT,               -- obligatoria si antes != despues
            creado_en         TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tap_mant   ON posicion_tap_transformador(mantenimiento_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tap_trafo  ON posicion_tap_transformador(transformador_id)")

    # ── Reportes / Plantillas ──────────────────────────────────────────────
    # Una empresa típica tiene UNA plantilla (su logo + datos). El esquema
    # admite varias para soportar perfiles distintos en el futuro (ej.
    # 'UVIE oficial' vs 'Cliente interno' vs 'Borrador').
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reportes_plantillas (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre             TEXT NOT NULL,
            es_predeterminada  INTEGER DEFAULT 0,

            -- Encabezado / Empresa
            logo_path          TEXT,
            empresa_nombre     TEXT,
            empresa_subtitulo  TEXT,
            empresa_direccion  TEXT,
            empresa_telefono   TEXT,
            empresa_correo     TEXT,
            empresa_rfc        TEXT,

            -- Pie de página
            pie_texto          TEXT,
            mostrar_paginacion INTEGER DEFAULT 1,

            -- Diseño
            color_principal    TEXT DEFAULT '#0078d7',
            color_secundario   TEXT DEFAULT '#666666',
            tamano_letra       INTEGER DEFAULT 10,
            orientacion        TEXT DEFAULT 'vertical',  -- 'vertical' | 'horizontal'
            tamano_pagina      TEXT DEFAULT 'A4',        -- 'A4' | 'Carta'

            creado_en          TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_plantillas_pred "
        "ON reportes_plantillas(es_predeterminada)"
    )

    # ── Reportes / Firmas y responsables ───────────────────────────────────
    # Catálogo de personas que pueden firmar un reporte. El rol indica EN
    # CALIDAD DE QUÉ firma (responsable técnico / supervisor / cliente /
    # UVIE / perito). Una misma persona puede tener varios roles (se crea
    # una fila por rol). La firma se almacena como ruta a un PNG con fondo
    # transparente; se copia a %LOCALAPPDATA%/CAMF/plantillas/firmas/.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reportes_firmas (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            rol               TEXT NOT NULL,   -- 'responsable_tecnico'|'supervisor'|'cliente'|'uvie'|'perito'
            persona_nombre    TEXT NOT NULL,
            persona_puesto    TEXT,
            persona_cedula    TEXT,            -- útil para UVIE / Perito
            firma_imagen_path TEXT,
            es_predeterminada INTEGER DEFAULT 0,
            creado_en         TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_firmas_rol "
        "ON reportes_firmas(rol, es_predeterminada)"
    )

    # ── Reportes / Configuración de folios ─────────────────────────────────
    # Un patrón por categoría (operativos, tecnicos, ingenieria, uvie,
    # gestion, inventario). El patrón soporta tokens: {YYYY} {MM} {####}.
    # 'siguiente_numero' se incrementa atómicamente al emitir un reporte.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reportes_folios_config (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria        TEXT NOT NULL UNIQUE,
            patron           TEXT NOT NULL,
            siguiente_numero INTEGER DEFAULT 1,
            anio_actual      INTEGER,   -- para resetear contador si patrón usa {YYYY}
            reset_anual      INTEGER DEFAULT 1
        )
    """)

    # ── Licencia ───────────────────────────────────────────────────────────
    # Singleton: una sola fila con id=1. El CHECK lo garantiza.
    # En desarrollo, la app fuerza 'completa' vía obtener_tier_actual().
    # Cuando se implemente el módulo real de licencias, esta tabla
    # almacena la clave de activación y el último timestamp validado
    # contra el backend.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS licencia (
            id                    INTEGER PRIMARY KEY CHECK (id = 1),
            tier                  TEXT DEFAULT 'completa',
                  -- 'basica' | 'profesional' | 'diseno' | 'completa'
            clave_activacion      TEXT,
            fecha_activacion      TEXT,
            fecha_expiracion      TEXT,   -- NULL = perpetua
            ultima_validacion     TEXT,
            licencia_dispositivo  TEXT
        )
    """)

    # ── Reportes / Bitácora de emitidos ────────────────────────────────────
    # Una fila por reporte generado. Sirve para:
    #   1) Historial visible al usuario (regenerar, reimprimir).
    #   2) Auditoría — quién emitió qué, cuándo, con qué parámetros (crítico
    #      para reportes UVIE: folio único e irrepetible).
    # mantenimiento_id se conserva por compatibilidad con uso histórico.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reportes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Categorización
            categoria        TEXT,        -- 'operativos'|'tecnicos'|'ingenieria'|'uvie'|'gestion'|'inventario'
            tipo_reporte     TEXT,        -- identificador del subtipo, ej. 'historial_equipo'

            -- Emisión
            folio            TEXT,
            fecha            TEXT,        -- ISO timestamp de emisión
            usuario_emisor   TEXT,
            formato          TEXT DEFAULT 'pdf',   -- 'pdf'|'excel'|'word'

            -- Plantilla con la que se generó
            plantilla_id     INTEGER REFERENCES reportes_plantillas(id) ON DELETE SET NULL,

            -- Filtros / parámetros usados (rango de fechas, equipo, etc.)
            parametros_json  TEXT,

            -- Archivo generado
            archivo_ruta     TEXT,        -- ruta genérica para cualquier formato

            -- Compatibilidad con esquema previo (no se usa en el módulo nuevo)
            mantenimiento_id INTEGER,
            archivo_pdf      TEXT,        -- DEPRECATED: usar archivo_ruta
            observaciones    TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reportes_categoria ON reportes(categoria)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reportes_fecha     ON reportes(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reportes_folio     ON reportes(folio)")

    # ══════════════════════════════════════════════════════════════════════
    #  FASE 4 — ARCHIVO HISTÓRICO Y METADATA DEL SISTEMA
    # ══════════════════════════════════════════════════════════════════════

    # ── Metadata del sistema ───────────────────────────────────────────────
    # Tabla clave-valor para estado global de la aplicación que no puede
    # derivarse de las tablas de negocio. Ejemplos:
    #   - ultima_migracion_archivo   → año en que corrió la última migración
    #   - notif_archivo_YYYY_leida   → flag de notificación de éxito leída
    #   - notif_archivo_fallo_activo → hay un fallo pendiente de reintento
    #   - notif_archivo_fallo_msg    → mensaje técnico del último fallo
    # Patrón estándar de settings de aplicación; extensible sin migraciones.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata_sistema (
            clave       TEXT PRIMARY KEY,
            valor       TEXT,
            actualizado TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Mantenimientos archivados (bodega histórica) ───────────────────────
    # Estructura IDÉNTICA a la tabla `mantenimientos`. Aloja los cierres de
    # años que ya cumplieron el criterio de archivo (5 años cerrados
    # completos por defecto). Los datos se MUEVEN aquí (no se copian):
    # después de una migración exitosa, el row desaparece de
    # `mantenimientos` y aparece aquí.
    #
    # Diseño: tabla separada en vez de flag `archivado` en la tabla actual.
    # Razón: las queries de operación (Programados, Finalizados año en
    # curso) jamás tocan estos datos, ni para descartarlos. El motor SQL
    # nunca los ve. Esto mantiene la BD operativa liviana aunque el archivo
    # crezca a decenas de miles de rows.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mantenimientos_archivo (
            id                   INTEGER PRIMARY KEY,
            tipo_mantenimiento   TEXT NOT NULL,
            urgente              INTEGER DEFAULT 0,
            fecha_inicio         TEXT NOT NULL,
            fecha_fin            TEXT NOT NULL,
            costo                INTEGER DEFAULT 0,
            costo_moneda         TEXT DEFAULT 'MXN',
            descripcion          TEXT NOT NULL,
            responsable_tipo     TEXT NOT NULL,
            responsable_id       TEXT NOT NULL,
            responsable_nombre   TEXT NOT NULL,
            responsable_correo   TEXT,
            responsable_telefono TEXT,
            estado               TEXT DEFAULT 'programado',
            motivo_cancelacion   TEXT,
            fecha_cierre         TEXT,
            costo_real           INTEGER,
            costo_real_moneda    TEXT,
            retroalimentacion    TEXT,
            informe_pdf_path     TEXT,
            google_event_id      TEXT,
            calendar_sync        INTEGER DEFAULT 0,
            calendar_last_error  TEXT,
            calendar_last_sync   TEXT,
            es_recurrente            INTEGER DEFAULT 0,
            recurrencia_meses        INTEGER,
            dias_aviso_responsable   INTEGER DEFAULT 7,
            mantenimiento_padre_id   INTEGER,
            serie_id                 INTEGER,
            creado_en            TEXT NOT NULL,
            -- Metadata del archivado (solo en esta tabla):
            archivado_en         TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Índice para las consultas típicas del archivo: filtrar por año.
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_mant_archivo_anio
        ON mantenimientos_archivo (fecha_cierre)
    """)

    # ── Tabla puente archivada (mantenimiento ↔ equipos) ───────────────────
    # Espejo de `mantenimientos_equipos`. Los rows se mueven aquí junto
    # con su mantenimiento padre durante la migración anual. Sin esto,
    # los equipos de un mantenimiento archivado quedarían huérfanos
    # (o mezclados con los actuales) y romperían el aislamiento.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mantenimientos_equipos_archivo (
            id                INTEGER PRIMARY KEY,
            mantenimiento_id  INTEGER NOT NULL,
            equipo_id         TEXT NOT NULL,
            equipo_tipo       TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_me_archivo_mantenimiento
        ON mantenimientos_equipos_archivo (mantenimiento_id)
    """)

    # ── Cambios al equipo archivados (espejo de cambios_equipo) ────────────
    # Espejo de `cambios_equipo` para la Fase 4 del archivo histórico. Los
    # cambios registrados por un mantenimiento viajan junto con éste cuando
    # se archiva: no es información que se pueda perder porque es justo la
    # traza de auditoría (qué se cambió, cuándo, quién y por qué).
    #
    # Sin este espejo, la ficha de un mantenimiento archivado abriría con
    # la sección "CAMBIOS AL EQUIPO" vacía aunque sí hubiera habido cambios
    # el día que se cerró — se perdería la auditoría.
    #
    # NOTA: la lógica de MOVE (INSERT ... SELECT + DELETE) queda pendiente
    # de agregar en `migracion_archivo.py` cuando UMBRAL_ANIOS_ARCHIVO deje
    # de ser -1. Mientras tanto la tabla existe pero está vacía; se llenará
    # en la primera migración anual una vez habilitada.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cambios_equipo_archivo (
            id                INTEGER PRIMARY KEY,
            mantenimiento_id  INTEGER NOT NULL,
            equipo_tipo       TEXT NOT NULL,
            equipo_id         TEXT NOT NULL,
            tablero_id        TEXT,
            campo             TEXT NOT NULL,
            valor_anterior    TEXT,
            valor_nuevo       TEXT NOT NULL,
            justificacion     TEXT NOT NULL,
            responsable       TEXT,
            creado_en         TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cambios_equipo_archivo_mant
        ON cambios_equipo_archivo (mantenimiento_id)
    """)

    # ── Espejos de archivo: pruebas, inspección y tap del transformador ──
    # Mismo patrón que cambios_equipo_archivo: cuando un mantenimiento
    # migra a `mantenimientos_archivo` (Fase 4), sus registros asociados
    # de pruebas, inspección y posición de tap viajan aquí. Sin este
    # espejo, la ficha del mantenimiento archivado abriría con las
    # secciones vacías aunque sí hubiera datos en el momento del cierre.
    #
    # NOTA: la lógica de MOVE queda pendiente en `migracion_archivo.py`
    # para agregarla cuando UMBRAL_ANIOS_ARCHIVO deje de ser -1. Por
    # ahora las tablas existen pero permanecen vacías; se llenarán en
    # la primera migración anual una vez habilitada.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pruebas_transformador_archivo (
            id                INTEGER PRIMARY KEY,
            mantenimiento_id  INTEGER NOT NULL,
            transformador_id  TEXT NOT NULL,
            prueba_codigo     TEXT NOT NULL,
            valor             REAL,
            unidad            TEXT,
            estado            TEXT NOT NULL,
            observacion       TEXT,
            creado_en         TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pruebas_trafo_archivo_mant
        ON pruebas_transformador_archivo (mantenimiento_id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inspeccion_transformador_archivo (
            id                INTEGER PRIMARY KEY,
            mantenimiento_id  INTEGER NOT NULL,
            transformador_id  TEXT NOT NULL,
            punto             TEXT NOT NULL,
            estado            TEXT NOT NULL,
            observacion       TEXT,
            creado_en         TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_insp_trafo_archivo_mant
        ON inspeccion_transformador_archivo (mantenimiento_id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posicion_tap_transformador_archivo (
            id                INTEGER PRIMARY KEY,
            mantenimiento_id  INTEGER NOT NULL,
            transformador_id  TEXT NOT NULL,
            posicion_antes    INTEGER NOT NULL,
            posicion_despues  INTEGER NOT NULL,
            justificacion     TEXT,
            creado_en         TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tap_archivo_mant
        ON posicion_tap_transformador_archivo (mantenimiento_id)
    """)

    # Seed inicial de reportes (plantilla, folios, licencia). La función
    # está definida en el bloque de migración temporal — es la misma que
    # se usa para BDs preexistentes. Idempotente: si ya hay datos, no
    # hace nada. Esto garantiza que una BD recién creada arranca con la
    # plantilla y los folios listos para usarse desde el primer click.
    _sembrar_reportes_si_vacios(cursor)
 
def connect_db(create_if_missing: bool = False) -> Optional[sqlite3.Connection]:
    db_path = get_db_path()
    exists = os.path.exists(db_path)
    print(f"[DB DEBUG] connect_db -> path: {db_path} ; exists={exists}")
    if not exists:
        if create_if_missing:
            create_database()
        else:
            return None
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
 
 
# ══════════════════════════════════════════════════════════════
#  FUNCIONES GENÉRICAS
# ══════════════════════════════════════════════════════════════
 
def insertar_datos(tabla: str, datos: Dict[str, Any]) -> int:
    conn = connect_db(create_if_missing=True)
    cursor = conn.cursor()
    columnas = ", ".join(datos.keys())
    placeholders = ", ".join(["?"] * len(datos))
    valores = tuple(datos.values())
    cursor.execute(f"INSERT INTO {tabla} ({columnas}) VALUES ({placeholders})", valores)
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id
 
def obtener_datos(tabla: str) -> List[Tuple]:
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return []
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {tabla}")
        rows = cursor.fetchall()
    except Exception as e:
        print(f"[DB] Error SELECT {tabla}: {e}")
        rows = []
    conn.close()
    return rows
 
def ejecutar_query(query: str, params: Tuple = ()) -> List[Tuple]:
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return []
    cur = conn.cursor()
    cur.execute(query, params)
    filas = cur.fetchall()
    conn.close()
    return filas


# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE MANTENIMIENTOS (acciones del footer de la ficha)
# ══════════════════════════════════════════════════════════════

def cancelar_mantenimiento(mant_id: int):
    """
    Marca el mantenimiento como cancelado.
    El motivo de cancelación NO se captura aquí: se pide más adelante,
    cuando el usuario cierra el mantenimiento ya cancelado desde la
    ficha (botón 'Cerrar mantenimiento' del estado Cancelado), y eso
    es lo que lo manda a la pestaña Finalizados.
    """
    conn = connect_db()
    if conn is None:
        return
    conn.execute(
        "UPDATE mantenimientos SET estado = 'cancelado' WHERE id = ?",
        (mant_id,)
    )
    conn.commit()
    conn.close()


def reprogramar_mantenimiento(mant_id: int, fecha_inicio: str, fecha_fin: str):
    """
    Actualiza las fechas y deja el mantenimiento en estado 'programado'.
    - Desde 'programado': edita las fechas.
    - Desde 'pendiente cierre' (estado_db='programado' con fecha vencida):
      extiende el trabajo.
    - Desde 'cancelado': resucita el mantenimiento. Limpia motivo_cancelacion
      para no arrastrar un motivo viejo que ya no aplica.
    """
    conn = connect_db()
    if conn is None:
        return
    conn.execute(
        "UPDATE mantenimientos "
        "SET fecha_inicio = ?, fecha_fin = ?, estado = 'programado', motivo_cancelacion = NULL "
        "WHERE id = ?",
        (fecha_inicio, fecha_fin, mant_id)
    )
    conn.commit()
    conn.close()
# ── Cierre de mantenimientos (PDF + helpers de UPDATE) ─────────────────

def carpeta_informes() -> str:
    """
    Devuelve la ruta absoluta de la carpeta donde se guardan los PDFs de
    informes (copias gestionadas, opción C). Por ahora vive junto a la BD,
    en %LOCALAPPDATA%/CAMF/informes/. La función centraliza la decisión
    para que si en el futuro queremos cambiar la ubicación (carpeta de red,
    carpeta configurable, etc.) modifiquemos solo aquí.

    NO crea la carpeta — solo devuelve la ruta. Quien necesite escribir
    en ella debe llamar a os.makedirs(..., exist_ok=True) primero (lo hace
    copiar_informe_pdf por dentro).
    """
    base_dir = os.path.join(os.getenv('LOCALAPPDATA', os.getcwd()), "CAMF")
    return os.path.join(base_dir, "informes")


def copiar_informe_pdf(mant_id: int, ruta_origen: str) -> str:
    """
    Copia el PDF seleccionado por el usuario a la carpeta gestionada por
    la app (opción C). El archivo original del usuario NO se mueve ni se
    toca: la app trabaja con la copia para que el usuario pueda borrar/
    mover su archivo sin romper nada.

    Nombre del archivo copiado: mantenimiento_<id>_<YYYYMMDDHHMMSS>.pdf
    (identificable, único, y ordenable por fecha de cierre).

    Devuelve la ruta absoluta del archivo copiado, que es lo que se debe
    guardar en la columna informe_pdf_path de la BD.
    """
    carpeta = carpeta_informes()
    os.makedirs(carpeta, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    nombre_destino = f"mantenimiento_{mant_id}_{timestamp}.pdf"
    ruta_destino = os.path.join(carpeta, nombre_destino)

    shutil.copy2(ruta_origen, ruta_destino)
    return ruta_destino


def _insertar_cambios_equipo_lote(cursor, mant_id: int, cambios: list) -> None:
    """
    Helper interno: inserta un lote de filas en `cambios_equipo` usando el
    cursor de una transacción externa. No hace commit ni close — quien lo
    invoque es responsable de la transacción.

    Diseñado para ser llamado desde `cerrar_mantenimiento_pendiente` de modo
    que los INSERT vivan en la misma transacción atómica que los UPDATE al
    inventario y al mantenimiento. Así, si algo falla, todo se revierte y
    no queda un mantenimiento "cerrado a medias" con historial roto.

    Cada elemento de `cambios` es un dict con las llaves:
        equipo_tipo    → 'circuitos' (por defecto)
        equipo_id      → id del registro modificado
        tablero_id     → id del tablero (opcional pero recomendado)
        campo          → nombre del campo modificado
        valor_anterior → valor previo (se guarda como string; None permitido)
        valor_nuevo    → valor nuevo (obligatorio)
        justificacion  → texto obligatorio
        responsable    → nombre del responsable del mantenimiento (opcional)
    """
    for c in cambios:
        cursor.execute("""
            INSERT INTO cambios_equipo
            (mantenimiento_id, equipo_tipo, equipo_id, tablero_id,
             campo, valor_anterior, valor_nuevo, justificacion, responsable)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mant_id,
            c.get("equipo_tipo", "circuitos"),
            str(c["equipo_id"]),
            c.get("tablero_id"),
            c["campo"],
            None if c.get("valor_anterior") is None else str(c["valor_anterior"]),
            str(c["valor_nuevo"]),
            c["justificacion"],
            c.get("responsable"),
        ))


def _insertar_pruebas_transformador_lote(cursor, mant_id: int,
                                         pruebas: list) -> None:
    """
    Helper interno: inserta un lote de filas en `pruebas_transformador`.
    Diseñado para vivir en la transacción de `cerrar_mantenimiento_pendiente`.

    Cada elemento de `pruebas` es un dict con:
        transformador_id → id del transformador (obligatorio)
        prueba_codigo    → código estable de la prueba
                           (ver evaluacion_transformador.PRUEBA_*)
        valor            → valor numérico capturado (None si no_ejecutada)
        unidad           → unidad de medida
        estado           → 'capturada' | 'no_ejecutada'
        observacion      → nota opcional (o motivo si no_ejecutada)
    """
    for p in pruebas:
        cursor.execute("""
            INSERT INTO pruebas_transformador
            (mantenimiento_id, transformador_id, prueba_codigo,
             valor, unidad, estado, observacion)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            mant_id,
            str(p["transformador_id"]),
            p["prueba_codigo"],
            p.get("valor"),
            p.get("unidad"),
            p.get("estado", "capturada"),
            p.get("observacion"),
        ))


def _insertar_inspeccion_transformador_lote(cursor, mant_id: int,
                                            inspecciones: list) -> None:
    """
    Helper interno: inserta un lote de filas en `inspeccion_transformador`.
    Diseñado para vivir en la transacción de `cerrar_mantenimiento_pendiente`.

    Cada elemento de `inspecciones` es un dict con:
        transformador_id → id del transformador (obligatorio)
        punto            → código del punto ('nivel_aceite', 'silica_gel'...)
        estado           → 'ok' | 'atencion' | 'falla' | 'na' | 'no_revisado'
        observacion      → nota opcional
    """
    for i in inspecciones:
        cursor.execute("""
            INSERT INTO inspeccion_transformador
            (mantenimiento_id, transformador_id, punto, estado, observacion)
            VALUES (?, ?, ?, ?, ?)
        """, (
            mant_id,
            str(i["transformador_id"]),
            i["punto"],
            i["estado"],
            i.get("observacion"),
        ))


def _insertar_posicion_tap_lote(cursor, mant_id: int, taps: list) -> None:
    """
    Helper interno: inserta un lote de filas en `posicion_tap_transformador`.
    Solo se inserta si el ingeniero capturó ambos valores (antes/después).

    Cada elemento de `taps` es un dict con:
        transformador_id → id del transformador (obligatorio)
        posicion_antes   → int
        posicion_despues → int
        justificacion    → obligatoria si antes != despues (validada en UI)
    """
    for t in taps:
        cursor.execute("""
            INSERT INTO posicion_tap_transformador
            (mantenimiento_id, transformador_id,
             posicion_antes, posicion_despues, justificacion)
            VALUES (?, ?, ?, ?, ?)
        """, (
            mant_id,
            str(t["transformador_id"]),
            int(t["posicion_antes"]),
            int(t["posicion_despues"]),
            t.get("justificacion"),
        ))


def cerrar_mantenimiento_pendiente(mant_id: int,
                                   retroalimentacion: str,
                                   informe_pdf_path: str,
                                   costo_real: Optional[int] = None,
                                   updates_circuitos: Optional[list] = None,
                                   cambios_equipo: Optional[list] = None,
                                   pruebas_transformador: Optional[list] = None,
                                   inspeccion_transformador: Optional[list] = None,
                                   posicion_tap: Optional[list] = None):
    """
    Cierra un mantenimiento que estaba en estado 'Pendiente cierre'
    (estado_db='programado' con fechas vencidas). Pasa estado='finalizado',
    llena fecha_cierre = ahora, retroalimentación, ruta del PDF y costo
    real con su moneda.

    Si costo_real es None (el usuario no lo capturó), se copia el costo
    estimado del propio mantenimiento al costo_real. Esto facilita queries
    futuras del módulo de reportes (siempre hay un costo_real con valor),
    a costa de no distinguir "no se capturó" vs "se confirmó igual al
    estimado" — para nuestro caso de uso esa distinción no aporta.

    La moneda del cierre siempre coincide con la del costo original
    (es la regla del producto: si se programó en MXN, se cierra en MXN).

    ── Cierre de tableros: cambios al inventario ──────────────────────────
    Cuando el ingeniero, al cerrar un mantenimiento de tableros, edita
    algún campo de un circuito (calibre, ITM, material, etc.), la UI pasa
    dos payloads opcionales:

      updates_circuitos: [
          {"circuito_id": 42, "campo": "calibre_fase", "valor_nuevo": "8 AWG"},
          {"circuito_id": 42, "campo": "amperaje_a",   "valor_nuevo": 30},
          ...
      ]
      cambios_equipo: [
          {"equipo_tipo": "circuitos", "equipo_id": "42", "tablero_id": "TAB001",
           "campo": "calibre_fase", "valor_anterior": "10 AWG", "valor_nuevo": "8 AWG",
           "justificacion": "Disparos frecuentes por sobrecarga...",
           "responsable": "Cesar Andrés Mijangos"},
          ...
      ]

    Ambos payloads se aplican en la MISMA transacción que el UPDATE del
    mantenimiento: primero se sobreescriben los circuitos (inventario al
    día), luego se registra el histórico en `cambios_equipo`, y por último
    se marca el mantenimiento como finalizado. Si cualquier paso falla,
    rollback total y el mantenimiento no queda "cerrado a medias".

    Los cierres de transformadores por ahora llaman a esta función sin los
    dos parámetros nuevos (comportamiento idéntico al original).
    """
    conn = connect_db()
    if conn is None:
        return

    try:
        cur = conn.cursor()

        # Si no se capturó costo_real, copiar costo estimado
        if costo_real is None:
            row = cur.execute(
                "SELECT costo FROM mantenimientos WHERE id = ?",
                (mant_id,)
            ).fetchone()
            costo_real = row[0] if row else 0

        # La moneda del cierre coincide con la moneda del costo original
        row = cur.execute(
            "SELECT costo_moneda FROM mantenimientos WHERE id = ?",
            (mant_id,)
        ).fetchone()
        moneda = (row[0] if row else 'MXN') or 'MXN'

        # ── Sustituir datos de inventario si el cierre trae cambios ────────
        # Se hace ANTES del INSERT en cambios_equipo para que si un UPDATE
        # falla (columna inválida, valor imposible), la BD no quede con
        # historial sin correspondencia. La lista de columnas permitidas
        # es un whitelist duro contra inyección: `campo` viene de la UI,
        # así que jamás se concatena crudo al SQL.
        if updates_circuitos:
            _CAMPOS_CIRCUITO_EDITABLES = {
                'calibre_fase', 'calibre_neutro', 'calibre_tierra',
                'material', 'aislamiento',
                'amperaje_a', 'capacidad_int_ka',
                'tuberia_mm', 'observaciones',
            }
            for upd in updates_circuitos:
                campo = upd["campo"]
                if campo not in _CAMPOS_CIRCUITO_EDITABLES:
                    raise ValueError(
                        f"Campo no editable desde cierre: {campo!r}. "
                        f"Permitidos: {sorted(_CAMPOS_CIRCUITO_EDITABLES)}"
                    )
                cur.execute(
                    f"UPDATE circuitos SET {campo} = ? WHERE id = ?",
                    (upd["valor_nuevo"], upd["circuito_id"])
                )

        # ── Registrar el histórico de cambios (tableros) ───────────────────
        if cambios_equipo:
            _insertar_cambios_equipo_lote(cur, mant_id, cambios_equipo)

        # ── Registrar pruebas del transformador ────────────────────────────
        if pruebas_transformador:
            _insertar_pruebas_transformador_lote(
                cur, mant_id, pruebas_transformador)

        # ── Registrar inspección física del transformador ──────────────────
        if inspeccion_transformador:
            _insertar_inspeccion_transformador_lote(
                cur, mant_id, inspeccion_transformador)

        # ── Registrar posición del tap ─────────────────────────────────────
        if posicion_tap:
            _insertar_posicion_tap_lote(cur, mant_id, posicion_tap)

        # ── UPDATE final del mantenimiento ─────────────────────────────────
        fecha_cierre = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur.execute("""
            UPDATE mantenimientos SET
                estado            = 'finalizado',
                fecha_cierre      = ?,
                retroalimentacion = ?,
                informe_pdf_path  = ?,
                costo_real        = ?,
                costo_real_moneda = ?
            WHERE id = ?
        """, (fecha_cierre, retroalimentacion, informe_pdf_path,
              costo_real, moneda, mant_id))

        conn.commit()

    except Exception:
        conn.rollback()
        conn.close()
        raise

    conn.close()

    # Si el mantenimiento era parte de una serie recurrente, intentar generar
    # la siguiente instancia. Se hace después del commit/close del padre para
    # no entrelazar transacciones. Cualquier error queda contenido aquí: el
    # cierre del padre ya está consolidado y no se revierte.
    try:
        generar_siguiente_recurrencia(mant_id)
    except Exception as e:
        print(f"[RECURRENCIA] Falla post-cierre del padre {mant_id}: {e}")


def obtener_cambios_equipo(mant_id: int) -> list:
    """
    Devuelve los cambios registrados en el cierre de un mantenimiento,
    listos para pintarse en la sección "CAMBIOS AL EQUIPO" de la ficha
    o para incluirse en reportes.

    Fallback a archivo histórico: si el mantenimiento ya se archivó (vive
    en `mantenimientos_archivo` en vez de `mantenimientos`), sus cambios
    también se buscan en `cambios_equipo_archivo`. El consumidor no tiene
    que saber si el mantenimiento está activo o archivado — misma llamada.

    Devuelve lista de dicts, uno por cambio, en orden de tablero → equipo
    → id (útil para agrupar en la UI). Lista vacía si no hubo cambios.
    """
    conn = connect_db()
    if conn is None:
        return []

    cur = conn.cursor()
    cur.execute("""
        SELECT id, equipo_tipo, equipo_id, tablero_id, campo,
               valor_anterior, valor_nuevo, justificacion, responsable, creado_en
        FROM cambios_equipo
        WHERE mantenimiento_id = ?
        ORDER BY tablero_id, equipo_id, id
    """, (mant_id,))
    filas = cur.fetchall()

    # Si no hay filas en la tabla activa, probar en el archivo histórico.
    # Un mantenimiento archivado nunca coexiste con datos en la tabla
    # activa (la migración los MUEVE), así que este fallback es correcto.
    if not filas:
        cur.execute("""
            SELECT id, equipo_tipo, equipo_id, tablero_id, campo,
                   valor_anterior, valor_nuevo, justificacion, responsable, creado_en
            FROM cambios_equipo_archivo
            WHERE mantenimiento_id = ?
            ORDER BY tablero_id, equipo_id, id
        """, (mant_id,))
        filas = cur.fetchall()

    cols = [d[0] for d in cur.description]
    resultado = [dict(zip(cols, row)) for row in filas]
    conn.close()
    return resultado


def obtener_pruebas_transformador(mant_id: int) -> list:
    """
    Devuelve las pruebas capturadas para un mantenimiento, listas para
    pintarse en la sección "PRUEBAS DEL TRANSFORMADOR" de la ficha
    finalizada (donde el motor `evaluar_prueba` se aplica on-demand para
    generar el veredicto normativo).

    Fallback a archivo histórico: si el mantenimiento está archivado, los
    datos se buscan en `pruebas_transformador_archivo`.

    Devuelve lista de dicts en orden estable (por prueba_codigo) para que
    el widget pinte las filas en el mismo orden que el catálogo.
    """
    conn = connect_db()
    if conn is None:
        return []

    cur = conn.cursor()
    cur.execute("""
        SELECT id, transformador_id, prueba_codigo, valor, unidad,
               estado, observacion, creado_en
        FROM pruebas_transformador
        WHERE mantenimiento_id = ?
        ORDER BY transformador_id, prueba_codigo, id
    """, (mant_id,))
    filas = cur.fetchall()

    if not filas:
        cur.execute("""
            SELECT id, transformador_id, prueba_codigo, valor, unidad,
                   estado, observacion, creado_en
            FROM pruebas_transformador_archivo
            WHERE mantenimiento_id = ?
            ORDER BY transformador_id, prueba_codigo, id
        """, (mant_id,))
        filas = cur.fetchall()

    cols = [d[0] for d in cur.description]
    resultado = [dict(zip(cols, row)) for row in filas]
    conn.close()
    return resultado


def obtener_inspeccion_transformador(mant_id: int) -> list:
    """
    Devuelve los puntos de inspección física capturados en el cierre.
    Fallback a `inspeccion_transformador_archivo` si el mantenimiento
    fue archivado.
    """
    conn = connect_db()
    if conn is None:
        return []

    cur = conn.cursor()
    cur.execute("""
        SELECT id, transformador_id, punto, estado, observacion, creado_en
        FROM inspeccion_transformador
        WHERE mantenimiento_id = ?
        ORDER BY transformador_id, punto, id
    """, (mant_id,))
    filas = cur.fetchall()

    if not filas:
        cur.execute("""
            SELECT id, transformador_id, punto, estado, observacion, creado_en
            FROM inspeccion_transformador_archivo
            WHERE mantenimiento_id = ?
            ORDER BY transformador_id, punto, id
        """, (mant_id,))
        filas = cur.fetchall()

    cols = [d[0] for d in cur.description]
    resultado = [dict(zip(cols, row)) for row in filas]
    conn.close()
    return resultado


def obtener_posicion_tap(mant_id: int) -> list:
    """
    Devuelve las posiciones de tap registradas en el cierre.
    Fallback a `posicion_tap_transformador_archivo` si aplicable.
    """
    conn = connect_db()
    if conn is None:
        return []

    cur = conn.cursor()
    cur.execute("""
        SELECT id, transformador_id, posicion_antes, posicion_despues,
               justificacion, creado_en
        FROM posicion_tap_transformador
        WHERE mantenimiento_id = ?
        ORDER BY transformador_id, id
    """, (mant_id,))
    filas = cur.fetchall()

    if not filas:
        cur.execute("""
            SELECT id, transformador_id, posicion_antes, posicion_despues,
                   justificacion, creado_en
            FROM posicion_tap_transformador_archivo
            WHERE mantenimiento_id = ?
            ORDER BY transformador_id, id
        """, (mant_id,))
        filas = cur.fetchall()

    cols = [d[0] for d in cur.description]
    resultado = [dict(zip(cols, row)) for row in filas]
    conn.close()
    return resultado


def cerrar_mantenimiento_cancelado(mant_id: int, motivo: str):
    """
    Cierra un mantenimiento que estaba en estado 'Cancelado'. NO cambia el
    estado_db (sigue 'cancelado'); solo llena motivo_cancelacion y
    fecha_cierre. El criterio para que aparezca en Finalizados es
    fecha_cierre IS NOT NULL, no el estado, así que con esto basta.

    Conservar estado='cancelado' nos permite distinguir en Finalizados
    entre los completados (estado='finalizado', color verde) y los
    cancelados-cerrados (estado='cancelado', color rojo).
    """
    conn = connect_db()
    if conn is None:
        return
    fecha_cierre = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE mantenimientos SET
            motivo_cancelacion = ?,
            fecha_cierre       = ?
        WHERE id = ?
    """, (motivo, fecha_cierre, mant_id))
    conn.commit()
    conn.close()
 
 
def asignar_responsable_mantenimiento(mant_id: int, datos: dict) -> bool:
    """
    Asigna o reemplaza el responsable de un mantenimiento existente.

    Pensado para el flujo "asignar responsable rápido desde Notificaciones":
    al hacer click en una notificación de tipo 'responsable_pendiente', se
    abre ListaResponsablesDialog y, al elegir, ese diálogo emite el dict
    con los campos {tipo, id, nombre, correo, telefono}. Esta función toma
    ese dict y persiste los 5 campos con un solo UPDATE.

    Acepta cualquier mantenimiento, no solo los recurrentes — útil también
    si en el futuro se quiere reasignar responsable desde otro contexto.

    Devuelve True si el UPDATE corrió, False si la BD no abrió o el dict
    estaba incompleto (sin 'tipo' o 'id', que son los obligatorios).
    """
    if not datos or not datos.get("tipo") or datos.get("id") in (None, ""):
        return False

    conn = connect_db()
    if conn is None:
        return False
    try:
        conn.execute("""
            UPDATE mantenimientos SET
                responsable_tipo     = ?,
                responsable_id       = ?,
                responsable_nombre   = ?,
                responsable_correo   = ?,
                responsable_telefono = ?
            WHERE id = ?
        """, (
            datos["tipo"],
            str(datos["id"]),
            datos.get("nombre") or "",
            datos.get("correo") or "",
            datos.get("telefono") or "",
            mant_id,
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"[RESPONSABLE] Error al asignar a mant_id={mant_id}: {e}")
        return False
    finally:
        conn.close()


def detener_serie_recurrente(mant_id: int) -> bool:
    """
    Detiene la serie recurrente marcando es_recurrente=0 en el evento
    indicado. Con esto, al cerrar el evento (Finalizado) NO se generará
    la siguiente instancia.

    No cambia estado, fechas ni ninguna otra cosa del evento — solo
    apaga la bandera de recurrencia. Se usa desde dos flujos:
      - Diálogo de cancelación → opción "Cancelar y detener toda la serie"
      - (Futuro) Cualquier otro punto donde queramos parar el ciclo
        sin cancelar el evento actual.

    Devuelve True si el UPDATE corrió, False si la BD no abrió.
    """
    conn = connect_db()
    if conn is None:
        return False
    try:
        conn.execute(
            "UPDATE mantenimientos SET es_recurrente = 0 WHERE id = ?",
            (mant_id,),
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[RECURRENCIA] Error al detener serie de mant_id={mant_id}: {e}")
        return False
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
#  RECURRENCIA DE MANTENIMIENTOS PREVENTIVOS
# ══════════════════════════════════════════════════════════════

def _sumar_meses(dt: datetime, meses: int) -> datetime:
    """
    Suma N meses a un datetime manejando bordes de fin de mes.
    Ej: 31/ene + 1 mes → 28/feb (o 29/feb en bisiesto). Conserva hora/min.
    """
    total_meses = dt.month - 1 + meses
    nuevo_anio = dt.year + total_meses // 12
    nuevo_mes = total_meses % 12 + 1
    ultimo_dia_mes = calendar.monthrange(nuevo_anio, nuevo_mes)[1]
    nuevo_dia = min(dt.day, ultimo_dia_mes)
    return dt.replace(year=nuevo_anio, month=nuevo_mes, day=nuevo_dia)


# Formato canónico de fechas en BD para mantenimientos. Coincide con cómo
# las guarda programar_nuevo.py al armar fecha_inicio / fecha_fin.
_FMT_FECHA_MANT = "%Y-%m-%d %H:%M"


def generar_siguiente_recurrencia(mant_id_padre: int) -> Optional[int]:
    """
    Genera la siguiente instancia de una serie recurrente.

    Se invoca al cerrar un mantenimiento Finalizado. Si el padre tiene
    es_recurrente=1 y un recurrencia_meses válido, clona el evento:
      - fechas: +N meses sobre fecha_inicio, conservando duración (fin-inicio)
      - hereda: tipo_mantenimiento, equipos (via tabla puente), costo estimado
        + moneda, descripción, recurrencia_meses, dias_aviso_responsable,
        serie_id
      - vacía: responsable_* → placeholders ('pendiente'/'0'/'(por asignar)')
      - resetea: urgente=0, costo_real/retroalimentacion/informe_pdf=NULL,
        fecha_cierre=NULL
      - enlaza: mantenimiento_padre_id apunta al padre que la generó

    El hijo nace con estado='programado'. La query de Programados lo filtra
    fuera mientras responsable_tipo='pendiente'. Al asignarle responsable
    real, aparece automáticamente.

    Devuelve el ID del hijo creado, o None si:
      - el padre no existe
      - el padre no tiene es_recurrente=1 (incluye el caso de "ciclo detenido")
      - falta recurrencia_meses o es <= 0

    No lanza excepciones para no romper el flujo de cierre del padre. Si
    algo falla internamente, loguea y devuelve None.
    """
    try:
        conn = connect_db()
        if conn is None:
            return None

        row = conn.execute("""
            SELECT
                tipo_mantenimiento,
                fecha_inicio, fecha_fin,
                costo, costo_moneda, descripcion,
                es_recurrente, recurrencia_meses, dias_aviso_responsable,
                serie_id
            FROM mantenimientos
            WHERE id = ?
        """, (mant_id_padre,)).fetchone()

        if row is None:
            conn.close()
            return None

        (tipo, fi, ff, costo, moneda, desc,
         es_rec, rec_meses, dias_aviso, serie_id_padre) = row

        # Sin recurrencia activa o sin período válido → no se genera nada.
        # Esto cubre el caso "ciclo detenido" (es_recurrente=0).
        # Nota: rec_meses == 0 es válido (sentinela de prueba, ver más abajo);
        # solo rechazamos NULL o valores negativos.
        if not es_rec or rec_meses is None or rec_meses < 0:
            conn.close()
            return None

        # Calcular nuevas fechas: +N meses sobre fecha_inicio, conservar duración.
        try:
            dt_inicio = datetime.strptime(fi, _FMT_FECHA_MANT)
            dt_fin    = datetime.strptime(ff, _FMT_FECHA_MANT)
        except ValueError as e:
            print(f"[RECURRENCIA] Formato de fecha inesperado en padre {mant_id_padre}: {e}")
            conn.close()
            return None

        duracion = dt_fin - dt_inicio
        # ──── TEMPORAL · PRUEBAS QA ─────────────────────────────────────────
        # recurrencia_meses == 0 es un sentinela que desplaza +1 día en vez
        # de +N meses. Sirve para validar el ciclo recurrente sin esperar
        # semanas. Quitar este bloque (y la opción "1 día (prueba)" en
        # programar_nuevo.py) antes de salir a producción.
        if int(rec_meses) == 0:
            nuevo_inicio = dt_inicio + timedelta(days=1)
        else:
            nuevo_inicio = _sumar_meses(dt_inicio, int(rec_meses))
        # ────────────────────────────────────────────────────────────────────
        nuevo_fin = nuevo_inicio + duracion

        # Si el padre es el primero de la serie, su serie_id puede ser NULL;
        # en ese caso, la serie queda anclada al ID del padre.
        serie_id_efectivo = serie_id_padre if serie_id_padre else mant_id_padre

        ahora_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dias_aviso_efectivo = dias_aviso if dias_aviso is not None else 7

        cursor = conn.execute("""
            INSERT INTO mantenimientos (
                tipo_mantenimiento, urgente,
                fecha_inicio, fecha_fin,
                costo, costo_moneda, descripcion,
                responsable_tipo, responsable_id, responsable_nombre,
                estado,
                es_recurrente, recurrencia_meses, dias_aviso_responsable,
                mantenimiento_padre_id, serie_id,
                creado_en
            ) VALUES (
                ?, 0,
                ?, ?,
                ?, ?, ?,
                'pendiente', '0', '(por asignar)',
                'programado',
                1, ?, ?,
                ?, ?,
                ?
            )
        """, (
            tipo,
            nuevo_inicio.strftime(_FMT_FECHA_MANT),
            nuevo_fin.strftime(_FMT_FECHA_MANT),
            costo, moneda, desc,
            int(rec_meses), int(dias_aviso_efectivo),
            mant_id_padre, serie_id_efectivo,
            ahora_iso,
        ))
        hijo_id = cursor.lastrowid

        # Si el padre era el primero (serie_id NULL en BD), anclamos la serie
        # a su propio ID retroactivamente. Esto deja el grafo limpio:
        # toda la serie comparte serie_id = id_del_primero.
        if serie_id_padre is None:
            conn.execute(
                "UPDATE mantenimientos SET serie_id = ? WHERE id = ?",
                (mant_id_padre, mant_id_padre)
            )

        # Heredar equipos del padre vía tabla puente.
        conn.execute("""
            INSERT INTO mantenimientos_equipos (mantenimiento_id, equipo_id, equipo_tipo)
            SELECT ?, equipo_id, equipo_tipo
            FROM mantenimientos_equipos
            WHERE mantenimiento_id = ?
        """, (hijo_id, mant_id_padre))

        conn.commit()
        conn.close()
        return hijo_id

    except Exception as e:
        print(f"[RECURRENCIA] Error generando siguiente instancia de mant_id={mant_id_padre}: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE GRUPOS
# ══════════════════════════════════════════════════════════════
 
def crear_grupo(nombre: str, padre_id: Optional[int] = None) -> int:
    """Crea un grupo y devuelve su id."""
    return insertar_datos("grupos", {"nombre": nombre, "padre_id": padre_id})
 
def obtener_grupos() -> List[Tuple]:
    """Devuelve todos los grupos: (id, nombre, padre_id, creado_en)."""
    return ejecutar_query("SELECT id, nombre, padre_id, creado_en FROM grupos ORDER BY nombre")
 
def renombrar_grupo(grupo_id: int, nuevo_nombre: str):
    conn = connect_db()
    if conn is None:
        return
    conn.execute("UPDATE grupos SET nombre = ? WHERE id = ?", (nuevo_nombre, grupo_id))
    conn.commit()
    conn.close()
 
def eliminar_grupo(grupo_id: int):
    """
    Elimina el grupo. Los equipos y subgrupos hijos quedan con grupo_id / padre_id = NULL
    (gracias al ON DELETE SET NULL definido en las FKs).
    """
    conn = connect_db()
    if conn is None:
        return
    conn.execute("DELETE FROM grupos WHERE id = ?", (grupo_id,))
    conn.commit()
    conn.close()
 
def asignar_grupo_equipo(tabla: str, equipo_id: str, grupo_id: Optional[int]):
    """Asigna o quita grupo a un tablero/transformador."""
    conn = connect_db()
    if conn is None:
        return
    conn.execute(f"UPDATE {tabla} SET grupo_id = ? WHERE id = ?", (grupo_id, equipo_id))
    conn.commit()
    conn.close()
 
def obtener_equipos_por_grupo(tabla: str, grupo_id: Optional[int]) -> List[Tuple]:
    """
    Devuelve equipos de una tabla que pertenezcan al grupo indicado.
    Si grupo_id es None, devuelve los que no tienen grupo asignado.
    """
    conn = connect_db()
    if conn is None:
        return []
    cur = conn.cursor()
    if grupo_id is None:
        cur.execute(f"SELECT * FROM {tabla} WHERE grupo_id IS NULL")
    else:
        cur.execute(f"SELECT * FROM {tabla} WHERE grupo_id = ?", (grupo_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def _grupo_tiene_equipos_en_tabla(tabla: str, grupo_id: int) -> bool:
    """Comprueba recursivamente si un grupo o algún subgrupo tiene equipos en tabla."""
    conn = connect_db()
    if conn is None:
        return False
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {tabla} WHERE grupo_id = ?", (grupo_id,))
    count = cur.fetchone()[0]
    conn.close()
    if count > 0:
        return True
    hijos = ejecutar_query("SELECT id FROM grupos WHERE padre_id = ?", (grupo_id,))
    return any(_grupo_tiene_equipos_en_tabla(tabla, h[0]) for h in hijos)
 
def construir_arbol_grupos(tabla_db: Optional[str] = None) -> List[Dict]:
    """
    Devuelve árbol de grupos anidados.
    Si se pasa tabla_db, filtra mostrando solo grupos que tengan equipos en esa tabla.
    Así tableros y transformadores ven únicamente sus grupos relevantes en la UI.
    """
    grupos = obtener_grupos()
    nodos = {g[0]: {"id": g[0], "nombre": g[1], "padre_id": g[2], "hijos": []} for g in grupos}
    raices = []
    for nodo in nodos.values():
        padre = nodo["padre_id"]
        if padre and padre in nodos:
            nodos[padre]["hijos"].append(nodo)
        else:
            raices.append(nodo)
 
    # Sin filtro → devolver todo (usado internamente o en formularios)
    if tabla_db is None:
        return raices
 
    # Con filtro → solo ramas que tengan equipos en esa tabla
    def filtrar(lista):
        resultado = []
        for n in lista:
            n["hijos"] = filtrar(n["hijos"])
            if _grupo_tiene_equipos_en_tabla(tabla_db, n["id"]) or n["hijos"]:
                resultado.append(n)
        return resultado
 
    return filtrar(raices)

# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE JERARQUÍA ELÉCTRICA  (para el unifilar)
# ══════════════════════════════════════════════════════════════

def obtener_subarbol_grupo(grupo_id: int) -> List[int]:
    """
    Devuelve el id del grupo dado y todos sus descendientes recursivamente.
    Útil para filtrar tableros 'del mismo conjunto' sin importar el nivel.
    """
    if grupo_id is None:
        return []
    conn = connect_db()
    if conn is None:
        return []
    cur = conn.cursor()
    cur.execute("""
        WITH RECURSIVE subarbol(id) AS (
            SELECT ?
            UNION ALL
            SELECT g.id FROM grupos g
            JOIN subarbol s ON g.padre_id = s.id
        )
        SELECT id FROM subarbol
    """, (grupo_id,))
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    return ids



# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║   ⚠️  CÓDIGO DE MIGRACIÓN TEMPORAL — BORRAR EN PRODUCCIÓN  ⚠️             ║
# ║                                                                          ║
# ║   Todo lo que está entre este banner y el banner "FIN" de más abajo      ║
# ║   sirve para migrar BDs creadas con el schema viejo (que tenía           ║
# ║   columnas equipo_id / equipo_tipo dentro de la tabla 'mantenimientos')  ║
# ║   al schema nuevo (donde esos datos viven en la tabla puente             ║
# ║   'mantenimientos_equipos' y se agrega 'costo_moneda').                  ║
# ║                                                                          ║
# ║   Es seguro mantenerlo durante el desarrollo y las pruebas. Una vez      ║
# ║   que borres la BD de pruebas y empieces "limpio", este bloque ya no     ║
# ║   hace nada útil (la función es idempotente: detecta que la BD ya está   ║
# ║   en el schema nuevo y sale en su primera línea).                        ║
# ║                                                                          ║
# ║   PARA LIMPIAR EN PRODUCCIÓN:                                            ║
# ║      1. Borrar todo este bloque (hasta el banner "FIN").                 ║
# ║      2. El resto del archivo queda como un schema diseñado desde cero.   ║
# ║                                                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝
 
 
def _migrar_mantenimientos_si_necesario(cursor):
    """
    Migra la tabla 'mantenimientos' del schema viejo al nuevo si hace falta.
 
    Schema viejo: tenía columnas equipo_id / equipo_tipo (NOT NULL) directamente
    en la tabla. Schema nuevo: esas columnas se mueven a la tabla puente
    'mantenimientos_equipos', y se agrega 'costo_moneda'.
 
    Esta migración:
    - No hace nada si la tabla no existe (la creará crear_tablas).
    - No hace nada si ya está en el schema nuevo.
    - Si tiene el schema viejo: copia los pares (id, equipo_id, equipo_tipo) a
      la tabla puente y recrea 'mantenimientos' sin esas columnas y con
      'costo_moneda'.
    """
    cursor.execute("PRAGMA table_info(mantenimientos)")
    cols = [row[1] for row in cursor.fetchall()]
    if not cols:
        return  # la tabla no existe todavía
 
    tiene_equipo_id = 'equipo_id' in cols
    tiene_costo_moneda = 'costo_moneda' in cols
 
    # Ya está en el schema nuevo
    if not tiene_equipo_id and tiene_costo_moneda:
        return
 
    # Caso intermedio: schema viejo sin costo_moneda. La recreación de
    # más abajo lo añadirá. Si solo falta costo_moneda (schema híbrido raro),
    # un ALTER TABLE basta:
    if not tiene_equipo_id and not tiene_costo_moneda:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN costo_moneda TEXT DEFAULT 'MXN'")
        return
 
    # Schema viejo completo → recreación.
    # 1) Asegurar que exista la tabla puente.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mantenimientos_equipos (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            mantenimiento_id  INTEGER NOT NULL REFERENCES mantenimientos(id) ON DELETE CASCADE,
            equipo_id         TEXT NOT NULL,
            equipo_tipo       TEXT NOT NULL
        )
    """)
 
    # 2) Leer los pares (id, equipo_id, equipo_tipo) en memoria. No
    # podemos hacer INSERT...SELECT directo a la tabla puente porque
    # el DROP TABLE posterior dispara ON DELETE CASCADE y borraría
    # las filas recién insertadas.
    cursor.execute("""
        SELECT id, equipo_id, equipo_tipo
        FROM mantenimientos
        WHERE equipo_id IS NOT NULL AND equipo_id != ''
    """)
    pares_a_migrar = cursor.fetchall()
 
    # 3) Crear tabla nueva, copiar columnas comunes, dropear vieja, renombrar.
    cursor.execute("""
        CREATE TABLE mantenimientos_new (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_mantenimiento   TEXT NOT NULL,
            urgente              INTEGER DEFAULT 0,
            fecha_inicio         TEXT NOT NULL,
            fecha_fin            TEXT NOT NULL,
            costo                INTEGER DEFAULT 0,
            costo_moneda         TEXT DEFAULT 'MXN',
            descripcion          TEXT NOT NULL,
            responsable_tipo     TEXT NOT NULL,
            responsable_id       TEXT NOT NULL,
            responsable_nombre   TEXT NOT NULL,
            responsable_correo   TEXT,
            responsable_telefono TEXT,
            estado               TEXT DEFAULT 'programado',
            motivo_cancelacion   TEXT,
            fecha_cierre         TEXT,
            costo_real           INTEGER,
            costo_real_moneda    TEXT,
            retroalimentacion    TEXT,
            informe_pdf_path     TEXT,
            google_event_id      TEXT,
            calendar_sync        INTEGER DEFAULT 0,
            calendar_last_error  TEXT,
            calendar_last_sync   TEXT,
            creado_en            TEXT NOT NULL
        )
    """)
 
    # Si la tabla vieja ya tenía costo_moneda (caso muy raro), úsala; si no, MXN.
    expr_costo_moneda = "COALESCE(costo_moneda, 'MXN')" if tiene_costo_moneda else "'MXN'"
 
    cursor.execute(f"""
        INSERT INTO mantenimientos_new
            (id, tipo_mantenimiento, urgente, fecha_inicio, fecha_fin,
             costo, costo_moneda, descripcion,
             responsable_tipo, responsable_id, responsable_nombre,
             responsable_correo, responsable_telefono, estado,
             google_event_id, calendar_sync, calendar_last_error,
             calendar_last_sync, creado_en)
        SELECT id, tipo_mantenimiento, urgente, fecha_inicio, fecha_fin,
               costo, {expr_costo_moneda}, descripcion,
               responsable_tipo, responsable_id, responsable_nombre,
               responsable_correo, responsable_telefono, estado,
               google_event_id, calendar_sync, calendar_last_error,
               calendar_last_sync, creado_en
        FROM mantenimientos
    """)
 
    cursor.execute("DROP TABLE mantenimientos")
    cursor.execute("ALTER TABLE mantenimientos_new RENAME TO mantenimientos")
 
    # 4) Volcar los pares a la tabla puente (post-rename, ya sin riesgo
    # de cascade), evitando duplicados por si ya se habían migrado antes.
    for mant_id, eq_id, eq_tipo in pares_a_migrar:
        cursor.execute("""
            INSERT INTO mantenimientos_equipos (mantenimiento_id, equipo_id, equipo_tipo)
            SELECT ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM mantenimientos_equipos
                WHERE mantenimiento_id = ? AND equipo_id = ? AND equipo_tipo = ?
            )
        """, (mant_id, eq_id, eq_tipo, mant_id, eq_id, eq_tipo))
 
    print(f"[MIGRACIÓN] Tabla 'mantenimientos' migrada al nuevo schema "
          f"({len(pares_a_migrar)} pares equipo→mantenimiento preservados).")


def _asegurar_columnas_mantenimientos(cursor):
    """
    Sub-bloque idempotente que añade columnas introducidas en fases
    posteriores a la migración principal. Útil para BDs que ya están en
    'schema nuevo' pero que se crearon antes de que existieran ciertas
    columnas (motivo_cancelacion, fecha_cierre, costo_real, etc.).

    Se llama después de la migración principal, así corre tanto para
    BDs migradas como para las que ya estaban actualizadas.
    """
    cursor.execute("PRAGMA table_info(mantenimientos)")
    cols = {row[1] for row in cursor.fetchall()}
    if not cols:
        return  # la tabla aún no existe (crear_tablas la creará completa)

    # Fase 3 — Cancelar
    if 'motivo_cancelacion' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN motivo_cancelacion TEXT")

    # Fase 3 — Cerrar mantenimiento (Pendiente cierre y Cancelado).
    # Se llenan al ejecutar "Cerrar mantenimiento":
    #   - Pendiente cierre: PDF + retro + costo real, estado='finalizado'
    #   - Cancelado:        motivo (en motivo_cancelacion), estado='cancelado'
    # La pestaña Finalizados filtra por fecha_cierre IS NOT NULL.
    if 'fecha_cierre' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN fecha_cierre TEXT")
    if 'costo_real' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN costo_real INTEGER")
    if 'costo_real_moneda' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN costo_real_moneda TEXT")
    if 'retroalimentacion' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN retroalimentacion TEXT")
    if 'informe_pdf_path' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN informe_pdf_path TEXT")

    # Fase 4 — Recurrencias (preventivos repetitivos)
    # Al cerrar un mantenimiento con es_recurrente=1, db_manager genera la
    # siguiente instancia. El hijo nace con responsable placeholder y queda
    # invisible en Programados hasta que se le asigne responsable real.
    if 'es_recurrente' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN es_recurrente INTEGER DEFAULT 0")
    if 'recurrencia_meses' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN recurrencia_meses INTEGER")
    if 'dias_aviso_responsable' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN dias_aviso_responsable INTEGER DEFAULT 7")
    if 'mantenimiento_padre_id' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN mantenimiento_padre_id INTEGER")
    if 'serie_id' not in cols:
        cursor.execute("ALTER TABLE mantenimientos ADD COLUMN serie_id INTEGER")


def _asegurar_tablas_reportes(cursor):
    """
    Crea las 4 tablas del módulo de reportes si no existen, para BDs de
    desarrollo que se crearon antes de que esas tablas estuvieran en
    crear_tablas. Idempotente: si ya existen, no hace nada.

    Las tablas son: reportes_plantillas, reportes_firmas,
    reportes_folios_config, licencia. La tabla 'reportes' YA existe en el
    esquema viejo; sus columnas nuevas las añade _asegurar_columnas_reportes.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reportes_plantillas (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre             TEXT NOT NULL,
            es_predeterminada  INTEGER DEFAULT 0,
            logo_path          TEXT,
            empresa_nombre     TEXT,
            empresa_subtitulo  TEXT,
            empresa_direccion  TEXT,
            empresa_telefono   TEXT,
            empresa_correo     TEXT,
            empresa_rfc        TEXT,
            pie_texto          TEXT,
            mostrar_paginacion INTEGER DEFAULT 1,
            color_principal    TEXT DEFAULT '#0078d7',
            color_secundario   TEXT DEFAULT '#666666',
            tamano_letra       INTEGER DEFAULT 10,
            orientacion        TEXT DEFAULT 'vertical',
            tamano_pagina      TEXT DEFAULT 'A4',
            creado_en          TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_plantillas_pred "
        "ON reportes_plantillas(es_predeterminada)"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reportes_firmas (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            rol               TEXT NOT NULL,
            persona_nombre    TEXT NOT NULL,
            persona_puesto    TEXT,
            persona_cedula    TEXT,
            firma_imagen_path TEXT,
            es_predeterminada INTEGER DEFAULT 0,
            creado_en         TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_firmas_rol "
        "ON reportes_firmas(rol, es_predeterminada)"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reportes_folios_config (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria        TEXT NOT NULL UNIQUE,
            patron           TEXT NOT NULL,
            siguiente_numero INTEGER DEFAULT 1,
            anio_actual      INTEGER,
            reset_anual      INTEGER DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS licencia (
            id                    INTEGER PRIMARY KEY CHECK (id = 1),
            tier                  TEXT DEFAULT 'completa',
            clave_activacion      TEXT,
            fecha_activacion      TEXT,
            fecha_expiracion      TEXT,
            ultima_validacion     TEXT,
            licencia_dispositivo  TEXT
        )
    """)


def _asegurar_columnas_reportes(cursor):
    """
    Añade a la tabla 'reportes' las columnas del módulo nuevo si no están.

    En el esquema viejo la tabla solo tenía: id, mantenimiento_id,
    archivo_pdf, observaciones, fecha. Aquí agregamos las columnas que
    el módulo de reportes necesita, e indexes asociados.

    Idempotente: detecta cada columna y solo añade las faltantes.
    """
    cursor.execute("PRAGMA table_info(reportes)")
    cols = {row[1] for row in cursor.fetchall()}
    if not cols:
        return  # la tabla aún no existe (crear_tablas la creará completa)

    if 'categoria' not in cols:
        cursor.execute("ALTER TABLE reportes ADD COLUMN categoria TEXT")
    if 'tipo_reporte' not in cols:
        cursor.execute("ALTER TABLE reportes ADD COLUMN tipo_reporte TEXT")
    if 'folio' not in cols:
        cursor.execute("ALTER TABLE reportes ADD COLUMN folio TEXT")
    if 'usuario_emisor' not in cols:
        cursor.execute("ALTER TABLE reportes ADD COLUMN usuario_emisor TEXT")
    if 'formato' not in cols:
        cursor.execute("ALTER TABLE reportes ADD COLUMN formato TEXT DEFAULT 'pdf'")
    if 'plantilla_id' not in cols:
        # No podemos agregar una FK con ALTER TABLE en SQLite, pero la
        # columna sí; las queries hacen el JOIN normalmente.
        cursor.execute("ALTER TABLE reportes ADD COLUMN plantilla_id INTEGER")
    if 'parametros_json' not in cols:
        cursor.execute("ALTER TABLE reportes ADD COLUMN parametros_json TEXT")
    if 'archivo_ruta' not in cols:
        cursor.execute("ALTER TABLE reportes ADD COLUMN archivo_ruta TEXT")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reportes_categoria ON reportes(categoria)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reportes_fecha     ON reportes(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reportes_folio     ON reportes(folio)")


def _sembrar_reportes_si_vacios(cursor):
    """
    Inserta datos por defecto la primera vez:
      - 1 plantilla 'Plantilla predeterminada' (vacía, lista para que el
        usuario la configure desde Configuración → Reportes).
      - 6 patrones de folio (uno por categoría).
      - 1 fila en licencia con tier='completa' (desarrollo).

    Idempotente: solo siembra si la tabla está vacía.
    """
    # Plantilla predeterminada
    row = cursor.execute(
        "SELECT COUNT(*) FROM reportes_plantillas"
    ).fetchone()
    if row and row[0] == 0:
        cursor.execute("""
            INSERT INTO reportes_plantillas
                (nombre, es_predeterminada, empresa_nombre, empresa_subtitulo)
            VALUES
                ('Plantilla predeterminada', 1, 'CAMF', 'Asset Intelligence')
        """)

    # Patrones de folio por categoría
    row = cursor.execute(
        "SELECT COUNT(*) FROM reportes_folios_config"
    ).fetchone()
    if row and row[0] == 0:
        anio = datetime.now().year
        patrones = [
            ('operativos',  'CAMF-OP-{YYYY}-{####}'),
            ('tecnicos',    'CAMF-TEC-{YYYY}-{####}'),
            ('ingenieria',  'CAMF-ING-{YYYY}-{####}'),
            ('uvie',        'CAMF-UVIE-{YYYY}-{####}'),
            ('gestion',     'CAMF-GES-{YYYY}-{####}'),
            ('inventario',  'CAMF-INV-{YYYY}-{####}'),
        ]
        cursor.executemany("""
            INSERT INTO reportes_folios_config
                (categoria, patron, siguiente_numero, anio_actual, reset_anual)
            VALUES (?, ?, 1, ?, 1)
        """, [(c, p, anio) for (c, p) in patrones])

    # Licencia singleton
    row = cursor.execute("SELECT COUNT(*) FROM licencia").fetchone()
    if row and row[0] == 0:
        cursor.execute("""
            INSERT INTO licencia (id, tier) VALUES (1, 'completa')
        """)


def _migrar_enfriamiento_transformadores_si_necesario(cursor):
    """
    Migración TEMPORAL (borrable en producción, una vez que todas las
    instalaciones existentes hayan corrido esta función al menos una vez).

    Simplifica la columna `enfriamiento` de la tabla `transformadores`:
    los valores IEC antiguos (AA, ONAN, ONAF, OFWF) se traducen a solo
    dos opciones que reflejan la información técnicamente relevante para
    el widget de pruebas: si el transformador está sumergido en aceite
    o es seco.

    Mapeo:
        AA                        → "Aire"     (transformador seco)
        ONAN, ONAF, OFWF          → "Aceite"   (transformador sumergido)
        (cualquier otro string)   → sin cambio

    Idempotente: si no encuentra valores viejos, no hace nada. Segura
    para correr en cada inicio hasta que se retire.
    """
    try:
        # Detectar rápidamente si hay algo que migrar
        row = cursor.execute("""
            SELECT COUNT(*) FROM transformadores
            WHERE enfriamiento IN ('AA', 'ONAN', 'ONAF', 'OFWF')
        """).fetchone()
        pendientes = row[0] if row else 0
        if pendientes == 0:
            return

        cursor.execute("""
            UPDATE transformadores SET enfriamiento = 'Aire'
            WHERE enfriamiento = 'AA'
        """)
        n_aire = cursor.rowcount

        cursor.execute("""
            UPDATE transformadores SET enfriamiento = 'Aceite'
            WHERE enfriamiento IN ('ONAN', 'ONAF', 'OFWF')
        """)
        n_aceite = cursor.rowcount

        print(f"[Migración enfriamiento] {n_aire} seco(s) → 'Aire', "
              f"{n_aceite} aceite(s) → 'Aceite'")
    except sqlite3.OperationalError as e:
        # Tabla puede no existir aún si es una BD recién creada
        if "no such table" in str(e).lower():
            return
        raise


def _ejecutar_migracion_al_importar():
    """
    Hook que corre la migración una sola vez al importar este módulo.
    Si la BD no existe todavía, no hace nada (crear_tablas la creará limpia
    cuando alguien llame a create_database()).
    """
    db_path = get_db_path()
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()
        _migrar_mantenimientos_si_necesario(cur)
        _asegurar_columnas_mantenimientos(cur)
        _asegurar_tablas_reportes(cur)
        _asegurar_columnas_reportes(cur)
        _sembrar_reportes_si_vacios(cur)
        _migrar_enfriamiento_transformadores_si_necesario(cur)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Migración] Aviso: {e}")
 
 
# Disparador automático: la migración corre al importar db_manager.
# Como es idempotente, no pasa nada si la BD ya está al día.
_ejecutar_migracion_al_importar()
 
 
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║   ═══════ FIN DEL CÓDIGO DE MIGRACIÓN TEMPORAL ═══════                   ║
# ║                                                                          ║
# ║   Borrar todo desde el banner de arriba hasta esta línea cuando se       ║
# ║   abandone la BD de pruebas. El archivo queda como un schema limpio.     ║
# ║                                                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# ══════════════════════════════════════════════════════════════════════════
#  FASE 4 — FUNCIONES DE METADATA Y MIGRACIÓN AL ARCHIVO HISTÓRICO
# ══════════════════════════════════════════════════════════════════════════
# Funciones de bajo nivel. La orquestación completa (respaldo automático,
# rotación, notificaciones) vive en `migracion_archivo.py`.


def metadata_get(clave: str, default: Optional[str] = None) -> Optional[str]:
    """Lee un valor de la tabla metadata_sistema. Devuelve default si no
    existe la clave o la BD no está accesible."""
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return default
    try:
        row = conn.cursor().execute(
            "SELECT valor FROM metadata_sistema WHERE clave = ?",
            (clave,)
        ).fetchone()
        return row[0] if row else default
    except Exception as e:
        print(f"[metadata_get] error leyendo '{clave}': {e}")
        return default
    finally:
        conn.close()


def metadata_set(clave: str, valor: str) -> bool:
    """Guarda o actualiza un valor en metadata_sistema. Devuelve True si
    la operación fue exitosa."""
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return False
    try:
        conn.cursor().execute("""
            INSERT INTO metadata_sistema (clave, valor, actualizado)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(clave) DO UPDATE SET
                valor = excluded.valor,
                actualizado = datetime('now')
        """, (clave, valor))
        conn.commit()
        return True
    except Exception as e:
        print(f"[metadata_set] error escribiendo '{clave}': {e}")
        return False
    finally:
        conn.close()


def metadata_delete(clave: str) -> bool:
    """Borra una clave de metadata_sistema. Útil para 'marcar notificación
    como leída' (borrar el flag). Devuelve True si la operación fue
    exitosa (incluye el caso de que la clave no existiera)."""
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return False
    try:
        conn.cursor().execute(
            "DELETE FROM metadata_sistema WHERE clave = ?",
            (clave,)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[metadata_delete] error borrando '{clave}': {e}")
        return False
    finally:
        conn.close()


def obtener_anios_para_archivar(umbral_anios: int = 5) -> List[int]:
    """Devuelve la lista de años cerrados completos que ya cumplieron el
    criterio de archivo, ordenados ascendente (el más viejo primero).

    Un año Y es candidato si:
      - Y < (año_actual - umbral_anios)
      - Existe al menos un mantenimiento con fecha_cierre en ese año.

    Por defecto umbral_anios=5, es decir: si es 2028, se archivan los
    cierres de 2022 y anteriores (2028 - 5 = 2023, entonces años < 2023).

    Devuelve [] si no hay años candidatos o si la BD falla.
    """
    from datetime import datetime as _dt
    anio_corte = _dt.now().year - umbral_anios

    conn = connect_db(create_if_missing=False)
    if conn is None:
        return []
    try:
        rows = conn.cursor().execute("""
            SELECT DISTINCT CAST(strftime('%Y', fecha_cierre) AS INTEGER) AS anio
            FROM mantenimientos
            WHERE fecha_cierre IS NOT NULL
              AND CAST(strftime('%Y', fecha_cierre) AS INTEGER) < ?
            ORDER BY anio ASC
        """, (anio_corte,)).fetchall()
        return [r[0] for r in rows if r[0] is not None]
    except Exception as e:
        print(f"[obtener_anios_para_archivar] error: {e}")
        return []
    finally:
        conn.close()


def mover_anio_a_archivo(anio: int) -> Tuple[bool, int, str]:
    """Mueve TODOS los mantenimientos cerrados del año dado desde las
    tablas operativas a las tablas de archivo, dentro de UNA transacción
    atómica.

    Retorna: (exito, cantidad_movida, mensaje_error)
      - exito=True   → la migración se completó y commiteó.
      - exito=False  → algo falló y se hizo rollback; la BD quedó intacta.
      - cantidad_movida es el número de mantenimientos migrados.
      - mensaje_error solo tiene contenido si exito=False.

    Garantías:
      - Atomicidad: si algo falla a mitad (corte de luz, disco lleno,
        bug de código), SQLite hace rollback y la BD queda idéntica.
      - Verificación posterior: se cuenta antes y después para asegurar
        que los números cuadran. Si no cuadran, se hace rollback manual.
    """
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return False, 0, "No se pudo abrir la base de datos."

    try:
        cur = conn.cursor()

        # Contar cuántos mantenimientos deberían migrarse (para verificación).
        n_esperado = cur.execute("""
            SELECT COUNT(*) FROM mantenimientos
            WHERE fecha_cierre IS NOT NULL
              AND CAST(strftime('%Y', fecha_cierre) AS INTEGER) = ?
        """, (anio,)).fetchone()[0]

        if n_esperado == 0:
            return True, 0, ""  # Nada que hacer, éxito trivial.

        # Envolver todo en una transacción explícita.
        cur.execute("BEGIN TRANSACTION")

        # 1) Copiar los mantenimientos del año al archivo.
        cur.execute("""
            INSERT INTO mantenimientos_archivo (
                id, tipo_mantenimiento, urgente, fecha_inicio, fecha_fin,
                costo, costo_moneda, descripcion,
                responsable_tipo, responsable_id, responsable_nombre,
                responsable_correo, responsable_telefono,
                estado, motivo_cancelacion,
                fecha_cierre, costo_real, costo_real_moneda,
                retroalimentacion, informe_pdf_path,
                google_event_id, calendar_sync, calendar_last_error, calendar_last_sync,
                es_recurrente, recurrencia_meses, dias_aviso_responsable,
                mantenimiento_padre_id, serie_id, creado_en
            )
            SELECT
                id, tipo_mantenimiento, urgente, fecha_inicio, fecha_fin,
                costo, costo_moneda, descripcion,
                responsable_tipo, responsable_id, responsable_nombre,
                responsable_correo, responsable_telefono,
                estado, motivo_cancelacion,
                fecha_cierre, costo_real, costo_real_moneda,
                retroalimentacion, informe_pdf_path,
                google_event_id, calendar_sync, calendar_last_error, calendar_last_sync,
                es_recurrente, recurrencia_meses, dias_aviso_responsable,
                mantenimiento_padre_id, serie_id, creado_en
            FROM mantenimientos
            WHERE fecha_cierre IS NOT NULL
              AND CAST(strftime('%Y', fecha_cierre) AS INTEGER) = ?
        """, (anio,))

        # 2) Copiar los rows de mantenimientos_equipos correspondientes.
        cur.execute("""
            INSERT INTO mantenimientos_equipos_archivo (
                id, mantenimiento_id, equipo_id, equipo_tipo
            )
            SELECT me.id, me.mantenimiento_id, me.equipo_id, me.equipo_tipo
            FROM mantenimientos_equipos me
            INNER JOIN mantenimientos m ON m.id = me.mantenimiento_id
            WHERE m.fecha_cierre IS NOT NULL
              AND CAST(strftime('%Y', m.fecha_cierre) AS INTEGER) = ?
        """, (anio,))

        # 3) Borrar los rows de mantenimientos_equipos originales
        #    (antes de mantenimientos, para respetar FK).
        cur.execute("""
            DELETE FROM mantenimientos_equipos
            WHERE mantenimiento_id IN (
                SELECT id FROM mantenimientos
                WHERE fecha_cierre IS NOT NULL
                  AND CAST(strftime('%Y', fecha_cierre) AS INTEGER) = ?
            )
        """, (anio,))

        # 4) Borrar los mantenimientos originales del año.
        cur.execute("""
            DELETE FROM mantenimientos
            WHERE fecha_cierre IS NOT NULL
              AND CAST(strftime('%Y', fecha_cierre) AS INTEGER) = ?
        """, (anio,))

        # 5) Verificación posterior antes del commit: contar en el archivo.
        n_en_archivo = cur.execute("""
            SELECT COUNT(*) FROM mantenimientos_archivo
            WHERE CAST(strftime('%Y', fecha_cierre) AS INTEGER) = ?
        """, (anio,)).fetchone()[0]

        n_restante_en_activos = cur.execute("""
            SELECT COUNT(*) FROM mantenimientos
            WHERE fecha_cierre IS NOT NULL
              AND CAST(strftime('%Y', fecha_cierre) AS INTEGER) = ?
        """, (anio,)).fetchone()[0]

        # El archivo debe tener al menos n_esperado más rows que antes,
        # y no deben quedar del año en la tabla operativa.
        if n_restante_en_activos != 0:
            conn.rollback()
            return False, 0, (
                f"Verificación falló: quedaron {n_restante_en_activos} "
                f"mantenimientos del año {anio} en la tabla operativa."
            )
        if n_en_archivo < n_esperado:
            conn.rollback()
            return False, 0, (
                f"Verificación falló: se esperaba mover {n_esperado} "
                f"mantenimientos pero solo {n_en_archivo} están en el archivo."
            )

        conn.commit()
        return True, n_esperado, ""

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, 0, f"Error durante la migración: {e}"
    finally:
        conn.close()


def obtener_mantenimientos_archivados(
    anio: Optional[int] = None,
    mes: Optional[int] = None,
) -> List[Tuple]:
    """Consulta la tabla de archivo con el mismo SELECT-shape que
    obtener_mantenimientos_finalizados() de finalizados.py, para que la
    vista de archivo histórico pueda reusar las mismas rutinas de
    enriquecimiento (equipos_lineas, calcular_estado).

    Filtros combinables (ambos opcionales):
      - anio: si se pasa, solo cierres de ese año.
      - mes:  si se pasa, solo cierres de ese mes (1-12). Requiere que
              anio también esté definido — filtrar por mes sin año no
              tiene sentido (mezclaría febreros de años distintos).

    Sin filtros devuelve TODOS los archivados. Con año y sin mes devuelve
    el año completo. Con ambos devuelve solo ese mes de ese año.
    """
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return []
    try:
        base_query = """
            SELECT
                m.id,
                m.tipo_mantenimiento,
                m.urgente,
                m.fecha_inicio,
                m.fecha_fin,
                m.costo,
                m.costo_moneda,
                m.responsable_nombre,
                m.estado,
                GROUP_CONCAT(me.equipo_id || ':' || me.equipo_tipo, '|') AS equipos_lista,
                m.fecha_cierre
            FROM mantenimientos_archivo m
            LEFT JOIN mantenimientos_equipos_archivo me
                   ON me.mantenimiento_id = m.id
        """
        if anio is not None and mes is not None:
            # Año + mes específicos.
            query = base_query + """
                WHERE CAST(strftime('%Y', m.fecha_cierre) AS INTEGER) = ?
                  AND CAST(strftime('%m', m.fecha_cierre) AS INTEGER) = ?
                GROUP BY m.id
                ORDER BY m.fecha_cierre DESC
            """
            return conn.cursor().execute(query, (anio, mes)).fetchall()
        elif anio is not None:
            # Año completo.
            query = base_query + """
                WHERE CAST(strftime('%Y', m.fecha_cierre) AS INTEGER) = ?
                GROUP BY m.id
                ORDER BY m.fecha_cierre DESC
            """
            return conn.cursor().execute(query, (anio,)).fetchall()
        else:
            # Todo el archivo (poco frecuente, útil para casos administrativos).
            query = base_query + """
                GROUP BY m.id
                ORDER BY m.fecha_cierre DESC
            """
            return conn.cursor().execute(query).fetchall()
    except Exception as e:
        print(f"[obtener_mantenimientos_archivados] error: {e}")
        return []
    finally:
        conn.close()


def obtener_anios_disponibles_en_archivo() -> List[int]:
    """Devuelve la lista de años con al menos un cierre en el archivo,
    ordenados descendente (más reciente primero). Útil para poblar los
    pills de año de la vista de archivo histórico."""
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return []
    try:
        rows = conn.cursor().execute("""
            SELECT DISTINCT CAST(strftime('%Y', fecha_cierre) AS INTEGER) AS anio
            FROM mantenimientos_archivo
            WHERE fecha_cierre IS NOT NULL
            ORDER BY anio DESC
        """).fetchall()
        return [r[0] for r in rows if r[0] is not None]
    except Exception as e:
        print(f"[obtener_anios_disponibles_en_archivo] error: {e}")
        return []
    finally:
        conn.close()


def obtener_conteos_por_anio_en_archivo() -> Dict[int, int]:
    """Devuelve {anio: cantidad_de_cierres} para todos los años que tengan
    al menos un cierre en el archivo. Útil para poblar el dropdown de años
    del diálogo de selección con etiquetas tipo '2022 (245 registros)'.

    Devuelve {} si no hay datos o la BD falla.
    """
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return {}
    try:
        rows = conn.cursor().execute("""
            SELECT CAST(strftime('%Y', fecha_cierre) AS INTEGER) AS anio,
                   COUNT(*) AS cantidad
            FROM mantenimientos_archivo
            WHERE fecha_cierre IS NOT NULL
            GROUP BY anio
            ORDER BY anio DESC
        """).fetchall()
        return {r[0]: r[1] for r in rows if r[0] is not None}
    except Exception as e:
        print(f"[obtener_conteos_por_anio_en_archivo] error: {e}")
        return {}
    finally:
        conn.close()


def obtener_conteos_por_mes_en_archivo(anio: int) -> Dict[int, int]:
    """Devuelve {mes: cantidad_de_cierres} para el año dado, con las
    llaves como enteros 1-12. Solo incluye meses con al menos un cierre —
    los meses vacíos NO aparecen en el dict (para poblar el dropdown de
    mes solo con las opciones que tienen contenido).

    Devuelve {} si no hay datos del año o la BD falla.
    """
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return {}
    try:
        rows = conn.cursor().execute("""
            SELECT CAST(strftime('%m', fecha_cierre) AS INTEGER) AS mes,
                   COUNT(*) AS cantidad
            FROM mantenimientos_archivo
            WHERE fecha_cierre IS NOT NULL
              AND CAST(strftime('%Y', fecha_cierre) AS INTEGER) = ?
            GROUP BY mes
            ORDER BY mes ASC
        """, (anio,)).fetchall()
        return {r[0]: r[1] for r in rows if r[0] is not None}
    except Exception as e:
        print(f"[obtener_conteos_por_mes_en_archivo] error: {e}")
        return {}
    finally:
        conn.close()
