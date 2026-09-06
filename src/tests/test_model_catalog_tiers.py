"""모델 카탈로그(받을 수 있는 것)와 사다리(고를 수 있는 것)는 서로의 거울이어야 한다.

두 표가 갈라지면 증상이 조용하다.
  * TIERS 에만 있는 태그 → 사다리가 1순위로 고르지만 SETUP 어디에서도 받을 수 없다.
    실제로 agent 역할의 1단계(gemma4:26b-a4b-it-qat)가 이 상태였다.
  * 카탈로그에만 있는 태그 → 사용자가 디스크를 써서 받아도 런타임이 한 번도 고르지 않는다.
    실제로 gemma4:26b / gemma4:e4b / ARA Q5_K_M / 무검열 코딩 30b 가 이 상태였다.
둘 다 예외도 경고도 없이 지나가므로 여기서 못 박는다.
"""
import unittest

from installer.steps import model as installer_model
from launcher.models import model_catalog as catalog
from launcher.models import model_roles as roles


def _tier_tags():
    tags = set()
    for tier_list in roles.TIERS.values():
        for tier in tier_list:
            tags.add(tier["primary"])
            tags.update(tier.get("alts", []))
    return tags


class CatalogTierMirrorTests(unittest.TestCase):
    def test_every_selectable_model_can_be_installed(self):
        missing = sorted(_tier_tags() - catalog.catalog_tags())
        self.assertEqual(
            missing, [],
            "TIERS 가 고를 수 있는데 카탈로그에 없어 받을 방법이 없는 태그: %s" % missing)

    def test_every_installable_chat_model_is_reachable_from_some_tier(self):
        # 임베더(kind="embed")는 역할 사다리가 아니라 AnythingLLM RAG 용이라 제외.
        chat = {e.tag for e in catalog.chat_entries()}
        orphan = sorted(chat - _tier_tags())
        self.assertEqual(
            orphan, [],
            "받을 수는 있는데 어떤 사다리에도 없어 절대 선택되지 않는 태그: %s" % orphan)

    def test_retired_tags_are_not_also_offered(self):
        both = sorted(set(catalog.replaced_tags()) & catalog.catalog_tags())
        self.assertEqual(both, [], "삭제 권장이면서 동시에 설치 권장인 태그: %s" % both)

    def test_catalog_has_no_duplicate_tags(self):
        tags = [e.tag for e in catalog.all_entries()]
        self.assertEqual(sorted(tags), sorted(set(tags)))

    def test_every_tag_names_an_explicit_version(self):
        # ":" 없는 태그는 Ollama 에서 latest 로 풀린다. 카탈로그가 크기를 표기하는
        # 이상 어떤 빌드인지 고정돼 있어야 한다.
        for entry in catalog.all_entries():
            self.assertIn(":", entry.tag, entry.tag)
            self.assertGreater(entry.size_gb, 0.0, entry.tag)


class InstallSetTests(unittest.TestCase):
    def test_installer_pulls_exactly_the_core_set(self):
        self.assertEqual([tag for _label, tag in catalog.install_pairs()],
                         catalog.core_tags())

    def test_inline_fallback_matches_the_core_set(self):
        # 카탈로그 import 가 실패했을 때 쓰이는 목록. 세트가 다르면 설치 결과가
        # 조용히 갈린다.
        self.assertEqual([tag for _label, tag in installer_model._INLINE],
                         catalog.core_tags())


class RoleDisplayTests(unittest.TestCase):
    """ROLES 의 model/fallback 은 화면 표시용이고, 선택은 TIERS 가 한다."""

    def test_roles_mirror_the_first_two_tiers(self):
        for role in roles.ROLES:
            tier_list = roles.TIERS.get(role.name)
            self.assertTrue(tier_list, role.name)
            self.assertEqual(role.model, tier_list[0]["primary"], role.name)
            self.assertEqual(role.need_gb, float(tier_list[0]["need"]), role.name)
            expected_fb = tier_list[1]["primary"] if len(tier_list) > 1 else None
            self.assertEqual(role.fallback, expected_fb, role.name)

    def test_every_role_has_a_ladder(self):
        for role in roles.ROLES:
            self.assertIn(role.name, roles.LADDERS, role.name)

    def test_tier_primaries_step_down_in_memory(self):
        """기본단계(primary)를 이은 선이 곧 강등 경로다. 반드시 무거운 쪽에서
        가벼운 쪽으로 내려가야 resolve_with_rollback 의 '한 칸 아래'가 실제로
        더 가벼워진다. 대안(alts)은 같은 역할의 옆자리라 크기가 달라도 된다 —
        설치돼 있을 때만 뽑히기 때문이다."""
        for name, tier_list in roles.TIERS.items():
            steps = [catalog.memory_gb(t["primary"]) or float(t["need"])
                     for t in tier_list]
            self.assertEqual(steps, sorted(steps, reverse=True),
                             "%s 기본단계가 메모리 순으로 내려가지 않는다: %s" % (name, steps))

    def test_tier_need_matches_its_primary(self):
        for name, tier_list in roles.TIERS.items():
            for tier in tier_list:
                self.assertEqual(float(tier["need"]),
                                 catalog.memory_gb(tier["primary"]),
                                 "%s / %s" % (name, tier["primary"]))


class LadderResolutionTests(unittest.TestCase):
    def setUp(self):
        self._real_installed = roles.installed_models
        self.addCleanup(setattr, roles, "installed_models", self._real_installed)

    def test_an_installed_lower_rung_beats_an_uninstalled_top_rung(self):
        ladder = roles.LADDERS["coding"]
        top, lower = ladder[0][0], ladder[-1][0]
        roles.installed_models = lambda *a, **kw: {lower}
        # 여유는 넉넉하게 줘서 '메모리 때문에' 내려간 게 아님을 분명히 한다.
        self.assertEqual(roles.resolve_ladder("coding", 64.0), lower)
        roles.installed_models = lambda *a, **kw: {top, lower}
        self.assertEqual(roles.resolve_ladder("coding", 64.0), top)

    def test_unknown_role_has_no_ladder(self):
        self.assertIsNone(roles.resolve_ladder("no-such-role", 64.0))


class RollbackTerminationTests(unittest.TestCase):
    """사다리에 같은 태그가 두 번 나와도 롤백이 끝나야 한다.

    예전 구현은 매번 seq.index(model) 로 위치를 되찾았다. registry.json 의
    add 로 중복이 생기면 두 번째 위치에서 첫 번째 위치로 되돌아가 같은 구간을
    영원히 맴돌았다(= 에이전트 시작이 멈춘 채로 끝나지 않음).
    """

    def setUp(self):
        self._real_ladders = roles.LADDERS
        self._real_probe = roles._load_probe
        self._real_installed = roles.installed_models
        self.addCleanup(setattr, roles, "LADDERS", self._real_ladders)
        self.addCleanup(setattr, roles, "_load_probe", self._real_probe)
        self.addCleanup(setattr, roles, "installed_models", self._real_installed)

    def test_duplicate_rungs_still_terminate(self):
        calls = []

        def never_loads(model, host=None, timeout=None):
            calls.append(model)
            # 무한 루프면 테스트가 매달리는 대신 여기서 죽는다.
            assert len(calls) < 50, "롤백이 끝나지 않는다: %s" % calls[:12]
            return False

        roles.LADDERS = {
            "dup": [("a", 20.0), ("b", 12.0), ("a", 12.0), ("c", 6.0)],
        }
        roles._load_probe = never_loads
        roles.installed_models = lambda *a, **kw: None

        final = roles.resolve_with_rollback("dup", free_gb=64.0)
        self.assertEqual(final, "c")
        self.assertLessEqual(len(calls), 4)

    def test_first_model_that_loads_wins(self):
        roles.LADDERS = {"x": [("big", 20.0), ("mid", 12.0), ("small", 6.0)]}
        roles._load_probe = lambda model, host=None, timeout=None: model == "mid"
        roles.installed_models = lambda *a, **kw: None
        self.assertEqual(roles.resolve_with_rollback("x", free_gb=64.0), "mid")


class MemoryFigureTests(unittest.TestCase):
    """다운로드 크기와 상주 메모리를 섞어 쓰면 사다리가 틀린 판단을 한다."""

    def test_ladder_needs_come_from_the_catalog(self):
        table = catalog.by_tag()
        for name, ladder in roles.LADDERS.items():
            for tag, need in ladder:
                self.assertIn(tag, table, tag)
                self.assertEqual(need, table[tag].memory_gb, "%s / %s" % (name, tag))

    def test_download_and_resident_size_are_both_positive(self):
        for entry in catalog.all_entries():
            self.assertGreater(entry.size_gb, 0.0, entry.tag)
            self.assertGreater(entry.memory_gb, 0.0, entry.tag)

    def test_e4b_is_lighter_to_run_than_to_download(self):
        # Gemma 4 E 계열은 활성 파라미터만 올린다. 이 구분이 사라지면 저사양
        # 구간에서 실제로 돌아가는 모델을 "안 맞는다"고 걸러 버린다.
        e4b = catalog.by_tag()["gemma4:e4b-it-qat"]
        self.assertLess(e4b.memory_gb, e4b.size_gb)


class ToolCallingTests(unittest.TestCase):
    """Open Interpreter 는 도구 호출로 돈다. 못 부르는 모델을 고르면 멈춘 것처럼 보인다."""

    TOOL_ROLES = ("agent", "coding")

    def test_agent_and_coding_ladders_only_hold_tool_capable_models(self):
        table = catalog.by_tag()
        for role in self.TOOL_ROLES:
            for tag, _need in roles.LADDERS[role]:
                self.assertTrue(table[tag].tools,
                                "%s 사다리에 도구 호출을 못 하는 %s 가 있다" % (role, tag))

    def test_a_non_tool_model_is_still_allowed_elsewhere(self):
        # exaone3.5 는 한국어용으로 남겨 두되 도구 역할에는 못 들어간다.
        non_tool = [e.tag for e in catalog.chat_entries() if not e.tools]
        self.assertTrue(non_tool, "tools=False 표본이 사라졌다 — 테스트가 무의미해진다")
        for tag in non_tool:
            for role in self.TOOL_ROLES:
                self.assertNotIn(tag, [m for m, _ in roles.LADDERS[role]])


class MemoryAwareInstallTests(unittest.TestCase):
    """설치 기본 선택이 그 PC 에서 실제로 돌아가는 것이어야 한다.

    예전에는 정적 recommended 플래그 하나뿐이라, 여유 8GB 짜리 PC 도 50GB 를
    받아 놓고 정작 자기 사다리가 쓰는 저사양 단계는 하나도 받지 않았다.
    """

    def _picked(self, free_gb):
        return catalog.recommended_for(free_gb, roles.LADDERS)

    def test_small_machine_gets_something_it_can_actually_run(self):
        picked = self._picked(8.0)
        self.assertTrue(picked)
        usable = 8.0 * catalog._SAFETY
        for tag in picked:
            self.assertLessEqual(catalog.memory_gb(tag), usable, tag)

    def test_small_machine_does_not_download_the_big_models(self):
        picked = self._picked(8.0)
        self.assertNotIn("qwen3.6:27b", picked)
        self.assertNotIn("gemma4:26b-a4b-it-qat", picked)
        self.assertLess(catalog.download_gb(picked), 25.0)

    def test_the_set_never_shrinks_as_memory_grows(self):
        previous = 0.0
        for free in (6.0, 8.0, 12.0, 16.0, 20.0, 24.0, 48.0):
            size = catalog.download_gb(self._picked(free))
            self.assertGreaterEqual(size, previous, "여유 %.0fGB 에서 세트가 줄었다" % free)
            previous = size

    def test_a_huge_machine_does_not_pull_the_whole_catalog(self):
        # 여유가 아무리 커도 '빈 구멍 채우기'만 하므로 카탈로그 전체를 받지 않는다.
        picked = self._picked(256.0)
        self.assertLess(len(picked), len(catalog.chat_entries()))
        self.assertNotIn("prutser/gemma-4-26B-A4B-it-ara-abliterated:Q5_K_M", picked)

    def test_priority_roles_always_get_their_best_fitting_rung(self):
        for free in (8.0, 12.0, 16.0, 20.0, 24.0):
            picked = self._picked(free)
            usable = free * catalog._SAFETY
            for role in catalog.PRIORITY_ROLES:
                best = next(tag for tag, need in roles.LADDERS[role] if need <= usable)
                self.assertIn(best, picked, "여유 %.0fGB / %s" % (free, role))

    def test_big_machine_gets_the_top_rungs(self):
        picked = self._picked(24.0)
        self.assertIn("qwen3.6:27b", picked)
        self.assertIn("gemma4:26b-a4b-it-qat", picked)

    def test_every_role_is_covered_at_each_memory_level(self):
        for free in (6.0, 8.0, 12.0, 16.0, 20.0, 24.0, 48.0):
            picked = self._picked(free)
            for role, ladder in roles.LADDERS.items():
                self.assertTrue(picked & {tag for tag, _ in ladder},
                                "여유 %.0fGB 에서 %s 역할이 받을 모델이 없다" % (free, role))

    def test_undetected_memory_falls_back_to_the_static_flags(self):
        self.assertEqual(catalog.recommended_for(None),
                         {e.tag for e in catalog.all_entries() if e.recommended})


class EndToEndCoverageTests(unittest.TestCase):
    """설치 화면이 기본으로 골라 준 것만 받아도 모든 역할이 실제로 뜬다.

    이게 깨지면 증상은 "설치는 끝났는데 에이전트를 켜면 모델이 없다" 이다.
    예전에는 저사양 PC 에서 정확히 그랬다 — 사다리가 원하는 저사양 단계가
    카탈로그에도 기본 선택에도 없었다.
    """

    def setUp(self):
        self._real = roles.installed_models
        self.addCleanup(setattr, roles, "installed_models", self._real)

    def test_the_default_set_satisfies_every_role(self):
        for free in (6.0, 8.0, 12.0, 16.0, 20.0, 24.0, 48.0):
            picked = catalog.recommended_for(free, roles.LADDERS)
            roles.installed_models = lambda *a, **kw: set(picked)
            for role in roles.LADDERS:
                chosen = roles.resolve_ladder(role, free)
                self.assertIn(chosen, picked,
                              "여유 %.0fGB / %s -> %s 를 골랐는데 받은 적이 없다"
                              % (free, role, chosen))

    def test_the_chosen_model_always_fits_in_memory(self):
        for free in (6.0, 8.0, 12.0, 16.0, 20.0, 24.0):
            picked = catalog.recommended_for(free, roles.LADDERS)
            roles.installed_models = lambda *a, **kw: set(picked)
            for role in roles.LADDERS:
                chosen = roles.resolve_ladder(role, free)
                self.assertLessEqual(catalog.memory_gb(chosen), free * catalog._SAFETY,
                                     "여유 %.0fGB / %s -> %s" % (free, role, chosen))


if __name__ == "__main__":
    unittest.main()
