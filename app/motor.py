"""Lógica del bot: guarda, deduplica (CA-3), agrupa ráfagas (CA-4), se calla ante echoes (CA-5),
respeta la allowlist (CA-6) y nunca deja que un fallo externo tumbe el webhook (CA-10)."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .prompt import RESPUESTA_SIN_MODELO, leer_conocimiento, sistema
from .telefonos import canonico

log = logging.getLogger("bot")


def ahora_utc():
    return datetime.now(timezone.utc)


class Motor:
    def __init__(self, settings, store, whatsapp, modelo, reloj=ahora_utc):
        self.s = settings
        self.store = store
        self.wa = whatsapp
        self.modelo = modelo
        self.reloj = reloj
        self.conocimiento = leer_conocimiento(settings.conocimiento_path)
        self.pendientes: dict[str, asyncio.Task] = {}

    async def procesar_payload(self, payload: dict):
        try:
            for entrada in payload.get("entry", []):
                for cambio in entrada.get("changes", []):
                    valor = cambio.get("value", {})
                    if cambio.get("field") == "smb_message_echoes" or "message_echoes" in valor:
                        for eco in valor.get("message_echoes", []):
                            await self._echo(eco)
                    for msg in valor.get("messages", []):
                        await self._entrante(msg)
        except Exception:
            log.exception("Error procesando el webhook")

    async def _echo(self, eco: dict):
        numero = canonico(eco.get("to", ""))
        texto = (eco.get("text") or {}).get("body", "")
        hasta = self.reloj() + timedelta(hours=self.s.reactivar_tras_horas)
        await self.store.guardar(numero, "humano", texto or "[echo]", self.reloj(), wa_id=eco.get("id"))
        await self.store.pausar(numero, hasta)
        tarea = self.pendientes.pop(numero, None)
        if tarea:
            tarea.cancel()
        log.info("Echo de un humano: bot en pausa para …%s hasta %s", numero[-4:], hasta.isoformat())

    async def _entrante(self, msg: dict):
        numero = canonico(msg.get("from", ""))
        wa_id = msg.get("id", "")
        if msg.get("type") == "text":
            texto = (msg.get("text") or {}).get("body", "")
        else:
            texto = f"[mensaje de tipo {msg.get('type')}]"

        nuevo = await self.store.guardar_entrante(wa_id, numero, texto, self.reloj())
        if not nuevo:
            log.info("Mensaje duplicado ignorado")
            return
        if self.s.numeros_permitidos and numero not in self.s.numeros_permitidos:
            log.info("Número …%s fuera de NUMEROS_PERMITIDOS: guardado sin respuesta", numero[-4:])
            return
        pausa = await self.store.pausada_hasta(numero)
        if pausa and pausa > self.reloj():
            log.info("Conversación …%s atendida por un humano: sin respuesta", numero[-4:])
            return

        try:
            await self.wa.marcar_leido(wa_id)
        except Exception:
            log.exception("No se pudo marcar como leído")

        anterior = self.pendientes.get(numero)
        if anterior:
            anterior.cancel()
        self.pendientes[numero] = asyncio.create_task(self._responder_tras_pausa(numero))

    async def _responder_tras_pausa(self, numero: str):
        try:
            await asyncio.sleep(self.s.coalesce_segundos)
        except asyncio.CancelledError:
            return
        self.pendientes.pop(numero, None)
        await self.responder(numero)

    async def responder(self, numero: str):
        try:
            historial = await self.store.historial(numero, self.s.historial_mensajes)
            mensajes = [{"role": "system", "content": sistema(self.s.nombre_agente, self.conocimiento)}]
            for m in historial:
                if m["rol"] == "user":
                    mensajes.append({"role": "user", "content": m["texto"]})
                else:
                    mensajes.append({"role": "assistant", "content": m["texto"]})
            try:
                texto = await self.modelo.responder(mensajes)
            except Exception:
                log.exception("Falló el modelo")
                texto = ""
            texto = texto or RESPUESTA_SIN_MODELO
            await self.wa.enviar_texto(numero, texto)
            await self.store.guardar(numero, "assistant", texto, self.reloj())
        except Exception:
            log.exception("Error respondiendo a …%s", numero[-4:])
