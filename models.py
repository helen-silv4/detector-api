import datetime

from sqlalchemy import Column, Date, ForeignKey, Integer, Numeric, String

from database import Base


class Voo(Base):
    __tablename__ = "voo"

    id_voo = Column(Integer, primary_key=True, autoincrement=True)
    data_voo = Column(Date, nullable=False, default=datetime.date.today)


class Deteccao(Base):
    __tablename__ = "deteccao"

    id_deteccao = Column(Integer, primary_key=True, autoincrement=True)
    id_voo = Column(
        Integer,
        ForeignKey("voo.id_voo", ondelete="RESTRICT"),
        nullable=False,
    )
    latitude = Column(Numeric(precision=10, scale=8), nullable=False)
    longitude = Column(Numeric(precision=11, scale=8), nullable=False)
    confianca_ia = Column(Numeric(precision=3, scale=2))
    caminho_imagem = Column(String(255), nullable=False)


class Recorrencia(Base):
    __tablename__ = "recorrencia"

    id_recorrencia = Column(Integer, primary_key=True, autoincrement=True)
    id_deteccao_hoje = Column(
        Integer,
        ForeignKey("deteccao.id_deteccao"),
        nullable=False,
    )
    id_deteccao_passado = Column(
        Integer,
        ForeignKey("deteccao.id_deteccao"),
        nullable=False,
    )
