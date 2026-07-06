import urllib.request
import urllib.parse
import sys

# URL del webhook local en Django
URL_WEBHOOK = "http://127.0.0.1:8000/api/webhook/kommo/"

# Payload que simula exactamente la estructura urlencoded enviada por Kommo
payload_prueba = {
    'account[subdomain]': 'rusvenezoficial',
    'account[id]': '36398783',
    'account[_links][self]': 'https://rusvenezoficial.amocrm.com',
    'contacts[add][0][id]': '43684612',
    'contacts[add][0][name]': 'wilmermendez',
    'contacts[add][0][responsible_user_id]': '0',
    'contacts[add][0][group_id]': '-1',
    'contacts[add][0][date_create]': '1783305452',
    'contacts[add][0][last_modified]': '1783305452',
    'contacts[add][0][created_user_id]': '0',
    'contacts[add][0][modified_user_id]': '15179615',
    'contacts[add][0][account_id]': '36398783',
    'contacts[add][0][custom_fields][0][id]': '2031462',
    'contacts[add][0][custom_fields][0][name]': 'Teléfono',
    'contacts[add][0][custom_fields][0][values][0][value]': '2001',
    'contacts[add][0][custom_fields][0][values][0][enum]': '1364056',
    'contacts[add][0][custom_fields][0][code]': 'PHONE',
    'contacts[add][0][linked_leads_id][35144366][ID]': '35144366',
    'contacts[add][0][created_at]': '1783305452',
    'contacts[add][0][updated_at]': '1783305452',
    'contacts[add][0][type]': 'contact'
}

def enviar_webhook_prueba():
    print("================================================================")
    print("  SIMULADOR DE WEBHOOK KOMMO -> DJANGO + CELERY + ASTERISK  ")
    print("================================================================\n")
    
    # Codificar los datos en formato x-www-form-urlencoded
    data_encoded = urllib.parse.urlencode(payload_prueba).encode('utf-8')
    
    req = urllib.request.Request(URL_WEBHOOK, data=data_encoded, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    
    try:
        print(f"[1/3] Enviando petición POST simulada a: {URL_WEBHOOK}")
        print(f"      Nombre: {payload_prueba['contacts[add][0][name]']}")
        print(f"      Teléfono original: {payload_prueba['contacts[add][0][custom_fields][0][values][0][value]']}")
        print(f"      ID de Lead asociado: {payload_prueba['contacts[add][0][linked_leads_id][35144366][ID]']}")
        print("-" * 64)
        
        with urllib.request.urlopen(req) as response:
            status_code = response.getcode()
            response_body = response.read().decode('utf-8')
            
            print(f"[2/3] Respuesta HTTP recibida: {status_code}")
            print(f"      Contenido: {response_body}")
            print("-" * 64)
            print("[3/3] ¡Éxito! La petición fue entregada de forma asíncrona a Django.")
            print("      Ahora revisa la terminal donde se está ejecutando './run_services.sh'.")
            print("      Allí deberías ver:")
            print("        - El guardado del Lead en la BD (Supabase).")
            print("        - El encolamiento de la tarea en Celery.")
            print("        - La conexión por Socket e intento de llamada en Asterisk.")
            
    except urllib.error.URLError as e:
        print(f"\n[ERROR] No se pudo establecer conexión con el servidor Django.")
        print(f"        Detalle: {e}")
        print("\n[CONSEJO] Asegúrate de iniciar primero los servicios ejecutando:")
        print("          ./run_services.sh")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Ocurrió un error inesperado durante la ejecución: {e}")
        sys.exit(1)

if __name__ == "__main__":
    enviar_webhook_prueba()
