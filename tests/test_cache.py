from apollo_config.client import ApolloClient


def test_cache_roundtrip(tmp_path):
    c = ApolloClient(app_id="app", config_url="http://x", cache_dir=str(tmp_path))
    c._save_cache("application", "rk1", {"a": "1", "b": "2"})

    loaded = c._load_cache("application")
    assert loaded == {"releaseKey": "rk1", "configurations": {"a": "1", "b": "2"}}


def test_cache_missing_returns_none(tmp_path):
    c = ApolloClient(app_id="app", config_url="http://x", cache_dir=str(tmp_path))
    assert c._load_cache("nope") is None


def test_cache_path_isolation_by_env(tmp_path):
    c1 = ApolloClient(app_id="app", config_url="http://x", env="DEV", cache_dir=str(tmp_path))
    c2 = ApolloClient(app_id="app", config_url="http://x", env="PROD", cache_dir=str(tmp_path))
    assert c1._cache_path("application").parent != c2._cache_path("application").parent
