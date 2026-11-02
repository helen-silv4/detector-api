"""
crud.py — Operações de persistência e análise espacial (PostGIS).
"""

import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import Voo, Deteccao, Recorrencia


# ---------------------------------------------------------------------------
# 1. Iniciar um novo voo
# ---------------------------------------------------------------------------

def iniciar_voo(db: Session) -> Voo:
    """Insere um novo registro de Voo com a data atual e retorna o objeto."""
    novo_voo = Voo(data_voo=datetime.date.today())
    db.add(novo_voo)
    db.commit()
    db.refresh(novo_voo)
    return novo_voo


# ---------------------------------------------------------------------------
# 2. Salvar uma detecção
# ---------------------------------------------------------------------------

def salvar_deteccao(
    db: Session,
    id_voo: int,
    lat: float,
    lon: float,
    confianca: float,
    img_path: str,
) -> int:
    """Persiste uma Detecção e retorna seu id_deteccao."""
    nova = Deteccao(
        id_voo=id_voo,
        latitude=lat,
        longitude=lon,
        confianca_ia=confianca,
        caminho_imagem=img_path,
    )
    db.add(nova)
    db.commit()
    db.refresh(nova)
    return nova.id_deteccao


# ---------------------------------------------------------------------------
# 3. Verificação assíncrona de recorrência espacial
# ---------------------------------------------------------------------------

def verificar_recorrencia_assincrona(
    db: Session,
    nova_deteccao_id: int,
    lat: float,
    lon: float,
    raio_metros: float = 15.0,
) -> None:
    """
    Busca detecções anteriores dentro de *raio_metros* da coordenada
    informada utilizando ST_DWithin do PostGIS (cálculo geodésico via
    geography cast).  Para cada correspondência, cria um registro de
    Recorrência vinculando a detecção atual à detecção passada.

    Esta função é projetada para ser executada como *background task*
    do FastAPI, de modo a não bloquear a resposta HTTP.
    """

    query = text(
        """
        SELECT id_deteccao
        FROM   deteccao
        WHERE  id_deteccao != :nova_id
          AND  ST_DWithin(
                   ST_MakePoint(longitude, latitude)::geography,
                   ST_MakePoint(:lon, :lat)::geography,
                   :raio
               )
        """
    )

    resultado = db.execute(
        query,
        {"nova_id": nova_deteccao_id, "lon": lon, "lat": lat, "raio": raio_metros},
    )

    for row in resultado:
        recorrencia = Recorrencia(
            id_deteccao_hoje=nova_deteccao_id,
            id_deteccao_passado=row.id_deteccao,
        )
        db.add(recorrencia)

    db.commit()
