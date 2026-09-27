
class GoogleCalendarService:

    def __init__(self):
        self.service = self._conectar()

    def _conectar(self):
        """
        Devuelve el cliente de Google Calendar
        """
        # aquí va la autenticación (siguiente paso)
        pass

    def crear_evento(self, mantenimiento: dict) -> dict:
        """
        Intenta crear el evento.
        Devuelve:
        {
            "ok": True,
            "event_id": "...",
        }
        o
        {
            "ok": False,
            "error": "mensaje"
        }
        """
        try:
            evento = {
                "summary": f"{mantenimiento['tipo_mantenimiento']} - {mantenimiento['equipo_tipo']}",
                "description": mantenimiento["descripcion"],
                "start": {
                    "dateTime": mantenimiento["fecha_inicio"],
                    "timeZone": "America/Mexico_City",
                },
                "end": {
                    "dateTime": mantenimiento["fecha_fin"],
                    "timeZone": "America/Mexico_City",
                },
                "attendees": [
                    {"email": mantenimiento["responsable_correo"]}
                ],
            }

            creado = self.service.events().insert(
                calendarId="primary",
                body=evento
            ).execute()

            return {
                "ok": True,
                "event_id": creado["id"]
            }

        except Exception as e:
            return {
                "ok": False,
                "error": str(e)
            }