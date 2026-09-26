"""저장소의 blob 파일과 모델 이름을 잇는 표.

Ollama 는 받은 모델을 내용 해시로만 저장한다. C:\\LLM_Models 를 열어 보면
`sha256-...` 파일만 있고 어느 모델인지, 지워도 되는지 알 수 없다.
model_files 가 manifest 를 읽어 그 대응을 복원한다 — 여기서 그 복원이
맞는지, 그리고 사람이 헷갈릴 만한 세 가지 경우를 제대로 구분하는지 본다.
  * 여러 모델이 같은 blob 을 공유하는 경우 (지워도 파일이 안 사라진다)
  * manifest 는 가리키는데 파일이 없는 경우 (받다 만 모델)
  * 아무 manifest 도 안 쓰는 파일 (지워도 되는 잔여물)
"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from launcher.models import model_files as mf

_A = "a" * 64
_B = "b" * 64
_SHARED = "c" * 64
_CONFIG = "d" * 64
_ORPHAN = "e" * 64
_GONE = "f" * 64


def _sized(path: Path, size: int) -> None:
    with open(path, "wb") as fh:
        if size:
            fh.seek(size - 1)
            fh.write(b"\0")


def _store(tmp: Path) -> Path:
    blobs = tmp / "blobs"
    blobs.mkdir(parents=True)
    _sized(blobs / ("sha256-" + _A), 4096)
    _sized(blobs / ("sha256-" + _B), 8192)
    _sized(blobs / ("sha256-" + _SHARED), 128)
    _sized(blobs / ("sha256-" + _CONFIG), 64)
    _sized(blobs / ("sha256-" + _ORPHAN), 2048)

    manifests = tmp / "manifests" / "registry.ollama.ai"

    def manifest(namespace, name, tag, weights):
        folder = manifests / namespace / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / tag).write_text(json.dumps({
            "schemaVersion": 2,
            "config": {"mediaType": "application/vnd.docker.container.image.v1+json",
                       "digest": "sha256:" + _CONFIG, "size": 64},
            "layers": [
                {"mediaType": "application/vnd.ollama.image.model",
                 "digest": "sha256:" + weights, "size": 4096},
                {"mediaType": "application/vnd.ollama.image.template",
                 "digest": "sha256:" + _SHARED, "size": 128},
            ],
        }), encoding="utf-8")

    manifest("library", "gemma4", "12b", _A)
    manifest("prutser", "gemma-4-26B-A4B-it-ara-abliterated", "Q4_K_S", _B)
    # manifest 폴더에 섞여 있는 비-manifest 파일은 조용히 건너뛰어야 한다.
    (manifests / "library" / "gemma4" / ".DS_Store").write_text("junk", encoding="utf-8")
    return tmp


class NameRecoveryTests(unittest.TestCase):
    def test_library_models_lose_the_namespace_and_others_keep_it(self):
        with tempfile.TemporaryDirectory() as td:
            names = set(mf.read_manifests(_store(Path(td))))
        self.assertEqual(names, {
            "gemma4:12b",
            "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S",
        })

    def test_a_missing_store_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(mf.read_manifests(Path(td) / "nope"), {})
            self.assertEqual(mf.scan(Path(td) / "nope"), [])

    def test_digest_becomes_the_on_disk_file_name(self):
        self.assertEqual(mf._blob_file_name("sha256:" + _A), "sha256-" + _A)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = _store(Path(self._tmp.name))
        self.rows = mf.scan(self.root)

    def _find(self, digest, model=None):
        name = "sha256-" + digest
        return [r for r in self.rows
                if r.file_name == name and (model is None or r.model == model)]

    def test_weights_are_matched_to_their_model(self):
        row, = self._find(_A)
        self.assertEqual(row.model, "gemma4:12b")
        self.assertEqual(row.layer, "weights")
        self.assertEqual(row.status, "ok")
        self.assertEqual(row.size_bytes, 4096)

    def test_a_shared_blob_is_reported_against_every_model_that_uses_it(self):
        shared = self._find(_SHARED)
        self.assertEqual(len(shared), 2)
        for row in shared:
            self.assertEqual(row.shared_with, 2,
                             "공유 파일인데 전용처럼 보이면 지워도 되는 줄 오해한다")

    def test_a_file_only_one_model_uses_is_marked_exclusive(self):
        row, = self._find(_B)
        self.assertEqual(row.shared_with, 1)

    def test_unreferenced_files_are_reported_as_orphans(self):
        row, = self._find(_ORPHAN)
        self.assertEqual(row.status, "orphan")
        self.assertEqual(row.model, "")
        self.assertEqual(row.shared_with, 0)

    def test_a_manifest_pointing_at_a_file_that_is_gone_is_flagged(self):
        folder = self.root / "manifests" / "registry.ollama.ai" / "library" / "gemma4"
        data = json.loads((folder / "12b").read_text(encoding="utf-8"))
        data["layers"].append({"mediaType": "application/vnd.ollama.image.model",
                               "digest": "sha256:" + _GONE, "size": 999})
        (folder / "12b").write_text(json.dumps(data), encoding="utf-8")
        rows = mf.scan(self.root)
        gone = [r for r in rows if r.file_name == "sha256-" + _GONE]
        self.assertTrue(gone)
        self.assertEqual(gone[0].status, "missing")

    def test_biggest_files_come_first(self):
        sizes = [r.size_bytes for r in self.rows]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_catalog_role_is_attached_when_the_model_is_known(self):
        row, = self._find(_A)
        self.assertTrue(row.role, "카탈로그에 있는 모델인데 역할 라벨이 비어 있다")


class CsvTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = _store(Path(self._tmp.name))

    def test_csv_lands_next_to_the_models_and_round_trips(self):
        out = mf.write_csv(self.root)
        self.assertEqual(out, self.root / mf.CSV_NAME)
        with open(out, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(list(rows[0]), list(mf.FIELDS))
        self.assertEqual(len(rows), len(mf.scan(self.root)))
        models = {r["model"] for r in rows}
        self.assertIn("gemma4:12b", models)

    def test_csv_is_written_with_a_bom_so_excel_reads_korean(self):
        out = mf.write_csv(self.root)
        self.assertTrue(out.read_bytes().startswith(b"\xef\xbb\xbf"))


    def test_default_csv_path_is_always_the_shared_store(self):
        self.assertEqual(mf.default_csv_path(self.root), self.root / mf.CSV_NAME)


    def test_refresh_is_safe_when_the_store_cannot_be_read(self):
        self.assertIsNone(mf.refresh(Path(self._tmp.name) / "missing" / "x" / "y"))

    def test_summary_names_the_weight_files(self):
        text = "\n".join(mf.summary_lines(mf.scan(self.root)))
        self.assertIn("gemma4:12b", text)
        self.assertIn("잔여", text)


if __name__ == "__main__":
    unittest.main()
