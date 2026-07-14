import os
import pymysql
import logging
import datetime
import random
from django.conf import settings

logger = logging.getLogger(__name__)

class AsteriskDBClient:
    """
    Cliente para conectar y consultar la base de datos de Asterisk FreePBX (MariaDB/MySQL).
    Si no se puede conectar o no está configurada, genera datos de prueba de forma transparente.
    """
    def __init__(self):
        # Cargar configuraciones del .env o settings
        self.host = getattr(settings, 'ASTERISK_DB_HOST', os.environ.get('ASTERISK_DB_HOST', '192.168.0.106'))
        self.port = int(getattr(settings, 'ASTERISK_DB_PORT', os.environ.get('ASTERISK_DB_PORT', 3306)))
        self.user = getattr(settings, 'ASTERISK_DB_USER', os.environ.get('ASTERISK_DB_USER', 'freepbxuser'))
        self.password = getattr(settings, 'ASTERISK_DB_PASSWORD', os.environ.get('ASTERISK_DB_PASSWORD', ''))
        self.database = getattr(settings, 'ASTERISK_DB_NAME', os.environ.get('ASTERISK_DB_NAME', 'asteriskcdrdb'))
        self.connection = None

    def connect(self):
        """Intenta abrir conexión TCP con MariaDB/MySQL de FreePBX."""
        if not self.password:
            # Si no hay contraseña configurada, evitamos intentar para no causar cuelgues innecesarios
            raise ValueError("La contraseña de la base de datos de Asterisk no está configurada en el .env.")

        try:
            self.connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                connect_timeout=3,
                cursorclass=pymysql.cursors.DictCursor
            )
            return True
        except Exception as e:
            logger.error(f"No se pudo conectar a la BD de Asterisk en {self.host}:{self.port}. Detalle: {e}")
            raise e

    def close(self):
        """Cierra la conexión si está abierta."""
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

    def clean_agent_extension(self, channel_str):
        """
        Limpia la cadena de canal o agente para extraer sólo la extensión.
        Ejemplos:
        - "PJSIP/2005-000001a" -> "2005"
        - "SIP/2001-abc" -> "2001"
        - "Local/2005@from-queue/n" -> "2005"
        - "Agent/3001" -> "3001"
        """
        if not channel_str:
            return ""
        
        parsed = channel_str
        # Si tiene un '/', tomamos la parte derecha
        if '/' in parsed:
            parsed = parsed.split('/')[1]
        # Si tiene un '-', tomamos la parte izquierda
        if '-' in parsed:
            parsed = parsed.split('-')[0]
        # Si tiene un '@', tomamos la parte izquierda
        if '@' in parsed:
            parsed = parsed.split('@')[0]
        
        return parsed.strip()

    def _get_phone_to_lead_map(self):
        """Obtiene un mapeo de números de teléfono normalizados a leads de Django."""
        try:
            from leads.models import Lead
            from leads.ami import normalize_phone_number
            
            leads = Lead.objects.exclude(telefono__isnull=True).exclude(telefono='')
            phone_map = {}
            for lead in leads:
                norm = normalize_phone_number(lead.telefono)
                if norm:
                    # Usar los últimos 9 dígitos para coincidir sin prefijos nacionales
                    key = norm[-9:] if len(norm) >= 9 else norm
                    phone_map[key] = {
                        "id": lead.id,
                        "kommo_id": lead.kommo_id,
                        "nombre": lead.nombre,
                        "telefono_original": lead.telefono
                    }
            return phone_map
        except Exception as e:
            logger.error(f"Error al obtener mapa de teléfonos a leads: {e}")
            return {}

    def _find_lead_for_number(self, phone_str, phone_to_lead_map):
        """Busca un lead en el mapa usando el número de teléfono."""
        if not phone_str:
            return None
            
        from leads.ami import normalize_phone_number
        norm = normalize_phone_number(phone_str)
        if not norm:
            return None
            
        key = norm[-9:] if len(norm) >= 9 else norm
        return phone_to_lead_map.get(key)

    def get_queue_report(self, start_date=None, end_date=None, queue=None, agent=None, status_filter=None, search=None):

        """
        Consulta la base de datos de Asterisk para traer las llamadas cursadas por colas.
        Si la conexión falla, delega en get_mock_queue_report().
        """
        is_mock = False
        error_message = None
        calls = []
        phone_map = self._get_phone_to_lead_map()

        try:
            self.connect()
            cursor = self.connection.cursor()

            # Consulta base sobre la tabla cdr de Asterisk
            # Buscaremos llamadas donde dst coincida con el queue (ej: 3000)
            # o lastapp sea 'Queue' (que indica que pasó por cola)
            query = """
                SELECT 
                    uniqueid,
                    calldate AS date,
                    src AS caller,
                    dst AS destination,
                    dstchannel AS agent_channel,
                    duration AS total_duration,
                    billsec AS talk_time,
                    (duration - billsec) AS wait_time,
                    disposition AS status,
                    recordingfile,
                    lastdata
                FROM cdr
                WHERE 1=1
            """
            params = []

            # Aplicar filtros
            if queue:
                # Si se especifica una cola
                query += " AND (dst = %s OR lastdata LIKE %s)"
                params.extend([queue, f"{queue},%"])
            else:
                # Por defecto, asumimos colas típicas (3000, 4000, etc.) o llamadas a través de la app Queue
                query += " AND (lastapp = 'Queue' OR dst REGEXP '^[0-9]{4}$')"

            if start_date:
                query += " AND calldate >= %s"
                params.append(f"{start_date} 00:00:00")
            if end_date:
                query += " AND calldate <= %s"
                params.append(f"{end_date} 23:59:59")

            if agent:
                # Buscar agente en dstchannel
                query += " AND (dstchannel LIKE %s OR channel LIKE %s)"
                params.extend([f"%{agent}%", f"%{agent}%"])

            if status_filter:
                if status_filter == 'ANSWERED':
                    query += " AND disposition = 'ANSWERED'"
                elif status_filter == 'ABANDONED':
                    # En CDR general de Asterisk, las llamadas abandonadas en cola
                    # usualmente quedan como 'NO ANSWER' o 'BUSY'
                    query += " AND disposition IN ('NO ANSWER', 'BUSY')"
                elif status_filter == 'FAILED':
                    query += " AND disposition = 'FAILED'"
            
            if search:
                query += " AND (src LIKE %s OR dstchannel LIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])

            # Ordenar por fecha descendente
            query += " ORDER BY calldate DESC LIMIT 500"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            for row in rows:
                # Extraer la cola
                # Si lastdata contiene algo como "3000,t,,,,,", extraemos "3000"
                extracted_queue = row['destination']
                lastdata = row['lastdata'] or ""
                if ',' in lastdata:
                    parts = lastdata.split(',')
                    if parts[0].isdigit():
                        extracted_queue = parts[0]

                # Limpiar el agente
                clean_agent = self.clean_agent_extension(row['agent_channel'])
                
                # Mapear estados para que sean amigables
                raw_status = row['status']
                mapped_status = raw_status
                if raw_status == 'NO ANSWER':
                    # Si no contestó en una cola, usualmente es abandonada por el cliente
                    mapped_status = 'ABANDONED'
                elif raw_status == 'BUSY':
                    mapped_status = 'BUSY'
                elif raw_status == 'ANSWERED':
                    mapped_status = 'ANSWERED'
                else:
                    mapped_status = 'FAILED'

                # Formatear la fecha
                call_date = row['date']
                if isinstance(call_date, datetime.datetime):
                    call_date = call_date.isoformat()

                # Buscar lead para el número
                lead_info = self._find_lead_for_number(row['caller'], phone_map)
                if not lead_info:
                    lead_info = self._find_lead_for_number(row['destination'], phone_map)

                kommo_id = lead_info["kommo_id"] if lead_info else None
                lead_name = lead_info["nombre"] if lead_info else None
                lead_id = lead_info["id"] if lead_info else None

                calls.append({
                    "id": row['uniqueid'] or str(random.random()),
                    "date": call_date,
                    "caller": row['caller'],
                    "destination": row['destination'],
                    "queue": extracted_queue,
                    "agent": clean_agent or None,
                    "duration": int(row['total_duration'] or 0),
                    "talk_time": int(row['talk_time'] or 0),
                    "wait_time": max(0, int(row['wait_time'] or 0)),
                    "status": mapped_status,
                    "recording_file": row['recordingfile'] or None,
                    "kommo_id": kommo_id,
                    "lead_name": lead_name,
                    "lead_id": lead_id
                })


        except Exception as e:
            is_mock = True
            error_message = str(e)
            logger.warning(f"Usando datos de reporte simulados por error de conexión: {error_message}")
            calls = self.get_mock_queue_report(
                start_date=start_date,
                end_date=end_date,
                queue=queue,
                agent=agent,
                status_filter=status_filter,
                search=search,
                phone_map=phone_map
            )
        finally:
            self.close()

        # Calcular sumarios basados en la lista final obtenida
        total_calls = len(calls)
        answered_calls = sum(1 for c in calls if c['status'] == 'ANSWERED')
        abandoned_calls = sum(1 for c in calls if c['status'] == 'ABANDONED')
        failed_calls = sum(1 for c in calls if c['status'] not in ('ANSWERED', 'ABANDONED'))
        
        # Calcular promedios
        avg_wait_time = 0
        avg_talk_time = 0
        if total_calls > 0:
            avg_wait_time = round(sum(c['wait_time'] for c in calls) / total_calls, 1)
        
        answered_with_talk = [c for c in calls if c['status'] == 'ANSWERED' and c['talk_time'] > 0]
        if len(answered_with_talk) > 0:
            avg_talk_time = round(sum(c['talk_time'] for c in answered_with_talk) / len(answered_with_talk), 1)

        return {
            "summary": {
                "total_calls": total_calls,
                "answered_calls": answered_calls,
                "abandoned_calls": abandoned_calls,
                "failed_calls": failed_calls,
                "answer_rate": round((answered_calls / total_calls * 100), 1) if total_calls > 0 else 0,
                "avg_wait_time": avg_wait_time,
                "avg_talk_time": avg_talk_time
            },
            "calls": calls,
            "is_mock": is_mock,
            "error_message": error_message
        }

    def get_mock_queue_report(self, start_date=None, end_date=None, queue=None, agent=None, status_filter=None, search=None, phone_map=None):
        """Generador de datos simulados realistas para el reporte."""
        mock_calls = []
        
        # Definir agentes y números de prueba
        mock_agents = ["2001", "2002", "2003", "2004", "2005"]
        if agent:
            mock_agents = [agent]
            
        mock_queues = ["3000", "4000"]
        if queue:
            mock_queues = [queue]

        # Fechas
        today = datetime.datetime.now()
        start = today - datetime.timedelta(days=7)
        if start_date:
            try:
                start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                pass
        
        end = today
        if end_date:
            try:
                end = datetime.datetime.strptime(end_date, "%Y-%m-%d")
                # Poner fin del día
                end = end.replace(hour=23, minute=59, second=59)
            except ValueError:
                pass

        # Generar alrededor de 40 llamadas aleatorias distribuidas
        delta_seconds = int((end - start).total_seconds())
        if delta_seconds <= 0:
            delta_seconds = 86400
        
        # Semilla estable para que los reportes no cambien drásticamente entre llamadas consecutivas del mismo día
        random.seed(int(start.timestamp()))

        statuses = ['ANSWERED', 'ANSWERED', 'ANSWERED', 'ABANDONED', 'ANSWERED', 'ABANDONED', 'FAILED']
        
        first_names = ["Juan", "Maria", "Carlos", "Ana", "Jose", "Luis", "Patricia", "Pedro", "Gabriela", "Javier"]
        last_names = ["Perez", "Rodriguez", "Gomez", "Gonzalez", "Hernandez", "Diaz", "Martinez", "Sanchez", "Alvarez", "Torres"]

        # Convertir el mapa de leads en una lista para selección aleatoria
        leads_list = list(phone_map.values()) if phone_map else []

        for i in range(45):
            # Timestamp aleatorio en el rango
            offset = random.randint(0, delta_seconds)
            call_time = start + datetime.timedelta(seconds=offset)
            
            # Elegir cola, agente y estado
            chosen_queue = random.choice(mock_queues)
            chosen_status = random.choice(statuses)
            
            if chosen_status == 'ANSWERED':
                chosen_agent = random.choice(mock_agents)
                wait_time = random.randint(5, 45)       # Tiempos de espera cortos para contestadas
                talk_time = random.randint(30, 600)     # Conversación entre 30s y 10m
                duration = wait_time + talk_time
            elif chosen_status == 'ABANDONED':
                chosen_agent = None
                wait_time = random.randint(10, 120)     # Tiempos de espera antes de colgar
                talk_time = 0
                duration = wait_time
            else:
                chosen_agent = None
                wait_time = random.randint(10, 30)
                talk_time = 0
                duration = wait_time

            # Decidir si usamos un lead real o inventamos uno
            matched_lead = None
            if leads_list and random.random() < 0.6:  # 60% de probabilidad de usar un lead real
                matched_lead = random.choice(leads_list)
                caller_num = matched_lead["telefono_original"] or ""
                caller_name = matched_lead["nombre"] or "Cliente Sin Nombre"
                caller_id = f'"{caller_name}" <{caller_num}>'
            else:
                # Formatear cliente aleatorio
                country_code = random.choice(["58", "57", "1", "34"])
                area = random.randint(412, 426)
                number = random.randint(1000000, 9999999)
                caller_num = f"+{country_code}{area}{number}"
                
                # Nombre aleatorio
                caller_name = f"{random.choice(first_names)} {random.choice(last_names)}"
                caller_id = f'"{caller_name}" <{caller_num}>'

            # Aplicar filtros específicos en el bucle generador para simular búsqueda exacta
            if status_filter and chosen_status != status_filter:
                continue
                
            if search:
                # Comprobar si coincide con caller o agente
                search_lower = search.lower()
                matches = (
                    search_lower in caller_num.lower() or 
                    search_lower in caller_name.lower() or
                    (chosen_agent and search_lower in chosen_agent.lower())
                )
                if not matches:
                    continue

            # Nombre del archivo de grabación simulado si contestó
            recording = None
            if chosen_status == 'ANSWERED' and talk_time > 15:
                date_str = call_time.strftime("%Y%m%d-%H%M%S")
                recording = f"q-{chosen_queue}-{caller_num}-{date_str}.wav"

            mock_calls.append({
                "id": f"mock-{call_time.timestamp()}-{i}",
                "date": call_time.isoformat(),
                "caller": caller_id,
                "destination": chosen_queue,
                "queue": chosen_queue,
                "agent": chosen_agent,
                "duration": duration,
                "talk_time": talk_time,
                "wait_time": wait_time,
                "status": chosen_status,
                "recording_file": recording,
                "kommo_id": matched_lead["kommo_id"] if matched_lead else None,
                "lead_name": matched_lead["nombre"] if matched_lead else None,
                "lead_id": matched_lead["id"] if matched_lead else None
            })


        # Ordenar descendente por fecha
        mock_calls.sort(key=lambda x: x['date'], reverse=True)
        return mock_calls
