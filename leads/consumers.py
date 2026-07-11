import json
from channels.generic.websocket import AsyncWebsocketConsumer
from urllib.parse import parse_qs

class LeadsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Opcional: Validación de token simple (puedes extraerlo del query string si lo envías desde el frontend)
        # query_string = self.scope.get('query_string', b'').decode('utf-8')
        # params = parse_qs(query_string)
        # token = params.get('token', [None])[0]
        
        # Para la conexión inicial, aceptamos la conexión.
        await self.accept()

        # Unirse a un grupo general de leads
        self.room_group_name = 'leads_updates'
        try:
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            print("WebSocket conectado y suscrito a Redis exitosamente")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"CRÍTICO: Falló la conexión a Redis Channel Layer: {e}")
            await self.close()

    async def disconnect(self, close_code):
        # Salir del grupo
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        # No esperamos recibir datos del frontend, solo enviar
        pass

    # Manejador para los eventos enviados al grupo
    async def lead_update(self, event):
        lead_data = event['lead']

        # Enviar mensaje al WebSocket
        await self.send(text_data=json.dumps({
            'type': 'lead_update',
            'lead': lead_data
        }))
