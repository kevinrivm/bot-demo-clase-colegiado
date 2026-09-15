"""FastAPI: /health, handshake y recepción del webhook."""
import asyncio
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from . import config
from .clientes import Modelo, WhatsApp
from .motor import Motor
from .store import PostgresStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


def firma_valida(secreto: str, cuerpo: bytes, cabecera: str | None) -> bool:
    if not secreto:
        return True
    if not cabecera or not cabecera.startswith("sha256="):
        return False
    esperada = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, cabecera.removeprefix("sha256="))


def crear_app(settings=None, store=None, whatsapp=None, modelo=None, reloj=None) -> FastAPI:
    if settings is None:
        try:
            settings = config.cargar()
        except config.ConfigError as e:
            log.error(str(e))
            raise
    store = store or PostgresStore(settings.database_url)
    extras = {"reloj": reloj} if reloj else {}
    motor = Motor(settings, store, whatsapp or WhatsApp(settings), modelo or Modelo(settings), **extras)
    tareas: set[asyncio.Task] = set()

    @asynccontextmanager
    async def ciclo(app):
        await store.iniciar()
        log.info("Bot listo · modelo %s · allowlist %s números", settings.llm_model, len(settings.numeros_permitidos))
        yield
        await store.cerrar()

    app = FastAPI(lifespan=ciclo)
    app.state.motor = motor
    app.state.tareas = tareas

    @app.get("/health")
    async def health():
        try:
            db = "ok" if await store.ping() else "error"
        except Exception:
            log.exception("Health: la base no responde")
            db = "error"
        return JSONResponse({"status": "ok" if db == "ok" else "error", "db": db}, status_code=200 if db == "ok" else 503)

    @app.get("/webhook/{token}")
    async def handshake(token: str, request: Request):
        q = request.query_params
        if (
            not hmac.compare_digest(token, settings.webhook_token)
            or q.get("hub.mode") != "subscribe"
            or not hmac.compare_digest(q.get("hub.verify_token", ""), settings.webhook_token)
        ):
            return Response(status_code=403)
        return PlainTextResponse(q.get("hub.challenge", ""))

    @app.post("/webhook/{token}")
    async def recibir(token: str, request: Request):
        if not hmac.compare_digest(token, settings.webhook_token):
            return Response(status_code=403)
        cuerpo = await request.body()
        if not firma_valida(settings.meta_app_secret, cuerpo, request.headers.get("x-hub-signature-256")):
            log.warning("Firma X-Hub-Signature-256 inválida: descartado")
            return Response(status_code=403)
        try:
            payload = json.loads(cuerpo or b"{}")
        except ValueError:
            log.warning("Webhook con JSON inválido")
            return {"ok": True}
        # Se responde 200 ya; el mensaje se procesa después (CA-1).
        tarea = asyncio.create_task(motor.procesar_payload(payload))
        tareas.add(tarea)
        tarea.add_done_callback(tareas.discard)
        return {"ok": True}

    return app


def app_desde_entorno():
    return crear_app()
