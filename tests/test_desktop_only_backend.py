"""The desktop API must not expose business routes to local browsers."""

from channel.desktop.desktop_channel import desktop_only_wsgi


def _call(app, path, headers=None):
    status = []
    body = b"".join(app({"PATH_INFO": path, **(headers or {})},
                       lambda value, _: status.append(value)))
    return status[0], body


def test_desktop_api_requires_the_owning_shell_token():
    api = desktop_only_wsgi(lambda env, start: (
        start("200 OK", []), [b"private"])[1], "secret")

    status, body = _call(api, "/api/channels")
    assert status == "403 Forbidden"
    assert b"private" not in body

    assert _call(api, "/api/channels", {
        "HTTP_X_STELLA_DESKTOP_TOKEN": "secret"}) == ("200 OK", b"private")
    assert _call(api, "/api/channels", {
        "HTTP_AUTHORIZATION": "Bearer secret"}) == ("200 OK", b"private")

    # Liveness and browser-based OAuth redirects cannot carry the token.
    assert _call(api, "/api/health") == ("200 OK", b"private")
    assert _call(api, "/mcp/oauth/callback") == ("200 OK", b"private")


def test_electron_file_origin_preflight_and_response_headers():
    captured = []

    def respond(status, headers):
        captured.append((status, dict(headers)))

    api = desktop_only_wsgi(lambda env, start: (
        start("200 OK", []), [b"private"])[1], "secret")

    result = b"".join(api({
        "PATH_INFO": "/api/channels",
        "REQUEST_METHOD": "OPTIONS",
        "HTTP_ORIGIN": "null",
    }, respond))
    assert result == b""
    assert captured[-1][0] == "204 No Content"
    assert captured[-1][1]["Access-Control-Allow-Origin"] == "null"

    result = b"".join(api({
        "PATH_INFO": "/api/channels",
        "REQUEST_METHOD": "GET",
        "HTTP_ORIGIN": "null",
        "HTTP_X_STELLA_DESKTOP_TOKEN": "secret",
    }, respond))
    assert result == b"private"
    assert captured[-1][1]["Access-Control-Allow-Credentials"] == "true"

    assert _call(api, "/api/channels", {
        "REQUEST_METHOD": "OPTIONS",
        "HTTP_ORIGIN": "https://untrusted.example",
    })[0] == "403 Forbidden"
