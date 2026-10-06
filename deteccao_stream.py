"""
deteccao_stream.py – Detecção de resíduos em tempo real com YOLOv8 + DJI Tello.

Arquitetura de 3 Threads Isoladas:
  - Thread 1 (Heartbeat/Anti-Queda Isolado): Daemon enviando send_rc_control(0, 0, 0, 0) a cada 1.5s
  - Thread 2 (Gerenciador de Vídeo Nativo): djitellopy.BackgroundFrameRead via PyAV (porta UDP 11111)
  - Thread 3 (YOLO Assíncrono): Inferência paralela em GPU/CPU atualizando estado global sem travar o vídeo
  - Loop Principal: Gerador MJPEG fluido a 30 FPS renderizando anotações e telemetria
"""

import logging
import os
import time
import threading
from pathlib import Path
from typing import Generator

import cv2
import torch
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
_MODEL_PATH = Path(__file__).parent / "models" / "best.pt"
_CONF_THRESHOLD = 0.60
_INFER_IMGSZ = 320  # Resolução otimizada para velocidade

_INIT_LAT = -23.522230
_INIT_LON = -46.673620
_METROS_PARA_GRAUS = 0.000009

_HUD_COLOR = (0, 255, 0)
_HUD_FONT = cv2.FONT_HERSHEY_SIMPLEX
_HUD_SCALE = 0.55
_HUD_THICKNESS = 1

# ---------------------------------------------------------------------------
# Variável Global de Estado da IA (Thread 3)
# ---------------------------------------------------------------------------
_estado_ia = {
    "frame_recente": None,
    "resultado": None,
    "lock": threading.Lock(),
    "evento_novo_frame": threading.Event(),
}


# ---------------------------------------------------------------------------
# Funções Auxiliares
# ---------------------------------------------------------------------------
def _carregar_modelo(caminho: Path | str | None = None) -> YOLO:
    caminho = Path(caminho or os.getenv("YOLO_MODEL_PATH", str(_MODEL_PATH)))
    if not caminho.exists():
        raise FileNotFoundError(f"Modelo YOLO não encontrado em '{caminho}'.")
    logger.info("Carregando modelo YOLO de '%s'...", caminho)
    return YOLO(str(caminho))


def _desenhar_hud(frame, bateria: int, velocidade: float, lat: float, lon: float) -> None:
    linhas = [
        f"BAT: {bateria}%",
        f"VEL: {velocidade:.1f} cm/s",
        f"LAT: {lat:.6f}",
        f"LON: {lon:.6f}",
    ]
    y0 = 25
    for i, texto in enumerate(linhas):
        y = y0 + i * 22
        cv2.putText(frame, texto, (11, y + 1), _HUD_FONT, _HUD_SCALE, (0, 0, 0), _HUD_THICKNESS + 1)
        cv2.putText(frame, texto, (10, y), _HUD_FONT, _HUD_SCALE, _HUD_COLOR, _HUD_THICKNESS)


def _frame_para_jpeg(frame) -> bytes:
    sucesso, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not sucesso:
        raise RuntimeError("Falha ao codificar frame em JPEG.")
    return buffer.tobytes()


# ---------------------------------------------------------------------------
# Thread 1: Heartbeat Anti-Queda Isolado
# ---------------------------------------------------------------------------
def _thread_heartbeat_anti_queda(tello: Tello, stop_event: threading.Event) -> None:
    """
    Roda em segundo plano em uma Thread Daemon.
    Envia comando neutro RC (0, 0, 0, 0) a cada 1.5 segundos para impedir que
    o firmware do Tello acione o failsafe de auto-pouso (timeout de 15 segundos).
    Totalmente isolado do processamento de vídeo e da inferência de IA.
    """
    logger.info("Thread 1 (Heartbeat Anti-Queda) iniciada.")
    while not stop_event.is_set():
        try:
            tello.send_rc_control(0, 0, 0, 0)
        except Exception as e:
            logger.warning("Falha temporária no heartbeat do drone: %s", e)
        # Aguarda 1.5 segundos ou desperta imediatamente ao receber stop_event
        stop_event.wait(1.5)
    logger.info("Thread 1 (Heartbeat Anti-Queda) finalizada.")


# ---------------------------------------------------------------------------
# Thread 3: YOLO Assíncrono
# ---------------------------------------------------------------------------
def _thread_ia_yolo(modelo: YOLO, stop_event: threading.Event) -> None:
    """
    Roda a inferência YOLO em uma thread paralela dedicada.
    Consome uma cópia do frame mais recente, executa a predição na GPU/CPU
    e atualiza a variável global _estado_ia sem travar o loop de renderização MJPEG.
    """
    logger.info("Thread 3 (YOLO Assíncrono) iniciada.")
    device = "0" if torch.cuda.is_available() else "cpu"
    logger.info("Dispositivo de inferência YOLO: %s", device)

    while not stop_event.is_set():
        # Aguarda notificação de novo frame disponível ou timeout periódico
        if not _estado_ia["evento_novo_frame"].wait(timeout=0.05):
            continue
        _estado_ia["evento_novo_frame"].clear()

        frame_copia = None
        with _estado_ia["lock"]:
            if _estado_ia["frame_recente"] is not None:
                frame_copia = _estado_ia["frame_recente"]
                _estado_ia["frame_recente"] = None

        if frame_copia is None:
            continue

        try:
            resultados = modelo.predict(
                source=frame_copia,
                conf=_CONF_THRESHOLD,
                imgsz=_INFER_IMGSZ,
                device=device,
                verbose=False,
            )
            if resultados:
                with _estado_ia["lock"]:
                    _estado_ia["resultado"] = resultados[0]
        except Exception as e:
            logger.warning("Falha durante inferência YOLO: %s", e)

    logger.info("Thread 3 (YOLO Assíncrono) finalizada.")


# ---------------------------------------------------------------------------
# Gerador Principal MJPEG (Thread 2 + Pipeline de Streaming)
# ---------------------------------------------------------------------------
def gerar_stream_deteccao(tello: Tello, modelo_path: str | None = None) -> Generator[bytes, None, None]:
    """
    Gerador principal de stream MJPEG utilizando a Arquitetura de 3 Threads Isoladas.
    O ritmo de geração é ditado pelo fluxo da câmera sem introduzir sleeps artificiais.
    """
    modelo = _carregar_modelo(modelo_path)
    stop_event = threading.Event()

    thread_heartbeat = None
    thread_ia = None
    frame_reader = None

    try:
        # Conexão inicial e verificação de integridade
        logger.info("Verificando conexão com o DJI Tello...")
        try:
            tello.connect()
        except Exception as e:
            logger.warning("Aviso na conexão com o Tello (pode já estar conectado): %s", e)

        try:
            bateria = tello.get_battery()
            logger.info("Conectado ao Tello. Bateria: %s%%", bateria)
            if bateria is not None and bateria < 10:
                logger.warning("Bateria crítica (%d%%). Abortando inicialização do stream.", bateria)
                return
        except Exception as e:
            logger.warning("Não foi possível obter a bateria inicial: %s", e)

        # Ativação do stream nativo de vídeo
        logger.info("Ativando stream de vídeo nativo...")
        tello.streamon()
        time.sleep(1.0)  # Breve estabilização do hardware da câmera do drone

        # -----------------------------------------------------------------------
        # 1. Inicialização da Thread 1: Heartbeat Anti-Queda Isolado
        # -----------------------------------------------------------------------
        thread_heartbeat = threading.Thread(
            target=_thread_heartbeat_anti_queda,
            args=(tello, stop_event),
            daemon=True,
            name="Thread-Heartbeat-Tello",
        )
        thread_heartbeat.start()

        # -----------------------------------------------------------------------
        # 2. Inicialização da Thread 2: Gerenciador de Vídeo Nativo (PyAV)
        # -----------------------------------------------------------------------
        frame_reader = tello.get_frame_read()

        # -----------------------------------------------------------------------
        # 3. Inicialização da Thread 3: YOLO Assíncrono
        # -----------------------------------------------------------------------
        thread_ia = threading.Thread(
            target=_thread_ia_yolo,
            args=(modelo, stop_event),
            daemon=True,
            name="Thread-YOLO-Inferencia",
        )
        thread_ia.start()

        logger.info("Stream e threads ativas. Iniciando transmissão MJPEG...")

        lat, lon = _INIT_LAT, _INIT_LON
        t_anterior = time.time()

        # -----------------------------------------------------------------------
        # Loop Principal: Gerador MJPEG sem sleeps artificiais
        # -----------------------------------------------------------------------
        while True:
            try:
                frame = frame_reader.frame
            except Exception as e:
                logger.debug("Falha na captura do frame PyAV: %s", e)
                time.sleep(0.01)
                continue

            # Se o frame falhar ou o buffer PyAV ainda estiver vazio, aguarda brevemente sem estourar exceção
            if frame is None or frame.size == 0 or not frame.any():
                time.sleep(0.01)
                continue

            # O djitellopy/PyAV decodifica em RGB; convertemos para BGR para uso no OpenCV e YOLO
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # Thread 3 (YOLO): envia o frame recente e busca o resultado mais recente
            with _estado_ia["lock"]:
                _estado_ia["frame_recente"] = frame_bgr.copy()
                resultado_atual = _estado_ia["resultado"]
            _estado_ia["evento_novo_frame"].set()

            # Renderização das bounding boxes se houver inferência concluída
            if resultado_atual is not None:
                frame_anotado = resultado_atual.plot(img=frame_bgr)
            else:
                frame_anotado = frame_bgr

            # Telemetria local não-bloqueante (leitura de estado em memória do Tello)
            try:
                bat_val = tello.get_battery()
                bateria = bat_val if isinstance(bat_val, int) else 0
                vx_val = tello.get_speed_x()
                speed_x = vx_val if isinstance(vx_val, (int, float)) else 0
                vy_val = tello.get_speed_y()
                speed_y = vy_val if isinstance(vy_val, (int, float)) else 0
            except Exception:
                bateria = 0
                speed_x, speed_y = 0, 0

            velocidade = (speed_x**2 + speed_y**2) ** 0.5

            t_agora = time.time()
            delta_t = t_agora - t_anterior
            t_anterior = t_agora

            lat += ((speed_x * delta_t) / 100.0) * _METROS_PARA_GRAUS
            lon += ((speed_y * delta_t) / 100.0) * _METROS_PARA_GRAUS

            _desenhar_hud(frame_anotado, bateria, velocidade, lat, lon)

            # Codificação JPEG e envio do multipart MJPEG
            jpeg_bytes = _frame_para_jpeg(frame_anotado)
            yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n")

    except GeneratorExit:
        logger.info("Cliente desconectou do stream MJPEG.")
    except Exception as e:
        logger.exception("Exceção inesperada no loop do stream: %s", e)
    finally:
        logger.info("Iniciando limpeza e encerramento seguro dos recursos do stream...")

        # 1. Sinaliza parada para todas as threads
        stop_event.set()
        _estado_ia["evento_novo_frame"].set()

        # 2. Aguarda a finalização das threads de suporte
        if thread_heartbeat is not None and thread_heartbeat.is_alive():
            thread_heartbeat.join(timeout=2.0)
        if thread_ia is not None and thread_ia.is_alive():
            thread_ia.join(timeout=2.0)

        # 3. Encerra o worker de decodificação de frames PyAV
        if frame_reader is not None:
            try:
                frame_reader.stop()
            except Exception as e:
                logger.debug("Erro ao parar frame_reader: %s", e)

        # 4. Desliga o stream de vídeo no Tello (libera a porta UDP 11111)
        try:
            tello.streamoff()
            logger.info("Stream de vídeo desativado (tello.streamoff com sucesso).")
        except Exception as e:
            logger.warning("Falha ao desligar o stream no Tello: %s", e)

        # 5. Reseta a variável global de estado da IA
        with _estado_ia["lock"]:
            _estado_ia["frame_recente"] = None
            _estado_ia["resultado"] = None

        logger.info("Recursos liberados e gerador de stream finalizado.")