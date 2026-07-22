"""可选领域辅助（需要对应的 extra 依赖）。

安装方式::

    pip install apollo-config-client[models]   # DatabaseConfig / LdapConfig（依赖 pydantic）
    pip install apollo-config-client[oracle]   # init_oracle_thick_mode（依赖 oracledb）
    pip install apollo-config-client[all]      # 以上全部

核心库（``apollo_config``）刻意不依赖这些领域模型；这里仅作为「拿来即用」的参考实现，
你完全可以用自己的项目模型调用 ``ConfigManager.get_typed(namespace, YourModel)``。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

try:
    from pydantic import BaseModel, ConfigDict
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "apollo_config.contrib 的模型需要 pydantic，请执行 "
        "pip install apollo-config-client[models]"
    ) from exc

logger = logging.getLogger("apollo.contrib")


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # 数据库类型 / 驱动：默认 Oracle 11g + python-oracledb
    dialect: str = "oracle"        # oracle / postgresql / mysql
    driver: str = "oracledb"       # Oracle: oracledb(推荐) / cx_oracle
    host: str
    port: int = 1521               # Oracle 默认监听端口 1521
    username: str
    password: str
    # Oracle 连接标识：service_name 与 sid 二选一（11g 常用 service_name）
    service_name: str | None = None
    sid: str | None = None
    pool_size: int = 10
    echo: bool = False

    @classmethod
    def from_namespace(cls, configs: Dict[str, Any]) -> "DatabaseConfig":
        # Apollo 所有值均为字符串，pydantic 在 lax 模式下自动做类型转换
        return cls.model_validate(dict(configs))

    def connection_url(self, redact: bool = False) -> str:
        """生成 SQLAlchemy 连接串；redact=True 时隐藏密码（用于日志输出）。"""
        pwd = "***" if redact else self.password
        if self.dialect == "oracle":
            base = f"oracle+{self.driver}://{self.username}:{pwd}@{self.host}:{self.port}"
            if self.service_name:
                return f"{base}/?service_name={self.service_name}"
            if self.sid:
                return f"{base}/{self.sid}"
            return base
        if self.dialect == "postgresql":
            db = self.service_name or self.sid or ""
            return f"postgresql+psycopg2://{self.username}:{pwd}@{self.host}:{self.port}/{db}"
        if self.dialect == "mysql":
            db = self.service_name or ""
            return f"mysql+pymysql://{self.username}:{pwd}@{self.host}:{self.port}/{db}"
        raise ValueError(f"unsupported dialect: {self.dialect}")

    def public_dict(self) -> Dict[str, Any]:
        """对外暴露配置时脱敏（不返回密码）。"""
        return {
            "dialect": self.dialect,
            "driver": self.driver,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "service_name": self.service_name,
            "sid": self.sid,
            "pool_size": self.pool_size,
            "echo": self.echo,
        }


class LdapConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    server: str
    port: int = 389
    use_ssl: bool = False
    bind_dn: str
    bind_password: str
    base_dn: str
    user_search_base: str
    user_search_filter: str = "(uid={user})"
    timeout: int = 5

    @classmethod
    def from_namespace(cls, configs: Dict[str, Any]) -> "LdapConfig":
        return cls.model_validate(dict(configs))

    def public_dict(self) -> Dict[str, Any]:
        return {
            "server": self.server,
            "port": self.port,
            "use_ssl": self.use_ssl,
            "bind_dn": self.bind_dn,
            "base_dn": self.base_dn,
            "user_search_base": self.user_search_base,
            "user_search_filter": self.user_search_filter,
            "timeout": self.timeout,
        }


def init_oracle_thick_mode(lib_dir: str | None = None) -> None:
    """启用 Oracle thick 模式；重复调用安全（第二次直接跳过）。

    重要：Oracle 11g 无法使用 python-oracledb 的 thin 模式（thin 要求 Oracle DB ≥ 12.1），
    必须在创建任何连接前用 Instant Client 启用 thick 模式。

    Instant Client 路径通过环境变量 ``ORACLE_INSTANT_CLIENT`` 指定，例如::

        /opt/lib/instantclient-basiclite-arm-23.26.1.0.0
    """
    _INITIALIZED = getattr(init_oracle_thick_mode, "_initialized", False)
    if _INITIALIZED:
        return

    try:
        import oracledb
    except ImportError:
        logger.warning("未安装 oracledb，跳过 Oracle 驱动初始化（连接 11g 将失败）")
        init_oracle_thick_mode._initialized = True
        return

    lib_dir = lib_dir or os.getenv("ORACLE_INSTANT_CLIENT")
    if not lib_dir:
        logger.info("未配置 ORACLE_INSTANT_CLIENT，使用 oracledb thin 模式（仅支持 Oracle >= 12.1，11g 无法连接）")
        init_oracle_thick_mode._initialized = True
        return

    try:
        oracledb.init_oracle_client(lib_dir=lib_dir)
        logger.info("Oracle thick 模式已启用, lib_dir=%s", lib_dir)
    except Exception as exc:  # 已初始化会抛 DPI-1049，忽略即可
        logger.info("Oracle 驱动初始化跳过(可能已初始化): %s", exc)
    init_oracle_thick_mode._initialized = True
