"""工厂函数：构建 ConfigManager。

库只提供工厂，不提供全局单例（避免与应用框架的生命周期冲突）。
应用侧（如 Flask / FastAPI 的 settings 模块）可自行决定是否缓存为单例。
"""
from __future__ import annotations

import os
from typing import List, Optional

from apollo_config.manager import ConfigManager


def _env_namespaces() -> List[str]:
    """运行时读取 APOLLO_NAMESPACES，避免模块导入时缓存导致后续设置不生效。"""
    return [
        n.strip()
        for n in os.getenv("APOLLO_NAMESPACES", "application").split(",")
        if n.strip()
    ]


def create_config_manager(
    app_id: str,
    config_url: str,
    cluster: str = "default",
    namespaces: Optional[List[str]] = None,
    env: Optional[str] = None,
    access_key_secret: Optional[str] = None,
    cache_dir: str = ".apollo_cache",
    auto_start: bool = True,
    poll_timeout: int = 70,
    request_timeout: int = 5,
    poll_interval: float = 2.0,
    max_retry_backoff: float = 30.0,
) -> ConfigManager:
    """以显式参数创建 ConfigManager。

    ``auto_start=True``（默认）时立即拉取一次全量配置并启动后台长轮询线程。
    """
    mgr = ConfigManager(
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
    if auto_start:
        mgr.start()
    return mgr


def create_config_manager_from_env(auto_start: bool = True) -> ConfigManager:
    """从环境变量构建 ConfigManager。

    读取以下环境变量::

        APOLLO_APP_ID           应用 AppId（默认 "apollo-app"）
        APOLLO_CONFIG_URL       Config Service 地址（默认 http://localhost:8080）
        APOLLO_CLUSTER          集群（默认 "default"）
        APOLLO_NAMESPACES       逗号分隔的 namespace 列表（默认 "application"）
        APOLLO_ENV              环境名（默认 None）
        APOLLO_ACCESS_KEY_SECRET 访问密钥（默认 None，留空走匿名）
        APOLLO_CACHE_DIR        本地缓存目录（默认 ".apollo_cache"）

    若已安装 ``python-dotenv``，则自动调用 ``load_dotenv()``（未安装则跳过，不报错）。
    """
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    return create_config_manager(
        app_id=os.getenv("APOLLO_APP_ID", "apollo-app"),
        config_url=os.getenv("APOLLO_CONFIG_URL", "http://localhost:8080"),
        cluster=os.getenv("APOLLO_CLUSTER", "default"),
        namespaces=_env_namespaces(),
        env=os.getenv("APOLLO_ENV"),
        access_key_secret=os.getenv("APOLLO_ACCESS_KEY_SECRET"),
        cache_dir=os.getenv("APOLLO_CACHE_DIR", ".apollo_cache"),
        auto_start=auto_start,
    )
