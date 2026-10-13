"""Browser subrequests obey the same local-file and metadata boundaries."""

from types import SimpleNamespace

from agent.tools.browser.browser_service import BrowserService


class _Route:
    def __init__(self, url):
        self.request = SimpleNamespace(url=url)
        self.result = None

    def abort(self):
        self.result = "blocked"

    def continue_(self):
        self.result = "continued"


def test_browser_subrequest_file_scope_and_metadata(tmp_path):
    service = object.__new__(BrowserService)
    service._config = {}
    workspace = tmp_path / "project"
    workspace.mkdir()
    inside = workspace / "inside.txt"
    outside = tmp_path / "outside.txt"
    inside.write_text("inside")
    outside.write_text("outside")
    service._set_authorized_roots((str(workspace),), ())

    for url, expected in ((inside.as_uri(), "continued"),
                          (outside.as_uri(), "blocked"),
                          ("http://169.254.169.254/latest/meta-data/", "blocked")):
        route = _Route(url)
        service._authorize_request(route)
        assert route.result == expected

    linked = workspace / "linked.txt"
    linked.symlink_to(outside)
    route = _Route(linked.as_uri())
    service._authorize_request(route)
    assert route.result == "blocked"

    service._set_authorized_roots((str(workspace),), (str(outside),))
    route = _Route(outside.as_uri())
    service._authorize_request(route)
    assert route.result == "continued"


def test_browser_full_access_subrequests_still_hide_other_chats(tmp_path, monkeypatch):
    from agent.workspace import project_store
    from agent.workspace.context import resolve_context

    work = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr(project_store, "_store_file", lambda: str(tmp_path / "projects.json"))
    owner = resolve_context("owner", "alpha", ensure=True)
    recipient = resolve_context("recipient", "alpha", ensure=True)
    other = owner.root / "secret.txt"
    own = recipient.root / "own.txt"
    other.write_text("secret")
    own.write_text("own")
    service = object.__new__(BrowserService)
    service._config = {}
    service._set_authorized_roots((str(tmp_path),), (), recipient)
    for path, expected in ((own, "continued"), (other, "blocked")):
        route = _Route(path.as_uri())
        service._authorize_request(route)
        assert route.result == expected
