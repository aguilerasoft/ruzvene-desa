import os
import socket
import logging
from celery import shared_task
from django.conf import settings
from .ami import AMIClient, normalize_phone_number

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def trigger_outbound_call_task(self, lead_id, phone_number, name=None):
    """
    Tarea asíncrona de Celery para originar una llamada a través del Asterisk Manager Interface (AMI).
    Si ocurre un error en la conexión del socket o transmisión, la tarea se reintentará automáticamente
    hasta 3 veces con una espera de 10 segundos entre cada reintento.
    """
    logger.info(f"Iniciando tarea de llamada para Lead ID: {lead_id}, Nombre: {name}, Teléfono original: {phone_number}")
    
    # 1. Normalizar el número del lead
    normalized_number = normalize_phone_number(phone_number)
    if not normalized_number:
        logger.error(f"Abortando tarea: El número de teléfono normalizado está vacío para Lead ID: {lead_id}")
        return False

    # 2. Cargar configuraciones de Asterisk AMI desde Django settings o variables de entorno
    ami_host = getattr(settings, 'ASTERISK_AMI_HOST', os.environ.get('ASTERISK_AMI_HOST', '127.0.0.1'))
    ami_port = getattr(settings, 'ASTERISK_AMI_PORT', os.environ.get('ASTERISK_AMI_PORT', 5038))
    ami_user = getattr(settings, 'ASTERISK_AMI_USER', os.environ.get('ASTERISK_AMI_USER', ''))
    ami_secret = getattr(settings, 'ASTERISK_AMI_SECRET', os.environ.get('ASTERISK_AMI_SECRET', ''))

    if not ami_user or not ami_secret:
        logger.error("Credenciales de Asterisk AMI no configuradas (usuario o contraseña vacíos).")
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
                # Enviar comando Originate
                success = client.originate_call(
                    phone_number=normalized_number,
                    context="from-internal",
                    exten="3000",
                    priority="1"
                )
            # Siempre desconectar de manera limpia
            client.disconnect()
        else:
            raise socket.error("Fallo al conectar al socket de Asterisk AMI.")
            
    except Exception as e:
        logger.error(f"Error durante el envío de acción AMI para Lead {lead_id}: {e}")
        # Reintentar la tarea si falla la red o hay un problema transitorio
        try:
            self.retry(exc=e)
        except Exception as retry_err:
            logger.error(f"Límite de reintentos superado para la tarea del Lead {lead_id}: {retry_err}")
            raise retry_err

    return success
