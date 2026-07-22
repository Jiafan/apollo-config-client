import base64
import hashlib
import hmac
from unittest import mock

from apollo_config.client import ApolloClient


def test_anonymous_has_no_auth_headers():
    c = ApolloClient(app_id="app", config_url="http://x")
    assert c._auth_headers("/configs/app/default/application") == {}


def test_signed_headers_shape_and_value():
    c = ApolloClient(app_id="app", config_url="http://x", access_key_secret="secret")
    fixed_ts = 1600000000.0
    with mock.patch("time.time", return_value=fixed_ts):
        headers = c._auth_headers("/configs/app/default/application")

    assert headers["Timestamp"] == "1600000000000"
    assert headers["Authorization"].startswith("Apollo app:")

    plain = "1600000000000\n/configs/app/default/application"
    expected = base64.b64encode(
        hmac.new(b"secret", plain.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    assert headers["Authorization"] == f"Apollo app:{expected}"
