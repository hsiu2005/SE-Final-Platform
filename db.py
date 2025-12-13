from typing import Optional
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row             

# db.py
defaultDB = "midterm" 
dbUser = "postgres"
dbPassword = "81305"
dbHost = "localhost"
dbPort = 5432

DATABASE_URL = f"dbname={defaultDB} user={dbUser} password={dbPassword} host={dbHost} port={dbPort}"

# 修正為 Python 3.9/3.10+ 兼容的類型提示
_pool: Optional[AsyncConnectionPool] = None

#取得 DB 連線物件
async def getDB():
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            kwargs={"row_factory": dict_row},
            open=False
        )
        await _pool.open()
    async with _pool.connection() as conn:
        yield conn

# 關閉 Pool
async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None