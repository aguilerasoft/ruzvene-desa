import os
import socket
import logging
from celery import shared_task
from django.conf import settings
from .ami import AMIClient, normalize_phone_number

from .models import Lead

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def trigger_outbound_call_task(self, lead_id, phone_number, name=None):
    """
    Tarea asíncrona de Celery para originar una llamada a través del Asterisk Manager Interface (AMI).
    1. Verifica si hay agentes disponibles en la cola.
    2. Si no hay agentes, reprograma la tarea.
    3. Si hay agentes, inicia la llamada de forma sincrónica para registrar el resultado en el Lead.
    """
    logger.info(f"Iniciando tarea de llamada para Lead ID: {lead_id}, Nombre: {name}, Teléfono original: {phone_number}")
    
    # 0. Intentar obtener el Lead de la base de datos
    try:
        lead = Lead.objects.get(id=lead_id)
    except Lead.DoesNotExist:
        logger.error(f"Abortando tarea: El Lead con ID {lead_id} no existe en la base de datos.")
        return False

    # 1. Normalizar el número del lead
    normalized_number = normalize_phone_number(phone_number)
    if not normalized_number:
        logger.error(f"Abortando tarea: El número de teléfono normalizado está vacío para Lead ID: {lead_id}")
        lead.estado_llamada = 'fallida'
        lead.save()
        return False

    # Actualizar estado inicial de la llamada a pendiente
    lead.estado_llamada = 'pendiente'
    lead.save()

    # 2. Cargar configuraciones de Asterisk AMI desde Django settings o variables de entorno
    ami_host = getattr(settings, 'ASTERISK_AMI_HOST', os.environ.get('ASTERISK_AMI_HOST', '127.0.0.1'))
    ami_port = getattr(settings, 'ASTERISK_AMI_PORT', os.environ.get('ASTERISK_AMI_PORT', 5038))
    ami_user = getattr(settings, 'ASTERISK_AMI_USER', os.environ.get('ASTERISK_AMI_USER', ''))
    ami_secret = getattr(settings, 'ASTERISK_AMI_SECRET', os.environ.get('ASTERISK_AMI_SECRET', ''))

    if not ami_user or not ami_secret:
        logger.error("Credenciales de Asterisk AMI no configuradas (usuario o contraseña vacíos).")
        lead.estado_llamada = 'fallida'
        lead.save()
        return False

    # 3. Inicializar el cliente AMI
    client = AMIClient(
        host=ami_host,
        port=ami_port,
        username=ami_user,
        secret=ami_secret
    )

    success = False
    try:
        # Intentar conectar
        if client.connect():
            # Intentar iniciar sesión
            if client.login():
                # A. Verificar si hay agentes libres/disponibles en la cola 3000
                if not client.check_agents_available("3000"):
                    logger.warning(f"No hay agentes disponibles para el Lead {lead_id}. Guardando en espera...")
                    lead.estado_llamada = 'sin_operadores'
                    lead.save()
                    client.disconnect()
                    return False

                # B. Enviar comando Originate de forma sincrónica si hay agentes
                success = client.originate_call(
                    phone_number=normalized_number,
                    context="custom-kommo-outbound",
                    agent_exten="3000",
                    priority="1",
                    lead_name=name,
                    kommo_id=lead.kommo_id,
                    lead_id=lead.id
                )
                
                # Actualizar el estado final según el resultado de originate_call
                if success:
                    lead.estado_llamada = 'realizada'
                else:
                    lead.estado_llamada = 'fallida'
                lead.save()
                
            # Siempre desconectar de manera limpia
            client.disconnect()
        else:
            raise socket.error("Fallo al conectar al socket de Asterisk AMI.")
            
    except Exception as e:
        # Si la excepción es del tipo Retry, propagarla directamente sin capturarla como fallo definitivo
        if type(e).__name__ == 'Retry':
            raise e
            
        logger.error(f"Error durante el envío de acción AMI para Lead {lead_id}: {e}")
        # Reintentar la tarea si falla la red o hay un problema transitorio
        try:
            self.retry(exc=e, countdown=15)
        except Exception as retry_err:
            if type(retry_err).__name__ == 'Retry':
                raise retry_err
            logger.error(f"Límite de reintentos superado para la tarea del Lead {lead_id}: {retry_err}")
            lead.estado_llamada = 'fallida'
            lead.save()
            raise retry_err

    return success

@shared_task
def process_pending_calls_task():
    """
    Tarea periódica de Celery (ejecutada vía Celery Beat) que procesa los leads
    que quedaron en espera (pendiente o sin_operadores).
    """
    pending_leads = Lead.objects.filter(estado_llamada__in=['pendiente', 'sin_operadores']).order_by('creado_en')
    if not pending_leads.exists():
        return "No hay llamadas pendientes de procesar."

    logger.info(f"Procesando {pending_leads.count()} llamadas pendientes...")

    # Cargar configuraciones de Asterisk AMI
    ami_host = getattr(settings, 'ASTERISK_AMI_HOST', os.environ.get('ASTERISK_AMI_HOST', '127.0.0.1'))
    ami_port = getattr(settings, 'ASTERISK_AMI_PORT', os.environ.get('ASTERISK_AMI_PORT', 5038))
    ami_user = getattr(settings, 'ASTERISK_AMI_USER', os.environ.get('ASTERISK_AMI_USER', ''))
    ami_secret = getattr(settings, 'ASTERISK_AMI_SECRET', os.environ.get('ASTERISK_AMI_SECRET', ''))

    if not ami_user or not ami_secret:
        logger.error("Periodic Task Error: Credenciales de Asterisk AMI no configuradas.")
        return "Error: Credenciales no configuradas"

    client = AMIClient(
        host=ami_host,
        port=ami_port,
        username=ami_user,
        secret=ami_secret
    )

    processed_count = 0
    try:
        if client.connect():
            if client.login():
                for lead in pending_leads:
                    # 1. Verificar si hay agentes disponibles en la cola en este instante
                    if not client.check_agents_available("3000"):
                        logger.info("No hay operadores libres en la cola 3000. Deteniendo procesamiento de cola de espera por ahora.")
                        break

                    # 2. Normalizar número
                    normalized_number = normalize_phone_number(lead.telefono)
                    if not normalized_number:
                        logger.error(f"Lead ID {lead.id} tiene número inválido: {lead.telefono}")
                        lead.estado_llamada = 'fallida'
                        lead.save()
                        continue

                    # 3. Marcar estado como 'pendiente' mientras intentamos
                    lead.estado_llamada = 'pendiente'
                    lead.save()

                    logger.info(f"Procesando llamada para Lead ID {lead.id} en cola de espera.")
                    # 4. Originar llamada
                    success = client.originate_call(
                        phone_number=normalized_number,
                        context="custom-kommo-outbound",
                        agent_exten="3000",
                        priority="1",
                        lead_name=lead.nombre,
                        kommo_id=lead.kommo_id,
                        lead_id=lead.id
                    )

                    if success:
                        lead.estado_llamada = 'realizada'
                        logger.info(f"Llamada en cola realizada con éxito para Lead ID {lead.id}")
                    else:
                        lead.estado_llamada = 'fallida'
                        logger.error(f"Llamada en cola falló para Lead ID {lead.id}")
                    
                    lead.save()
                    processed_count += 1

            client.disconnect()
    except Exception as e:
        logger.error(f"Excepción en la tarea periódica process_pending_calls_task: {e}")
        try:
            client.disconnect()
        except Exception:
            pass

    return f"Procesamiento finalizado. Llamadas procesadas en esta ejecución: {processed_count}"
