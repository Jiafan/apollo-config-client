"""Flask 示例（Oracle 11g + SQLAlchemy）：接入 Apollo 配置中心，演示数据库配置热更新。

热更新核心思路：
  - 监听 `database` namespace 的变更回调；
  - 回调里 dispose 旧连接池并置空，下一次 DB 请求用「最新配置」惰性重建（lazy）；
  - 也可开启 RECONNECT_EAGER 让配置一发布就立即重连（eager），即时验证连通性；
  - 因此修改 Apollo 中的数据库密码 / 连接参数后，无需重启进程即生效。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from flask import Flask, jsonify
from sqlalchemy import Engine, create_engine, text

from apollo_config import ConfigManager
from apollo_config.contrib import DatabaseConfig, LdapConfig
from settings import get_config_manager

# Oracle thick 模式已在 settings.get_config_manager() 内统一初始化（见 settings.py），
# 任何脚本只要 import get_config_manager 都会自动生效，无需在应用里重复调用。
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("flask-app")

app = Flask(__name__)
cm: ConfigManager = get_config_manager()

# 配置一发布是否立即重连（eager）；默认 False 表示惰性到下次请求再重连（更安全，避免回调里做重 IO）
RECONNECT_EAGER = False

_engine: Optional[Engine] = None
_engine_sig: Optional[str] = None
_engine_lock = threading.Lock()


def _db_sig() -> str:
    """配置签名：任意连接参数变化都应触发重连。"""
    cfg = cm.get_typed("database", DatabaseConfig)
    return (
        f"{cfg.dialect}:{cfg.driver}:{cfg.host}:{cfg.port}"
        f":{cfg.service_name}:{cfg.sid}:{cfg.username}:{cfg.password}"
        f":{cfg.pool_size}:{cfg.echo}"
    )


def _build_engine() -> Engine:
    """用当前 Apollo 中的最新配置创建连接池。"""
    cfg = cm.get_typed("database", DatabaseConfig)
    engine = create_engine(
        cfg.connection_url(), pool_size=cfg.pool_size, echo=cfg.echo, pool_pre_ping=True
    )
    logger.info("已用新配置创建 Oracle 连接池 -> %s", cfg.connection_url(redact=True))
    return engine


def get_engine() -> Engine:
    """线程安全地获取连接池；配置变更后自动用新配置重建。"""
    global _engine, _engine_sig
    sig = _db_sig()
    if _engine is None or sig != _engine_sig:
        with _engine_lock:
            sig = _db_sig()  # 加锁后二次检查，避免重复创建
            if _engine is None or sig != _engine_sig:
                if _engine is not None:
                    logger.info("DB 配置已变更，销毁旧连接池")
                    _engine.dispose()
                _engine = _build_engine()
                _engine_sig = sig
    return _engine


@cm.on_namespace_change("database")
def _on_db_change(namespace: str, changes: dict) -> None:
    """配置中心更新数据库连接信息时的回调 —— 触发重连。"""
    logger.info("收到 database 配置热更新: %s", list(changes.keys()))
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()   # 立即断开旧连接，释放连接池
        _engine = None          # 置空，下次请求惰性重建（lazy）
        if RECONNECT_EAGER:
            _engine = _build_engine()   # 立即用新配置重建（eager），即刻验证连通性


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/config/database")
def database_config():
    # 注意：public_dict() 已脱敏，不会返回密码
    return jsonify(cm.get_typed("database", DatabaseConfig).public_dict())


@app.get("/config/ldap")
def ldap_config():
    return jsonify(cm.get_typed("ldap", LdapConfig).public_dict())


@app.get("/db/ping")
def db_ping():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM DUAL"))  # Oracle 需用 DUAL
        return jsonify(connected=True)
    except Exception as exc:  # noqa: BLE001
        # 没有真实数据库也能跑示例，这里把错误透出便于观察（生产应记录日志）
        return jsonify(connected=False, error=str(exc)), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
