"""FastAPI 示例：接入 Apollo 配置中心，并演示配置热更新。

与 Flask 示例相同的热更新思路，把可变的连接池放在 app.state（或本例中的 AppState 单例）里，
监听 `database` namespace 变更后惰性重建连接池。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from fastapi import FastAPI
from sqlalchemy import Engine, create_engine, text

from apollo_config import ConfigManager
from apollo_config.contrib import DatabaseConfig, LdapConfig
from settings import get_config_manager

# Oracle thick 模式已在 settings.get_config_manager() 内统一初始化（见 settings.py），
# 任何脚本只要 import get_config_manager 都会自动生效，无需在应用里重复调用。
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("fastapi-app")

cm: ConfigManager = get_config_manager()


class AppState:
    """持有可变运行时资源（如 DB 连接池），配置变更时重建。"""

    def __init__(self) -> None:
        self.engine: Optional[Engine] = None
        self.engine_sig: Optional[str] = None
        self.lock = threading.Lock()
        self.reconnect_eager = False   # True: 配置一发布立即重连验证

    def _db_sig(self) -> str:
        cfg = cm.get_typed("database", DatabaseConfig)
        return (
            f"{cfg.dialect}:{cfg.driver}:{cfg.host}:{cfg.port}"
            f":{cfg.service_name}:{cfg.sid}:{cfg.username}:{cfg.password}"
            f":{cfg.pool_size}:{cfg.echo}"
        )

    def _build_engine(self) -> Engine:
        cfg = cm.get_typed("database", DatabaseConfig)
        engine = create_engine(
            cfg.connection_url(), pool_size=cfg.pool_size, echo=cfg.echo, pool_pre_ping=True
        )
        logger.info("已用新配置创建 Oracle 连接池 -> %s", cfg.connection_url(redact=True))
        return engine

    def get_engine(self) -> Engine:
        sig = self._db_sig()
        if self.engine is None or sig != self.engine_sig:
            with self.lock:
                sig = self._db_sig()
                if self.engine is None or sig != self.engine_sig:
                    if self.engine is not None:
                        logger.info("DB 配置已变更，销毁旧连接池")
                        self.engine.dispose()
                    self.engine = self._build_engine()
                    self.engine_sig = sig
        return self.engine

    def on_db_change(self, namespace: str, changes: dict) -> None:
        logger.info("收到 database 配置热更新: %s", list(changes.keys()))
        with self.lock:
            if self.engine is not None:
                self.engine.dispose()
            self.engine = None
            if self.reconnect_eager:
                self.engine = self._build_engine()


state = AppState()


@cm.on_namespace_change("database")
def _on_db_change(namespace: str, changes: dict) -> None:
    state.on_db_change(namespace, changes)


app = FastAPI(title="FastAPI + Apollo Lab")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/config/database")
def database_config():
    return cm.get_typed("database", DatabaseConfig).public_dict()


@app.get("/config/ldap")
def ldap_config():
    return cm.get_typed("ldap", LdapConfig).public_dict()


@app.get("/db/ping")
def db_ping():
    try:
        engine = state.get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM DUAL"))  # Oracle 需用 DUAL
        return {"connected": True}
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "error": str(exc)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
