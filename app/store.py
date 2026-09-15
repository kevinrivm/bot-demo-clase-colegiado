"""Persistencia: conversaciones y mensajes. Postgres en producción, memoria en las pruebas."""
from datetime import datetime

MIGRACIONES = [
    """
    CREATE TABLE IF NOT EXISTS conversaciones (
        numero TEXT PRIMARY KEY,
        pausada_hasta TIMESTAMPTZ,
        creada TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mensajes (
        id BIGSERIAL PRIMARY KEY,
        wa_id TEXT UNIQUE,
        numero TEXT NOT NULL REFERENCES conversaciones(numero),
        rol TEXT NOT NULL,
        texto TEXT NOT NULL,
        creado TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS mensajes_numero_idx ON mensajes (numero, id)",
]


class PostgresStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None

    async def iniciar(self):
        import asyncpg

        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        async with self.pool.acquire() as con:
            for sql in MIGRACIONES:
                await con.execute(sql)

    async def cerrar(self):
        if self.pool:
            await self.pool.close()

    async def ping(self) -> bool:
        async with self.pool.acquire() as con:
            return await con.fetchval("SELECT 1") == 1

    async def _conversacion(self, con, numero):
        await con.execute("INSERT INTO conversaciones (numero) VALUES ($1) ON CONFLICT DO NOTHING", numero)

    async def guardar_entrante(self, wa_id: str, numero: str, texto: str, cuando: datetime) -> bool:
        async with self.pool.acquire() as con:
            await self._conversacion(con, numero)
            fila = await con.fetchrow(
                "INSERT INTO mensajes (wa_id, numero, rol, texto, creado) VALUES ($1,$2,'user',$3,$4) "
                "ON CONFLICT (wa_id) DO NOTHING RETURNING id",
                wa_id, numero, texto, cuando,
            )
            return fila is not None

    async def guardar(self, numero: str, rol: str, texto: str, cuando: datetime, wa_id: str | None = None):
        async with self.pool.acquire() as con:
            await self._conversacion(con, numero)
            await con.execute(
                "INSERT INTO mensajes (wa_id, numero, rol, texto, creado) VALUES ($1,$2,$3,$4,$5) "
                "ON CONFLICT (wa_id) DO NOTHING",
                wa_id, numero, rol, texto, cuando,
            )

    async def pausar(self, numero: str, hasta: datetime):
        async with self.pool.acquire() as con:
            await self._conversacion(con, numero)
            await con.execute("UPDATE conversaciones SET pausada_hasta=$2 WHERE numero=$1", numero, hasta)

    async def pausada_hasta(self, numero: str) -> datetime | None:
        async with self.pool.acquire() as con:
            return await con.fetchval("SELECT pausada_hasta FROM conversaciones WHERE numero=$1", numero)

    async def historial(self, numero: str, limite: int) -> list[dict]:
        async with self.pool.acquire() as con:
            filas = await con.fetch(
                "SELECT rol, texto FROM mensajes WHERE numero=$1 ORDER BY id DESC LIMIT $2", numero, limite
            )
        return [{"rol": f["rol"], "texto": f["texto"]} for f in reversed(filas)]


class MemoryStore:
    def __init__(self):
        self.mensajes: list[dict] = []
        self.pausas: dict[str, datetime] = {}

    async def iniciar(self):
        pass

    async def cerrar(self):
        pass

    async def ping(self) -> bool:
        return True

    async def guardar_entrante(self, wa_id, numero, texto, cuando) -> bool:
        if any(m["wa_id"] == wa_id for m in self.mensajes):
            return False
        self.mensajes.append({"wa_id": wa_id, "numero": numero, "rol": "user", "texto": texto, "creado": cuando})
        return True

    async def guardar(self, numero, rol, texto, cuando, wa_id=None):
        if wa_id and any(m["wa_id"] == wa_id for m in self.mensajes):
            return
        self.mensajes.append({"wa_id": wa_id, "numero": numero, "rol": rol, "texto": texto, "creado": cuando})

    async def pausar(self, numero, hasta):
        self.pausas[numero] = hasta

    async def pausada_hasta(self, numero):
        return self.pausas.get(numero)

    async def historial(self, numero, limite):
        propios = [{"rol": m["rol"], "texto": m["texto"]} for m in self.mensajes if m["numero"] == numero]
        return propios[-limite:]
