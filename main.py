import logging
import os
import re
import time

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import cv2
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from djitellopy import Tello

from deteccao_stream import definir_origem, gerar_stream_deteccao, obter_captura

from database import engine, get_db, Base
import crud
import models  # noqa: F401 — registra os modelos na Base
from models import Deteccao

Base.metadata.create_all(bind=engine)

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

# ---------------------------------------------------------------------------
# Arquivos estáticos — imagens das infrações
# O caminho gravado no banco segue o padrão "capturas/drone_frame_<ts>.jpg",
# portanto a pasta "capturas" (ao lado deste arquivo) é exposta em /imagens.
# Ex.: capturas/drone_frame_123.jpg -> http://localhost:8000/imagens/drone_frame_123.jpg
# ---------------------------------------------------------------------------
DIRETORIO_IMAGENS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")
os.makedirs(DIRETORIO_IMAGENS, exist_ok=True)  # StaticFiles falha se a pasta não existir

app.mount("/imagens", StaticFiles(directory=DIRETORIO_IMAGENS), name="imagens")


# ---------------------------------------------------------------------------
# Trava de coordenadas: erros de validação na rota de decolagem viram 400
# (o padrão do FastAPI seria 422). Demais rotas mantêm o comportamento padrão.
# ---------------------------------------------------------------------------
ROTA_DECOLAGEM = "/missao/decolar"
MSG_ERRO_COORDENADAS = "As coordenadas devem conter exatamente 8 casas decimais"


@app.exception_handler(RequestValidationError)
async def tratar_erro_validacao(request: Request, exc: RequestValidationError):
    if request.url.path == ROTA_DECOLAGEM:
        campos = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")})
        return JSONResponse(
            status_code=400,
            content={"detail": MSG_ERRO_COORDENADAS, "campos_invalidos": campos},
        )
    return await request_validation_exception_handler(request, exc)

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
    """
    Endpoint dummy. A conexão real (connect/streamon) é feita exclusivamente
    pelo GET /deteccao/stream, chamado pela tag <img> do Angular.
    """
    return {"status": "ok"}

@app.post("/testes/voo-video")
def teste_voo_video():
    if DRONE_MODE == "real":
        return teste_voo_video_real()
    return teste_voo_video_mock()


# ---------------------------------------------------------------------------
# Decolagem da missão com trava de 8 casas decimais nas coordenadas
# ---------------------------------------------------------------------------

# Mesma regex do frontend. re.ASCII faz \d aceitar apenas 0-9 (sem dígitos Unicode).
REGEX_COORDENADA = re.compile(r"^-?\d+\.\d{8}$", re.ASCII)


class CoordenadasDecolagem(BaseModel):
    """
    As coordenadas são recebidas como *string* de propósito: um float JSON
    perde zeros à direita (-23.52223000 -> -23.52223), o que tornaria
    impossível verificar a quantidade exata de casas decimais.
    Valores numéricos (não-string) são rejeitados pelo Pydantic v2.
    """
    latitude: str
    longitude: str

    @field_validator("latitude", "longitude")
    @classmethod
    def validar_oito_casas(cls, valor: str) -> str:
        if not REGEX_COORDENADA.fullmatch(valor):
            raise ValueError(MSG_ERRO_COORDENADAS)
        return valor


@app.post(ROTA_DECOLAGEM)
def rota_decolar_missao(coords: CoordenadasDecolagem):
    """
    Decola o drone somente após validar as coordenadas (8 casas decimais).
    Coordenadas inválidas retornam 400 via `tratar_erro_validacao`.
    """
    logger.info("Decolagem autorizada em LAT=%s LON=%s", coords.latitude, coords.longitude)
    try:
        definir_origem(float(coords.latitude), float(coords.longitude))
    except Exception as e:
        logger.warning("Falha ao definir origem de decolagem: %s", e)

    resultado = teste_voo_video_real() if DRONE_MODE == "real" else teste_voo_video_mock()
    resultado["logs"].insert(
        0,
        f"[SYS] Coordenadas de decolagem validadas: LAT {coords.latitude} | LON {coords.longitude}",
    )
    resultado["coordenadas"] = {"latitude": coords.latitude, "longitude": coords.longitude}
    return resultado


# ---------------------------------------------------------------------------
# Rota de detecção de resíduos com stream MJPEG em tempo real
# ---------------------------------------------------------------------------

@app.get("/deteccao/stream")
def deteccao_stream(ia: bool = True):
    """
    Stream MJPEG com detecção de resíduos em tempo real via YOLOv8.
    Usa a instância global do Tello para evitar conflitos de porta UDP.
    Permite desativar a IA usando o parâmetro de query ?ia=false.
    """
    logger.info(f"Iniciando stream de vídeo (IA ativada: {ia})...")
    return StreamingResponse(
        gerar_stream_deteccao(drone_global, usar_ia=ia),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# Schema Pydantic e rotas de persistência (Voo + Detecção + Recorrência)
# ---------------------------------------------------------------------------

class DeteccaoCreate(BaseModel):
    lat: float
    lon: float
    confianca: float
    img_path: str


@app.post("/voo/iniciar")
def rota_iniciar_voo(db: Session = Depends(get_db)):
    """Cria um novo registro de voo com a data atual."""
    voo = crud.iniciar_voo(db)
    return {"id_voo": voo.id_voo, "data_voo": str(voo.data_voo)}


@app.post("/deteccao/registrar/{id_voo}")
def rota_registrar_deteccao(
    id_voo: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Captura automaticamente o frame atual, coordenadas estimadas e confiança
    da IA a partir do estado global do stream/drone, salvando a imagem em disco.
    """
    captura = obter_captura()

    if captura is not None:
        frame = captura["frame"]
        lat = float(captura["lat"])
        lon = float(captura["lon"])
        confianca = float(captura["confianca"])
    else:
        # Fallback seguro caso o stream ainda não tenha gerado frames ou esteja em teste
        import numpy as np
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        lat = -23.52223000
        lon = -46.67362000
        confianca = 0.85

    nome_img = f"drone_frame_{int(time.time() * 1000)}.jpg"
    caminho_completo = os.path.join(DIRETORIO_IMAGENS, nome_img)
    cv2.imwrite(caminho_completo, frame)
    caminho_relativo = f"capturas/{nome_img}"

    id_deteccao = crud.salvar_deteccao(
        db, id_voo, lat, lon, confianca, caminho_relativo
    )

    background_tasks.add_task(
        crud.verificar_recorrencia_assincrona,
        db, id_deteccao, lat, lon,
    )

    return {
        "status": "sucesso",
        "id_deteccao": id_deteccao,
        "latitude": lat,
        "longitude": lon,
        "confianca_ia": confianca,
        "caminho_imagem": caminho_relativo,
    }
 
 
@app.get("/deteccao/listar")
def listar_deteccoes(db: Session = Depends(get_db)):
    """Retorna todas as detecções salvas no PostgreSQL para o Dashboard do Angular."""
    try:
        registros = db.query(Deteccao).order_by(Deteccao.id_deteccao.desc()).all()
        # Extrai os dados do SQLAlchemy e converte em dicionários JSON-friendly
        resultado = [
            {
                "id_deteccao": reg.id_deteccao,
                "id_voo": reg.id_voo,
                "latitude": float(reg.latitude),
                "longitude": float(reg.longitude),
                "confianca_ia": float(reg.confianca_ia),
                "caminho_imagem": reg.caminho_imagem
            }
            for reg in registros
        ]
        return resultado
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

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
    """
    Usa a instância global (Singleton). NÃO chama tello.end(): no djitellopy,
    end() remove o host '192.168.10.1' do registro interno de drones,
    quebrando o stream/heartbeat em execução (KeyError: '192.168.10.1').
    """
    logs = []
    tello = drone_global
    try:
        logs.append("[SYS] Conectando ao drone...")
        tello.connect()  # mesmo objeto/socket do Singleton: não abre nova porta UDP

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

def teste_voo_video_real():
    """
    Executa apenas a decolagem usando a instância global do drone.
    A conexão (connect/streamon) é responsabilidade exclusiva do
    gerador do stream (GET /deteccao/stream), aberto pela tag <img> do Angular.
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