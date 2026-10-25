"""Regression tests for the five-role / three-level model picker."""
import json
import unittest

from launcher.models import model_catalog as catalog, model_roles as roles
from services.models.service import ModelService
from tools.verify_model_catalog import check

TREVOR = "hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q8_0"
RETIRED_Q4 = "hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q4_K_M"
HIGH = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"
PREVIOUS = "huihui_ai/qwen3-abliterated:14b"


class ModelTierVisibilityTests(unittest.TestCase):
    def test_uncensored_three_levels_preserve_high_and_low(self):
        tiers = roles.TIERS["uncensored"]
        self.assertEqual(len(tiers), 3)
        self.assertEqual(tiers[0]["primary"], HIGH)
        self.assertEqual(tiers[1]["primary"], TREVOR)
        self.assertIn(PREVIOUS, tiers[1]["alts"])
        self.assertNotIn(RETIRED_Q4, tiers[1]["alts"])
        self.assertEqual(tiers[2]["primary"], "huihui_ai/qwen3-abliterated:8b")

    def test_middle_primary_is_installable_and_recommended(self):
        entry = catalog.by_tag()[TREVOR]
        self.assertEqual(catalog.level_of(TREVOR), "mid")
        self.assertEqual(entry.memory_gb, 12.7)
        self.assertEqual(entry.size_gb, 12.7)
        self.assertIsNone(catalog.level_of(RETIRED_Q4))
        self.assertNotIn(RETIRED_Q4, catalog.by_tag())
        self.assertTrue(entry.uncensored)
        self.assertIn(TREVOR, catalog.recommended_for(20.0))
        self.assertNotIn(PREVIOUS, catalog.recommended_for(20.0))
        self.assertNotIn(RETIRED_Q4, catalog.recommended_for(20.0))
        self.assertIn(TREVOR, catalog.plan_by_level(20.0)["mid"])
        self.assertIn(PREVIOUS, catalog.catalog_tags())
        self.assertNotIn(RETIRED_Q4, catalog.catalog_tags())

    def test_runtime_chooses_trevor_before_previous_mid(self):
        actual = roles.resolve_ladder(
            "uncensored", free_gb=15.0, installed={TREVOR, PREVIOUS})
        self.assertEqual(actual, TREVOR)

    def test_uses_previous_mid_option_not_retired_q4_when_q8_cannot_fit(self):
        selected = roles.resolve_ladder(
            "uncensored", free_gb=11.0,
            installed={TREVOR, RETIRED_Q4, PREVIOUS})
        self.assertEqual(selected, PREVIOUS)

    def test_catalog_reports_roles_and_their_three_tiers(self):
        service = object.__new__(ModelService)
        view = service.catalog(installed=set(), budget_gb=20.0)
        groups = {group["key"]: group for group in view["role_tiers"]}
        self.assertEqual(set(groups), set(roles.TIERS))
        for key, group in groups.items():
            self.assertEqual(len(group["tiers"]), 3, key)
            self.assertEqual(
                [tier["level_label"] for tier in group["tiers"]],
                ["상", "중", "하"], key)
        self.assertEqual(groups["uncensored"]["tiers"][0]["primary"], HIGH)
        self.assertEqual(groups["uncensored"]["tiers"][1]["primary"], TREVOR)
        self.assertIn(PREVIOUS, groups["uncensored"]["tiers"][1]["alts"])
        self.assertNotIn(RETIRED_Q4, groups["uncensored"]["tiers"][1]["alts"])

    def test_current_stack_marks_recommended_and_optional(self):
        service = object.__new__(ModelService)
        view = service.current_stack(
            free_gb=15.0, installed={TREVOR, PREVIOUS})
        group = next(r for r in view["roles"] if r["name"] == "uncensored")
        self.assertEqual(group["chosen"], TREVOR)
        self.assertTrue(group["on_disk"])
        trevor = next(r for r in group["ladder"] if r["tag"] == TREVOR)
        previous = next(r for r in group["ladder"] if r["tag"] == PREVIOUS)
        self.assertEqual(trevor["level_label"], "중")
        self.assertTrue(trevor["is_primary"])
        self.assertFalse(previous["is_primary"])

    def test_old_q4_if_installed_remains_manageable_but_not_recommended(self):
        service = object.__new__(ModelService)
        view = service.catalog(installed={RETIRED_Q4}, budget_gb=20.0)
        self.assertIn(RETIRED_Q4, view["extra_installed"])
        self.assertNotIn(RETIRED_Q4, view["recommended"])
        self.assertNotIn(RETIRED_Q4, [item["tag"] for item in view["models"]])
        self.assertIn(TREVOR, view["recommended"])


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]


class _FakeOpener:
    def __init__(self, entries):
        self.entries = entries
        self.urls = []

    def open(self, request, timeout=None):
        self.urls.append(request.full_url)
        return _FakeResponse(json.dumps(self.entries).encode("utf-8"))


class HuggingFaceCatalogVerificationTests(unittest.TestCase):
    def test_hf_tag_uses_gguf_file_listing_instead_of_ollama_registry(self):
        fake = _FakeOpener([{
            "path": "gemma-4-12B-it-uncensored-Q8_0.gguf",
            "size": 12700000000,
            "type": "file",
        }])
        result = check(TREVOR, 12.7, opener=fake)
        self.assertTrue(result.exists)
        self.assertIsNotNone(result.actual_gb)
        self.assertIn("/api/models/TrevorJS/gemma-4-12B-it-uncensored-GGUF/tree/main",
                      fake.urls[0])
        self.assertNotIn("registry.ollama.ai", fake.urls[0])

    def test_missing_quantization_is_not_mistaken_for_a_valid_model(self):
        fake = _FakeOpener([{"path": "model-Q4_K_M.gguf", "size": 7400000000}])
        self.assertFalse(check(TREVOR, 12.7, opener=fake).exists)


if __name__ == "__main__":
    unittest.main()
