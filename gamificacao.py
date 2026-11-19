"""Regras do Jardim da Saude. Etica: pontos so sobem; dia perdido o jardim apenas descansa."""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .timeutil import agora

# (nome, pontos minimos, emoji)
ESTAGIOS = [
    ("Semente", 0, "🌱"),
    ("Broto", 30, "🌿"),
    ("Planta", 80, "🪴"),
    ("Flor", 160, "🌸"),
    ("Jardim Florido", 300, "🌳"),
]
PONTOS_DOSE_NO_HORARIO = 10
PONTOS_DOSE_ATRASADA = 6  # ainda pontua: sem puniçao
PONTOS_BULA = 5

CONQUISTAS_INICIAIS = [
    ("primeiro_passo", "Primeiro Passo", "Você confirmou sua primeira dose no aplicativo.", 10),
    ("manha_em_dia", "Manhã em Dia", "Tomou todas as doses da manhã por 5 dias seguidos.", 20),
    ("semana_firme", "Semana Firme", "Completou 7 dias seguidos cuidando da sua saúde.", 40),
    ("curiosa", "Curiosa", "Leu 5 bulas ou receitas para entender seus remédios.", 25),
    ("sem_pressa", "Sem Pressa", "Tomou uma dose atrasada sem desistir do cuidado.", 15),
    ("recomeco", "Recomeço", "Voltou a registrar suas doses depois de um dia de descanso.", 15),
    ("em_familia", "Em Família", "Recebeu carinho de um familiar cuidador pelo aplicativo.", 15),
    ("mes_de_cuidado", "Mês de Cuidado", "Completou 30 dias cuidando bem dos seus remédios.", 100),
]


def registrar(db: Session, uid: int, origem: str, pontos: int) -> None:
    db.add(m.PontuacaoEvento(id_usuario=uid, origem=origem, pontos=max(0, pontos), criado_em=agora()))


def pontos_totais(db: Session, uid: int) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(m.PontuacaoEvento.pontos), 0)).where(m.PontuacaoEvento.id_usuario == uid)
    )
    return int(total or 0)


def estagio_para(pontos: int):
    atual, proximo = ESTAGIOS[0], None
    for i, e in enumerate(ESTAGIOS):
        if pontos >= e[1]:
            atual = e
            proximo = ESTAGIOS[i + 1] if i + 1 < len(ESTAGIOS) else None
    return atual, proximo


def _registros_tomados(db: Session, uid: int):
    return db.scalars(
        select(m.RegistroDose)
        .join(m.Prescricao, m.Prescricao.id == m.RegistroDose.id_prescricao)
        .where(m.Prescricao.id_idoso == uid, m.RegistroDose.tomado_em.is_not(None))
    ).all()


def dias_com_dose(db: Session, uid: int) -> set:
    return {r.tomado_em.date() for r in _registros_tomados(db, uid)}


def sequencia(db: Session, uid: int) -> int:
    """Dias seguidos com ao menos uma dose. Se hoje ainda nao tem, conta a partir de ontem."""
    dias = dias_com_dose(db, uid)
    d = agora().date()
    if d not in dias:
        d -= timedelta(days=1)
    n = 0
    while d in dias:
        n += 1
        d -= timedelta(days=1)
    return n


def semana(db: Session, uid: int):
    dias = dias_com_dose(db, uid)
    hoje = agora().date()
    return [
        {"data": (hoje - timedelta(days=i)).isoformat(), "cumprido": (hoje - timedelta(days=i)) in dias}
        for i in range(6, -1, -1)
    ]


def _manhas_completas(db: Session, uid: int) -> set:
    regs = db.scalars(
        select(m.RegistroDose)
        .join(m.Prescricao, m.Prescricao.id == m.RegistroDose.id_prescricao)
        .where(m.Prescricao.id_idoso == uid, m.RegistroDose.horario_previsto < "12:00")
    ).all()
    por_dia = {}
    for r in regs:
        por_dia.setdefault(r.data, []).append(r.tomado_em is not None)
    return {d for d, lista in por_dia.items() if lista and all(lista)}


def _regra_cumprida(codigo: str, db: Session, uid: int, ctx: dict) -> bool:
    if codigo == "primeiro_passo":
        return len(ctx["tomados"]) >= 1
    if codigo == "manha_em_dia":
        ok = ctx["manhas"]
        return any(all((d - timedelta(days=k)) in ok for k in range(5)) for d in ok)
    if codigo == "semana_firme":
        return ctx["seq"] >= 7
    if codigo == "curiosa":
        return ctx["n_docs"] >= 5
    if codigo == "sem_pressa":
        return any(r.com_atraso for r in ctx["tomados"])
    if codigo == "recomeco":
        ordenados = sorted(ctx["dias"])
        return any((b - a).days >= 2 for a, b in zip(ordenados, ordenados[1:]))
    if codigo == "em_familia":
        return ctx["n_msgs"] >= 1
    if codigo == "mes_de_cuidado":
        return ctx["seq"] >= 30
    return False


def avaliar_conquistas(db: Session, uid: int) -> list:
    """Concede conquistas novas (sem duplicar) e soma seus pontos. Devolve as recem-obtidas."""
    db.flush()
    tomados = _registros_tomados(db, uid)
    ctx = {
        "tomados": tomados,
        "dias": {r.tomado_em.date() for r in tomados},
        "seq": sequencia(db, uid),
        "manhas": _manhas_completas(db, uid),
        "n_docs": db.scalar(select(func.count()).select_from(m.LeituraDocumento).where(m.LeituraDocumento.id_idoso == uid)),
        "n_msgs": db.scalar(select(func.count()).select_from(m.MensagemAfetiva).where(m.MensagemAfetiva.id_destinatario == uid)),
    }
    obtidas = set(db.scalars(select(m.ConquistaUsuario.id_tipo_conquista).where(m.ConquistaUsuario.id_usuario == uid)))
    novas = []
    for tipo in db.scalars(select(m.TipoConquista)).all():
        if tipo.id in obtidas or not _regra_cumprida(tipo.codigo, db, uid, ctx):
            continue
        db.add(m.ConquistaUsuario(id_usuario=uid, id_tipo_conquista=tipo.id, obtida_em=agora()))
        registrar(db, uid, f"conquista:{tipo.codigo}", tipo.pontos)
        novas.append({"codigo": tipo.codigo, "nome": tipo.nome, "pontos": tipo.pontos})
    db.flush()
    return novas


def estado(db: Session, uid: int) -> dict:
    pontos = pontos_totais(db, uid)
    atual, proximo = estagio_para(pontos)
    obtidas = {
        c.id_tipo_conquista: c.obtida_em
        for c in db.scalars(select(m.ConquistaUsuario).where(m.ConquistaUsuario.id_usuario == uid))
    }
    conquistas = [
        {
            "codigo": t.codigo,
            "nome": t.nome,
            "descricao": t.descricao,
            "pontos": t.pontos,
            "conquistada": t.id in obtidas,
            "obtidaEm": obtidas[t.id].date().isoformat() if t.id in obtidas else None,
        }
        for t in db.scalars(select(m.TipoConquista).order_by(m.TipoConquista.id)).all()
    ]
    nao_lidas = db.scalar(
        select(func.count()).select_from(m.MensagemAfetiva).where(
            m.MensagemAfetiva.id_destinatario == uid, m.MensagemAfetiva.lida_em.is_(None)
        )
    )
    return {
        "pontos": pontos,
        "estagio": atual[0],
        "emoji": atual[2],
        "proximoEstagio": proximo[0] if proximo else None,
        "pontosParaProximo": (proximo[1] - pontos) if proximo else 0,
        "metaProximo": proximo[1] if proximo else None,
        "sequenciaDias": sequencia(db, uid),
        "semana": semana(db, uid),
        "conquistas": conquistas,
        "totalConquistadas": sum(1 for c in conquistas if c["conquistada"]),
        "totalConquistas": len(conquistas),
        "mensagensNaoLidas": int(nao_lidas or 0),
    }
