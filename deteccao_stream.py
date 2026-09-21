import logging
import os
import time
from pathlib import Path
from typing import Generator

import cv2
from djitellopy import Tello
from ultralytics import YOLO

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

_MODEL_PATH = Path(__file__).parent / "models" / "best.pt"
_CONF_THRESHOLD = 0.60
_BATERIA_MINIMA_PARA_STREAM = 10

_LATITUDE_INICIAL_SIMULADA = -23.522230
_LONGITUDE_INICIAL_SIMULADA = -46.673620
_METROS_PARA_GRAUS = 0.000009  # aproximação equatorial simplificada

_HUD_COLOR = (0, 255, 0)
_HUD_FONT = cv2.FONT_HERSHEY_SIMPLEX
_HUD_SCALE = 0.55
_HUD_THICKNESS = 1

_FRAMES_ENTRE_INFERENCIAS = 3
_TAMANHO_IMAGEM_INFERENCIA = 480


def _carregar_modelo_yolo(caminho: Path | str | None = None) -> YOLO:
    caminho = Path(caminho or os.getenv("YOLO_MODEL_PATH", str(_MODEL_PATH)))
    if not caminho.exists():
        raise FileNotFoundError(
            f"Modelo YOLO não encontrado em '{caminho}'. "
            "Verifique o caminho ou defina a variável YOLO_MODEL_PATH."
        )
    logger.info("Carregando modelo YOLO de '%s'...", caminho)
    modelo = YOLO(str(caminho))
    logger.info("Modelo carregado com sucesso.")
    return modelo

def _desenhar_texto_com_sombra(frame, texto: str, posicao: tuple[int, int]) -> None:
    x, y = posicao
    cv2.putText(frame, texto, (x + 1, y + 1), _HUD_FONT, _HUD_SCALE, (0, 0, 0), _HUD_THICKNESS + 1)
    cv2.putText(frame, texto, (x, y), _HUD_FONT, _HUD_SCALE, _HUD_COLOR, _HUD_THICKNESS)

def _desenhar_hud(frame, bateria: int, velocidade: float, latitude: float, longitude: float) -> None:
    linhas = [
        f"BAT: {bateria}%",
        f"VEL: {velocidade:.1f} cm/s",
        f"LAT: {latitude:.6f}",
        f"LON: {longitude:.6f}",
    ]
    for indice, texto in enumerate(linhas):
        _desenhar_texto_com_sombra(frame, texto, (10, 25 + indice * 22))

def _codificar_frame_em_jpeg(frame) -> bytes:
    sucesso, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not sucesso:
        raise RuntimeError("Falha ao codificar frame em JPEG.")
    return buffer.tobytes()

def _deve_rodar_inferencia(numero_do_frame: int) -> bool:
    return numero_do_frame % _FRAMES_ENTRE_INFERENCIAS == 0

def _detectar_residuos(modelo: YOLO, frame):
    resultados = modelo.predict(
        frame,
        conf=_CONF_THRESHOLD,
        imgsz=_TAMANHO_IMAGEM_INFERENCIA,
        device=0,
        verbose=False,
    )
    return resultados[0]

def _capturar_telemetria(drone: Tello) -> tuple[int, float, float]:
    bateria = drone.get_battery()
    velocidade_x = drone.get_speed_x()
    velocidade_y = drone.get_speed_y()
    return bateria, velocidade_x, velocidade_y

def _calcular_velocidade_escalar(velocidade_x: float, velocidade_y: float) -> float:
    return (velocidade_x**2 + velocidade_y**2) ** 0.5

def _estimar_nova_posicao(
    latitude_atual: float,
    longitude_atual: float,
    velocidade_x: float,
    velocidade_y: float,
    segundos_desde_ultima_leitura: float,
) -> tuple[float, float]:
    deslocamento_x_metros = (velocidade_x * segundos_desde_ultima_leitura) / 100.0
    deslocamento_y_metros = (velocidade_y * segundos_desde_ultima_leitura) / 100.0
    nova_latitude = latitude_atual + deslocamento_x_metros * _METROS_PARA_GRAUS
    nova_longitude = longitude_atual + deslocamento_y_metros * _METROS_PARA_GRAUS
    return nova_latitude, nova_longitude

def gerar_stream_deteccao(drone: Tello, modelo_path: str | None = None) -> Generator[bytes, None, None]:
    modelo = _carregar_modelo_yolo(modelo_path)

    try:
        drone.connect()
        bateria = drone.get_battery()
        if bateria < _BATERIA_MINIMA_PARA_STREAM:
            logger.warning("Bateria crítica (%d%%). Abortando stream.", bateria)
            return

        drone.streamon()
        time.sleep(2)
        leitor_de_frames = drone.get_frame_read()

        latitude = _LATITUDE_INICIAL_SIMULADA
        longitude = _LONGITUDE_INICIAL_SIMULADA
        momento_da_ultima_leitura = time.time()

        numero_do_frame = 0
        ultima_deteccao = None

        while True:
            frame = leitor_de_frames.frame
            if frame is None or frame.size == 0:
                time.sleep(0.03)
                continue

            if _deve_rodar_inferencia(numero_do_frame):
                ultima_deteccao = _detectar_residuos(modelo, frame)
            numero_do_frame += 1

            frame_anotado = ultima_deteccao.plot(img=frame) if ultima_deteccao else frame.copy()

            bateria, velocidade_x, velocidade_y = _capturar_telemetria(drone)
            velocidade = _calcular_velocidade_escalar(velocidade_x, velocidade_y)

            momento_atual = time.time()
            segundos_desde_ultima_leitura = momento_atual - momento_da_ultima_leitura
            momento_da_ultima_leitura = momento_atual

            latitude, longitude = _estimar_nova_posicao(
                latitude, longitude, velocidade_x, velocidade_y, segundos_desde_ultima_leitura
            )

            _desenhar_hud(frame_anotado, bateria, velocidade, latitude, longitude)

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + _codificar_frame_em_jpeg(frame_anotado) + b"\r\n"
            )

    except GeneratorExit:
        logger.info("Cliente desconectou do stream MJPEG.")
    except Exception:
        logger.exception("Erro inesperado no loop de detecção.")
    finally:
        try:
            drone.streamoff()
        except Exception:
            logger.warning("Falha ao desativar stream.", exc_info=True)
