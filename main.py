from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import time

app = FastAPI(title="Drone Waste Monitoring - API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/testes/voo")
def teste_voo():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[SYS] Bateria: 85%")
    logs.append("[SYS] Decolando...")
    time.sleep(1)
    logs.append("[SYS] Voo estabilizado.")
    logs.append("[SYS] Pousando...")
    logs.append("[SYS] Pouso concluído com sucesso.")
    return {"status": "sucesso", "logs": logs}

@app.post("/testes/video")
def teste_video():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[VID] Ativando stream de vídeo...")
    time.sleep(1)
    logs.append("[VID] Stream recebido com sucesso.")
    logs.append("[SYS] Encerrando stream.")
    return {"status": "sucesso", "logs": logs}

@app.post("/testes/voo-video")
def teste_voo_video():
    logs = []
    logs.append("[SYS] Conectando ao drone (simulado)...")
    logs.append("[VID] Ativando stream de vídeo...")
    logs.append("[SYS] Decolando...")
    time.sleep(1)
    logs.append("[SYS] Voo estabilizado, vídeo ativo em paralelo.")
    logs.append("[SYS] Pousando...")
    logs.append("[SYS] Pouso concluído com sucesso.")
    return {"status": "sucesso", "logs": logs}