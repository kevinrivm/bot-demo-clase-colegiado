import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.config import cargar
from app.main import crear_app
from app.store import MemoryStore

TOKEN = "token-de-prueba"
SECRETO = "secreto-de-app"

ENV_BASE = {
    "WA_PHONE_NUMBER_ID": "123",
    "WA_TOKEN": "wa",
    "WEBHOOK_TOKEN": TOKEN,
    "LLM_API_KEY": "llm",
    "DATABASE_URL": "postgres://x",
    "META_APP_SECRET": SECRETO,
    "COALESCE_SEGUNDOS": "0.2",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeWhatsApp:
    def __init__(self):
        self.enviados = []
        self.leidos = []
        self.falla = False

    async def marcar_leido(self, wa_id, escribiendo=True):
        self.leidos.append((wa_id, escribiendo))

    async def enviar_texto(self, numero, texto):
        if self.falla:
            raise RuntimeError("Meta caída")
        self.enviados.append((numero, texto))


class FakeModelo:
    def __init__(self, respuesta="Respuesta del Colegio", demora=0.0):
        self.respuesta = respuesta
        self.demora = demora
        self.llamadas = []
        self.falla = False

    async def responder(self, mensajes):
        self.llamadas.append(mensajes)
        await asyncio.sleep(self.demora)
        if self.falla:
            raise RuntimeError("modelo caído")
        return self.respuesta


class Reloj:
    def __init__(self):
        self.t = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


class Bot:
    def __init__(self, **env_extra):
        self.settings = cargar({**ENV_BASE, **env_extra})
        self.store = MemoryStore()
        self.wa = FakeWhatsApp()
        self.modelo = FakeModelo()
        self.reloj = Reloj()
        self.app = crear_app(self.settings, self.store, self.wa, self.modelo, reloj=self.reloj)
        self.cliente = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://bot")

    async def post(self, payload, token=TOKEN, firma=None):
        cuerpo = json.dumps(payload).encode()
        if firma is None:
            firma = "sha256=" + hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()
        return await self.cliente.post(
            f"/webhook/{token}", content=cuerpo,
            headers={"content-type": "application/json", "x-hub-signature-256": firma},
        )

    async def esperar(self, segundos=0.5):
        await asyncio.sleep(segundos)


def mensaje(wa_id, texto="hola", de="5214621234567"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": {
            "messages": [{"from": de, "id": wa_id, "type": "text", "text": {"body": texto}}]
        }}]}],
    }


def echo(wa_id, para="5214621234567", texto="Hola, soy Laura del Colegio"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "smb_message_echoes", "value": {
            "message_echoes": [{"from": "524620000000", "to": para, "id": wa_id, "type": "text", "text": {"body": texto}}]
        }}]}],
    }


@pytest.fixture
def bot():
    return Bot()
