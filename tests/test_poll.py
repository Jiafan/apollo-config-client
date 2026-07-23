import time

import requests_mock

from apollo_config.client import ApolloClient


def test_start_loads_config_and_fires_callback(tmp_path):
    cfg = {
        "appId": "app", "cluster": "default", "namespaceName": "application",
        "configurations": {"k": "v"}, "releaseKey": "rk1",
    }
    captured = []
    with requests_mock.Mocker() as m:
        m.get("http://x/configs/app/default/application", json=cfg)
        m.get("http://x/notifications/v2", json=[])
        c = ApolloClient(
            app_id="app", config_url="http://x", cache_dir=str(tmp_path),
            poll_timeout=1, poll_interval=0.1, max_retry_backoff=1,
        )
        c.register_callback(lambda ns, ch: captured.append((ns, ch)))
        c.start()
        time.sleep(0.3)
        c.stop()

    assert c.get_configs("application") == {"k": "v"}
    assert captured, "初始加载应触发一次变更回调"


def test_signed_requests_carry_auth_headers(tmp_path):
    with requests_mock.Mocker() as m:
        m.get("http://x/configs/app/default/application",
              json={"configurations": {}, "releaseKey": ""})
        m.get("http://x/notifications/v2", json=[])
        c = ApolloClient(
            app_id="app", config_url="http://x", access_key_secret="secret",
            cache_dir=str(tmp_path), poll_timeout=1, poll_interval=0.1,
        )
        c.start()
        time.sleep(0.2)
        c.stop()

    reqs = m.request_history
    assert any(r.headers.get("Authorization", "").startswith("Apollo app:") for r in reqs)
    assert any("Timestamp" in r.headers for r in reqs)


def test_long_poll_detects_notification_change(tmp_path):
    cfg_initial = {"configurations": {"k": "v1"}, "releaseKey": "rk1"}
    cfg_updated = {"configurations": {"k": "v2"}, "releaseKey": "rk2"}

    captured = []
    with requests_mock.Mocker() as m:
        m.get("http://x/configs/app/default/application", [
            {"json": cfg_initial},
            {"json": cfg_updated},
        ])
        # 第一次长轮询返回一次变更通知，随后保持无变更
        m.get("http://x/notifications/v2", [
            {"json": [{"namespaceName": "application", "notificationId": 2}]},
            {"json": []},
        ])
        c = ApolloClient(
            app_id="app", config_url="http://x", cache_dir=str(tmp_path),
            poll_timeout=1, poll_interval=0.1, max_retry_backoff=1,
        )
        c.register_callback(lambda ns, ch: captured.append((ns, ch)))
        c.start()
        time.sleep(1.0)
        c.stop()

    assert c.get_configs("application") == {"k": "v2"}
    # 初始加载一次 + 通知触发一次
    assert len(captured) >= 2


def test_304_no_change_does_not_raise(tmp_path):
    # 初始加载返回 200 + 完整配置；通知触发后的增量拉取带 releaseKey，
    # Apollo 返回 HTTP 304 空 body 表示无变更，不应抛 JSONDecodeError。
    cfg = {"configurations": {"k": "v1"}, "releaseKey": "rk1"}
    with requests_mock.Mocker() as m:
        m.get("http://x/configs/app/default/application", [
            {"json": cfg},
            {"status_code": 304, "text": ""},
        ])
        m.get("http://x/notifications/v2", [
            {"json": [{"namespaceName": "application", "notificationId": 2}]},
            {"json": []},
        ])
        c = ApolloClient(
            app_id="app", config_url="http://x", cache_dir=str(tmp_path),
            poll_timeout=1, poll_interval=0.1, max_retry_backoff=1,
        )
        c.start()
        time.sleep(1.0)
        c.stop()

    # 304 应被视为无变更：配置保持初始值，且 releaseKey 不被清空
    assert c.get_configs("application") == {"k": "v1"}
