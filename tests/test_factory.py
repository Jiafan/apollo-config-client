import pytest

from apollo_config._factory import create_config_manager, create_config_manager_from_env


def test_from_env_reads_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("APOLLO_APP_ID", "env-app")
    monkeypatch.setenv("APOLLO_CONFIG_URL", "http://env:8080")
    monkeypatch.setenv("APOLLO_CLUSTER", "cluster-a")
    monkeypatch.setenv("APOLLO_NAMESPACES", "application,database")

    mgr = create_config_manager_from_env(auto_start=False)
    assert mgr._client.app_id == "env-app"
    assert mgr._client.config_url == "http://env:8080"
    assert mgr._client.cluster == "cluster-a"
    assert set(mgr._client.namespaces) == {"application", "database"}


def test_from_env_anonymous_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APOLLO_APP_ID", "env-app")
    monkeypatch.setenv("APOLLO_CONFIG_URL", "http://env:8080")
    monkeypatch.delenv("APOLLO_ACCESS_KEY_SECRET", raising=False)

    mgr = create_config_manager_from_env(auto_start=False)
    assert mgr._client.access_key_secret is None


def test_create_config_manager_explicit():
    mgr = create_config_manager(
        app_id="a", config_url="http://x", namespaces=["application"],
        auto_start=False,
    )
    assert mgr._client.app_id == "a"
    assert mgr._client.namespaces == ["application"]
