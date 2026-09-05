"""
deteccao_stream.py – Detecção de resíduos em tempo real com YOLOv8 + DJI Tello.

Responsabilidades:
  • Conectar ao Tello e ativar o stream de vídeo.
  • Rodar inferência YOLOv8 frame-a-frame.
  • Calcular odometria (Mock GPS) a partir das velocidades do drone.
  • Renderizar HUD com bateria, velocidade e coordenadas.
  • Gerar frames JPEG via yield para StreamingResponse (MJPEG).
"""

from djitellopy import tello


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

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
# O caminho agora fica simples e relativo à pasta da API
_MODEL_PATH = Path(__file__).parent / "models" / "best.pt"
_CONF_THRESHOLD = 0.60

# Coordenadas iniciais (Mock GPS – região de São Paulo)
_INIT_LAT = -23.522230
_INIT_LON = -46.673620

# 1 metro ≈ 0.000009 graus (aproximação equatorial simplificada)
_METROS_PARA_GRAUS = 0.000009

# Cores / fontes do HUD
_HUD_COLOR = (0, 255, 0)
_HUD_FONT = cv2.FONT_HERSHEY_SIMPLEX
_HUD_SCALE = 0.55
_HUD_THICKNESS = 1


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def _carregar_modelo(caminho: Path | str | None = None) -> YOLO:
    """Carrega o modelo YOLOv8 a partir do caminho informado."""
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


def _desenhar_hud(
    frame,
    bateria: int,
    velocidade: float,
    lat: float,
    lon: float,
) -> None:
    """Desenha informações de telemetria (HUD) no canto superior-esquerdo do frame."""
    linhas = [
        f"BAT: {bateria}%",
        f"VEL: {velocidade:.1f} cm/s",
        f"LAT: {lat:.6f}",
        f"LON: {lon:.6f}",
    ]
    y0 = 25
    for i, texto in enumerate(linhas):
        y = y0 + i * 22
        # Sombra para legibilidade
        cv2.putText(frame, texto, (11, y + 1), _HUD_FONT, _HUD_SCALE, (0, 0, 0), _HUD_THICKNESS + 1)
        cv2.putText(frame, texto, (10, y), _HUD_FONT, _HUD_SCALE, _HUD_COLOR, _HUD_THICKNESS)


def _frame_para_jpeg(frame) -> bytes:
    """Codifica um frame OpenCV em JPEG e retorna os bytes."""
    sucesso, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not sucesso:
        raise RuntimeError("Falha ao codificar frame em JPEG.")
    return buffer.tobytes()


_SKIP_INTERVAL = 3  # roda inferência a cada N frames
_INFER_IMGSZ = 480   # resolução menor para inferência mais rápida


def gerar_stream_deteccao(
    tello: Tello,
    modelo_path: str | None = None,
) -> Generator[bytes, None, None]:
    """
    Gerador que roda inferência YOLOv8 sobre o stream do Tello e produz
    frames MJPEG com bounding boxes e HUD de telemetria.

    Implementa *frame skipping*: a inferência roda apenas a cada
    ``_SKIP_INTERVAL`` frames. Nos frames intermediários, as bounding boxes
    da última detecção são reutilizadas para manter o vídeo fluido (~30 FPS).

    Args:
        tello: Instância compartilhada do DJI Tello (gerenciada externamente).
        modelo_path: Caminho opcional para o arquivo de pesos .pt.

    Yields:
        bytes no formato multipart/x-mixed-replace para StreamingResponse.
    """
    modelo = _carregar_modelo(modelo_path)

    try:
        # ── Conexão e stream ───────────────────────────────────────────
        logger.info("Conectando ao DJI Tello...")
        tello.connect()
        bateria = tello.get_battery()
        logger.info("Conectado. Bateria: %d%%", bateria)

        if bateria < 10:
            logger.warning("Bateria crítica (%d%%). Abortando stream.", bateria)
            return

        logger.info("Ativando stream de vídeo...")
        tello.streamon()
        time.sleep(2)  # aguarda estabilização do hardware da câmera
        frame_reader = tello.get_frame_read()
        logger.info("Stream de vídeo ativo.")

        # ── Estado da odometria ────────────────────────────────────────
        lat = _INIT_LAT
        lon = _INIT_LON
        t_anterior = time.time()

        # ── Estado do frame skipping ───────────────────────────────────
        frame_count = 0
        ultimo_resultado = None  # último Results do YOLO (para reutilizar boxes)

        # ── Loop principal ─────────────────────────────────────────────
        while True:
            frame = frame_reader.frame
            if frame is None or frame.size == 0:
                logger.debug("Frame vazio recebido, pulando...")
                time.sleep(0.03)
                continue

            # Inferência YOLOv8 — apenas a cada _SKIP_INTERVAL frames
            if frame_count % _SKIP_INTERVAL == 0:
                resultados = modelo.predict(
                    frame,
                    conf=_CONF_THRESHOLD,
                    imgsz=_INFER_IMGSZ,
                    device = 0,
                    verbose=False,
                )
                ultimo_resultado = resultados[0]

            frame_count += 1

            # Desenhar bounding boxes (detecção atual ou reutilizada)
            if ultimo_resultado is not None:
                frame_anotado = ultimo_resultado.plot(img=frame)
            else:
                frame_anotado = frame.copy()

            # Telemetria
            bateria = tello.get_battery()
            speed_x = tello.get_speed_x()  # cm/s
            speed_y = tello.get_speed_y()  # cm/s
            velocidade = (speed_x**2 + speed_y**2) ** 0.5

            # Odometria (Mock GPS)
            t_agora = time.time()
            delta_t = t_agora - t_anterior
            t_anterior = t_agora

            deslocamento_x_cm = speed_x * delta_t  # cm
            deslocamento_y_cm = speed_y * delta_t  # cm

            # Converter cm → metros → graus
            lat += (deslocamento_x_cm / 100.0) * _METROS_PARA_GRAUS
            lon += (deslocamento_y_cm / 100.0) * _METROS_PARA_GRAUS

            # HUD
            _desenhar_hud(frame_anotado, bateria, velocidade, lat, lon)

            # Codificar e emitir MJPEG (todos os frames — manter fluidez)
            jpeg_bytes = _frame_para_jpeg(frame_anotado)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
            )

    except GeneratorExit:
        logger.info("Cliente desconectou do stream MJPEG.")

    except Exception:
        logger.exception("Erro inesperado no loop de detecção.")

    finally:
        # Garantir encerramento do stream
        logger.info("Encerrando stream...")
        try:
            tello.streamoff()
            logger.info("Stream de vídeo desativado.")
        except Exception:
            logger.warning("Falha ao desativar stream.", exc_info=True)
            
        logger.info("Gerador de stream finalizado.")



