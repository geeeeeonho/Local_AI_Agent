"""Models 화면이 고른 모델이 실제로 그 경로에 받아지고, 런처가 그걸 골라 쓰는가.

단위 테스트는 각 조각이 맞다고만 말한다. 조각이 서로 다른 경로를 보고 있으면
전부 통과하면서도 프로그램은 "모델이 없다" 고 한다. 그래서 여기서는 가짜
Ollama API 로 진짜 저장소를 만들어 놓고, 사슬 전체를 한 번에 지난다.

  카탈로그 3단계 계획
    -> ModelService.plan_changes() / install_model()  (Models 화면이 쓰는 경로)
    -> Ollama /api/pull 이 공용 저장소에 blobs/ + manifests/ 생성
    -> model_files 가 그 blob 이 어느 모델인지 MODEL_FILES.csv 로 기록
    -> model_roles 가 '설치된 것' 을 읽어 역할별 모델 결정
    -> 그 태그가 AgentConfig.model 로, 다시 Open Interpreter 스레드 파라미터로

가짜 Ollama 는 실제 Ollama 와 같은 레이아웃(내용 해시 blob + OCI manifest)을
만든다. 레이아웃이 틀리면 model_files 가 못 읽으므로 그것까지 함께 검증된다.
(예전 콘솔 다운로더와 선택 창은 Models 화면으로 합쳐지며 제거되었다.)
"""
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from launcher.models import model_catalog as catalog
from launcher.models import model_files
from launcher.models import model_index
from launcher.models import model_roles as roles


class _FakeOllama:
    """Ollama 의 pull / delete / tags 를 진짜와 같은 디스크 레이아웃으로 흉내낸다."""

    SHARED = hashlib.sha256(b"shared-template").hexdigest()

    def __init__(self, store: Path):
        self.store = store
        self.blobs = store / "blobs"
        self.manifests = store / "manifests" / "registry.ollama.ai"
        self.pulled = []
        self.removed = []

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

    # OllamaClient 와 같은 이름의 표면
    def list_models(self):
        return [{"name": name} for name in self.installed()]

    def pull(self, tag, progress=None):
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
        if progress is not None:
            progress({"status": "success"})
        self.pulled.append(tag)

    def remove(self, tag):
        """`ollama rm` 은 manifest 를 지운다. (진짜는 참조 없는 blob 도 함께
        정리하지만, 여기서는 manifest 제거만으로 '설치됨' 판정이 바뀐다.)"""
        name, _, version = tag.partition(":")
        namespace, _, short = name.rpartition("/")
        (self.manifests / (namespace or "library") / short / version).unlink(missing_ok=True)
        self.removed.append(tag)


class _Inference:
    """InferenceService 자리. 저장소 경로와 클라이언트만 넘긴다."""

    def __init__(self, store, client):
        self.model_dir, self.client = store, client

    def ensure_ready(self, log=None):
        return "http://127.0.0.1:11434"


class ModelPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.store = root / "models"              # C:\\LocalAI\\models 자리
        self.env = root / "environment"
        self.store.mkdir(parents=True)
        self.env.mkdir(parents=True)
        self.paths = {"env": self.env, "models": self.store}

        from services.models.service import ModelService
        self.ollama = _FakeOllama(self.store)
        self.models = ModelService(_Inference(self.store, self.ollama),
                                   lock_path=root / "model-mutation.lock")

    # ── 설치 ────────────────────────────────────────────────────
    def _apply(self, wanted):
        """Models 화면의 [선택대로 적용] 과 같은 순서: 계획, 삭제, 설치."""
        plan = self.models.plan_changes(wanted)
        for tag in plan["remove"]:
            self.models.remove_model(tag)
        for tag in plan["install"]:
            self.models.install_model(tag)
        return plan

    def _install(self):
        planned = catalog.recommended_for(catalog.MEMORY_BUDGET_GB)
        self._apply(planned)
        return sorted(planned)

    def test_the_models_screen_pulls_the_three_level_plan_into_the_model_store(self):
        pulled = self._install()
        planned = catalog.recommended_for(catalog.MEMORY_BUDGET_GB)
        self.assertEqual(set(self.ollama.pulled), planned,
                         "받은 것과 3단계 계획이 다르다")
        self.assertEqual(set(pulled), planned)
        # 진짜 저장소 자리에 파일이 생겼는가
        self.assertTrue((self.store / "blobs").is_dir())
        self.assertTrue((self.store / "manifests").is_dir())

    def test_applying_the_same_selection_again_downloads_nothing(self):
        self._install()
        before = sorted(p.name for p in (self.store / "blobs").iterdir())
        self.ollama.pulled.clear()
        plan = self._apply(catalog.recommended_for(catalog.MEMORY_BUDGET_GB))
        self.assertEqual((plan["install"], plan["remove"]), ([], []))
        self.assertEqual(self.ollama.pulled, [])
        after = sorted(p.name for p in (self.store / "blobs").iterdir())
        self.assertEqual(before, after)

    def test_the_selection_screen_receives_the_catalog_and_the_memory_budget(self):
        view = self.models.catalog()
        self.assertEqual({m["tag"] for m in view["models"]}, set(catalog.catalog_tags()))
        self.assertEqual(view["budget_gb"], catalog.MEMORY_BUDGET_GB)
        self.assertEqual(set(view["recommended"]),
                         catalog.recommended_for(catalog.MEMORY_BUDGET_GB))
        self.assertFalse(any(m["installed"] for m in view["models"]))

    def test_an_explicit_selection_installs_and_removes_exactly_what_was_checked(self):
        self._install()                       # 권장 세트를 먼저 받아 둔다
        keep, drop = sorted(self.ollama.pulled)[0], sorted(self.ollama.pulled)[-1]
        extra = next(t for t in sorted(catalog.catalog_tags())
                     if t not in self.ollama.pulled)
        self.ollama.pulled.clear()

        self._apply({keep, extra})
        self.assertEqual(self.ollama.pulled, [extra],
                         "체크한 미설치 모델만 받아야 한다")
        self.assertNotIn(drop, self.ollama.installed(),
                         "체크 해제한 설치 모델이 지워지지 않았다")
        self.assertIn(keep, self.ollama.installed())

    # ── 파일 대응표 ─────────────────────────────────────────────
    def _rows(self):
        return model_files.build_index(self.store)["files"]

    def test_the_csv_lands_next_to_the_models_and_names_every_weight_file(self):
        planned = self._install()
        csv_path = self.store / model_files.CSV_NAME
        self.assertTrue(csv_path.is_file(), "대응표가 저장소 옆에 없다")
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            written = list(csv.DictReader(stream))
        named = {r["model"] for r in written if r["layer"] == "weights" and r["status"] == "ok"}
        self.assertEqual(named, set(planned),
                         "받은 모델인데 blob 이 어느 모델인지 복원되지 않는다")
        for row in written:
            if row["status"] == "ok":
                self.assertTrue((self.store / row["rel_path"]).is_file(),
                                "표의 경로가 실제 파일을 가리키지 않는다: " + row["rel_path"])

    def test_a_shared_blob_is_reported_as_shared_not_exclusive(self):
        planned = self._install()
        shared = [r for r in self._rows() if r["layer"] == "template"]
        self.assertTrue(shared)
        self.assertEqual(shared[0]["shared_with"], len(planned),
                         "여러 모델이 함께 쓰는 파일인데 전용처럼 보인다")

    def test_nothing_is_left_unaccounted_for(self):
        self._install()
        orphans = [r for r in self._rows() if r["status"] == "orphan"]
        self.assertEqual(orphans, [], "설치 직후인데 정체불명 파일이 있다")

    def test_the_csv_belongs_to_the_shared_store_and_never_to_one_account(self):
        """쓸 수 없으면 오류로 알리고, 계정마다 두 번째 정본을 만들지 않는다."""
        self.assertEqual(model_files.default_csv_path(self.store),
                         self.store / model_files.CSV_NAME)

    def test_a_failed_index_write_never_breaks_the_install(self):
        real = model_index.publish
        self.addCleanup(setattr, model_index, "publish", real)

        def boom(*a, **kw):
            raise OSError("read-only file system")

        model_index.publish = boom
        tag = sorted(catalog.recommended_for(catalog.MEMORY_BUDGET_GB))[0]
        result = self.models.install_model(tag)   # 예외가 새어 나오면 여기서 실패한다
        self.assertEqual(result["model"], tag)
        self.assertFalse(result["index_refreshed"])
        self.assertIn(tag, self.ollama.installed())

    # ── 런처가 그걸 실제로 고르는가 ─────────────────────────────
    def _installed_from_store(self):
        names = set(model_index.read_manifests(self.store))
        return catalog.canonicalize_installed(names)

    def test_the_launcher_resolves_every_role_to_something_actually_on_disk(self):
        self._install()
        on_disk = self._installed_from_store()
        for free in (20.0, 16.0, 12.0, 8.0):
            for role in roles.LADDERS:
                chosen = roles.resolve_ladder(role, free, installed=on_disk)
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
        missing = next(t for t in sorted(catalog.catalog_tags()) if t not in on_disk)
        picked, note = roles.auto_match_installed(missing, "agent", 20.0)
        self.assertIn(picked, on_disk)
        self.assertTrue(note)

    # ── 그 태그가 실제 실행 파라미터까지 가는가 ─────────────────
    def test_the_resolved_tag_reaches_the_open_interpreter_thread(self):
        self._install()
        chosen = roles.resolve_ladder("agent", 20.0, installed=self._installed_from_store())

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
