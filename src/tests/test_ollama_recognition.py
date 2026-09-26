"""Recognition rules for the machine-shared LocalAI Ollama broker."""
import hashlib
import json

import pytest

from launcher.services.ollama import OllamaService


def make_store(root, tags):
    payload = b"weights"
    digest = hashlib.sha256(payload).hexdigest()
    (root / "blobs").mkdir(parents=True, exist_ok=True)
    (root / "blobs" / ("sha256-" + digest)).write_bytes(payload)
    for tag in tags:
        name, _, version = tag.partition(":")
        folder = root / "manifests" / "registry.ollama.ai" / "library" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / version).write_text(json.dumps({
            "schemaVersion": 2,
            "config": {"digest": "sha256:" + digest, "size": len(payload)},
            "layers": [{
                "digest": "sha256:" + digest,
                "size": len(payload),
                "mediaType": "application/vnd.ollama.image.model",
            }],
        }))
    return root


def shared_service(tmp_path, monkeypatch, tags=("qwen3:8b",)):
    import model_router_stub as router
    import project_paths

    root = tmp_path / "LocalAI"
    broker = root / "ollama"
    broker.mkdir(parents=True)
    exe = broker / "ollama.exe"
    exe.write_text("managed", encoding="utf-8")
    store = make_store(root / "models", list(tags))
    router.serve(monkeypatch, list(tags))

    monkeypatch.setattr(project_paths, "OLLAMA_INSTALL_DIR", broker)
    svc = OllamaService(root / "environment", model_dir=store)
    svc.exe = exe
    svc.portable_exe = exe
    return svc, store, exe


def test_running_shared_broker_is_recognised_without_this_accounts_state(tmp_path, monkeypatch):
    svc, store, exe = shared_service(tmp_path, monkeypatch)
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: 4242)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: exe)
    monkeypatch.setattr(svc, "_state_matches", lambda _pid: False)
    monkeypatch.setattr(svc, "_launched_by_us", lambda _pid: False)

    assert svc.is_managed_running() is True
    assert svc.ensure_running(boot_timeout=1) is True


def test_external_ollama_on_the_port_is_not_substituted_for_shared_broker(tmp_path, monkeypatch):
    svc, store, exe = shared_service(tmp_path, monkeypatch)
    foreign = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("external", encoding="utf-8")
    monkeypatch.setattr(svc, "is_running", lambda: True)
    monkeypatch.setattr(svc, "_listener_pid", lambda: 4242)
    monkeypatch.setattr(svc, "_process_executable", lambda _pid: foreign)

    assert svc.is_managed_running() is False
    assert svc.ensure_running(boot_timeout=1) is False


def test_shared_store_matches_router_inventory(tmp_path, monkeypatch):
    svc, store, exe = shared_service(tmp_path, monkeypatch, tags=("qwen3:8b",))
    assert svc.store_agrees() is True
    assert svc.describe_store().startswith("모델 저장소 일치")


def test_a_manifest_the_scan_cannot_read_is_not_evidence_of_anything(tmp_path, monkeypatch):
    import model_router_stub as router
    from integrations.ollama import inventory
    (tmp_path / "manifests").mkdir()
    router.serve(monkeypatch, ["qwen3:8b"])
    router.store(monkeypatch, [], unreadable=["manifests/library/qwen3/8b"])
    assert inventory.read(tmp_path).agreement is None


def test_a_store_that_does_not_exist_yet_holds_nothing_and_says_so(tmp_path, monkeypatch):
    import model_router_stub as router
    from integrations.ollama import inventory
    router.serve(monkeypatch, ["qwen3:8b"])
    read = inventory.read(tmp_path / "not-created-yet")
    assert read.on_disk == frozenset()
    assert read.agreement is False


def test_a_cloud_tag_is_served_without_ever_being_on_this_disk(tmp_path, monkeypatch):
    import model_router_stub as router
    from integrations.ollama import inventory
    router.serve(monkeypatch, ["gpt-oss:120b-cloud"])
    router.store(monkeypatch, [])
    assert inventory.read(tmp_path).agreement is True


def test_a_model_that_really_is_missing_still_disagrees(tmp_path, monkeypatch):
    import model_router_stub as router
    from integrations.ollama import inventory
    router.serve(monkeypatch, ["qwen3:8b"])
    router.store(monkeypatch, [])
    assert inventory.read(tmp_path).agreement is False


def test_health_probe_reports_model_store_detail(tmp_path):
    from test_desktop_integration import fixture
    from types import SimpleNamespace as NS

    backend, modules, calls = fixture(tmp_path)
    modules["launcher.services.ollama"] = NS(OllamaService=lambda *a, **k: NS(
        is_managed_running=lambda: True,
        describe_store=lambda: "모델 저장소 일치: C:/LocalAI/models",
    ))
    assert "C:/LocalAI/models" in backend.health(max_age=0)["ollama_store"]
