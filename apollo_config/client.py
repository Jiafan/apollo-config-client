"""Apollo 配置中心 HTTP 客户端（兼容 Apollo 2.x，含长轮询热更新与本地容灾缓存）。

直接基于 Apollo 开放的 HTTP 接口实现，不依赖任何第三方 Apollo 专用客户端：
  - 配置拉取: GET  {config_url}/configs/{appId}/{cluster}/{namespace}
  - 变更通知: GET  {config_url}/notifications/v2  (HTTP 长轮询)
官方 Java / .NET 客户端底层使用的也是同一套接口，因此本实现可稳定对接 Apollo 2.4.1。

特性：
  1. 长轮询（long polling）监听配置变更，秒级生效（热更新）。
  2. 变更回调：拿到 namespace 的 key 级 diff，方便业务层做热重建。
  3. 本地缓存：每次成功拉取都会落盘，Apollo 不可用时应用仍能用上次配置启动。
  4. 线程安全的运行时配置快照，供业务直接读取。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests
from requests import Request

logger = logging.getLogger("apollo")

# 变更回调签名: (namespace: str, changes: Dict[key, {"old":..., "new":...}])
ChangeCallback = Callable[[str, Dict[str, Any]], None]


class ApolloClient:
    def __init__(
        self,
        app_id: str,
        config_url: str,
        cluster: str = "default",
        namespaces: Optional[List[str]] = None,
        env: Optional[str] = None,
        client_ip: Optional[str] = None,
        access_key_secret: Optional[str] = None,
        cache_dir: str = ".apollo_cache",
        poll_timeout: int = 70,
        request_timeout: int = 5,
        poll_interval: float = 2.0,
        max_retry_backoff: float = 30.0,
    ) -> None:
        self.app_id = app_id
        self.config_url = config_url.rstrip("/")
        self.cluster = cluster
        self.env = env
        self.namespaces = namespaces or ["application"]
        self.client_ip = client_ip
        # 访问密钥（可选）：配了则对所有请求做 HMAC-SHA1 签名，否则走匿名访问。
        self.access_key_secret = access_key_secret
        self.cache_dir = Path(cache_dir)
        self.poll_timeout = poll_timeout          # 略大于 Apollo 服务端长轮询超时(默认 60s)
        self.request_timeout = request_timeout
        self.poll_interval = poll_interval
        self.max_retry_backoff = max_retry_backoff

        # 运行时状态（加锁保证线程安全）
        self._lock = threading.RLock()
        self._configs: Dict[str, Dict[str, str]] = {}
        self._release_keys: Dict[str, str] = {}
        self._notification_ids: Dict[str, int] = {ns: -1 for ns in self.namespaces}

        self._callbacks: List[ChangeCallback] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # 启动前先装载本地缓存，保证 Apollo 不可用时应用仍可启动
        for ns in self.namespaces:
            cached = self._load_cache(ns)
            if cached:
                with self._lock:
                    self._configs[ns] = cached.get("configurations", {})
                    self._release_keys[ns] = cached.get("releaseKey", "")
                logger.info("从本地缓存恢复 namespace=%s 的配置", ns)

    # ------------------------- 对外 API -------------------------
    def register_callback(self, cb: ChangeCallback) -> None:
        """注册全局配置变更回调。"""
        self._callbacks.append(cb)

    def get_configs(self, namespace: str = "application") -> Dict[str, str]:
        with self._lock:
            return dict(self._configs.get(namespace, {}))

    def get_value(self, key: str, default: Optional[str] = None, namespace: str = "application") -> Optional[str]:
        return self.get_configs(namespace).get(key, default)

    def start(self) -> None:
        """拉取一次全量配置并启动后台长轮询线程。"""
        if self._running:
            return
        for ns in self.namespaces:
            try:
                self._fetch_namespace(ns)
            except Exception as exc:  # noqa: BLE001
                logger.warning("启动时拉取 namespace=%s 失败(将使用本地缓存): %s", ns, exc)
        self._running = True
        self._thread = threading.Thread(target=self._long_poll, name="apollo-long-poll", daemon=True)
        self._thread.start()
        logger.info("Apollo 长轮询已启动, appId=%s namespaces=%s", self.app_id, self.namespaces)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    # ------------------------- 内部实现 -------------------------
    def _auth_headers(self, path_with_query: str) -> Dict[str, str]:
        """Apollo 1.6+ 客户端访问密钥签名。

        明文 = 毫秒时间戳 + "\\n" + pathWithQuery；HMAC-SHA1 + Base64。
        通过 Timestamp / Authorization 两个头传递（无独立 Signature 头）。
        未配置 access_key_secret 时返回空 dict（匿名访问）。
        """
        if not self.access_key_secret:
            return {}
        timestamp = str(int(time.time() * 1000))
        plain = f"{timestamp}\n{path_with_query}"
        digest = hmac.new(
            self.access_key_secret.encode("utf-8"), plain.encode("utf-8"), hashlib.sha1
        ).digest()
        signature = base64.b64encode(digest).decode("utf-8")
        return {
            "Timestamp": timestamp,
            "Authorization": f"Apollo {self.app_id}:{signature}",
        }

    def _signed_get(self, url: str, params: Dict[str, Any], timeout: int) -> "requests.Response":
        """构造带签名的 GET 请求。

        用 Request.prepare() 得到最终 pathWithQuery，确保签名用的 path 与
        实际发出的 URL 完全一致（含查询串的编码）。
        """
        prepared = Request("GET", url, params=params).prepare()
        headers = self._auth_headers(prepared.path_url)
        return requests.get(prepared.url, headers=headers, timeout=timeout)

    def _fetch_namespace(self, namespace: str) -> Dict[str, Any]:
        url = f"{self.config_url}/configs/{self.app_id}/{self.cluster}/{namespace}"
        params: Dict[str, Any] = {}
        release_key = self._release_keys.get(namespace)
        if release_key:
            params["releaseKey"] = release_key
        if self.client_ip:
            params["ip"] = self.client_ip

        resp = self._signed_get(url, params, self.request_timeout)

        # Apollo 在客户端携带的 releaseKey 与服务端最新版本一致时返回 HTTP 304 + 空 body，
        # 表示"配置未变更"。raise_for_status() 不会拦截 304，且对空 body 调 resp.json() 会抛
        # JSONDecodeError。这里直接当作无变更处理：不更新内存状态、不写缓存、不触发回调。
        if resp.status_code == 304 or not resp.text.strip():
            return {}

        resp.raise_for_status()
        data = resp.json()
        new_configs = data.get("configurations", {})
        new_release = data.get("releaseKey", "")

        with self._lock:
            old_configs = self._configs.get(namespace, {})
            changes = self._diff(old_configs, new_configs)
            self._configs[namespace] = new_configs
            self._release_keys[namespace] = new_release

        self._save_cache(namespace, new_release, new_configs)

        if changes:
            logger.info("namespace=%s 配置变更: %s", namespace, list(changes.keys()))
            for cb in self._callbacks:
                try:
                    cb(namespace, changes)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("配置变更回调执行失败: %s", exc)
        return changes

    @staticmethod
    def _diff(old: Dict[str, str], new: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
        changes: Dict[str, Dict[str, Any]] = {}
        for k in set(old) | set(new):
            ov, nv = old.get(k), new.get(k)
            if ov != nv:
                changes[k] = {"old": ov, "new": nv}
        return changes

    def _long_poll(self) -> None:
        backoff = self.poll_interval
        while self._running:
            try:
                notifications = [
                    {"namespaceName": ns, "notificationId": self._notification_ids.get(ns, -1)}
                    for ns in self.namespaces
                ]
                url = f"{self.config_url}/notifications/v2"
                params = {
                    "appId": self.app_id,
                    "cluster": self.cluster,
                    "notifications": json.dumps(notifications),
                }
                resp = self._signed_get(url, params, self.poll_timeout)
                if resp.status_code == 304:
                    continue
                resp.raise_for_status()
                items = resp.json() or []
                if not items:
                    backoff = self.poll_interval
                    continue
                for item in items:
                    ns = item["namespaceName"]
                    nid = item["notificationId"]
                    if nid > self._notification_ids.get(ns, -1):
                        self._notification_ids[ns] = nid
                        try:
                            self._fetch_namespace(ns)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("长轮询触发后拉取 namespace=%s 失败: %s", ns, exc)
                backoff = self.poll_interval
            except requests.exceptions.Timeout:
                # 长轮询超时(服务端 60s 无变更)是正常现象，立即继续下一轮
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Apollo 长轮询异常, %ss 后重试: %s", backoff, exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, self.max_retry_backoff)

    # ------------------------- 本地缓存 -------------------------
    def _cache_path(self, namespace: str) -> Path:
        d = self.cache_dir / self.app_id / (self.env or "default")
        d.mkdir(parents=True, exist_ok=True)
        safe = namespace.replace("/", "_")
        return d / f"{safe}.json"

    def _save_cache(self, namespace: str, release_key: str, configs: Dict[str, str]) -> None:
        try:
            payload = {"releaseKey": release_key, "configurations": configs}
            self._cache_path(namespace).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:  # noqa: BLE001
            logger.warning("写入本地缓存失败 namespace=%s: %s", namespace, exc)

    def _load_cache(self, namespace: str) -> Optional[Dict[str, Any]]:
        try:
            p = self._cache_path(namespace)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:  # noqa: BLE001
            logger.warning("读取本地缓存失败 namespace=%s: %s", namespace, exc)
        return None
