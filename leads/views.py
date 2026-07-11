import re
import os
import subprocess
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from .models import Lead
from .serializers import LeadSerializer
from .tasks import trigger_outbound_call_task

# 1. Endpoint para Next.js (Listar leads)
class LeadListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    queryset = Lead.objects.all().order_by('-creado_en')
    serializer_class = LeadSerializer

# 2. Endpoint para el Webhook de Kommo
class KommoWebhookView(APIView):
    authentication_classes = [] # Permitir acceso público de Kommo
    permission_classes = []

    def post(self, request, *args, **kwargs):
        # Kommo suele enviar los datos en formato x-www-form-urlencoded o JSON planos
        data = request.data
        
        print("\n=== WEBHOOK KOMMO RECIBIDO ===", flush=True)
        print(f"Payload completo recibido: {data}", flush=True)
        
        def get_flat_value(data, key):
            val = data.get(key)
            if isinstance(val, list):
                return val[0] if val else None
            return val

        try:
            # 1. Buscar todos los prefijos de contactos, ej. "contacts[add][0]" o "contacts[update][0]"
            contact_prefixes = set()
            for key in data.keys():
                match = re.match(r'^(contacts\[(?:add|update)\]\[\d+\])', key)
                if match:
                    contact_prefixes.add(match.group(1))

            if contact_prefixes:
                print(f"Se encontraron {len(contact_prefixes)} prefijos de contactos a procesar.", flush=True)
                for prefix in contact_prefixes:
                    # Extraer ID del contacto y nombre
                    contact_id = get_flat_value(data, f"{prefix}[id]")
                    nombre = get_flat_value(data, f"{prefix}[name]")
                    
                    print(f"Procesando contacto ID: {contact_id}, Nombre: {nombre}", flush=True)
                    
                    # Extraer los linked_leads_id de este contacto
                    # Buscamos claves como: contacts[add][0][linked_leads_id][LEAD_ID][ID]
                    lead_ids = []
                    lead_pattern = re.compile(rf"^{re.escape(prefix)}\[linked_leads_id\]\[(\d+)\]\[ID\]")
                    for k in data.keys():
                        m = lead_pattern.match(k)
                        if m:
                            lead_id = get_flat_value(data, k) or m.group(1)
                            lead_ids.append(lead_id)
                    
                    # Extraer teléfono de custom fields
                    # Buscamos índices de custom fields para este contacto
                    cf_indexes = set()
                    cf_pattern = re.compile(rf"^{re.escape(prefix)}\[custom_fields\]\[(\d+)\]")
                    for k in data.keys():
                        m = cf_pattern.match(k)
                        if m:
                            cf_indexes.add(m.group(1))
                            
                    telefono = None
                    for idx in cf_indexes:
                        code = get_flat_value(data, f"{prefix}[custom_fields][{idx}][code]")
                        cf_name = get_flat_value(data, f"{prefix}[custom_fields][{idx}][name]")
                        if code == 'PHONE' or (cf_name and cf_name.lower() in ('teléfono', 'telefono', 'phone')):
                            telefono = get_flat_value(data, f"{prefix}[custom_fields][{idx}][values][0][value]")
                            if telefono:
                                break
                    
                    print(f"Leads asociados: {lead_ids}, Teléfono: {telefono}", flush=True)
                    
                    # Si no hay leads asociados a este contacto, o el webhook es diferente,
                    # podemos guardar el lead usando el primer lead_id de lead_ids.
                    if lead_ids:
                        for lead_id in lead_ids:
                            lead, created = Lead.objects.update_or_create(
                                kommo_id=lead_id,
                                defaults={
                                    'nombre': nombre,
                                    'telefono': telefono,
                                }
                            )
                            accion = "CREADO" if created else "ACTUALIZADO"
                            print(f"Resultado en BD -> [{accion}] Lead ID: {lead.id} (Kommo ID: {lead.kommo_id}, Nombre: {lead.nombre}, Teléfono: {lead.telefono})", flush=True)
                            
                            # Disparar tarea asíncrona de Celery para realizar la llamada automática
                            if lead.telefono:
                                print(f"Encolando tarea de llamada en Celery para el número: {lead.telefono}", flush=True)
                                trigger_outbound_call_task.delay(lead.id, lead.telefono, lead.nombre)
                            else:
                                print(f"El lead {lead.id} no tiene teléfono asociado. Llamada omitida.", flush=True)
                    else:
                        print("No se encontraron leads vinculados (linked_leads_id) para este contacto.", flush=True)
            else:
                # Si el payload es del formato antiguo/directo de leads (por si acaso)
                leads_data = data.get('leads[add]') or data.get('leads[update]')
                if leads_data:
                    print(f"Se encontraron {len(leads_data)} leads directos en el payload.", flush=True)
                    for item in leads_data:
                        kommo_id = item.get('id')
                        status_id = item.get('status_id')
                        lead, created = Lead.objects.update_or_create(
                            kommo_id=kommo_id,
                            defaults={
                                'estado': status_id,
                            }
                        )
                        accion = "CREADO" if created else "ACTUALIZADO"
                        print(f"Resultado en BD (Lead Directo) -> [{accion}] Lead ID: {lead.id} (Kommo ID: {lead.kommo_id}, Estado: {lead.estado})", flush=True)
                else:
                    print("No se encontró estructura de contactos ni de leads en el payload.", flush=True)
            
            print("===============================\n", flush=True)
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        except Exception as e:
            print(f"ERROR procesando webhook: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            print("===============================\n", flush=True)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

# 3. Endpoint para ejecutar script de prueba desde el frontend
class TestFlowView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            # Ruta absoluta del script test_flow.py
            script_path = os.path.join(settings.BASE_DIR, 'test_flow.py')
            
            # Ejecutar el script capturando la salida
            result = subprocess.run(
                ['python3', script_path], 
                capture_output=True, 
                text=True
            )
            
            return Response({
                "status": "success" if result.returncode == 0 else "error",
                "output": result.stdout,
                "error": result.stderr
            }, status=status.HTTP_200_OK if result.returncode == 0 else status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 4. Webhook para recibir notificaciones desde Asterisk cuando un agente contesta
class CallAnsweredWebhookView(APIView):
    authentication_classes = [] # El PBX interno puede enviar sin auth
    permission_classes = []

    def post(self, request, *args, **kwargs):
        # Puede recibir por json o form-data
        lead_id = request.data.get('lead_id')
        agent_extension = request.data.get('agent_extension')

        print(f"\n=== WEBHOOK ASTERISK: LLAMADA CONTESTADA ===", flush=True)
        print(f"Lead ID: {lead_id} | Agente crudo: {agent_extension}", flush=True)

        if not lead_id or not agent_extension:
            print("Error: faltan datos (lead_id o agent_extension).", flush=True)
            return Response({"error": "Missing parameters"}, status=status.HTTP_400_BAD_REQUEST)

        # Parsear el número de agente a partir de la cadena cruda del canal (ej. SIP/2005-000001a o PJSIP/2005-...)
        parsed_agent = agent_extension
        if '/' in parsed_agent:
            parsed_agent = parsed_agent.split('/')[1]
        if '-' in parsed_agent:
            parsed_agent = parsed_agent.split('-')[0]
        if '@' in parsed_agent:
            parsed_agent = parsed_agent.split('@')[0]

        try:
            lead = Lead.objects.get(id=lead_id)
            lead.agente_extension = parsed_agent
            lead.save()
            print(f"Lead {lead_id} actualizado. Agente asignado: {parsed_agent}\n", flush=True)
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        except Lead.DoesNotExist:
            print(f"Error: Lead {lead_id} no encontrado.\n", flush=True)
            return Response({"error": "Lead not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"Error procesando webhook asterisk: {str(e)}\n", flush=True)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)