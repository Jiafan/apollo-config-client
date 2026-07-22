"""ConfigManager：在 ApolloClient 之上做二次封装。

职责：
  - 聚合多个 namespace 的 ApolloClient；
  - 提供「按 namespace 订阅变更」的回调（装饰器风格）；
  - 提供通用的配置读取；领域模型（如 DatabaseConfig）通过 get_typed() 接入，
    库本身不耦合任何业务模型，保持核心仅依赖 requests。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Type, TypeVar

from apollo_config.client import ApolloClient

logger = logging.getLogger("apollo.config")

# 回调签名: (namespace: str, changes: Dict[key, {"old":..., "new":...}])
NamespaceCallback = Callable[[str, Dict], None]
T = TypeVar("T")


class ConfigManager:
    def __init__(
        self,
        app_id: str,
        config_url: str,
        cluster: str = "default",
        namespaces: List[str] | None = None,
        env: str | None = None,
        access_key_secret: str | None = None,
        cache_dir: str = ".apollo_cache",
        poll_timeout: int = 70,
        request_timeout: int = 5,
        poll_interval: float = 2.0,
        max_retry_backoff: float = 30.0,
    ) -> None:
        self._client = ApolloClient(
            app_id=app_id,
            config_url=config_url,
            cluster=cluster,
            namespaces=namespaces,
            env=env,
            access_key_secret=access_key_secret,
            cache_dir=cache_dir,
            poll_timeout=poll_timeout,
            request_timeout=request_timeout,
            poll_interval=poll_interval,
            max_retry_backoff=max_retry_backoff,
        )
        self._ns_callbacks: Dict[str, List[NamespaceCallback]] = defaultdict(list)
        self._client.register_callback(self._dispatch)

    # ------------------------- 生命周期 -------------------------
    def start(self) -> None:
        self._client.start()

    def stop(self) -> None:
        self._client.stop()

    # ------------------------- 变更订阅 -------------------------
    def _dispatch(self, namespace: str, changes: dict) -> None:
        for cb in self._ns_callbacks.get(namespace, []):
            try:
                cb(namespace, changes)
            except Exception as exc:  # noqa: BLE001
                logger.exception("namespace=%s 变更回调失败: %s", namespace, exc)

    def on_namespace_change(self, namespace: str):
        """装饰器 / 注册器：订阅某个 namespace 的变更。回调签名 (namespace, changes)。"""
        def decorator(cb: NamespaceCallback) -> NamespaceCallback:
            self._ns_callbacks[namespace].append(cb)
            return cb
        return decorator

    # ------------------------- 通用读取 -------------------------
    def get_value(self, key: str, default: str | None = None, namespace: str = "application") -> str | None:
        return self._client.get_value(key, default, namespace)

    def get_configs(self, namespace: str = "application") -> Dict[str, str]:
        return self._client.get_configs(namespace)

    def get_typed(self, namespace: str, model_cls: Type[T]) -> T:
        """用任意模型类（如 pydantic.BaseModel 子类）解析某个 namespace 的配置。

        例::

            cfg = cm.get_typed("database", DatabaseConfig)

        库不绑定任何模型库：只要 ``model_cls`` 提供 ``model_validate(dict)`` 类方法即可
        （pydantic v2 天然满足）。
        """
        return model_cls.model_validate(dict(self.get_configs(namespace)))
