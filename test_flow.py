import urllib.request
import urllib.parse
import sys
import time

# URL del webhook local en Django
URL_WEBHOOK = "http://127.0.0.1:8000/api/webhook/kommo/"

# Lista de 3 leads para probar la cola y estados de llamada
leads_prueba = [
    {
        "name": "Cristian Aguilera",
        "phone": "04241222517",
        "contact_id": "43684617913",
        "lead_id": "351443627913"
    }
]

def generar_payload(name, phone, contact_id, lead_id):
    return {
        'account[subdomain]': 'rusvenezoficial',
        'account[id]': '36398783',
        'account[_links][self]': 'https://rusvenezoficial.amocrm.com',
        'contacts[add][0][id]': contact_id,
        'contacts[add][0][name]': name,
        'contacts[add][0][responsible_user_id]': '0',
        'contacts[add][0][group_id]': '-1',
        'contacts[add][0][date_create]': str(int(time.time())),
        'contacts[add][0][last_modified]': str(int(time.time())),
        'contacts[add][0][created_user_id]': '0',
        'contacts[add][0][modified_user_id]': '15179615',
        'contacts[add][0][account_id]': '36398783',
        'contacts[add][0][custom_fields][0][id]': '2031462',
        'contacts[add][0][custom_fields][0][name]': 'Teléfono',
        'contacts[add][0][custom_fields][0][values][0][value]': phone,
        'contacts[add][0][custom_fields][0][values][0][enum]': '1364056',
        'contacts[add][0][custom_fields][0][code]': 'PHONE',
        f'contacts[add][0][linked_leads_id][{lead_id}][ID]': lead_id,
        'contacts[add][0][created_at]': str(int(time.time())),
        'contacts[add][0][updated_at]': str(int(time.time())),
        'contacts[add][0][type]': 'contact'
    }

def enviar_webhooks_prueba():
    print("================================================================")
    print("  SIMULADOR DE WEBHOOK KOMMO (3 REGISTROS) -> DJANGO + CELERY  ")
    print("================================================================\n")
    
    for i, lead in enumerate(leads_prueba, 1):
        payload = generar_payload(lead["name"], lead["phone"], lead["contact_id"], lead["lead_id"])
        data_encoded = urllib.parse.urlencode(payload).encode('utf-8')
        
        req = urllib.request.Request(URL_WEBHOOK, data=data_encoded, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        
        try:
            print(f"[Lead {i}/3] Enviando: {lead['name']} | Teléfono: {lead['phone']} | ID: {lead['lead_id']}")
            
            with urllib.request.urlopen(req) as response:
                status_code = response.getcode()
                response_body = response.read().decode('utf-8')
                print(f"      Respuesta HTTP: {status_code} | Contenido: {response_body}")
                print("-" * 64)
            
            # Esperar un segundo entre peticiones para simular encolamiento
            if i < len(leads_prueba):
                time.sleep(1)
                
        except urllib.error.URLError as e:
            print(f"\n[ERROR] No se pudo establecer conexión con el servidor Django.")
            print(f"        Detalle: {e}")
            print("\n[CONSEJO] Asegúrate de iniciar primero los servicios ejecutando:")
            print("          ./run_services.sh")
            sys.exit(1)
        except Exception as e:
            print(f"\n[ERROR] Ocurrió un error inesperado durante la ejecución: {e}")
            sys.exit(1)

    print("\n¡Éxito! Las 3 peticiones fueron enviadas a Django.")
    print("Revisa la consola del servidor Django/Celery para ver cómo entran en la cola de espera.")

if __name__ == "__main__":
    enviar_webhooks_prueba()
