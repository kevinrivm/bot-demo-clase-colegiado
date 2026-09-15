"""Configuración por variables de entorno. Si falta una obligatoria, no arranca y dice cuál (CA-7)."""
import os
from dataclasses import dataclass, field

OBLIGATORIAS = ["WA_PHONE_NUMBER_ID", "WA_TOKEN", "WEBHOOK_TOKEN", "LLM_API_KEY", "DATABASE_URL"]


class ConfigError(RuntimeError):
    pass


def _entero(env, clave, defecto):
    valor = (env.get(clave) or "").strip()
    return int(valor) if valor else defecto


@dataclass
class Settings:
    wa_phone_number_id: str
    wa_token: str
    webhook_token: str
    llm_api_key: str
    database_url: str
    wa_graph_version: str = "v25.0"
    meta_app_secret: str = ""
    llm_model: str = "openai/gpt-4o-mini"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    conocimiento_path: str = "conocimiento/colegio-psicologos.md"
    nombre_agente: str = "Asistente virtual del Colegio de Psicólogos de Irapuato"
    zona_horaria: str = "America/Mexico_City"
    coalesce_segundos: float = 4.0
    reactivar_tras_horas: int = 24
    historial_mensajes: int = 12
    numeros_permitidos: set[str] = field(default_factory=set)


def cargar(env=None) -> Settings:
    env = os.environ if env is None else env
    faltan = [k for k in OBLIGATORIAS if not (env.get(k) or "").strip()]
    if faltan:
        raise ConfigError(f"Faltan variables obligatorias: {', '.join(faltan)}")

    from .telefonos import canonico

    permitidos = {canonico(n) for n in (env.get("NUMEROS_PERMITIDOS") or "").split(",") if n.strip()}
    temp = (env.get("LLM_TEMPERATURE") or "").strip()
    return Settings(
        wa_phone_number_id=env["WA_PHONE_NUMBER_ID"].strip(),
        wa_token=env["WA_TOKEN"].strip(),
        webhook_token=env["WEBHOOK_TOKEN"].strip(),
        llm_api_key=env["LLM_API_KEY"].strip(),
        database_url=env["DATABASE_URL"].strip(),
        wa_graph_version=(env.get("WA_GRAPH_VERSION") or "v25.0").strip(),
        meta_app_secret=(env.get("META_APP_SECRET") or "").strip(),
        llm_model=(env.get("LLM_MODEL") or "openai/gpt-4o-mini").strip(),
        llm_base_url=(env.get("LLM_BASE_URL") or "https://openrouter.ai/api/v1").strip().rstrip("/"),
        llm_temperature=float(temp) if temp else None,
        llm_max_tokens=_entero(env, "LLM_MAX_TOKENS", None),
        conocimiento_path=(env.get("CONOCIMIENTO_PATH") or "conocimiento/colegio-psicologos.md").strip(),
        nombre_agente=(env.get("NOMBRE_AGENTE") or "Asistente virtual del Colegio de Psicólogos de Irapuato").strip(),
        zona_horaria=(env.get("ZONA_HORARIA") or "America/Mexico_City").strip(),
        coalesce_segundos=float((env.get("COALESCE_SEGUNDOS") or "4").strip()),
        reactivar_tras_horas=_entero(env, "REACTIVAR_TRAS_HORAS", 24),
        historial_mensajes=_entero(env, "HISTORIAL_MENSAJES", 12),
        numeros_permitidos=permitidos,
    )
