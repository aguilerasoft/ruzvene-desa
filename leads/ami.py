import re
import socket
import logging

logger = logging.getLogger(__name__)

def normalize_phone_number(phone_str):
    """
    Normaliza el número de teléfono removiendo espacios, 
    caracteres especiales y el símbolo '+'
    """
    if not phone_str:
        return ""
    # Remueve todo lo que no sea un dígito numérico
    return re.sub(r'\D', '', phone_str)

class AMIClient:
    """
    Cliente socket TCP nativo para interactuar con la interfaz
    Asterisk Manager Interface (AMI) de FreePBX/Asterisk.
    """
    def __init__(self, host, port, username, secret, timeout=5):
        self.host = host
        self.port = int(port)
        self.username = username
        self.secret = secret
        self.timeout = timeout
        self.socket = None

    def connect(self):
        """Abre la conexión de socket TCP con Asterisk AMI."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            
            # Leer el saludo inicial de Asterisk (e.g. "Asterisk Call Manager/5.0.3")
            greeting = self.socket.recv(1024).decode('utf-8', errors='ignore')
            logger.info(f"Conectado a Asterisk AMI: {greeting.strip()}")
            return True
        except Exception as e:
            logger.error(f"Error al conectar al socket de Asterisk AMI en {self.host}:{self.port} - {e}")
            self.socket = None
            return False

    def send_action(self, action_dict):
        """Codifica y envía un diccionario de acción a través del socket."""
        if not self.socket:
            raise Exception("No hay conexión activa con Asterisk AMI. Llama a connect() primero.")
        
        payload = ""
        for key, val in action_dict.items():
            payload += f"{key}: {val}\r\n"
        payload += "\r\n"  # El protocolo AMI requiere una línea en blanco al final de cada paquete
        
        try:
            self.socket.sendall(payload.encode('utf-8'))
            logger.debug(f"Acción enviada a AMI:\n{payload}")
            
            # Leer respuesta hasta encontrar el delimitador de bloque del protocolo (\r\n\r\n)
            response = ""
            while "\r\n\r\n" not in response:
                chunk = self.socket.recv(1024).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                response += chunk
            logger.debug(f"Respuesta recibida de AMI:\n{response}")
            return response
        except Exception as e:
            logger.error(f"Error al transmitir datos en Asterisk AMI: {e}")
            raise

    def login(self):
        """Realiza el apretón de manos de autenticación (Login)."""
        login_action = {
            "Action": "Login",
            "Username": self.username,
            "Secret": self.secret
        }
        try:
            res = self.send_action(login_action)
            if "Response: Success" in res or "Authentication accepted" in res:
                logger.info(f"Autenticación exitosa en Asterisk AMI para el usuario: {self.username}")
                return True
            else:
                logger.error(f"Fallo de autenticación en Asterisk AMI: {res.strip()}")
                return False
        except Exception as e:
            logger.error(f"Excepción durante login en AMI: {e}")
            return False

    def originate_call(self, phone_number, context="from-internal", exten="3000", priority="1"):
        """
        Envía una acción Originate a Asterisk para marcar el número del lead
        y transferirlo a una extensión cuando conteste.
        """
        # Formato de canal local estándar en FreePBX
        channel = f"Local/{phone_number}@from-internal"
        
        originate_action = {
            "Action": "Originate",
            "Channel": channel,
            "Context": context,
            "Exten": exten,
            "Priority": priority,
            "Async": "true",  # Para no bloquear el socket esperando a que contesten la llamada
            "CallerID": f"Kommo Lead <{phone_number}>"
        }
        
        try:
            logger.info(f"Enviando Originate a {channel} -> Extensión {exten} en contexto {context}")
            res = self.send_action(originate_action)
            if "Response: Success" in res:
                logger.info(f"Acción Originate procesada con éxito para el número: {phone_number}")
                return True
            else:
                logger.error(f"Fallo al originar llamada para {phone_number}: {res.strip()}")
                return False
        except Exception as e:
            logger.error(f"Excepción al originar llamada a {phone_number}: {e}")
            return False

    def disconnect(self):
        """Cierra de forma limpia la sesión y el socket TCP."""
        if self.socket:
            try:
                # Intenta enviar Logoff de forma segura
                logoff_action = {"Action": "Logoff"}
                self.send_action(logoff_action)
            except Exception:
                pass
            finally:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
                logger.info("Conexión con Asterisk AMI cerrada.")
