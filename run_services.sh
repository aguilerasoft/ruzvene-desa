#!/bin/bash

# Guardar el directorio actual del proyecto
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "========================================="
echo "  Iniciando Servicios de Rusvenez Backend"
echo "========================================="

# Array para guardar PIDs de los procesos en segundo plano
PIDS=()

# Función para detener todos los procesos en segundo plano al salir
cleanup() {
    echo -e "\n\n========================================="
    echo "  Deteniendo servicios en segundo plano..."
    echo "========================================="
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "Deteniendo proceso con PID: $pid..."
            kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
        fi
    done
    echo "Servicios detenidos."
    exit 0
}

# Capturar Ctrl+C (SIGINT), SIGTERM y salida normal
trap cleanup EXIT INT TERM

# 1. Iniciar Redis (si no está ya corriendo)
if command -v redis-server &> /dev/null; then
    if nc -z localhost 6379 2>/dev/null; then
        echo "[Redis] -> Redis ya está corriendo en el puerto 6379."
    else
        echo "[Redis] -> Iniciando redis-server..."
        redis-server --daemonize yes 2>/dev/null || redis-server &
        # Si se corrió en background directo, guardar el PID
        if [ $? -eq 0 ]; then
            # Buscar el PID de redis si fue daemonized o guardarlo si fue directo
            sleep 1
            REDIS_PID=$(pgrep redis-server)
            if [ ! -z "$REDIS_PID" ]; then
                PIDS+=($REDIS_PID)
            fi
            echo "[Redis] -> redis-server iniciado con éxito."
        fi
    fi
else
    echo "[Redis] -> [ADVERTENCIA] 'redis-server' no está instalado en el sistema. Asegúrate de que Redis esté corriendo externamente."
fi

# 2. Iniciar Celery Worker
if [ -f ".venv/bin/celery" ]; then
    echo "[Celery] -> Iniciando worker de Celery..."
    .venv/bin/celery -A core worker --loglevel=info -B &
    CELERY_PID=$!
    PIDS+=($CELERY_PID)
    sleep 1
else
    echo "[Celery] -> [ERROR] No se encontró Celery en el entorno virtual (.venv/bin/celery)."
    exit 1
fi

# 3. Iniciar Django Development Server
if [ -f ".venv/bin/python" ]; then
    echo "[Django] -> Iniciando servidor en http://localhost:8000..."
    echo "Presiona Ctrl+C para detener todos los servicios simultáneamente."
    echo "---------------------------------------------------------"
    .venv/bin/python manage.py runserver 0.0.0.0:8000
else
    echo "[Django] -> [ERROR] No se encontró Python en el entorno virtual (.venv/bin/python)."
    exit 1
fi
