import logging
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from djitellopy import Tello

from deteccao_stream import gerar_stream_deteccao

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Instância global (Singleton) do drone — compartilhada entre todas as rotas
# para evitar conflito de portas UDP ao criar múltiplos Tello().
# ---------------------------------------------------------------------------
drone_global = Tello()

app = FastAPI(title="Drone Waste Monitoring - API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DRONE_MODE = "real"  # mock ou real

@app.get("/health")
def health():
    return {"status": "ok", "drone_mode": DRONE_MODE}

@app.post("/testes/voo")
def teste_voo():
    if DRONE_MODE == "real":
        return teste_voo_real()
    return teste_voo_mock()

@app.post("/testes/video")
def teste_video():
    if DRONE_MODE == "real":
        return teste_video_real()
    return teste_video_mock()

@app.post("/testes/voo-video")
def teste_voo_video():
    if DRONE_MODE == "real":
        return teste_voo_video_real()
    return teste_voo_video_mock()


# ---------------------------------------------------------------------------
# Rota de detecção de resíduos com stream MJPEG em tempo real
# ---------------------------------------------------------------------------

@app.get("/deteccao/stream")
def deteccao_stream():
    """
    Stream MJPEG com detecção de resíduos em tempo real via YOLOv8.
    Usa a instância global do Tello para evitar conflitos de porta UDP.
    """
    logger.info("Iniciando stream de detecção de resíduos...")
    return StreamingResponse(
        gerar_stream_deteccao(drone_global),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def teste_voo_mock():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[SYS] Bateria: 85%")
    logs.append("[SYS] Decolando...")
    time.sleep(1)
    logs.append("[SYS] Voo estabilizado.")
    logs.append("[SYS] Pousando...")
    logs.append("[SYS] Pouso concluído com sucesso.")
    return {"status": "sucesso", "logs": logs}

def teste_video_mock():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[VID] Ativando stream de vídeo...")
    time.sleep(1)
    logs.append("[VID] Stream recebido com sucesso.")
    logs.append("[SYS] Encerrando stream.")
    return {"status": "sucesso", "logs": logs}

def teste_voo_video_mock():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[VID] Ativando stream de vídeo...")
    logs.append("[SYS] Decolando...")
    time.sleep(1)
    logs.append("[SYS] Voo estabilizado, vídeo ativo em paralelo.")
    logs.append("[SYS] Pousando...")
    logs.append("[SYS] Pouso concluído com sucesso.")
    return {"status": "sucesso", "logs": logs}


def teste_voo_real():
    logs = []
    tello = Tello()
    try:
        logs.append("[SYS] Conectando ao drone...")
        tello.connect()

        bateria = tello.get_battery()
        logs.append(f"[SYS] Bateria: {bateria}%")

        if bateria < 20:
            logs.append("[SYS] Bateria abaixo de 20%. Abortando decolagem.")
            return {"status": "erro", "logs": logs}

        logs.append("[SYS] Decolando...")
        tello.takeoff()

        time.sleep(5)
        logs.append("[SYS] Voo estabilizado.")

        logs.append("[SYS] Pousando...")
        tello.land()
        logs.append("[SYS] Pouso concluído com sucesso.")

        return {"status": "sucesso", "logs": logs}

    except Exception as e:
        logs.append(f"[ERRO] {e}")
        return {"status": "erro", "logs": logs}

    finally:
        tello.end()

def teste_video_real():
    logs = []
    tello = Tello()
    try:
        logs.append("[SYS] Conectando ao drone...")
        tello.connect()

        logs.append("[VID] Ativando stream de vídeo...")
        tello.streamon()
        time.sleep(2)  # aguarda o hardware da câmera estabilizar

        frame_read = tello.get_frame_read()
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
            tello.streamoff()
        except Exception:
            pass
        tello.end()
        logs.append("[SYS] Encerrando stream.")

def teste_voo_video_real():
    """
    Executa apenas a decolagem usando a instância global do drone.
    O pouso é responsabilidade exclusiva da rota POST /emergencia.
    """
    logs = []
    try:
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
# Rota de emergência — pouso imediato
# ---------------------------------------------------------------------------

@app.post("/emergencia")
def emergencia():
    """Pouso de emergência. Envia o comando land() para o drone."""
    logs = []
    try:
        if drone_global.is_flying:
            logs.append("[SYS] Drone em voo — enviando comando de pouso...")
            drone_global.land()
            logs.append("[SYS] Pouso realizado com sucesso.")
        else:
            logs.append("[SYS] Drone já está no solo.")

        return {"status": "sucesso", "logs": logs}

    except Exception as e:
        logger.exception("Erro ao pousar o drone.")
        logs.append(f"[ERRO] {e}")
        return {"status": "erro", "logs": logs}


# ---------------------------------------------------------------------------
# Modelo e rota de controle manual (RC) via teclado
# ---------------------------------------------------------------------------

class ControleRC(BaseModel):
    lr: int  # left/right
    fb: int  # forward/backward
    ud: int  # up/down
    yv: int  # yaw velocity


@app.post("/controle")
def controle_rc(cmd: ControleRC):
    """Envia comando RC (send_rc_control) para o drone."""
    try:
        drone_global.send_rc_control(cmd.lr, cmd.fb, cmd.ud, cmd.yv)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Erro ao enviar controle RC.")
        return {"status": "erro", "erro": str(e)}