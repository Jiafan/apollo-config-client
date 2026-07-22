"""apollo-config-client：一个轻量、同步、贴近 Apollo 官方 HTTP API 的 Python 配置客户端。

特性：
  - 长轮询（long polling）热更新，秒级生效，带 key 级 diff 回调。
  - 本地磁盘缓存，Apollo 不可用时应用仍可用上一次配置启动（容灾）。
  - 访问密钥（Access Key）HMAC-SHA1 签名，兼容 Apollo 1.6+。
  - 极简依赖：核心仅依赖 `requests`；pydantic 模型与 Oracle 助手为可选 extra。

典型用法::

    from apollo_config import create_config_manager_from_env

    cm = create_config_manager_from_env()
    cm.get_configs("application")            # 读取普通 namespace
    cm.get_value("feature_flag", "off")      # 读取单个 key

    @cm.on_namespace_change("database")
    def _on_db_change(ns, changes):
        ...  # 配置变更时惰性重建连接池等可变资源

公开 API：
  - :class:`ApolloClient`：底层 HTTP 客户端（长轮询 / 缓存 / 签名）。
  - :class:`ConfigManager`：按 namespace 订阅变更的二次封装 + 通用读取。
  - :func:`create_config_manager`：显式参数创建。
  - :func:`create_config_manager_from_env`：读环境变量创建（可选 dotenv）。
"""
from __future__ import annotations

from apollo_config.client import ApolloClient
from apollo_config.manager import ConfigManager
from apollo_config._factory import (
    create_config_manager,
    create_config_manager_from_env,
)

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("apollo-config-client")
    except PackageNotFoundError:
        # 源码树内直接运行（未安装为发行版）时的兜底值
        __version__ = "0.1.1"
except ImportError:  # Python < 3.8
    __version__ = "0.1.1"

__all__ = [
    "ApolloClient",
    "ConfigManager",
    "create_config_manager",
    "create_config_manager_from_env",
    "__version__",
]
