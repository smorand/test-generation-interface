"""The E2E suite of SPEC-0001a: the CWE-22 class, attacked at each of its sinks.

Two rules govern every test here, and both were learned by getting them wrong.

The payload is `%2E%2E`, never `%2F`. Starlette decodes `%2F` before routing and a
segment holding a `/` cannot match a `{param}`, so such a request gets the router's 404
without reaching any handler: the test passes against code with no validation at all.

The target is a *complete* decoy. A traversal that lands on a directory holding no
readable state makes the handler fail on its own and answer 404, which again passes
without any validation. The decoy has to be something the vulnerable code would
successfully serve.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tgi.agents.orchestrator import Orchestrator
from tgi.services.git_service import GitService
from tgi.services.paths import InvalidIdentifier
from tgi.services.state_manager import StateManager

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "tgi"

# Two use cases, not one. With a single one, infer_grammar raises
# "max() iterable argument is empty" (grammar.py:184) and the background task dies
# silently: that is BL-0001, out of scope here, and the sample avoids it rather than
# letting it masquerade as a containment failure.
DOC = """
### F01.EU01.CU01 Visualiser son portefeuille
F01.EU01.CU01.RM01 : Le système affiche les relations.
F01.EU01.CU01.RM02 : Le système masque les inactives.

### F01.EU01.CU02 Supprimer une relation
F01.EU01.CU02.RM01 : La suppression demande confirmation.
F01.EU01.CU02.RM02 : Une suppression est journalisée.
"""


class _ScriptedLLM:
    """Answers per agent purpose, with the scenario generator bounded to one call.

    The bound matters: without it the number of tests produced follows the number of use
    cases distillation finds in the sample document, so "exactly one test" would assert
    the fixture rather than the behaviour.
    """

    def __init__(self, first_test: dict[str, Any]) -> None:
        self._first_test = first_test
        self._generator_calls = 0

    async def chat(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> str:
        return "reponse"

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        purpose = str(kwargs.get("purpose", ""))
        if purpose == "distiller":
            return {
                "context": "Gestion de portefeuille.",
                "scenarios": [
                    {
                        "title": "Voir son portefeuille",
                        "container": "F01.EU01.CU01",
                        "requirement_refs": ["F01.EU01.CU01.RM01", "F01.EU01.CU01.RM02"],
                        "kind": "nominal",
                    }
                ],
                "discards": [],
            }
        if purpose == "scenario_generator":
            self._generator_calls += 1
            return {"tests": [self._first_test]} if self._generator_calls == 1 else {"tests": []}
        return {"updated": [], "added": [], "untestable": []}


def _sources_mentioning(needle: str) -> list[str]:
    """Source files still carrying a symbol, named rather than dumped.

    Asserting on a concatenation of every source makes pytest print the whole tree on
    failure, which buries the one fact wanted: which file still has it.
    """
    return [
        str(p.relative_to(_REPO_ROOT)) for p in sorted(_SRC.rglob("*.py")) if needle in p.read_text(encoding="utf-8")
    ]


def _file_fingerprints(root: Path) -> dict[str, str]:
    """Every file under root, by sha256, so an effect can be read off the disk."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


async def _upload(client: AsyncClient, filename: str, body: bytes = b"# spec\n" * 100) -> Any:
    return await client.post("/upload", files={"file": (filename, body, "text/markdown")})


def _uploaded_names(projects_dir: Path) -> list[str]:
    uploads = projects_dir / "_uploads"
    return sorted(p.name for p in uploads.iterdir()) if uploads.exists() else []


# ---------------------------------------------------------------------------
# SC-001 — a received filename never leaves the projects directory
# ---------------------------------------------------------------------------


async def test_e2e_001_a_hostile_name_is_reduced_to_its_basename(client: AsyncClient, projects_dir: Path) -> None:
    """E2E-001 (FR-NEW-001)."""
    assert (await _upload(client, "../../../etc/passwd.md")).status_code in {200, 303}
    assert _uploaded_names(projects_dir) == ["passwd.md"]

    # The Windows separator counts too: a client sends the one its OS uses
    assert (await _upload(client, "..\\..\\..\\etc\\passwd.md")).status_code in {200, 303}
    assert _uploaded_names(projects_dir) == ["passwd.md"]

    # The emoji is category So; a whitelist of letters would have dropped it
    unicode_name = "sp\u00e9cification_\u00e9t\u00e9_\U0001f4c4.docx"
    await _upload(client, unicode_name)
    assert unicodedata.normalize("NFC", unicode_name) in set(_uploaded_names(projects_dir))

    # Sent decomposed, stored composed. Normalising the expected side as well would cancel
    # the assertion out: the name on disk has to BE in NFC, not merely compare equal after
    # one is applied to both sides.
    decomposed = unicodedata.normalize("NFD", "caf\u00e9_r\u00e9sum\u00e9.md")
    assert decomposed != unicodedata.normalize("NFC", decomposed)
    await _upload(client, decomposed)
    stored = set(_uploaded_names(projects_dir))
    assert unicodedata.normalize("NFC", decomposed) in stored
    assert decomposed not in stored


async def test_e2e_002_an_upload_never_lands_outside_the_projects_directory(
    client: AsyncClient, projects_dir: Path, tmp_path: Path
) -> None:
    """E2E-002 (FR-NEW-001, FR-NEW-002).

    The payloads are `../../`, not deeper. From projects/_uploads that reaches exactly
    tmp_path, so the escape is observable. `../../../etc/passwd.md` raises
    FileNotFoundError and writes nothing, and a payload that fails to write proves no
    containment at all.
    """
    witness = tmp_path / "temoin.md"
    witness.write_bytes(b"TEMOIN")
    # logs is excluded: TGI_LOGS points under tmp_path and the server writes there during
    # the test, so an equality over all of tmp_path would be red even after the fix
    before = {p for p in tmp_path.rglob("*") if p.is_file() and "logs" not in p.parts}

    for name in ("../../escaped.md", "../../temoin.md", "../../../etc/passwd.md", "/absolu/evil.md"):
        response = await _upload(client, name)
        assert response.status_code != 500, name

    # Read off the filesystem, not through the API that wrote it
    assert not (tmp_path / "escaped.md").exists()
    assert witness.read_bytes() == b"TEMOIN"
    appeared = {p for p in tmp_path.rglob("*") if p.is_file() and "logs" not in p.parts} - before
    assert all(projects_dir in p.parents for p in appeared), appeared


async def test_e2e_003_an_empty_or_oversized_document_is_refused_before_any_write(
    client: AsyncClient, projects_dir: Path
) -> None:
    """E2E-003 (FR-NEW-006, FR-NEW-001)."""
    empty = await _upload(client, "vide.md", b"")
    assert empty.status_code == 400
    assert empty.json() == {"detail": "document vide"}

    oversized = await _upload(client, "gros.md", b"x" * (60 * 1024 * 1024))
    assert oversized.status_code == 413
    assert oversized.json() == {"detail": "document trop volumineux (max 50 Mo)"}

    assert _uploaded_names(projects_dir) == []
    assert list(projects_dir.glob("*/state.json")) == []

    # The inclusive bound is what tells a correct check from a >= written backwards
    at_limit = await _upload(client, "limite.md", b"# s\n" + b"x" * (50 * 1024 * 1024 - 4))
    assert at_limit.status_code in {200, 303}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (".", "document"),
        ("..", "document"),
        ("...", "document"),
        ("/", "document"),
        ("\\", "document"),
        (".. ", "document"),
        # Without the quote: httpx percent-encodes it in the Content-Disposition header,
        # so the server receives <>:%22|?* and the %22 survives sanitising. The literal
        # string the spec names is covered directly by TestSafeBasename in test_paths.py,
        # where no transport sits in the way.
        ("<>:|?*", "document"),
        ("evil.md.", "evil.md"),
    ],
)
async def test_e2e_004_a_degenerate_basename_becomes_document(
    client: AsyncClient, projects_dir: Path, raw: str, expected: str
) -> None:
    """E2E-004 (FR-NEW-001, FR-NEW-005)."""
    response = await _upload(client, raw)

    assert response.status_code != 500, raw
    assert _uploaded_names(projects_dir) == [expected]
    assert (projects_dir / "_uploads" / expected).is_file()


@pytest.mark.skipif(os.name != "nt", reason="reserved device names only alias on Windows")
@pytest.mark.parametrize("raw", ["CON", "NUL", "COM1.md", "con.MD"])
async def test_e2e_004_a_windows_device_name_is_prefixed_not_opened(
    client: AsyncClient, projects_dir: Path, raw: str
) -> None:
    """E2E-004, the Windows half. DRIFT-004 records that this is not measured on POSIX.

    Opening CON through doc_parser's synchronous read would block the event loop for the
    whole server, so the response time is part of the assertion.
    """
    started = time.monotonic()
    response = await _upload(client, raw)

    assert time.monotonic() - started < 5
    assert response.status_code != 500
    assert _uploaded_names(projects_dir) == [f"_{raw}"]


# ---------------------------------------------------------------------------
# SC-002 — a received identifier never composes a path unvalidated
# ---------------------------------------------------------------------------

_BODY = {"hash": "HEAD", "message": "q", "decision": "accepted", "name": "x"}
_PATH_FILLERS = {"scenario_id": "SC-001", "test_id": "TEST-0001", "ref": "RM01", "index": "0"}


def _project_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every (method, template) of the app that takes a project_id in its path."""
    found = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if "{project_id}" not in path:
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            found.append((method, path))
    return sorted(found)


def _fill(template: str, project_id: str) -> str:
    path = template.replace("{project_id}", project_id)
    for name, value in _PATH_FILLERS.items():
        path = path.replace(f"{{{name}}}", value)
    return path


async def _status_of_stream(app: FastAPI, path: str) -> int:
    """Drive an endless SSE route in raw ASGI and return its status.

    httpx's ASGITransport buffers the whole body before returning, and /stream has no
    end, so AsyncClient times out on it even with a valid id and a correct fix. The test
    would never pass. Resolving on the first http.response.start reads the status without
    waiting for a body that never completes.
    """
    loop = asyncio.get_running_loop()
    started: asyncio.Future[int] = loop.create_future()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }

    async def receive() -> dict[str, Any]:
        await asyncio.Event().wait()  # a client that never disconnects
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start" and not started.done():
            started.set_result(int(message["status"]))

    task = asyncio.create_task(app(scope, receive, send))
    try:
        return await asyncio.wait_for(asyncio.shield(started), timeout=5)
    finally:
        task.cancel()


async def test_e2e_006_a_well_formed_identifier_still_works(
    client: AsyncClient, app: FastAPI, projects_dir: Path
) -> None:
    """E2E-006 (FR-NEW-002, FR-NEW-004).

    The test that stops the hardening from making every existing project unreachable,
    which is the risk 9.5 names: stored ids are 36-character uuid4s while SPEC-0001b will
    mint 12-hex ones, and a pattern cut to either shape orphans the other.
    """
    manager = StateManager()
    project_id = await manager.create(doc_path="/tmp/d.md", doc_text=DOC, model_generator="m")
    # The rollback route shells out to git, so the repo has to exist or it answers 500 for
    # a reason that has nothing to do with identifier validation
    await GitService().init(project_id)
    assert len(project_id) == 36

    # A real 12-hex project, because E2E-009 makes "absent" and "refused" indistinguishable:
    # without it, acceptance of the short form would not be observable
    short = projects_dir / "0123456789ab"
    short.mkdir(parents=True, exist_ok=True)
    shutil.copy(projects_dir / project_id / "state.json", short / "state.json")

    routes = _project_routes(app)
    assert len(routes) == 22, routes

    for method, template in routes:
        if template.endswith("/stream"):
            continue
        path = _fill(template, project_id)
        response = await client.request(method, path, json=_BODY if method in {"POST", "PUT"} else None)
        # On the body, not the status: three routes legitimately 404 because the secondary
        # object is absent, so asserting status != 404 could never pass
        assert response.status_code != 500, (method, path, response.text[:200])
        if response.status_code == 404:
            assert response.json() != {"detail": f"projet inconnu: {project_id}"}, (method, path)

    assert await _status_of_stream(app, f"/projects/{project_id}/stream") == 200
    assert (await client.get("/projects/0123456789ab")).status_code == 200


async def test_e2e_007_a_project_id_decoding_to_dotdot_never_reaches_the_disk(
    client: AsyncClient, projects_dir: Path, tmp_path: Path
) -> None:
    """E2E-007 (FR-NEW-002, FR-NEW-004).

    The decoy is a *complete* state, copied from a real project, so that projects/.. is a
    valid project in every respect but its name. A partial decoy would make the read fail
    and the 404 fall out on its own, and the test would pass against vulnerable code.
    """
    manager = StateManager()
    real = await manager.create(doc_path="/tmp/d.md", doc_text=DOC, model_generator="m")
    decoy = tmp_path / "state.json"
    state = json.loads((projects_dir / real / "state.json").read_text(encoding="utf-8"))
    state["doc_text"] = "ROOT-LEAK"
    decoy.write_text(json.dumps(state), encoding="utf-8")
    before = hashlib.sha256(decoy.read_bytes()).hexdigest()

    # %2E%2E decodes to ".." and does reach the handler, unlike ..%2F..%2F which Starlette
    # decodes before routing, so the router answers 404 without any handler running
    response = await client.get("/projects/%2E%2E")

    assert response.status_code == 404
    assert response.json() == {"detail": "projet inconnu: .."}
    assert "ROOT-LEAK" not in response.text
    assert hashlib.sha256(decoy.read_bytes()).hexdigest() == before


async def test_e2e_008_a_test_id_decoding_to_dotdot_writes_nothing(
    client: AsyncClient, projects_dir: Path, tmp_path: Path
) -> None:
    """E2E-008 (FR-NEW-002, FR-NEW-004, FR-NEW-007).

    The decoy test id is planted in state because update_test only writes when the id is
    already there; without it the current code answers 404 by itself and the test is green
    against a vulnerable sink.
    """
    manager = StateManager()
    project_id = await manager.create(doc_path="/tmp/d.md", doc_text=DOC, model_generator="m")
    await manager.update_field(
        project_id,
        "scenarios",
        [{"id": "SC-001", "status": "done", "tests": [{"id": "..\\..\\evil", "name": "avant"}]}],
    )
    before = _file_fingerprints(projects_dir)

    # %5C crosses the router as a single segment, where a %2F would be decoded first and
    # never match the {test_id} placeholder
    response = await client.put(f"/projects/{project_id}/tests/%2E%2E%5C%2E%2E%5Cevil", json={"name": "edited"})

    assert response.status_code == 404
    assert response.json() == {"detail": "test inconnu: ..\\..\\evil"}
    assert list(tmp_path.rglob("*evil*")) == []
    assert _file_fingerprints(projects_dir) == before


async def test_e2e_009_malformed_and_absent_are_indistinguishable(
    client: AsyncClient, projects_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """E2E-009 (FR-NEW-002, FR-NEW-006, FR-NEW-007), plus the 7.5 observability rule."""
    caplog.set_level("WARNING")
    started = time.monotonic()
    malformed = await client.get("/projects/%2E%2E")
    malformed_elapsed = time.monotonic() - started

    started = time.monotonic()
    absent = await client.get("/projects/ffffffffffff")
    absent_elapsed = time.monotonic() - started

    assert malformed.status_code == absent.status_code == 404
    assert malformed.json() == {"detail": "projet inconnu: .."}
    assert absent.json() == {"detail": "projet inconnu: ffffffffffff"}
    assert abs(malformed_elapsed - absent_elapsed) < 0.05

    # No header separates them either, or the timing equality above would be wasted.
    # content-length is excluded and not ignored: the two bodies differ in length only
    # because the contract makes each repeat the identifier it was given, which is a
    # property of the body already asserted, not a channel of its own.
    assert set(malformed.headers) == set(absent.headers)
    volatile = {"content-length"}
    assert {k: v for k, v in malformed.headers.items() if k not in volatile} == {
        k: v for k, v in absent.headers.items() if k not in volatile
    }

    # A probe leaves nothing behind: project_dir() used to create what it resolved
    assert not (projects_dir / "ffffffffffff").exists()

    # The same indistinguishability for test ids, which carry their own absent branch.
    # Guarding only the project half left the test half answering "Test TEST-9999 not
    # found", which tells a probe which of the two it just hit.
    manager = StateManager()
    pid = await manager.create(doc_path="/tmp/d.md", doc_text=DOC, model_generator="m")
    await manager.update_field(pid, "scenarios", [{"id": "SC-001", "status": "done", "tests": []}])

    bad_test = await client.put(f"/projects/{pid}/tests/%2E%2E", json={"name": "x"})
    absent_test = await client.put(f"/projects/{pid}/tests/TEST-9999", json={"name": "x"})

    assert bad_test.status_code == absent_test.status_code == 404
    assert bad_test.json() == {"detail": "test inconnu: .."}
    assert absent_test.json() == {"detail": "test inconnu: TEST-9999"}

    # 7.5: the refusal is logged by shape, never by value, so a scan stays recognisable
    # without the payload being copied where a log viewer will later render it
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("rejected project identifier" in m for m in warnings), warnings
    assert all(".." not in m for m in warnings), warnings


async def test_e2e_010_no_path_composition_escapes_the_primitive(client: AsyncClient, app: FastAPI) -> None:
    """E2E-010 (FR-NEW-005, FR-NEW-002, FR-NEW-003, FR-NEW-007).

    Enumerates app.routes rather than a hand-written list, so a route added later without
    validation turns this red. It checks the path helpers' behaviour and not a syntactic
    property of tgi.py, which composes no path of its own: a syntactic assertion there
    would be green while proving nothing.
    """
    for method, template in _project_routes(app):
        path = _fill(template, "%2E%2E")
        if template.endswith("/stream"):
            assert await _status_of_stream(app, _fill(template, "..")) == 404
            continue
        response = await client.request(method, path, json=_BODY if method in {"POST", "PUT"} else None)
        assert response.status_code == 404, (method, path, response.status_code)
        assert response.json() == {"detail": "projet inconnu: .."}, (method, path)

    # The guard sits where the traffic passes, not only at the boundary
    with pytest.raises(InvalidIdentifier):
        StateManager().project_dir("..")
    with pytest.raises(InvalidIdentifier):
        GitService().repo_dir("..")

    import tgi.services.paths as paths_module

    for name in (
        "safe_basename",
        "validated_project_id",
        "validated_version",
        "validated_test_id",
        "InvalidIdentifier",
    ):
        assert hasattr(paths_module, name), name

    # Found wherever it lives: a spec moves to specs/archived/ once implemented, and a
    # hard-coded live path would make this fail on the move rather than on the requirement
    candidates = sorted(_REPO_ROOT.glob("specs/**/SPEC-0001a_*/spec.md"))
    assert len(candidates) == 1, candidates
    spec = candidates[0].read_text(encoding="utf-8")
    cvss = next(line for line in spec.splitlines() if line.startswith("> CVSS:"))
    assert "not scored" not in cvss
    assert "AV:" in cvss


async def test_e2e_011_a_dotdot_project_id_does_not_run_git_outside(
    client: AsyncClient, projects_dir: Path, tmp_path: Path
) -> None:
    """E2E-011 (FR-NEW-005, FR-NEW-002, FR-NEW-004).

    The only test reaching a subprocess sink rather than a file write, and the one that
    earns the C:H of the CVSS vector.

    The two calls are measured separately and never chained before the effect is read.
    That is counter-intuitive and it is the condition of validity: on vulnerable code
    validate-map creates a commit and rollback undoes it, so chaining them cancels both
    attacks out and turns the effect assertions green while both succeeded.
    """
    manager = StateManager()
    real = await manager.create(doc_path="/tmp/d.md", doc_text=DOC, model_generator="m")
    state = json.loads((projects_dir / real / "state.json").read_text(encoding="utf-8"))
    state["doc_text"] = "ROOT-LEAK"
    decoy = tmp_path / "state.json"
    decoy.write_text(json.dumps(state), encoding="utf-8")

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _git("config", "user.email", "t@t")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("commit", "-qm", "un")
    (tmp_path / "deux.txt").write_text("deux", encoding="utf-8")
    _git("add", "-A")
    _git("commit", "-qm", "deux")

    head_before = _git("rev-parse", "HEAD")
    decoy_before = hashlib.sha256(decoy.read_bytes()).hexdigest()

    first = await client.post("/projects/%2E%2E/validate-map")

    assert first.status_code == 404
    assert first.json() == {"detail": "projet inconnu: .."}
    # Immediately, before the second call: a rollback would undo a commit made here
    assert hashlib.sha256(decoy.read_bytes()).hexdigest() == decoy_before
    assert _git("rev-parse", "HEAD") == head_before

    second = await client.post("/projects/%2E%2E/rollback", json={"hash": "HEAD~1"})

    assert second.status_code == 404
    assert second.json() == {"detail": "projet inconnu: .."}
    # Read back through git itself, a channel entirely different from the one attacked
    assert _git("rev-parse", "HEAD") == head_before
    assert _git("rev-list", "--count", "HEAD") == "2"


async def test_e2e_010_the_helper_stops_the_write_even_with_the_boundary_bypassed(
    projects_dir: Path, tmp_path: Path
) -> None:
    """E2E-010, the effect half for StateManager (FR-NEW-005).

    Called from code, not over HTTP, which is the whole point of FR-NEW-005: the boundary
    check is bypassed exactly as a route added later without it would bypass it. Asserting
    only that InvalidIdentifier is raised would be satisfied by a guard that raises after
    writing, so the decoy is reread from disk.
    """
    decoy = tmp_path / "state.json"
    decoy.write_text(json.dumps({"project_id": "..", "doc_text": "ROOT-LEAK"}), encoding="utf-8")
    before = hashlib.sha256(decoy.read_bytes()).hexdigest()

    refused = False
    with contextlib.suppress(InvalidIdentifier):
        await StateManager().save("..", {"project_id": "..", "doc_text": "OVERWRITTEN"})
        refused = True

    # The effect is asserted BEFORE the refusal, deliberately. Wrapping the call in
    # pytest.raises would short-circuit on a guard that does not raise, and the decoy
    # being overwritten is the fact that matters.
    assert hashlib.sha256(decoy.read_bytes()).hexdigest() == before
    assert "OVERWRITTEN" not in decoy.read_text(encoding="utf-8")
    assert not refused, "the guard must refuse, not merely happen to write elsewhere"


async def test_e2e_011_the_helper_stops_the_subprocess_even_with_the_boundary_bypassed(
    projects_dir: Path, tmp_path: Path
) -> None:
    """E2E-011, the effect half for GitService (FR-NEW-005).

    Same reasoning one sink further: this one runs a subprocess with the composed path as
    cwd, so the effect is read back through git itself rather than through the call.
    """

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _git("config", "user.email", "t@t")
    _git("config", "user.name", "t")
    (tmp_path / "un.txt").write_text("un", encoding="utf-8")
    _git("add", "-A")
    _git("commit", "-qm", "un")
    (tmp_path / "deux.txt").write_text("deux", encoding="utf-8")
    _git("add", "-A")
    _git("commit", "-qm", "deux")
    head_before = _git("rev-parse", "HEAD")

    refused = False
    with contextlib.suppress(InvalidIdentifier):
        await GitService().rollback("..", "HEAD~1")
        refused = True

    # Effect first, same reasoning as the sibling test above
    assert _git("rev-parse", "HEAD") == head_before
    assert _git("rev-list", "--count", "HEAD") == "2"
    assert not refused, "the guard must refuse, not merely happen to leave HEAD alone"


async def test_e2e_012_an_uploaded_state_json_does_not_become_a_project(
    client: AsyncClient, projects_dir: Path
) -> None:
    """E2E-012 (FR-NEW-009, FR-NEW-001, FR-NEW-005).

    The only test here whose two halves go red for opposite reasons. On the original code
    GET / lists _uploads as a project whose state the client wrote. On a fix that has
    FR-NEW-005 but not FR-NEW-009, the same directory makes GET / raise InvalidIdentifier
    and answer 500 permanently. It guards the fix as much as the original defect.
    """
    manager = StateManager()
    real = await manager.create(doc_path="/tmp/d.md", doc_text=DOC, model_generator="m")
    state = json.loads((projects_dir / real / "state.json").read_text(encoding="utf-8"))
    state["doc_text"] = "UPLOAD-LEAK"

    response = await client.post(
        "/upload",
        files={"file": ("state.json", json.dumps(state).encode(), "application/json")},
    )
    assert response.status_code != 500

    index = await client.get("/")

    assert index.status_code == 200
    assert "_uploads" not in index.text
    assert "UPLOAD-LEAK" not in index.text

    probed = await client.get("/projects/_uploads")
    assert probed.status_code == 404
    assert probed.json() == {"detail": "projet inconnu: _uploads"}


# ---------------------------------------------------------------------------
# SC-003 — a model-supplied identifier never composes a path
# ---------------------------------------------------------------------------


async def test_e2e_005_a_model_supplied_test_id_writes_nowhere(projects_dir: Path, tmp_path: Path) -> None:
    """E2E-005 (FR-NEW-003, FR-NEW-001).

    The structural assertion is the one that is red today. The filesystem assertions are
    a regression guard rather than an attack, because the sink has no caller: said plainly
    rather than dressed up, a false "red before the fix" being worth less than no test.
    """
    llm = _ScriptedLLM(
        {
            "id": "../../evil",
            "name": "cas nominal",
            "description": "d",
            "requirement_refs": ["F01.EU01.CU01.RM01"],
            "steps": [{"order": 1, "description": "agir", "expected_result": "vu"}],
        }
    )
    orchestrator = Orchestrator(StateManager(), GitService(), llm)  # type: ignore[arg-type]
    project_id = await orchestrator._state.create(doc_path="/tmp/doc.md", doc_text=DOC, model_generator="m")
    await orchestrator._git.init(project_id)

    await orchestrator.distil(project_id)
    await orchestrator.validate_map(project_id)
    await orchestrator.run_pipeline(project_id)

    # Structural: the sinks are gone from the source tree, not merely unreachable
    assert _sources_mentioning("add_or_update_tests") == []
    assert _sources_mentioning("def tests_dir") == []
    assert not hasattr(StateManager, "add_or_update_tests")
    assert not hasattr(StateManager, "tests_dir")

    # Read through the filesystem, not through the API that wrote it
    assert list(tmp_path.rglob("evil*")) == []
    assert list(projects_dir.rglob("tests")) == []

    state = await orchestrator._state.load(project_id)
    tests = [t for scenario in state["scenarios"] for t in scenario.get("tests") or []]
    assert len(tests) == 1
    assert tests[0]["name"] == "cas nominal"
    # The generator replaces the model's id (scenario_generator.py:142), so asserting the
    # id survived would make this test unpassable before and after the fix alike
    assert re.fullmatch(r"TEST-[0-9]+", tests[0]["id"])


async def test_e2e_013_a_legitimate_edit_writes_no_per_test_file(client: AsyncClient, projects_dir: Path) -> None:
    """E2E-013 (FR-NEW-008, FR-NEW-002).

    The only test that reaches update_test by its legitimate path. E2E-005 does a
    generation and E2E-008 is refused at validation, so without this one an implementation
    that kept the per-test write inline would pass everything else.
    """
    # Created directly rather than through POST /upload: the upload fires a background
    # distillation that rewrites `scenarios`, so a planted test would be raced away.
    manager = StateManager()
    project_id = await manager.create(doc_path="/tmp/doc.md", doc_text=DOC, model_generator="m")
    await manager.update_field(
        project_id,
        "scenarios",
        [{"id": "SC-001", "status": "done", "tests": [{"id": "TEST-0001", "name": "avant"}]}],
    )
    state_path = projects_dir / project_id / "state.json"

    before = _file_fingerprints(projects_dir)

    response = await client.put(f"/projects/{project_id}/tests/TEST-0001", json={"name": "edited"})

    assert response.status_code == 200
    reread = json.loads(state_path.read_text(encoding="utf-8"))
    assert reread["scenarios"][0]["tests"][0]["name"] == "edited"

    assert list(projects_dir.rglob("tests")) == []
    # Stronger than rglob("tests"): a flat <pid>/TEST-0001.json would slip past that one
    after = _file_fingerprints(projects_dir)
    assert set(after) == set(before), "the edit created or removed a file"
    assert {k for k in after if after[k] != before[k]} == {f"{project_id}/state.json"}
