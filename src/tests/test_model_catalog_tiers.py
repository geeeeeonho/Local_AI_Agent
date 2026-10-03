"""모델 카탈로그(받을 수 있는 것)와 사다리(고를 수 있는 것)는 서로의 거울이어야 한다.

두 표가 갈라지면 증상이 조용하다.
  * TIERS 에만 있는 태그 → 사다리가 1순위로 고르지만 SETUP 어디에서도 받을 수 없다.
    실제로 agent 역할의 1단계(gemma4:26b-a4b-it-qat)가 이 상태였다.
  * 카탈로그에만 있는 태그 → 사용자가 디스크를 써서 받아도 런타임이 한 번도 고르지 않는다.
    실제로 gemma4:26b / gemma4:e4b / ARA Q5_K_M / 무검열 코딩 30b 가 이 상태였다.
둘 다 예외도 경고도 없이 지나가므로 여기서 못 박는다.
"""
import unittest

from launcher.models import model_catalog as catalog
from launcher.models import model_classes as classes
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


class MemoryBudgetTests(unittest.TestCase):
    """카탈로그는 이 PC 가 실제로 적재할 수 있는 것만 담아야 한다.

    예산 20GB 에서 가중치 상한은 18.4GB 다(나머지는 KV 캐시 몫). 예전에는
    19~21GB 짜리가 네 개 들어 있었다 — 받아도 절대 안 뜨는데 목록에는 보여서,
    디스크만 먹고 사다리는 매번 그 아래로 떨어졌다.
    """

    def test_nothing_in_the_catalog_exceeds_what_can_be_loaded(self):
        too_big = [(e.tag, e.memory_gb) for e in catalog.chat_entries()
                   if e.memory_gb > catalog.MAX_MODEL_GB]
        self.assertEqual(too_big, [],
                         "예산 %.0fGB 로는 적재 불가(상한 %.1fGB): %s"
                         % (catalog.MEMORY_BUDGET_GB, catalog.MAX_MODEL_GB, too_big))

    def test_every_model_lands_in_exactly_one_level(self):
        for entry in catalog.chat_entries():
            self.assertIn(catalog.level_of(entry.tag), catalog.LEVEL_KEYS, entry.tag)

    def test_all_three_levels_are_populated(self):
        for key, rows in catalog.by_level().items():
            self.assertTrue(rows, "%s 등급에 모델이 없다" % key)


class ThreeLevelTests(unittest.TestCase):
    """역할마다 정확히 3단계. 여유 메모리는 하루에도 오르내리므로 한 단계만
    받아 두면 그 단계가 안 맞는 순간 쓸 게 없어지고, 단계가 너무 많으면 어느
    것이 실제로 도는지 알 수 없고 디스크만 먹는다."""

    def test_every_role_has_exactly_three_tiers(self):
        for name, tier_list in roles.TIERS.items():
            self.assertEqual(len(tier_list), 3,
                             "%s 는 %d단계 (3단계여야 함)" % (name, len(tier_list)))

    def test_the_three_tiers_are_one_per_level(self):
        for name, tier_list in roles.TIERS.items():
            levels = [catalog.level_of(t["primary"]) for t in tier_list]
            self.assertEqual(levels, list(catalog.LEVEL_KEYS),
                             "%s 의 단계별 등급이 상/중/하 순이 아니다: %s" % (name, levels))

    def test_alternatives_stay_inside_their_own_level(self):
        # 대안은 '같은 등급의 다른 선택' 이다. 등급이 다르면 사다리를 내려간
        # 것인지 옆으로 간 것인지 알 수 없어진다.
        for name, tier_list in roles.TIERS.items():
            for tier in tier_list:
                want = catalog.level_of(tier["primary"])
                for alt in tier.get("alts", []):
                    self.assertEqual(catalog.level_of(alt), want,
                                     "%s: %s 는 %s 단계의 대안이 아니다"
                                     % (name, alt, want))


class InstallPlanTests(unittest.TestCase):
    """설치 계획은 '지금 여유' 가 아니라 이 PC 의 메모리 예산에서 나와야 한다.

    브라우저를 켜 둔 채 SETUP 을 돌렸다는 이유로 상 등급을 영영 못 받으면
    안 된다. 예전에는 detect_free_memory_gb() 를 그대로 넣고 있었다.
    """

    def test_the_plan_covers_all_three_levels_within_budget(self):
        plan = catalog.plan_by_level(catalog.MEMORY_BUDGET_GB)
        for key in catalog.LEVEL_KEYS:
            self.assertTrue(plan[key], "%s 등급이 계획에 없다" % key)

    def test_core_is_exactly_the_plan(self):
        self.assertEqual(set(catalog.core_tags()),
                         catalog.recommended_for(catalog.MEMORY_BUDGET_GB))

    def test_the_plan_holds_only_models_that_can_load(self):
        for tag in catalog.recommended_for(catalog.MEMORY_BUDGET_GB):
            self.assertLessEqual(catalog.memory_gb(tag), catalog.MAX_MODEL_GB, tag)

    def test_the_plan_skips_alternatives(self):
        # 대안까지 받으면 기본 설치가 두 배가 된다.
        picked = catalog.recommended_for(catalog.MEMORY_BUDGET_GB)
        primaries = {t["primary"] for tl in roles.TIERS.values() for t in tl}
        self.assertTrue(picked <= primaries)

    def test_a_smaller_budget_drops_the_upper_levels(self):
        small = catalog.recommended_for(8.0)
        self.assertTrue(small)
        for tag in small:
            self.assertEqual(catalog.level_of(tag), "low", tag)
        self.assertLess(catalog.download_gb(small),
                        catalog.download_gb(catalog.recommended_for(20.0)))

    def test_every_role_is_covered_at_each_budget(self):
        for budget in (8.0, 12.0, 16.0, 20.0):
            picked = catalog.recommended_for(budget)
            for role, ladder in roles.LADDERS.items():
                self.assertTrue(picked & {tag for tag, _ in ladder},
                                "예산 %.0fGB 에서 %s 역할이 받을 모델이 없다"
                                % (budget, role))

    def test_undetected_budget_falls_back_to_the_static_flags(self):
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

    def test_the_budget_install_satisfies_every_role_at_every_free_memory(self):
        """예산대로 한 번 설치해 두면, 그 뒤 여유가 얼마로 떨어지든 모든 역할이
        실제로 받아 둔 모델로 해결돼야 한다."""
        picked = catalog.recommended_for(catalog.MEMORY_BUDGET_GB)
        roles.installed_models = lambda *a, **kw: set(picked)
        for free in (6.0, 8.0, 12.0, 16.0, 20.0):
            for role in roles.LADDERS:
                chosen = roles.resolve_ladder(role, free)
                self.assertIn(chosen, picked,
                              "여유 %.0fGB / %s -> %s 를 골랐는데 받은 적이 없다"
                              % (free, role, chosen))

    def test_the_chosen_model_always_fits_in_memory(self):
        picked = catalog.recommended_for(catalog.MEMORY_BUDGET_GB)
        roles.installed_models = lambda *a, **kw: set(picked)
        for free in (6.0, 8.0, 12.0, 16.0, 20.0):
            for role in roles.LADDERS:
                chosen = roles.resolve_ladder(role, free)
                self.assertLessEqual(catalog.memory_gb(chosen), free * catalog._SAFETY,
                                     "여유 %.0fGB / %s -> %s" % (free, role, chosen))


class GroupTaxonomyTests(unittest.TestCase):
    """용도 그룹은 사다리·역할·화면 세 곳에 같은 이름으로 있어야 한다.

    예전에는 "context" 역할이 CLASSES 에 빠져 있어서, 사다리도 있고 모델도
    깔리는데 화면에는 그 그룹이 아예 안 나왔다. 사용자는 그 모델이 왜 깔렸는지
    알 수 없었다.
    """

    def test_ladders_roles_and_screen_groups_are_the_same_set(self):
        ladder_names = set(roles.TIERS)
        role_names = {r.name for r in roles.ROLES}
        screen_names = {key for key, _title, _desc in classes.CLASSES}
        self.assertEqual(ladder_names, role_names)
        self.assertEqual(ladder_names, screen_names)

    def test_every_group_is_titled_and_described(self):
        for key, title, desc in classes.CLASSES:
            self.assertTrue(title.strip(), key)
            self.assertTrue(desc.strip(), key)

    def test_the_purpose_groups_the_user_asked_for_all_exist(self):
        for key in ("uncensored", "coding", "agent", "office"):
            self.assertIn(key, roles.TIERS)


class GroupDepthTests(unittest.TestCase):
    """그룹마다 메모리 구간이 끊기지 않아야 한다.

    무검열 그룹은 15GB 다음이 곧바로 5GB 라, 여유 8~14GB 인 PC 는 번역 같은
    무검열 작업을 8b 로밖에 못 했다. 사다리에 큰 구멍이 없는지 본다.
    """

    #  등급이 셋으로 고정돼 있으므로 '단계 간 배율' 은 밴드 구조가 정해 버린다
    #  (상 12~18.4 / 중 6~12 / 하 ~6 이라 배율 3배까지는 구조적으로 정상).
    #  대신 각 등급의 기본단계가 그 등급이 허용하는 메모리를 실제로 쓰는지 본다.
    #  예: 중 등급(상한 12GB)에 6.5GB 짜리를 기본으로 두면 5.5GB 를 놀리는 셈이다.
    MIN_BAND_USE = 0.6

    def test_each_level_uses_the_memory_it_is_allowed(self):
        ceilings = {key: hi for key, _label, _lo, hi in catalog.LEVELS}
        for name, tier_list in roles.TIERS.items():
            for tier in tier_list:
                tag = tier["primary"]
                key = catalog.level_of(tag)
                got = catalog.memory_gb(tag)
                self.assertGreaterEqual(
                    got / ceilings[key], self.MIN_BAND_USE,
                    "%s / %s 등급 기본 %s 가 %.1fGB — 상한 %.1fGB 를 놀린다"
                    % (name, catalog.level_label(key), tag, got, ceilings[key]))

    def test_every_group_reaches_both_ends_of_the_hardware_range(self):
        for name, tier_list in roles.TIERS.items():
            steps = [catalog.memory_gb(t["primary"]) for t in tier_list]
            self.assertGreaterEqual(max(steps), 14.0, "%s 에 상위 단계가 없다" % name)
            self.assertLessEqual(min(steps), 7.0, "%s 에 저사양 단계가 없다" % name)


class UncensoredGroupTests(unittest.TestCase):
    def test_the_group_is_actually_uncensored(self):
        # 이 그룹의 모든 후보는 무검열 계열이어야 한다. 검열 모델이 섞이면
        # "무검열" 을 골랐는데 거부당하는 일이 생긴다.
        # 이름으로 판단하지 않는다 — abliteration(가중치 편집) 말고 무검열
        # 데이터로 재학습한 dolphin 계열도 있어서, 태그에 "abliterated" 가
        # 없다는 이유로 걸러지면 안 된다.
        table = catalog.by_tag()
        for tag, _need in roles.LADDERS["uncensored"]:
            self.assertTrue(table[tag].uncensored,
                            "무검열 사다리에 검열 모델 %s 가 있다" % tag)

    def test_uncensored_models_do_not_leak_into_other_groups_by_accident(self):
        # 무검열 모델을 다른 그룹에 쓰는 것 자체는 가능하지만(ARA 는 에이전트
        # 상단이기도 하다), 그건 의도된 선택이어야 한다. 여기서는 최소한
        # 무검열 그룹이 무검열 전용인지만 확인한다.
        table = catalog.by_tag()
        uncensored_here = {t for t, _ in roles.LADDERS["uncensored"]}
        self.assertTrue(all(table[t].uncensored for t in uncensored_here))


class OfficeGroupTests(unittest.TestCase):
    def test_every_default_pick_can_read_scanned_documents(self):
        """사무 보조의 본업이 스캔본·스크린샷 읽기다. 등급마다 기본단계가
        이미지를 볼 수 있어야 한다 — 예전에는 상 등급 기본이 이미지를 전혀
        못 보는 모델이었다(추론 점수만 보고 골랐다)."""
        table = catalog.by_tag()
        for tier in roles.TIERS["office"]:
            self.assertTrue(table[tier["primary"]].vision,
                            "사무 %s 단계 기본 %s 가 이미지를 못 본다"
                            % (catalog.level_label(catalog.level_of(tier["primary"])),
                               tier["primary"]))

    def test_no_text_only_candidate_can_be_auto_picked_above_the_bottom_rung(self):
        """상·중 등급의 후보는 전부 이미지를 볼 수 있어야 한다.

        사다리는 '맞는 것 중 첫 번째' 를 자동으로 고른다. 이미지를 못 보는
        후보를 위쪽 등급에 끼워 두면, 여유가 조금 모자란 순간 그게 뽑혀서
        스캔본을 못 읽는 모델이 사무 역할에 앉는다. 맨 아래 등급만 예외를
        둔다(저사양 한국어용 exaone).
        """
        table = catalog.by_tag()
        for tier in roles.TIERS["office"]:
            if catalog.level_of(tier["primary"]) == "low":
                continue
            for tag in [tier["primary"]] + list(tier.get("alts", [])):
                self.assertTrue(table[tag].vision,
                                "사무 사다리 위쪽에 이미지를 못 보는 %s 가 있다" % tag)

    def test_a_vision_candidate_exists_even_on_a_tight_machine(self):
        table = catalog.by_tag()
        seeing = [tag for tag, _need in roles.LADDERS["office"] if table[tag].vision]
        self.assertTrue(seeing)
        self.assertLessEqual(min(table[t].memory_gb for t in seeing), 7.0,
                             "저사양에서 문서 이미지를 볼 수 있는 모델이 없다")

    def test_it_prefers_long_context(self):
        table = catalog.by_tag()
        for tag, _need in roles.LADDERS["office"]:
            self.assertGreaterEqual(table[tag].ctx_k, 32, tag)


class InstalledMatchingTests(unittest.TestCase):
    """벤더 태그는 대소문자가 섞여 있다. 그대로 비교하면 멀쩡히 깔린 18GB 짜리를
    '미설치' 로 보고 다시 받는다."""

    MIXED = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"

    def test_case_differences_do_not_hide_an_installed_model(self):
        self.assertTrue(catalog.is_installed(self.MIXED, {self.MIXED.lower()}))
        self.assertTrue(catalog.is_installed(self.MIXED, {self.MIXED.upper()}))

    def test_canonicalize_rewrites_to_the_catalog_spelling(self):
        got = catalog.canonicalize_installed({self.MIXED.lower()})
        self.assertEqual(got, {self.MIXED})

    def test_models_outside_the_catalog_are_left_alone(self):
        self.assertEqual(catalog.canonicalize_installed({"MyOwn:Tag"}), {"MyOwn:Tag"})

    def test_the_ladder_finds_a_differently_cased_install(self):
        real = roles.installed_models
        self.addCleanup(setattr, roles, "installed_models", real)
        roles.installed_models = lambda *a, **kw: {self.MIXED.lower()}
        self.assertEqual(roles.resolve_ladder("uncensored", 64.0), self.MIXED)


class CandidatePoolTests(unittest.TestCase):
    """등급마다 후보가 여럿이어야 한다.

    같은 메모리 등급 안에서도 무엇을 중시하느냐가 다르다(속도 / 품질 / 무검열 /
    이미지). 후보가 하나뿐이면 그게 안 맞을 때 곧바로 한 등급 아래로 떨어진다 —
    메모리는 남는데 품질만 깎이는 낭비다.
    """

    MIN_CANDIDATES = 3

    def test_every_level_offers_several_candidates(self):
        thin = []
        for name, tier_list in roles.TIERS.items():
            for tier in tier_list:
                n = 1 + len(tier.get("alts", []))
                if n < self.MIN_CANDIDATES:
                    thin.append("%s/%s(%d개)" % (name, tier["primary"], n))
        self.assertEqual(thin, [], "후보가 %d개 미만인 등급: %s"
                         % (self.MIN_CANDIDATES, thin))

    def test_candidates_in_a_level_are_distinct(self):
        for name, tier_list in roles.TIERS.items():
            for tier in tier_list:
                members = [tier["primary"]] + list(tier.get("alts", []))
                self.assertEqual(len(members), len(set(members)),
                                 "%s 등급에 같은 후보가 두 번: %s" % (name, members))

    def test_every_candidate_explains_what_it_is_for(self):
        # 후보가 여럿이면 "왜 이걸 고르나" 가 보여야 고를 수 있다.
        for entry in catalog.all_entries():
            self.assertTrue(entry.note.strip(),
                            "%s 에 성격 라벨(note)이 없다" % entry.tag)

    def test_notes_are_short_enough_to_sit_in_a_table(self):
        for entry in catalog.all_entries():
            self.assertLessEqual(len(entry.note), 12, entry.tag)


if __name__ == "__main__":
    unittest.main()
