"""
testes_drone.py – Infraestrutura exclusiva da TELA DE TESTES do frontend.

O que este módulo resolve:
  1. Logs em tempo real: os testes rodam em uma thread de fundo e publicam cada
     etapa em um barramento de logs. O frontend recebe tudo via Server-Sent Events
     (GET /testes/logs/stream) no momento em que acontece — não só quando o drone pousa.
  2. Vídeo de teste: stream MJPEG próprio (GET /testes/video/stream), SEM YOLO,
     com limpeza garantida dos recursos quando o navegador fecha a conexão.

Não altera nada da tela de detecção (que continua usando deteccao_stream.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from typing import AsyncGenerator, Callable

import cv2
import numpy as np
from djitellopy import Tello
from starlette.requests import Request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
CANAL_VOO = "voo"
CANAL_VIDEO = "video"
CANAL_VOO_VIDEO = "voo-video"
CANAIS_VALIDOS = {CANAL_VOO, CANAL_VIDEO, CANAL_VOO_VIDEO}

_BATERIA_MINIMA_VOO = 20
_TEMPO_PAIRANDO_S = 5
_FPS_STREAM = 30
_TIMEOUT_PRIMEIRO_FRAME_S = 15.0
_ESPERA_VIDEO_ANTES_VOO_S = 15.0
_SSE_INTERVALO_S = 0.2
_SSE_KEEPALIVE_S = 15.0


# ---------------------------------------------------------------------------
# Barramento de logs (thread-safe) consumido pelo SSE
# ---------------------------------------------------------------------------
class BarramentoLogs:
    """Fila circular de eventos com id incremental (suporta reconexão via Last-Event-ID)."""

    def __init__(self, capacidade: int = 1000) -> None:
        self._lock = threading.Lock()
        self._itens: deque[dict] = deque(maxlen=capacidade)
        self._seq = 0

    def publicar(self, canal: str, msg: str = "", tipo: str = "log", status: str | None = None) -> None:
        with self._lock:
            self._seq += 1
            evento = {"id": self._seq, "canal": canal, "tipo": tipo, "msg": msg, "ts": time.time()}
            if status is not None:
                evento["status"] = status
            self._itens.append(evento)
        if msg:
            logger.info("[TESTES:%s] %s", canal, msg)

    def ultimo_id(self) -> int:
        with self._lock:
            return self._seq

    def desde(self, ultimo_id: int) -> list[dict]:
        with self._lock:
            return [e for e in self._itens if e["id"] > ultimo_id]


barramento = BarramentoLogs()


async def gerar_sse_logs(request: Request) -> AsyncGenerator[str, None]:
    """
    Gerador assíncrono de Server-Sent Events. Não ocupa thread do pool:
    apenas consulta o barramento a cada 200 ms e envia os eventos novos.
    """
    try:
        ultimo_id = int(request.headers.get("last-event-id", ""))
    except ValueError:
        ultimo_id = barramento.ultimo_id()  # conexão nova: só eventos daqui pra frente

    yield "retry: 2000\n\n"
    ultimo_envio = time.monotonic()

    while True:
        if await request.is_disconnected():
            break

        eventos = barramento.desde(ultimo_id)
        for evento in eventos:
            ultimo_id = evento["id"]
            yield f"id: {evento['id']}\ndata: {json.dumps(evento, ensure_ascii=False)}\n\n"

        agora = time.monotonic()
        if eventos:
            ultimo_envio = agora
        elif agora - ultimo_envio >= _SSE_KEEPALIVE_S:
            ultimo_envio = agora
            yield ": keep-alive\n\n"

        await asyncio.sleep(_SSE_INTERVALO_S)


# ---------------------------------------------------------------------------
# Controle de concorrência
# ---------------------------------------------------------------------------
# Serializa os comandos com resposta (connect/takeoff/land/streamon/streamoff)
# disparados pela tela de testes: o djitellopy usa uma única fila de respostas
# por drone, e comandos simultâneos de threads diferentes trocariam as respostas.
_lock_comandos = threading.RLock()

# Apenas um teste de voo por vez
_lock_teste = threading.Lock()

# Sessão de vídeo ativa (uma nova sessão encerra a anterior)
_lock_sessao_video = threading.Lock()
_sessao_video_atual = 0
_video_ativo = threading.Event()


def teste_em_andamento() -> bool:
    return _lock_teste.locked()


def iniciar_teste(canal: str, alvo: Callable[[], None]) -> bool:
    """
    Executa o teste em uma thread de fundo. Retorna False se já houver um teste rodando.
    Ao final (com sucesso ou erro), publica um evento tipo='fim' no canal.
    """
    if not _lock_teste.acquire(blocking=False):
        return False

    def _executar() -> None:
        status = "sucesso"
        try:
            alvo()
        except _TesteAbortado as e:
            status = "erro"
            barramento.publicar(canal, f"[SYS] {e}")
        except Exception as e:  # noqa: BLE001 — qualquer erro precisa chegar ao frontend
            status = "erro"
            logger.exception("Erro no teste '%s'.", canal)
            barramento.publicar(canal, f"[ERRO] {e}")
        finally:
            barramento.publicar(canal, tipo="fim", status=status)
            _lock_teste.release()

    threading.Thread(target=_executar, daemon=True, name=f"Thread-Teste-{canal}").start()
    return True


class _TesteAbortado(Exception):
    """Interrupção controlada de um teste (ex.: bateria baixa)."""


# ---------------------------------------------------------------------------
# Testes de voo (real e simulado)
# ---------------------------------------------------------------------------
def _pousar_com_seguranca(tello: Tello, canal: str) -> None:
    try:
        if tello.is_flying:
            barramento.publicar(canal, "[SYS] Tentando pouso de segurança...")
            with _lock_comandos:
                tello.land()
            barramento.publicar(canal, "[SYS] Pouso de segurança concluído.")
    except Exception as e:  # noqa: BLE001
        barramento.publicar(canal, f"[ERRO] Falha no pouso de segurança: {e}")


def executar_voo_real(tello: Tello, canal: str = CANAL_VOO, aguardar_video: bool = False) -> None:
    pub = lambda msg: barramento.publicar(canal, msg)  # noqa: E731

    if aguardar_video:
        pub("[VID] Aguardando o stream de vídeo ficar ativo...")
        if _video_ativo.wait(_ESPERA_VIDEO_ANTES_VOO_S):
            pub("[VID] Vídeo ativo. Prosseguindo com o voo.")
        else:
            pub("[VID] Vídeo não ficou ativo a tempo. Prosseguindo apenas com o voo.")

    pub("[SYS] Conectando ao drone...")
    with _lock_comandos:
        tello.connect()
    pub("[SYS] Conectado.")

    bateria = tello.get_battery()
    pub(f"[SYS] Bateria: {bateria}%")
    if bateria < _BATERIA_MINIMA_VOO:
        raise _TesteAbortado(f"Bateria abaixo de {_BATERIA_MINIMA_VOO}%. Abortando decolagem.")

    try:
        pub("[SYS] Decolando...")
        with _lock_comandos:
            tello.takeoff()
        pub("[SYS] Decolagem concluída.")

        pub(f"[SYS] Pairando por {_TEMPO_PAIRANDO_S}s...")
        for restante in range(_TEMPO_PAIRANDO_S, 0, -1):
            try:
                altura = tello.get_height()
                pub(f"[TEL] Altura: {altura} cm | Bateria: {tello.get_battery()}% | {restante}s restantes")
            except Exception:  # noqa: BLE001 — telemetria é opcional
                pass
            time.sleep(1)
        pub("[SYS] Voo estabilizado.")

        pub("[SYS] Pousando...")
        with _lock_comandos:
            tello.land()
        pub("[SYS] Pouso concluído com sucesso.")
    except Exception:
        _pousar_com_seguranca(tello, canal)
        raise


def executar_voo_mock(canal: str = CANAL_VOO, aguardar_video: bool = False) -> None:
    pub = lambda msg: barramento.publicar(canal, msg)  # noqa: E731

    if aguardar_video:
        pub("[VID] Aguardando o stream de vídeo ficar ativo...")
        if _video_ativo.wait(_ESPERA_VIDEO_ANTES_VOO_S):
            pub("[VID] Vídeo ativo. Prosseguindo com o voo.")
        else:
            pub("[VID] Vídeo não ficou ativo a tempo. Prosseguindo apenas com o voo.")

    pub("[SYS] Conectando ao drone (simulado)...")
    time.sleep(0.5)
    pub("[SYS] Conectado.")
    pub("[SYS] Bateria: 85%")
    pub("[SYS] Decolando...")
    time.sleep(1.5)
    pub("[SYS] Decolagem concluída.")
    pub(f"[SYS] Pairando por {_TEMPO_PAIRANDO_S}s...")
    for restante in range(_TEMPO_PAIRANDO_S, 0, -1):
        pub(f"[TEL] Altura: 80 cm | Bateria: 85% | {restante}s restantes")
        time.sleep(1)
    pub("[SYS] Voo estabilizado.")
    pub("[SYS] Pousando...")
    time.sleep(1.5)
    pub("[SYS] Pouso concluído com sucesso.")


# ---------------------------------------------------------------------------
# Stream de vídeo da tela de testes (MJPEG, sem IA)
# ---------------------------------------------------------------------------
def _frame_para_jpeg(frame) -> bytes:
    sucesso, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not sucesso:
        raise RuntimeError("Falha ao codificar frame em JPEG.")
    return buffer.tobytes()


def _parte_mjpeg(jpeg: bytes) -> bytes:
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"


def _frame_simulado(n: int) -> np.ndarray:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    x = int((n * 4) % 640)
    cv2.rectangle(frame, (x, 200), (x + 80, 280), (16, 185, 129), -1)
    cv2.putText(frame, "MODO SIMULADO", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    cv2.putText(frame, time.strftime("%H:%M:%S"), (20, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
    return frame


def _nova_sessao_video() -> int:
    global _sessao_video_atual
    with _lock_sessao_video:
        _sessao_video_atual += 1
        return _sessao_video_atual


def _sessao_ainda_ativa(sessao: int) -> bool:
    with _lock_sessao_video:
        return _sessao_video_atual == sessao


def _heartbeat(tello: Tello, stop_event: threading.Event) -> None:
    """Comando RC neutro a cada 1.5 s para evitar o auto-pouso do Tello (timeout de 15 s)."""
    while not stop_event.is_set():
        try:
            tello.send_rc_control(0, 0, 0, 0)
        except Exception as e:  # noqa: BLE001
            logger.debug("Falha no heartbeat de teste: %s", e)
        stop_event.wait(1.5)


def _preparar_video_real(tello: Tello, canal: str):
    """Bloqueante (roda em thread): connect + streamon + leitor de frames."""
    pub = lambda msg: barramento.publicar(canal, msg)  # noqa: E731

    pub("[VID] Conectando ao drone...")
    with _lock_comandos:
        tello.connect()
        try:
            pub(f"[VID] Conectado. Bateria: {tello.get_battery()}%")
        except Exception:  # noqa: BLE001
            pub("[VID] Conectado.")

        # Leitor antigo parado (ex.: streamoff anterior falhou) nunca recebe frames novos
        leitor_antigo = tello.background_frame_read
        if leitor_antigo is not None and getattr(leitor_antigo, "stopped", False):
            tello.background_frame_read = None

        pub("[VID] Ativando stream de vídeo (streamon)...")
        tello.streamon()

        time.sleep(1.0)  # estabilização da câmera
        pub("[VID] Iniciando decodificador de vídeo (UDP 11111)...")
        # Mantido sob o lock: a limpeza (streamoff) só roda depois que o leitor existir,
        # mesmo que o navegador feche a conexão no meio da preparação.
        return tello.get_frame_read()


def _limpar_video_real(tello: Tello, stop_event: threading.Event, sessao: int, canal: str) -> None:
    """Bloqueante (roda em thread separada): encerra heartbeat, decodificador e streamoff."""
    stop_event.set()
    with _lock_comandos:
        if not _sessao_ainda_ativa(sessao):
            # Uma sessão mais nova já assumiu o vídeo; não derruba o stream dela.
            return
        _video_ativo.clear()

        frame_reader = tello.background_frame_read
        if frame_reader is not None:
            try:
                # O worker do PyAV só fecha o socket UDP 11111 ao decodificar o próximo frame,
                # por isso paramos ANTES do streamoff e aguardamos ele terminar. Sem isso a porta
                # fica presa e o próximo teste de vídeo não recebe imagem.
                frame_reader.stop()
                frame_reader.worker.join(timeout=1.5)
            except Exception as e:  # noqa: BLE001
                logger.debug("Erro ao parar frame_reader: %s", e)
        try:
            tello.streamoff()
            barramento.publicar(canal, "[VID] Stream de vídeo desativado no drone.")
        except Exception as e:  # noqa: BLE001
            barramento.publicar(canal, f"[VID] Aviso ao desativar stream: {e}")
        finally:
            tello.background_frame_read = None


async def gerar_stream_video_teste(tello: Tello, modo: str, canal: str) -> AsyncGenerator[bytes, None]:
    """
    Stream MJPEG da tela de testes (sem YOLO).

    É um gerador ASSÍNCRONO de propósito: quando o navegador fecha a conexão
    (botão "Parar Vídeo" ou troca de página), o Starlette cancela a tarefa e o
    bloco finally roda na hora, liberando o drone. Com gerador síncrono a limpeza
    podia ficar presa e o próximo teste de vídeo não recebia imagem.
    """
    canal = canal if canal in CANAIS_VALIDOS else CANAL_VIDEO
    pub = lambda msg: barramento.publicar(canal, msg)  # noqa: E731

    sessao = _nova_sessao_video()
    stop_event = threading.Event()
    frame_reader = None
    frames_enviados = 0
    intervalo = 1.0 / _FPS_STREAM

    try:
        if modo == "real":
            try:
                frame_reader = await asyncio.to_thread(_preparar_video_real, tello, canal)
            except Exception as e:  # noqa: BLE001
                logger.exception("Falha ao preparar vídeo de teste.")
                pub(f"[ERRO] Não foi possível iniciar o vídeo: {e}")
                barramento.publicar(canal, tipo="video", status="erro")
                return
            threading.Thread(
                target=_heartbeat, args=(tello, stop_event), daemon=True, name="Thread-Heartbeat-Testes"
            ).start()
        else:
            pub("[VID] Iniciando vídeo simulado...")

        pub("[VID] Aguardando o primeiro frame...")
        inicio = time.monotonic()

        while _sessao_ainda_ativa(sessao):
            if modo == "real":
                frame = frame_reader.frame
                if frame is None or frame.size == 0 or not frame.any():
                    if frames_enviados == 0 and time.monotonic() - inicio > _TIMEOUT_PRIMEIRO_FRAME_S:
                        pub(f"[ERRO] Nenhum frame recebido em {_TIMEOUT_PRIMEIRO_FRAME_S:.0f}s. "
                            "Verifique o Wi-Fi do drone e o firewall (porta UDP 11111).")
                        barramento.publicar(canal, tipo="video", status="erro")
                        return
                    await asyncio.sleep(0.05)
                    continue
                # djitellopy/PyAV entrega RGB; OpenCV espera BGR
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            else:
                frame_bgr = _frame_simulado(frames_enviados)

            jpeg = await asyncio.to_thread(_frame_para_jpeg, frame_bgr)
            yield _parte_mjpeg(jpeg)
            frames_enviados += 1

            if frames_enviados == 1:
                altura, largura = frame_bgr.shape[:2]
                _video_ativo.set()
                pub(f"[VID] Stream recebido com sucesso ({largura}x{altura}).")
                barramento.publicar(canal, tipo="video", status="ativo")

            await asyncio.sleep(intervalo)

        pub("[VID] Stream substituído por uma nova sessão de vídeo.")
    finally:
        pub(f"[VID] Stream encerrado ({frames_enviados} frames enviados).")
        barramento.publicar(canal, tipo="video", status="encerrado")
        if modo == "real":
            # Limpeza bloqueante fora do event loop (o await aqui seria cancelado junto com a tarefa)
            threading.Thread(
                target=_limpar_video_real,
                args=(tello, stop_event, sessao, canal),
                daemon=True,
                name="Thread-Limpeza-Video-Testes",
            ).start()
        elif _sessao_ainda_ativa(sessao):
            _video_ativo.clear()
