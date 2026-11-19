"""Dados ficticios de demonstracao (so roda se o banco estiver vazio)."""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import gamificacao as g
from . import models as m
from .timeutil import agora


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(m.Perfil)):
        return

    idoso = m.Perfil(descricao="idoso")
    cuidador = m.Perfil(descricao="cuidador")
    db.add_all([idoso, cuidador])
    for codigo, nome, descricao, pontos in g.CONQUISTAS_INICIAIS:
        db.add(m.TipoConquista(codigo=codigo, nome=nome, descricao=descricao, pontos=pontos))
    db.flush()

    maria = m.Usuario(nome="Dona Maria", id_perfil=idoso.id, consentimento_em=agora())
    ana = m.Usuario(nome="Ana (Filha)", id_perfil=cuidador.id, consentimento_em=agora())
    db.add_all([maria, ana])
    db.flush()
    db.add(m.VinculoCuidado(id_idoso=maria.id, id_cuidador=ana.id, ativo=True, autorizado_em=agora()))

    meds = {
        "Losartana 50 mg": ("losartana", "08:00", "Tomar com um copo de água"),
        "Metformina 850 mg": ("metformina", "12:00", "Tomar logo após o almoço"),
        "Sinvastatina 20 mg": ("sinvastatina", "20:00", "Tomar antes de dormir"),
    }
    prescricoes = []
    for nome, (ativo, horario, instrucao) in meds.items():
        med = m.Medicamento(nome=nome, principio_ativo=ativo)
        db.add(med)
        db.flush()
        p = m.Prescricao(id_idoso=maria.id, id_medicamento=med.id, dose="1 comprimido", horario=horario, instrucao=instrucao)
        db.add(p)
        prescricoes.append(p)
    db.flush()

    # Historico dos 4 dias anteriores, todas as doses tomadas (para a demo ja ter jardim e sequencia)
    hoje = agora().date()
    for k in range(4, 0, -1):
        dia = hoje - timedelta(days=k)
        for p in prescricoes:
            h, mi = map(int, p.horario.split(":"))
            tomado = datetime(dia.year, dia.month, dia.day, h, mi) + timedelta(minutes=5)
            db.add(m.RegistroDose(id_prescricao=p.id, data=dia, horario_previsto=p.horario, tomado_em=tomado))
            g.registrar(db, maria.id, "dose", g.PONTOS_DOSE_NO_HORARIO)

    db.add(m.MensagemAfetiva(
        id_remetente=ana.id, id_destinatario=maria.id,
        texto="Oi mãe! Vi que o seu jardim está lindo. Te amo, qualquer coisa me liga!", criada_em=agora(),
    ))
    db.flush()
    g.avaliar_conquistas(db, maria.id)
    db.commit()
