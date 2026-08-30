import os
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from djitellopy import Tello

app = FastAPI(title="Drone Waste Monitoring - API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DRONE_MODE = os.getenv("DRONE_MODE", "mock")  # mock ou real

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

        logs.append("[VID] Ativando stream de vídeo...")
        tello.streamon()
        time.sleep(2)

        logs.append("[SYS] Decolando...")
        tello.takeoff()
        time.sleep(5)
        logs.append("[SYS] Voo estabilizado, vídeo ativo em paralelo.")

        logs.append("[SYS] Pousando...")
        tello.land()
        logs.append("[SYS] Pouso concluído com sucesso.")

        return {"status": "sucesso", "logs": logs}

    except Exception as e:
        logs.append(f"[ERRO] {e}")
        return {"status": "erro", "logs": logs}

    finally:
        try:
            tello.streamoff()
        except Exception:
            pass
        tello.end()