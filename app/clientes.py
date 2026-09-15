"""Clientes externos: WhatsApp Cloud API y el modelo (OpenRouter, compatible con OpenAI)."""
import logging

import httpx

log = logging.getLogger("bot")


class WhatsApp:
    def __init__(self, settings):
        self.s = settings
        self.url = f"https://graph.facebook.com/{settings.wa_graph_version}/{settings.wa_phone_number_id}/messages"

    async def _post(self, cuerpo: dict, que: str):
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(self.url, json=cuerpo, headers={"Authorization": f"Bearer {self.s.wa_token}"})
        log.info("WhatsApp %s -> messages %s", que, r.status_code)
        if r.status_code >= 400:
            raise RuntimeError(f"Meta respondió {r.status_code}: {r.text[:300]}")

    async def marcar_leido(self, wa_id: str, escribiendo: bool = True):
        """Marca leído y, de paso, enciende los tres puntitos.

        Meta los apaga solos a los 25 s o cuando sale la respuesta, lo que pase primero."""
        cuerpo = {"messaging_product": "whatsapp", "status": "read", "message_id": wa_id}
        if escribiendo:
            cuerpo["typing_indicator"] = {"type": "text"}
        await self._post(cuerpo, "leído + escribiendo" if escribiendo else "leído")

    async def enviar_texto(self, numero: str, texto: str):
        await self._post(
            {"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": texto}}, "texto"
        )


class Modelo:
    def __init__(self, settings):
        self.s = settings

    async def responder(self, mensajes: list[dict]) -> str:
        cuerpo = {"model": self.s.llm_model, "messages": mensajes}
        if self.s.llm_temperature is not None:
            cuerpo["temperature"] = self.s.llm_temperature
        if self.s.llm_max_tokens:
            cuerpo["max_tokens"] = self.s.llm_max_tokens
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.post(
                f"{self.s.llm_base_url}/chat/completions",
                json=cuerpo,
                headers={"Authorization": f"Bearer {self.s.llm_api_key}"},
            )
        log.info("Modelo %s -> %s", self.s.llm_model, r.status_code)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"].get("content") or "").strip()
