import logging
import time
from datetime import timedelta

import pytest

from app.config import ConfigError, cargar
from app.main import crear_app
from app.prompt import CONTACTO, RESPUESTA_SIN_MODELO
from app.telefonos import canonico

from .conftest import ENV_BASE, TOKEN, Bot, echo, mensaje

pytestmark = pytest.mark.anyio


async def test_handshake_devuelve_la_palabra_clave(bot):
    r = await bot.cliente.get(f"/webhook/{TOKEN}", params={"hub.mode": "subscribe", "hub.verify_token": TOKEN, "hub.challenge": "reto123"})
    assert r.status_code == 200 and r.text == "reto123"


async def test_health(bot):
    r = await bot.cliente.get("/health")
    assert r.json() == {"status": "ok", "db": "ok"}


async def test_muestra_los_tres_puntitos_mientras_responde(bot):
    bot.modelo.demora = 0.3
    await bot.post(mensaje("wamid.t1", "¿qué requisitos piden?"))
    await bot.esperar(0.1)
    assert bot.wa.leidos == [("wamid.t1", True)]  # puntitos encendidos antes de contestar
    assert bot.wa.enviados == []
    await bot.esperar(0.6)
    assert len(bot.wa.enviados) == 1


async def test_los_puntitos_no_se_encienden_si_el_bot_no_va_a_contestar():
    bot = Bot(NUMEROS_PERMITIDOS="524621111111")
    await bot.post(mensaje("wamid.t2", de="5214629999999"))
    await bot.esperar()
    assert bot.wa.leidos == []


async def test_el_cuerpo_de_meta_lleva_el_typing_indicator():
    from app.clientes import WhatsApp

    enviados = []

    class WA(WhatsApp):
        async def _post(self, cuerpo, que):
            enviados.append(cuerpo)

    await WA(Bot().settings).marcar_leido("wamid.x")
    assert enviados[0]["status"] == "read"
    assert enviados[0]["typing_indicator"] == {"type": "text"}


async def test_el_log_de_acceso_no_expone_el_token(bot, caplog):
    with caplog.at_level(logging.INFO):
        await bot.post(mensaje("wamid.log"))
        await bot.esperar()
    del_bot = "\n".join(r.getMessage() for r in caplog.records if r.name == "bot")
    assert "POST /webhook 200" in del_bot
    assert TOKEN not in del_bot


# CA-1
async def test_ca1_responde_200_de_inmediato_y_procesa_despues(bot):
    bot.modelo.demora = 2.0
    inicio = time.monotonic()
    r = await bot.post(mensaje("wamid.1"))
    assert r.status_code == 200
    assert time.monotonic() - inicio < 0.5
    assert bot.wa.enviados == []
    bot.modelo.demora = 0
    await bot.esperar()
    assert len(bot.wa.enviados) == 1


# CA-2
async def test_ca2_token_de_url_incorrecto_da_403(bot):
    r = await bot.post(mensaje("wamid.2"), token="otro")
    assert r.status_code == 403
    r = await bot.cliente.get("/webhook/otro", params={"hub.mode": "subscribe", "hub.verify_token": "otro", "hub.challenge": "x"})
    assert r.status_code == 403
    await bot.esperar()
    assert bot.store.mensajes == [] and bot.wa.enviados == []


async def test_ca2_firma_invalida_da_403(bot):
    r = await bot.post(mensaje("wamid.3"), firma="sha256=deadbeef")
    assert r.status_code == 403
    await bot.esperar()
    assert bot.store.mensajes == [] and bot.wa.enviados == []


# CA-3
async def test_ca3_mismo_id_dos_veces_contesta_una_vez(bot):
    await bot.post(mensaje("wamid.dup"))
    await bot.post(mensaje("wamid.dup"))
    await bot.esperar()
    assert len(bot.wa.enviados) == 1
    assert len([m for m in bot.store.mensajes if m["rol"] == "user"]) == 1


# CA-4
async def test_ca4_rafaga_se_contesta_una_sola_vez(bot):
    for i, t in enumerate(["hola", "oye", "una pregunta: ¿qué requisitos piden?"]):
        await bot.post(mensaje(f"wamid.r{i}", t))
    await bot.esperar()
    assert len(bot.wa.enviados) == 1
    contenidos = [m["content"] for m in bot.modelo.llamadas[0] if m["role"] == "user"]
    assert contenidos == ["hola", "oye", "una pregunta: ¿qué requisitos piden?"]


# CA-5
async def test_ca5_echo_calla_al_bot_y_vuelve_tras_24h(bot):
    await bot.post(echo("wamid.e1"))
    await bot.esperar(0.1)
    await bot.post(mensaje("wamid.e2", "¿sigue ahí?"))
    await bot.esperar()
    assert bot.wa.enviados == []

    bot.reloj.t += timedelta(hours=24, minutes=1)
    await bot.post(mensaje("wamid.e3", "hola de nuevo"))
    await bot.esperar()
    assert len(bot.wa.enviados) == 1


async def test_ca5_echo_cancela_respuesta_pendiente(bot):
    await bot.post(mensaje("wamid.p1"))
    await bot.post(echo("wamid.p2"))
    await bot.esperar()
    assert bot.wa.enviados == []


# CA-6
async def test_ca6_allowlist_solo_contesta_a_permitidos():
    bot = Bot(NUMEROS_PERMITIDOS="524621111111")
    await bot.post(mensaje("wamid.a1", de="5214629999999"))
    await bot.post(mensaje("wamid.a2", de="5214621111111"))
    await bot.esperar()
    assert [n for n, _ in bot.wa.enviados] == ["524621111111"]
    assert any(m["numero"] == "524629999999" for m in bot.store.mensajes)


# CA-7
@pytest.mark.parametrize("falta", ["WA_PHONE_NUMBER_ID", "WA_TOKEN", "WEBHOOK_TOKEN", "LLM_API_KEY", "DATABASE_URL"])
async def test_ca7_falta_variable_no_arranca_y_dice_cual(falta, monkeypatch, caplog):
    env = {k: v for k, v in ENV_BASE.items() if k != falta}
    with pytest.raises(ConfigError, match=falta):
        cargar(env)
    monkeypatch.delenv(falta, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with caplog.at_level(logging.ERROR), pytest.raises(ConfigError):
        crear_app()
    assert falta in caplog.text


# CA-8
def test_ca8_numero_mexicano_al_formato_de_meta():
    assert canonico("525512345678") == "525512345678"
    assert canonico("5215512345678") == "525512345678"
    assert canonico("+52 1 55 1234 5678") == "525512345678"
    assert canonico("14155550100") == "14155550100"


async def test_ca8_responde_al_formato_de_meta(bot):
    await bot.post(mensaje("wamid.m1", de="5214621234567"))
    await bot.esperar()
    assert bot.wa.enviados[0][0] == "524621234567"


# CA-9
async def test_ca9_prompt_prohibe_inventar_y_da_contacto(bot):
    await bot.post(mensaje("wamid.c1", "¿Cuánto cuesta la cuota anual?"))
    await bot.esperar()
    sistema = bot.modelo.llamadas[0][0]["content"]
    assert "NO la inventes" in sistema
    assert CONTACTO in sistema
    assert "(462) 624 64 15" in sistema and "pscolegio.irapuato94@gmail.com" in sistema
    assert "800 911 2000" in sistema  # protocolo de crisis
    assert "Maldonado" not in sistema  # sin nombres del consejo directivo


async def test_ca9_sin_respuesta_del_modelo_no_afirma_y_da_contacto(bot):
    bot.modelo.respuesta = ""
    await bot.post(mensaje("wamid.c2", "¿Cuándo es el próximo diplomado?"))
    await bot.esperar()
    assert bot.wa.enviados[0][1] == RESPUESTA_SIN_MODELO
    assert "(462) 624 64 15" in RESPUESTA_SIN_MODELO


# CA-10
async def test_ca10_falla_el_modelo_registra_y_sigue_200(bot, caplog):
    bot.modelo.falla = True
    with caplog.at_level(logging.ERROR):
        r = await bot.post(mensaje("wamid.f1"))
        await bot.esperar()
    assert r.status_code == 200
    assert "Falló el modelo" in caplog.text
    assert (await bot.post(mensaje("wamid.f2"))).status_code == 200


async def test_ca10_falla_meta_registra_y_sigue_200(bot, caplog):
    bot.wa.falla = True
    with caplog.at_level(logging.ERROR):
        r = await bot.post(mensaje("wamid.f3"))
        await bot.esperar()
    assert r.status_code == 200
    assert "Error respondiendo" in caplog.text
    assert (await bot.post({"basura": True})).status_code == 200
