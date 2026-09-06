"""설치기가 고른 모델이 실제로 그 경로에 받아지고, 런처가 그걸 골라 쓰는가.

단위 테스트는 각 조각이 맞다고만 말한다. 조각이 서로 다른 경로를 보고 있으면
전부 통과하면서도 프로그램은 "모델이 없다" 고 한다. 그래서 여기서는 가짜
ollama 실행 파일로 진짜 저장소를 만들어 놓고, 사슬 전체를 한 번에 지난다.

  카탈로그 3단계 계획
    -> installer.steps.model.download()  (OLLAMA_MODELS 로 pull)
    -> C:\\LLM_Models 자리의 blobs/ + manifests/
    -> model_files 가 그 blob 이 어느 모델인지 CSV 로 기록
    -> model_roles 가 '설치된 것' 을 읽어 역할별 모델 결정
    -> 그 태그가 AgentConfig.model 로, 다시 Open Interpreter 스레드 파라미터로

가짜 ollama 는 실제 Ollama 와 같은 레이아웃(내용 해시 blob + OCI manifest)을
만든다. 레이아웃이 틀리면 model_files 가 못 읽으므로 그것까지 함께 검증된다.
"""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from launcher.models import model_catalog as catalog
from launcher.models import model_files
from launcher.models import model_roles as roles

class _FakeOllama:
    """`ollama list` / `ollama pull` 을 진짜와 같은 디스크 레이아웃으로 흉내낸다.

    실행 파일을 만들어 두고 셔뱅으로 돌리면 Windows CI 에서는 못 돌아
    검증이 통째로 건너뛰어진다. 그래서 subprocess.run 자리에 끼워 넣어
    두 플랫폼에서 똑같이 돈다.
    """

    SHARED = hashlib.sha256(b"shared-template").hexdigest()

    def __init__(self, store: Path):
        self.store = store
        self.blobs = store / "blobs"
        self.manifests = store / "manifests" / "registry.ollama.ai"
        self.pulled = []

    def installed(self):
        out = []
        if self.manifests.is_dir():
            for path in sorted(self.manifests.rglob("*")):
                if not path.is_file():
                    continue
                namespace, name, tag = path.relative_to(self.manifests).parts[-3:]
                out.append("%s:%s" % (name, tag) if namespace == "library"
                           else "%s/%s:%s" % (namespace, name, tag))
        return out

    def _pull(self, tag: str) -> None:
        name, _, version = tag.partition(":")
        namespace, _, short = name.rpartition("/")
        namespace = namespace or "library"
        digest = hashlib.sha256(tag.encode()).hexdigest()

        self.blobs.mkdir(parents=True, exist_ok=True)
        (self.blobs / ("sha256-" + digest)).write_bytes(b"W" * 4096)
        (self.blobs / ("sha256-" + self.SHARED)).write_bytes(b"T" * 64)

        folder = self.manifests / namespace / short
        folder.mkdir(parents=True, exist_ok=True)
        (folder / version).write_text(json.dumps({
            "schemaVersion": 2,
            "layers": [
                {"mediaType": "application/vnd.ollama.image.model",
                 "digest": "sha256:" + digest, "size": 4096},
                {"mediaType": "application/vnd.ollama.image.template",
                 "digest": "sha256:" + self.SHARED, "size": 64},
            ],
        }), encoding="utf-8")
        self.pulled.append(tag)

    def run(self, argv, **kwargs):
        """subprocess.run 대역. 설치기가 부르는 형태만 처리한다."""
        args = [str(a) for a in argv]
        verb = args[1] if len(args) > 1 else ""
        stdout = ""
        if verb == "list":
            stdout = "NAME\tID\tSIZE\tMODIFIED\n" + "".join(
                name + "\tabc123\t1 GB\t1 day ago\n" for name in self.installed())
        elif verb == "pull":
            self._pull(args[2])
        elif verb == "rm":
            pass
        else:
            return subprocess.CompletedProcess(args, 1, "", "unknown command")
        return subprocess.CompletedProcess(args, 0, stdout, "")


class ModelPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.store = root / "LLM_Models"          # C:\\LLM_Models 자리
        self.env = root / "llm_environment"
        self.ollama_dir = self.env / "ollama_runtime"
        self.ollama_dir.mkdir(parents=True)
        self.store.mkdir(parents=True)
        # 설치기는 실행 파일의 존재만 확인하고, 호출은 아래에서 가로챈다.
        (self.ollama_dir / "ollama.exe").write_bytes(b"")
        self.paths = {"env": self.env, "ollama": self.ollama_dir, "models": self.store}

        from installer.steps import model as installer_model
        self.ollama = _FakeOllama(self.store)
        real_run = installer_model.subprocess.run
        self.addCleanup(setattr, installer_model.subprocess, "run", real_run)
        installer_model.subprocess.run = self.ollama.run

    # ── 설치 ────────────────────────────────────────────────────
    def _install(self):
        from installer.steps import model as installer_model
        return installer_model.download(self.paths)

    def test_the_installer_pulls_the_three_level_plan_into_the_model_store(self):
        pulled = self._install()
        planned = catalog.recommended_for(catalog.MEMORY_BUDGET_GB)
        self.assertEqual(set(pulled), planned,
                         "설치기가 받은 것과 3단계 계획이 다르다")
        # 진짜 저장소 자리에 파일이 생겼는가
        self.assertTrue((self.store / "blobs").is_dir())
        self.assertTrue((self.store / "manifests").is_dir())

    def test_pulling_is_idempotent(self):
        self._install()
        before = sorted(p.name for p in (self.store / "blobs").iterdir())
        self._install()          # 두 번째 실행은 전부 건너뛰어야 한다
        after = sorted(p.name for p in (self.store / "blobs").iterdir())
        self.assertEqual(before, after)

    # ── 파일 대응표 ─────────────────────────────────────────────
    def test_the_csv_lands_next_to_the_models_and_names_every_weight_file(self):
        planned = self._install()
        csv_path = self.store / model_files.CSV_NAME
        self.assertTrue(csv_path.is_file(), "대응표가 저장소 옆에 없다")

        rows = model_files.scan(self.store)
        named = {r.model for r in rows if r.layer == "weights" and r.status == "ok"}
        self.assertEqual(named, set(planned),
                         "받은 모델인데 blob 이 어느 모델인지 복원되지 않는다")
        for row in rows:
            if row.status == "ok":
                self.assertTrue((self.store / row.rel_path).is_file(),
                                "표의 경로가 실제 파일을 가리키지 않는다: " + row.rel_path)

    def test_a_shared_blob_is_reported_as_shared_not_exclusive(self):
        planned = self._install()
        rows = model_files.scan(self.store)
        shared = [r for r in rows if r.layer == "template"]
        self.assertTrue(shared)
        self.assertEqual(shared[0].shared_with, len(planned),
                         "여러 모델이 함께 쓰는 파일인데 전용처럼 보인다")

    def test_nothing_is_left_unaccounted_for(self):
        self._install()
        orphans = [r for r in model_files.scan(self.store) if r.status == "orphan"]
        self.assertEqual(orphans, [], "설치 직후인데 정체불명 파일이 있다")

    # ── 런처가 그걸 실제로 고르는가 ─────────────────────────────
    def _installed_from_store(self):
        names = set(model_files.read_manifests(self.store))
        return catalog.canonicalize_installed(names)

    def test_the_launcher_resolves_every_role_to_something_actually_on_disk(self):
        self._install()
        on_disk = self._installed_from_store()
        real = roles.installed_models
        self.addCleanup(setattr, roles, "installed_models", real)
        roles.installed_models = lambda *a, **kw: on_disk

        for free in (20.0, 16.0, 12.0, 8.0):
            for role in roles.LADDERS:
                chosen = roles.resolve_ladder(role, free)
                self.assertIn(chosen, on_disk,
                              "여유 %.0fGB / %s -> %s 는 저장소에 없다"
                              % (free, role, chosen))
                self.assertLessEqual(catalog.memory_gb(chosen), free * catalog._SAFETY)

    def test_auto_match_falls_back_to_something_present(self):
        self._install()
        on_disk = self._installed_from_store()
        real = roles.installed_models
        self.addCleanup(setattr, roles, "installed_models", real)
        roles.installed_models = lambda *a, **kw: on_disk
        # 카탈로그에 있지만 받지 않은 태그를 요청 -> 받은 것 중에서 골라야 한다
        missing = next(t for t in catalog.catalog_tags() if t not in on_disk)
        picked, note = roles.auto_match_installed(missing, "agent", 20.0)
        self.assertIn(picked, on_disk)
        self.assertTrue(note)

    # ── 그 태그가 실제 실행 파라미터까지 가는가 ─────────────────
    def test_the_resolved_tag_reaches_the_open_interpreter_thread(self):
        self._install()
        on_disk = self._installed_from_store()
        real = roles.installed_models
        self.addCleanup(setattr, roles, "installed_models", real)
        roles.installed_models = lambda *a, **kw: on_disk
        chosen = roles.resolve_ladder("agent", 20.0)

        from launcher.agent.backend import AgentConfig
        from launcher.agent.interpreter_backend import OpenInterpreterBackend
        config = AgentConfig(
            workspace=self.env / "workspace",
            mode="host",
            model=chosen,
            network_mode="blocked",
            profile_name="agent",
        )
        params = OpenInterpreterBackend()._thread_params(config)
        self.assertEqual(params["model"], chosen,
                         "고른 모델이 에이전트 실행 파라미터에 실리지 않는다")
        self.assertEqual(params["modelProvider"], "ollama")

    # ── 설치기와 런처가 같은 곳을 보는가 ────────────────────────
    def test_installer_and_launcher_agree_on_the_model_directory(self):
        from installer.steps import ollama as installer_ollama
        from launcher.services.ollama import OllamaService

        installer_env = installer_ollama.env_for(self.paths)
        launcher_env = OllamaService(self.env, model_dir=self.store).env_vars({})
        self.assertEqual(installer_env["OLLAMA_MODELS"], str(self.store))
        self.assertEqual(launcher_env["OLLAMA_MODELS"], str(self.store))
        self.assertEqual(installer_env["OLLAMA_MODELS"], launcher_env["OLLAMA_MODELS"],
                         "설치기와 런처가 다른 모델 폴더를 본다")


    # ── 저장소가 읽기 전용일 때 ─────────────────────────────────
    def test_the_csv_falls_back_when_the_shared_store_cannot_be_written(self):
        """공용 저장소는 여러 사용자가 읽도록 쓰기를 막아 두기도 한다
        (README '경로 정책'). 그때 대응표를 못 쓴다고 설치가 깨지면 안 되고,
        표 자체는 user_data 쪽에 남아야 한다.

        chmod 은 root 로 돌리면 무력해지므로 쓰기 판정 자체를 막아 확인한다.
        """
        self._install()
        real = model_files._writable
        self.addCleanup(setattr, model_files, "_writable", real)
        model_files._writable = lambda path: False

        out = model_files.default_csv_path(self.store)
        self.assertNotEqual(out.parent, self.store,
                            "쓸 수 없는 곳에 표를 쓰려 한다")
        self.assertEqual(out.name, model_files.CSV_NAME)
        # 스캔 자체는 읽기만 하므로 계속 동작해야 한다
        self.assertTrue(model_files.scan(self.store))

    def test_a_failed_write_never_breaks_the_install(self):
        real = model_files.write_csv
        self.addCleanup(setattr, model_files, "write_csv", real)

        def boom(*a, **kw):
            raise OSError("read-only file system")

        model_files.write_csv = boom
        pulled = self._install()          # 예외가 새어 나오면 여기서 실패한다
        self.assertTrue(pulled)


class ListCommandTests(unittest.TestCase):
    """`python -m launcher.models` 가 카탈로그에서 직접 목록을 찍는다.

    문서에 표를 베껴 두면 카탈로그와 갈라진다. 목록이 필요하면 이걸 찍는다.
    """

    def _run(self, *args):
        from launcher.models import __main__ as cli
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(list(args))
        return code, buf.getvalue()

    def test_the_plan_dump_lists_every_default_model_with_both_sizes(self):
        code, text = self._run("--plan")
        self.assertEqual(code, 0)
        for tag in catalog.recommended_for(catalog.MEMORY_BUDGET_GB):
            self.assertIn(tag, text)
        for key in catalog.LEVEL_KEYS:
            self.assertIn("[%s]" % catalog.level_label(key), text)

    def test_the_full_dump_shows_every_group(self):
        from launcher.models import model_classes as classes
        code, text = self._run("--free", "20")
        self.assertEqual(code, 0)
        for _key, title, _desc in classes.CLASSES:
            self.assertIn(title, text)

    def test_a_bad_free_value_is_rejected_rather_than_guessed(self):
        code, _text = self._run("--free")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
