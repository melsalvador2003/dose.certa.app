from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, SessionLocal, engine
from .routes import router
from .seed import seed_if_empty


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_if_empty(db)
    yield


app = FastAPI(
    title="Dose Certa API",
    version="1.0.0",
    description="API do Dose Certa: agenda de remédios, leitura de bulas com IA, jardim da saúde e recados da família.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api")


@app.get("/")
def raiz():
    return {"servico": "Dose Certa API", "docs": "/docs", "saude": "/api/saude"}
