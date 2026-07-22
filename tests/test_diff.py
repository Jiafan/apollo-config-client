from apollo_config.client import ApolloClient


def test_diff_add_update_delete():
    old = {"a": "1", "b": "2"}
    new = {"b": "20", "c": "3"}
    changes = ApolloClient._diff(old, new)

    assert set(changes) == {"a", "b", "c"}
    assert changes["a"] == {"old": "1", "new": None}
    assert changes["b"] == {"old": "2", "new": "20"}
    assert changes["c"] == {"old": None, "new": "3"}


def test_diff_empty_when_equal():
    assert ApolloClient._diff({"a": "1"}, {"a": "1"}) == {}
