import logging
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from djitellopy import Tello

from deteccao_stream import gerar_stream_deteccao

# Instância global (Singleton) do drone — compartilhada entre todas as rotas
# para evitar conflito de portas UDP ao criar múltiplos Tello().

logger = logging.getLogger(__name__)
drone_global = Tello()
app = FastAPI(title="Drone Waste Monitoring - API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DRONE_MODE = os.getenv("DRONE_MODE", "mock")

# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "drone_mode": DRONE_MODE}

@app.post("/testes/voo")
def teste_executar_voo():
    if DRONE_MODE == "real":
        return teste_realizar_voo()
    return teste_simular_voo()

@app.post("/testes/video")
def teste_executar_video():
    if DRONE_MODE == "real":
        return teste_realizar_video()
    return teste_simular_video()

@app.post("/testes/voo-video")
def teste_executar_voo_video():
    if DRONE_MODE == "real":
        return decolar_com_video_sem_pouso_automatico()
    return teste_simular_voo_video()

@app.get("/deteccao/stream")
def iniciar_stream_deteccao():
    logger.info("Iniciando stream de detecção de resíduos...")
    return StreamingResponse(
        gerar_stream_deteccao(drone_global),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )

# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

def teste_simular_voo():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[SYS] Bateria: 85%")
    logs.append("[SYS] Decolando...")
    time.sleep(1)
    logs.append("[SYS] Voo estabilizado.")
    logs.append("[SYS] Pousando...")
    logs.append("[SYS] Pouso concluído com sucesso.")
    return {"status": "sucesso", "logs": logs}

def teste_simular_video():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[VID] Ativando stream de vídeo...")
    time.sleep(1)
    logs.append("[VID] Stream recebido com sucesso.")
    logs.append("[SYS] Encerrando stream.")
    return {"status": "sucesso", "logs": logs}

def teste_simular_voo_video():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[VID] Ativando stream de vídeo...")
    logs.append("[SYS] Decolando...")
    time.sleep(1)
    logs.append("[SYS] Voo estabilizado, vídeo ativo em paralelo.")
    logs.append("[SYS] Pousando...")
    logs.append("[SYS] Pouso concluído com sucesso.")
    return {"status": "sucesso", "logs": logs}

def teste_realizar_voo():
    logs = []
    try:
        logs.append("[SYS] Conectando ao drone...")
        drone_global.connect()

        bateria = drone_global.get_battery()
        logs.append(f"[SYS] Bateria: {bateria}%")

        if bateria < 20:
            logs.append("[SYS] Bateria abaixo de 20%. Abortando decolagem.")
            return {"status": "erro", "logs": logs}

        logs.append("[SYS] Decolando...")
        drone_global.takeoff()

        time.sleep(5)
        logs.append("[SYS] Voo estabilizado.")

        logs.append("[SYS] Pousando...")
        drone_global.land()
        logs.append("[SYS] Pouso concluído com sucesso.")

        return {"status": "sucesso", "logs": logs}

    except Exception as e:
        logs.append(f"[ERRO] {e}")
        return {"status": "erro", "logs": logs}

def teste_realizar_video():
    logs = []
    try:
        logs.append("[SYS] Conectando ao drone...")
        drone_global.connect()

        logs.append("[VID] Ativando stream de vídeo...")
        drone_global.streamon()
        time.sleep(2)  # aguarda o hardware da câmera estabilizar

        frame_read = drone_global.get_frame_read()
        frame = frame_read.frame

        if frame is not None and frame.size > 0:
            logs.append(f"[VID] Frame recebido com sucesso ({frame.shape[1]}x{frame.shape[0]}px).")
            status = "sucesso"
        else:
            logs.append("[ERRO] Nenhum frame recebido do stream.")
            status = "erro"

        return {"status": status, "logs": logs}

    except Exception as e:
        logs.append(f"[ERRO] {e}")
        return {"status": "erro", "logs": logs}

    finally:
        try:
            drone_global.streamoff()
        except Exception:
            pass
        logs.append("[SYS] Encerrando stream.")

def decolar_com_video_sem_pouso_automatico():
    # Não pousa sozinho de propósito: o pouso fica a cargo de /emergencia,
    # já que este endpoint mantém o drone voando com vídeo ativo.
    logs = []
    try:
        drone_global.connect()

        bateria = drone_global.get_battery()
        logs.append(f"[SYS] Bateria: {bateria}%")

        if bateria < 20:
            logs.append("[SYS] Bateria abaixo de 20%. Abortando decolagem.")
            return {"status": "erro", "logs": logs}

        logs.append("[SYS] Decolando...")
        drone_global.takeoff()
        logs.append("[SYS] Decolagem realizada com sucesso.")

        return {"status": "sucesso", "logs": logs}

    except Exception as e:
        logs.append(f"[ERRO] {e}")
        return {"status": "erro", "logs": logs}

# ---------------------------------------------------------------------------
# Comando
# ---------------------------------------------------------------------------

class ComandoRC(BaseModel):
    lr: int  # left/right
    fb: int  # forward/backward
    ud: int  # up/down
    yv: int  # yaw velocity

@app.post("/controle")
def enviar_comando_rc(comando: ComandoRC):
    try:
        drone_global.send_rc_control(comando.lr, comando.fb, comando.ud, comando.yv)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Erro ao enviar controle RC.")
        return {"status": "erro", "erro": str(e)}

# ---------------------------------------------------------------------------
# Emergência
# ---------------------------------------------------------------------------

@app.post("/emergencia")
def pousar_emergencialmente():
    logs = []
    try:
        if drone_global.is_flying:
            logs.append("[SYS] Drone em voo - enviando comando de pouso...")
            drone_global.land()
            logs.append("[SYS] Pouso realizado com sucesso.")
        else:
            logs.append("[SYS] Drone já está no solo.")

        return {"status": "sucesso", "logs": logs}

    except Exception as e:
        logger.exception("Erro ao pousar o drone.")
        logs.append(f"[ERRO] {e}")
        return {"status": "erro", "logs": logs}
    