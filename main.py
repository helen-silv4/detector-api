import logging
import os
import time
import json

from fastapi import FastAPI, HTTPException
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
    gerador = teste_realizar_voo() if DRONE_MODE == "real" else teste_simular_voo()
    return StreamingResponse(gerador, media_type="application/x-ndjson")

@app.post("/testes/video")
def teste_executar_video():
    gerador = teste_realizar_video() if DRONE_MODE == "real" else teste_simular_video()
    return StreamingResponse(gerador, media_type="application/x-ndjson")

@app.post("/testes/voo-video")
def teste_executar_voo_video():
    gerador = decolar_com_video_sem_pouso_automatico() if DRONE_MODE == "real" else teste_simular_voo_video()
    return StreamingResponse(gerador, media_type="application/x-ndjson")

@app.get("/deteccao/stream")
def iniciar_stream_deteccao():
    if DRONE_MODE != "real":
        raise HTTPException(
            status_code=503,
            detail="Stream indisponível em modo mock. Rode com DRONE_MODE=real."
        )

    logger.info("Iniciando stream de detecção de resíduos...")
    return StreamingResponse(
        gerar_stream_deteccao(drone_global),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )

# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

def teste_simular_voo():
    yield json.dumps({"log": "[SYS] Conectando ao drone (simulado)..."}) + "\n"
    yield json.dumps({"log": "[SYS] Bateria: 85%"}) + "\n"
    yield json.dumps({"log": "[SYS] Decolando..."}) + "\n"
    time.sleep(1)
    yield json.dumps({"log": "[SYS] Voo estabilizado."}) + "\n"
    yield json.dumps({"log": "[SYS] Pousando..."}) + "\n"
    yield json.dumps({"log": "[SYS] Pouso concluído com sucesso.", "status": "sucesso"}) + "\n"

def teste_simular_video():
    yield json.dumps({"log": "[SYS] Conectando ao drone (simulado)..."}) + "\n"
    yield json.dumps({"log": "[VID] Ativando stream de vídeo..."}) + "\n"
    time.sleep(1)
    yield json.dumps({"log": "[VID] Stream recebido com sucesso."}) + "\n"
    yield json.dumps({"log": "[SYS] Encerrando stream.", "status": "sucesso"}) + "\n"

def teste_simular_voo_video():
    yield json.dumps({"log": "[SYS] Conectando ao drone (simulado)..."}) + "\n"
    yield json.dumps({"log": "[VID] Ativando stream de vídeo..."}) + "\n"
    yield json.dumps({"log": "[SYS] Decolando..."}) + "\n"
    time.sleep(1)
    yield json.dumps({"log": "[SYS] Voo estabilizado, vídeo ativo em paralelo."}) + "\n"
    yield json.dumps({"log": "[SYS] Pousando..."}) + "\n"
    yield json.dumps({"log": "[SYS] Pouso concluído com sucesso.", "status": "sucesso"}) + "\n"

def teste_realizar_voo():
    try:
        yield json.dumps({"log": "[SYS] Conectando ao drone..."}) + "\n"
        drone_global.connect()

        bateria = drone_global.get_battery()
        yield json.dumps({"log": f"[SYS] Bateria: {bateria}%"}) + "\n"

        if bateria < 20:
            yield json.dumps({"log": "[SYS] Bateria abaixo de 20%. Abortando decolagem.", "status": "erro"}) + "\n"
            return

        yield json.dumps({"log": "[SYS] Decolando..."}) + "\n"
        drone_global.takeoff()

        time.sleep(5)
        yield json.dumps({"log": "[SYS] Voo estabilizado."}) + "\n"

        yield json.dumps({"log": "[SYS] Pousando..."}) + "\n"
        drone_global.land()
        yield json.dumps({"log": "[SYS] Pouso concluído com sucesso.", "status": "sucesso"}) + "\n"

    except Exception as e:
        yield json.dumps({"log": f"[ERRO] {e}", "status": "erro"}) + "\n"

def teste_realizar_video():
    try:
        yield json.dumps({"log": "[SYS] Conectando ao drone..."}) + "\n"
        drone_global.connect()

        yield json.dumps({"log": "[VID] Ativando stream de vídeo..."}) + "\n"
        drone_global.streamon()
        time.sleep(2)

        frame_read = drone_global.get_frame_read()
        frame = frame_read.frame

        if frame is not None and frame.size > 0:
            yield json.dumps({"log": f"[VID] Frame recebido com sucesso ({frame.shape[1]}x{frame.shape[0]}px)."}) + "\n"
            status = "sucesso"
        else:
            yield json.dumps({"log": "[ERRO] Nenhum frame recebido do stream."}) + "\n"
            status = "erro"

        yield json.dumps({"log": "[SYS] Encerrando stream.", "status": status}) + "\n"

    except Exception as e:
        yield json.dumps({"log": f"[ERRO] {e}", "status": "erro"}) + "\n"
    finally:
        try:
            drone_global.streamoff()
        except Exception:
            pass

def decolar_com_video_sem_pouso_automatico():
    try:
        yield json.dumps({"log": "[SYS] Conectando ao drone..."}) + "\n"
        drone_global.connect()

        bateria = drone_global.get_battery()
        yield json.dumps({"log": f"[SYS] Bateria: {bateria}%"}) + "\n"

        if bateria < 20:
            yield json.dumps({"log": "[SYS] Bateria abaixo de 20%. Abortando decolagem.", "status": "erro"}) + "\n"
            return

        yield json.dumps({"log": "[SYS] Decolando..."}) + "\n"
        drone_global.takeoff()
        yield json.dumps({"log": "[SYS] Decolagem realizada com sucesso.", "status": "sucesso"}) + "\n"

    except Exception as e:
        yield json.dumps({"log": f"[ERRO] {e}", "status": "erro"}) + "\n"

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
    if DRONE_MODE != "real":
        return {"status": "ok", "modo": "mock"}

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
    if DRONE_MODE != "real":
        return {"status": "sucesso", "logs": ["[SYS] Pouso de emergência simulado (modo mock)."]}

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
    