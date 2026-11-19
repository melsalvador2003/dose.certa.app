import base64
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import gamificacao as g
from . import models as m
from .database import get_db
from .timeutil import agora

router = APIRouter()

AVISO_BULA = "Esta é uma explicação do documento. Em caso de dúvida, pergunte ao seu médico ou farmacêutico."
TOLERANCIA_MIN = 60  # dose tomada ate 60 min depois do horario conta como "no horario"


# ---------- utilidades ----------
def _usuario(db: Session, uid: int) -> m.Usuario:
    u = db.get(m.Usuario, uid)
    if not u:
        raise HTTPException(404, "Usuário não encontrado")
    return u


def _periodo(horario: str) -> str:
    h = int(horario.split(":")[0])
    return "Manhã" if h < 12 else "Tarde" if h < 18 else "Noite"


def _garantir_registros(db: Session, id_idoso: int, dia) -> None:
    prescs = db.scalars(select(m.Prescricao).where(m.Prescricao.id_idoso == id_idoso, m.Prescricao.ativa.is_(True))).all()
    for p in prescs:
        existe = db.scalar(select(m.RegistroDose.id).where(m.RegistroDose.id_prescricao == p.id, m.RegistroDose.data == dia))
        if not existe:
            db.add(m.RegistroDose(id_prescricao=p.id, data=dia, horario_previsto=p.horario))
    db.flush()


def _dose_dict(db: Session, r: m.RegistroDose) -> dict:
    p = db.get(m.Prescricao, r.id_prescricao)
    med = db.get(m.Medicamento, p.id_medicamento)
    previsto = datetime.strptime(f"{r.data} {r.horario_previsto}", "%Y-%m-%d %H:%M")
    status = "tomada" if r.tomado_em else ("atrasada" if previsto < agora() else "pendente")
    return {
        "id": r.id,
        "remedio": med.nome,
        "dose": p.dose,
        "horario": r.horario_previsto,
        "periodo": _periodo(r.horario_previsto),
        "instrucao": p.instrucao,
        "status": status,  # tomada | atrasada ("ainda dá tempo") | pendente
        "horarioTomado": r.tomado_em.strftime("%H:%M") if r.tomado_em else None,
    }


# ---------- saude / entrada ----------
@router.get("/saude")
def saude():
    return {"status": "ok"}


class EntrarIn(BaseModel):
    apelido: str = Field(min_length=1, max_length=80)


@router.post("/auth/entrar")
def entrar(body: EntrarIn, db: Session = Depends(get_db)):
    """Entrada simplificada, so com apelido (sem senha), como no app. Cria o idoso se nao existir."""
    nome = body.apelido.strip()
    u = db.scalar(select(m.Usuario).join(m.Perfil).where(m.Usuario.nome == nome, m.Perfil.descricao == "idoso"))
    if not u:
        perfil = db.scalar(select(m.Perfil).where(m.Perfil.descricao == "idoso"))
        u = m.Usuario(nome=nome, id_perfil=perfil.id)
        db.add(u)
        db.commit()
        db.refresh(u)
    return {"id": u.id, "nome": u.nome, "consentiu": u.consentimento_em is not None}


class ConsentimentoIn(BaseModel):
    id_usuario: int


@router.post("/consentimento")
def consentimento(body: ConsentimentoIn, db: Session = Depends(get_db)):
    u = _usuario(db, body.id_usuario)
    u.consentimento_em = agora()
    db.commit()
    return {"ok": True, "consentimentoEm": u.consentimento_em.isoformat()}


# ---------- agenda e doses ----------
@router.get("/idosos/{id_idoso}/agenda")
def agenda(id_idoso: int, db: Session = Depends(get_db)):
    u = _usuario(db, id_idoso)
    hoje = agora().date()
    _garantir_registros(db, id_idoso, hoje)
    db.commit()
    regs = db.scalars(
        select(m.RegistroDose)
        .join(m.Prescricao, m.Prescricao.id == m.RegistroDose.id_prescricao)
        .where(m.Prescricao.id_idoso == id_idoso, m.RegistroDose.data == hoje, m.Prescricao.ativa.is_(True))
        .order_by(m.RegistroDose.horario_previsto)
    ).all()
    doses = [_dose_dict(db, r) for r in regs]
    return {
        "idoso": u.nome,
        "data": hoje.isoformat(),
        "total": len(doses),
        "tomadas": sum(1 for d in doses if d["status"] == "tomada"),
        "doses": doses,
    }


class ConfirmarIn(BaseModel):
    horarioConfirmacao: Optional[str] = None  # "HH:MM"; se vier em outro formato, usa o horario atual


def _parse_hhmm(valor: Optional[str]):
    try:
        h, mi = map(int, (valor or "").strip()[:5].split(":"))
        if 0 <= h < 24 and 0 <= mi < 60:
            return h, mi
    except Exception:
        pass
    return None


@router.post("/doses/{id_registro}/confirmar")
def confirmar_dose(id_registro: int, body: Optional[ConfirmarIn] = None, db: Session = Depends(get_db)):
    r = db.get(m.RegistroDose, id_registro)
    if not r:
        raise HTTPException(404, "Dose não encontrada")
    p = db.get(m.Prescricao, r.id_prescricao)
    if r.tomado_em:  # idempotente: o app pode reenviar a fila offline sem duplicar pontos
        return {"dose": _dose_dict(db, r), "pontosGanhos": 0, "novasConquistas": [], "gamificacao": g.estado(db, p.id_idoso)}

    hm = _parse_hhmm(body.horarioConfirmacao) if body else None
    tomado = datetime(r.data.year, r.data.month, r.data.day, hm[0], hm[1]) if hm else agora()
    previsto = datetime.strptime(f"{r.data} {r.horario_previsto}", "%Y-%m-%d %H:%M")
    r.tomado_em = tomado
    r.com_atraso = tomado > previsto + timedelta(minutes=TOLERANCIA_MIN)
    pontos = g.PONTOS_DOSE_ATRASADA if r.com_atraso else g.PONTOS_DOSE_NO_HORARIO
    g.registrar(db, p.id_idoso, f"dose:{r.id}", pontos)
    novas = g.avaliar_conquistas(db, p.id_idoso)
    db.commit()
    return {
        "dose": _dose_dict(db, r),
        "pontosGanhos": pontos,
        "novasConquistas": novas,
        "gamificacao": g.estado(db, p.id_idoso),
    }


class PrescricaoIn(BaseModel):
    id_idoso: int
    nome: str = Field(min_length=1, max_length=80)
    dose: str = Field(default="1 comprimido", max_length=60)
    horario: str = Field(pattern=r"^\d{2}:\d{2}$")
    instrucao: Optional[str] = Field(default=None, max_length=160)


@router.post("/prescricoes", status_code=201)
def criar_prescricao(body: PrescricaoIn, db: Session = Depends(get_db)):
    """Cadastro de remedio (pelo cuidador no painel ou pelo idoso apos conferir a leitura da receita)."""
    _usuario(db, body.id_idoso)
    med = db.scalar(select(m.Medicamento).where(m.Medicamento.nome == body.nome.strip()))
    if not med:
        med = m.Medicamento(nome=body.nome.strip())
        db.add(med)
        db.flush()
    p = m.Prescricao(id_idoso=body.id_idoso, id_medicamento=med.id, dose=body.dose, horario=body.horario, instrucao=body.instrucao)
    db.add(p)
    db.commit()
    return {"id": p.id, "remedio": med.nome, "horario": p.horario}


@router.put("/prescricoes/{id_prescricao}/pausar")
def pausar_prescricao(id_prescricao: int, db: Session = Depends(get_db)):
    p = db.get(m.Prescricao, id_prescricao)
    if not p:
        raise HTTPException(404, "Prescrição não encontrada")
    p.ativa = False  # pausa; o historico e mantido
    db.commit()
    return {"ok": True}


@router.get("/idosos/{id_idoso}/adesao")
def adesao(id_idoso: int, dias: int = 7, db: Session = Depends(get_db)):
    """Resumo para o painel do cuidador."""
    u = _usuario(db, id_idoso)
    ini = agora().date() - timedelta(days=max(1, dias) - 1)
    regs = db.scalars(
        select(m.RegistroDose)
        .join(m.Prescricao, m.Prescricao.id == m.RegistroDose.id_prescricao)
        .where(m.Prescricao.id_idoso == id_idoso, m.RegistroDose.data >= ini)
    ).all()
    previstas = len(regs)
    tomadas = sum(1 for r in regs if r.tomado_em)
    bulas = db.scalar(select(func.count()).select_from(m.LeituraDocumento).where(m.LeituraDocumento.id_idoso == id_idoso))
    estado = g.estado(db, id_idoso)
    return {
        "idoso": u.nome,
        "dias": dias,
        "dosesPrevistas": previstas,
        "dosesTomadas": tomadas,
        "adesaoPercentual": round(100 * tomadas / previstas) if previstas else 0,
        "bulasExplicadas": int(bulas or 0),
        "estagio": estado["estagio"],
        "pontos": estado["pontos"],
        "sequenciaDias": estado["sequenciaDias"],
        "conquistas": f'{estado["totalConquistadas"]}/{estado["totalConquistas"]}',
    }


# ---------- leitura de bula com IA ----------
SYSTEM_BULA = (
    "Você explica bulas, receitas e rótulos de remédio para pessoas idosas, em português do Brasil, "
    "com frases curtas e palavras simples. Use APENAS o que está no documento. Nunca prescreva, nunca altere dose, "
    "nunca diagnostique. Se algo não estiver legível ou não constar no documento, diga isso. "
    'Responda em JSON com as chaves: "resumo" (1 frase), "paraQueServe", "comoTomar", "cuidados".'
)

EXEMPLO_BULA = {
    "resumo": "Esse remédio é para pressão. Tome 1 comprimido de manhã, depois do café.",
    "paraQueServe": "Ajuda a controlar a pressão alta.",
    "comoTomar": "1 comprimido por dia, de manhã, com um copo de água.",
    "cuidados": "Não pare por conta própria. Se sentir tontura forte, procure seu médico.",
}


def _explicar_com_gemini(conteudo: bytes, mime: str) -> Optional[dict]:
    chave = os.getenv("GEMINI_API_KEY")
    if not chave:
        return None
    modelo = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    corpo = {
        "systemInstruction": {"parts": [{"text": SYSTEM_BULA}]},
        "contents": [{"parts": [
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(conteudo).decode()}},
            {"text": "Explique este documento para uma pessoa idosa."},
        ]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    try:
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
            json=corpo, headers={"x-goog-api-key": chave}, timeout=45,
        )
        r.raise_for_status()
        texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        dados = json.loads(texto)
        return dados if isinstance(dados, dict) and dados.get("resumo") else None
    except Exception:
        return None  # qualquer falha cai no exemplo, para a demonstracao nao quebrar


@router.post("/documentos/ler")
def ler_documento(
    id_idoso: int = Form(...),
    tipo: str = Form("bula"),
    imagem: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    _usuario(db, id_idoso)
    dados, origem = None, "exemplo"
    if imagem is not None:
        conteudo = imagem.file.read()
        dados = _explicar_com_gemini(conteudo, imagem.content_type or "image/jpeg")
        if dados:
            origem = "gemini"
    if not dados:
        dados = EXEMPLO_BULA
    resumo = " ".join(str(dados.get(k, "")) for k in ("resumo", "paraQueServe", "comoTomar", "cuidados")).strip()
    db.add(m.LeituraDocumento(id_idoso=id_idoso, tipo=tipo, resumo_simplificado=resumo, criado_em=agora()))  # so o resumo
    g.registrar(db, id_idoso, "bula", g.PONTOS_BULA)
    novas = g.avaliar_conquistas(db, id_idoso)
    db.commit()
    return {
        "resumo": dados.get("resumo"),
        "paraQueServe": dados.get("paraQueServe"),
        "comoTomar": dados.get("comoTomar"),
        "cuidados": dados.get("cuidados"),
        "aviso": AVISO_BULA,
        "origem": origem,
        "pontosGanhos": g.PONTOS_BULA,
        "novasConquistas": novas,
    }


# ---------- gamificacao ----------
@router.get("/gamificacao/{id_usuario}")
def gamificacao(id_usuario: int, db: Session = Depends(get_db)):
    _usuario(db, id_usuario)
    return g.estado(db, id_usuario)


# ---------- vinculos e recados ----------
class VinculoIn(BaseModel):
    id_idoso: int
    id_cuidador: int


@router.post("/vinculos", status_code=201)
def criar_vinculo(body: VinculoIn, db: Session = Depends(get_db)):
    """O idoso autoriza o cuidador a acompanhar."""
    _usuario(db, body.id_idoso)
    _usuario(db, body.id_cuidador)
    v = db.scalar(select(m.VinculoCuidado).where(
        m.VinculoCuidado.id_idoso == body.id_idoso, m.VinculoCuidado.id_cuidador == body.id_cuidador))
    if v:
        v.ativo, v.autorizado_em = True, agora()
    else:
        v = m.VinculoCuidado(id_idoso=body.id_idoso, id_cuidador=body.id_cuidador, ativo=True, autorizado_em=agora())
        db.add(v)
    db.commit()
    return {"id": v.id, "ativo": v.ativo}


@router.put("/vinculos/{id_vinculo}/revogar")
def revogar_vinculo(id_vinculo: int, db: Session = Depends(get_db)):
    """Pausa do compartilhamento (botao 'Simular pausa LGPD' do portal)."""
    v = db.get(m.VinculoCuidado, id_vinculo)
    if not v:
        raise HTTPException(404, "Vínculo não encontrado")
    v.ativo = False
    db.commit()
    return {"ok": True, "ativo": False}


class MensagemIn(BaseModel):
    id_remetente: int
    id_destinatario: int
    texto: str = Field(min_length=1, max_length=140)


@router.post("/mensagens", status_code=201)
def enviar_mensagem(body: MensagemIn, db: Session = Depends(get_db)):
    vinculo = db.scalar(select(m.VinculoCuidado).where(
        m.VinculoCuidado.id_idoso == body.id_destinatario,
        m.VinculoCuidado.id_cuidador == body.id_remetente,
        m.VinculoCuidado.ativo.is_(True),
    ))
    if not vinculo:
        raise HTTPException(403, "Sem vínculo ativo autorizado pelo idoso")
    msg = m.MensagemAfetiva(
        id_remetente=body.id_remetente, id_destinatario=body.id_destinatario, texto=body.texto.strip(), criada_em=agora())
    db.add(msg)
    novas = g.avaliar_conquistas(db, body.id_destinatario)
    db.commit()
    return {"id": msg.id, "novasConquistasDoIdoso": novas}


@router.get("/mensagens/{id_usuario}")
def listar_mensagens(id_usuario: int, apenas_nao_lidas: bool = False, db: Session = Depends(get_db)):
    q = select(m.MensagemAfetiva).where(m.MensagemAfetiva.id_destinatario == id_usuario)
    if apenas_nao_lidas:
        q = q.where(m.MensagemAfetiva.lida_em.is_(None))
    msgs = db.scalars(q.order_by(m.MensagemAfetiva.criada_em.desc())).all()
    return [
        {"id": x.id, "de": db.get(m.Usuario, x.id_remetente).nome, "texto": x.texto,
         "criadaEm": x.criada_em.isoformat(), "lida": x.lida_em is not None}
        for x in msgs
    ]


@router.post("/mensagens/{id_mensagem}/lida")
def marcar_lida(id_mensagem: int, db: Session = Depends(get_db)):
    x = db.get(m.MensagemAfetiva, id_mensagem)
    if not x:
        raise HTTPException(404, "Mensagem não encontrada")
    x.lida_em = agora()
    db.commit()
    return {"ok": True}


# ---------- LGPD: acesso e exclusao ----------
@router.get("/usuarios/{id_usuario}/dados")
def ver_dados(id_usuario: int, db: Session = Depends(get_db)):
    u = _usuario(db, id_usuario)
    prescs = db.scalars(select(m.Prescricao).where(m.Prescricao.id_idoso == id_usuario)).all()
    return {
        "usuario": {"id": u.id, "nome": u.nome, "consentimentoEm": u.consentimento_em.isoformat() if u.consentimento_em else None},
        "remedios": [{"nome": db.get(m.Medicamento, p.id_medicamento).nome, "horario": p.horario, "ativa": p.ativa} for p in prescs],
        "bulasLidas": db.scalar(select(func.count()).select_from(m.LeituraDocumento).where(m.LeituraDocumento.id_idoso == id_usuario)),
        "pontos": g.pontos_totais(db, id_usuario),
        "vinculos": db.scalar(select(func.count()).select_from(m.VinculoCuidado).where(
            (m.VinculoCuidado.id_idoso == id_usuario) | (m.VinculoCuidado.id_cuidador == id_usuario))),
    }


@router.delete("/usuarios/{id_usuario}/dados")
def apagar_dados(id_usuario: int, db: Session = Depends(get_db)):
    """Direito de exclusao: remove o usuario e tudo o que depende dele."""
    _usuario(db, id_usuario)
    presc_ids = select(m.Prescricao.id).where(m.Prescricao.id_idoso == id_usuario)
    db.execute(delete(m.RegistroDose).where(m.RegistroDose.id_prescricao.in_(presc_ids)))
    db.execute(delete(m.Prescricao).where(m.Prescricao.id_idoso == id_usuario))
    db.execute(delete(m.LeituraDocumento).where(m.LeituraDocumento.id_idoso == id_usuario))
    db.execute(delete(m.ConquistaUsuario).where(m.ConquistaUsuario.id_usuario == id_usuario))
    db.execute(delete(m.PontuacaoEvento).where(m.PontuacaoEvento.id_usuario == id_usuario))
    db.execute(delete(m.MensagemAfetiva).where(
        (m.MensagemAfetiva.id_remetente == id_usuario) | (m.MensagemAfetiva.id_destinatario == id_usuario)))
    db.execute(delete(m.VinculoCuidado).where(
        (m.VinculoCuidado.id_idoso == id_usuario) | (m.VinculoCuidado.id_cuidador == id_usuario)))
    db.execute(delete(m.Usuario).where(m.Usuario.id == id_usuario))
    db.commit()
    return {"ok": True, "mensagem": "Todos os seus dados foram apagados."}
