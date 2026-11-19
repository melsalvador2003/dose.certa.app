"""Modelo relacional em 3FN. Pontos totais, estagio e sequencia NAO sao colunas: sao calculados."""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Perfil(Base):
    __tablename__ = "perfil"
    id: Mapped[int] = mapped_column(primary_key=True)
    descricao: Mapped[str] = mapped_column(String(30), unique=True)  # idoso, cuidador


class Usuario(Base):
    __tablename__ = "usuario"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80))  # apelido (coleta minima)
    id_perfil: Mapped[int] = mapped_column(ForeignKey("perfil.id"))
    consentimento_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class VinculoCuidado(Base):
    __tablename__ = "vinculo_cuidado"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_idoso: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    id_cuidador: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    autorizado_em: Mapped[datetime] = mapped_column(DateTime)


class Medicamento(Base):
    __tablename__ = "medicamento"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)
    principio_ativo: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)


class Prescricao(Base):
    __tablename__ = "prescricao"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_idoso: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    id_medicamento: Mapped[int] = mapped_column(ForeignKey("medicamento.id"))
    dose: Mapped[str] = mapped_column(String(60))  # ex.: "1 comprimido"
    horario: Mapped[str] = mapped_column(String(5))  # "HH:MM", 1x ao dia
    instrucao: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)


class RegistroDose(Base):
    __tablename__ = "registro_dose"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_prescricao: Mapped[int] = mapped_column(ForeignKey("prescricao.id"))
    data: Mapped[date] = mapped_column(Date)
    horario_previsto: Mapped[str] = mapped_column(String(5))
    tomado_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    com_atraso: Mapped[bool] = mapped_column(Boolean, default=False)


class LeituraDocumento(Base):
    __tablename__ = "leitura_documento"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_idoso: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    tipo: Mapped[str] = mapped_column(String(20))  # bula, receita, rotulo
    resumo_simplificado: Mapped[str] = mapped_column(Text)  # a foto original nunca e guardada
    criado_em: Mapped[datetime] = mapped_column(DateTime)


class TipoConquista(Base):
    __tablename__ = "tipo_conquista"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nome: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(String(200))
    pontos: Mapped[int] = mapped_column(Integer)


class ConquistaUsuario(Base):
    __tablename__ = "conquista_usuario"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_usuario: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    id_tipo_conquista: Mapped[int] = mapped_column(ForeignKey("tipo_conquista.id"))
    obtida_em: Mapped[datetime] = mapped_column(DateTime)


class PontuacaoEvento(Base):
    __tablename__ = "pontuacao_evento"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_usuario: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    origem: Mapped[str] = mapped_column(String(60))
    pontos: Mapped[int] = mapped_column(Integer)  # nunca negativo: sem punicao
    criado_em: Mapped[datetime] = mapped_column(DateTime)


class MensagemAfetiva(Base):
    __tablename__ = "mensagem_afetiva"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_remetente: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    id_destinatario: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    texto: Mapped[str] = mapped_column(String(140))
    criada_em: Mapped[datetime] = mapped_column(DateTime)
    lida_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
