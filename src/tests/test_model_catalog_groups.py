"""Role-first model catalog remains complete and preserves shared choices."""
import unittest
from apps.shared.model_groups import group_catalog
from launcher.models import model_catalog as catalog, model_roles as roles
from services.models.service import ModelService


class RoleCatalogGroupingTests(unittest.TestCase):
    def setUp(self):
        service = object.__new__(ModelService)
        self.catalog = service.catalog(installed=set(), budget_gb=20.0)
        self.groups = group_catalog(self.catalog)

    def test_all_five_roles_have_exactly_three_recommended_levels(self):
        groups = self.groups['roles']
        self.assertEqual({g['key'] for g in groups}, set(roles.TIERS))
        for role in groups:
            self.assertEqual([x['level_label'] for x in role['tiers']],
                             ['상', '중', '하'])
            self.assertTrue(all(x['recommended'] is not None
                                for x in role['tiers']))
            self.assertGreater(role['optional_count'], 0)

    def test_no_catalog_model_disappears(self):
        tags = {x['tag'] for x in self.groups['extra']}
        for role in self.groups['roles']:
            for tier in role['tiers']:
                tags.add(tier['recommended']['tag'])
                tags.update(row['tag'] for row in tier['options'])
        self.assertEqual(tags, set(catalog.catalog_tags()))

    def test_shared_models_are_referenced_across_roles_not_cloned(self):
        rows = [tier['recommended'] for role in self.groups['roles']
                for tier in role['tiers']]
        gemma = [x for x in rows if x['tag'] == 'gemma4:12b']
        self.assertGreaterEqual(len(gemma), 2)
        self.assertIs(gemma[0], gemma[1])

    def test_uncensored_high_mid_low_and_previous_option(self):
        role = next(r for r in self.groups['roles'] if r['key'] == 'uncensored')
        self.assertEqual(
            role['tiers'][0]['recommended']['tag'],
            'prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S')
        self.assertEqual(
            role['tiers'][1]['recommended']['tag'],
            'hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q8_0')
        self.assertNotIn('hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q4_K_M',
                         [x['tag'] for x in role['tiers'][1]['options']])
        self.assertIn('huihui_ai/qwen3-abliterated:14b',
                      [x['tag'] for x in role['tiers'][1]['options']])
        self.assertEqual(
            role['tiers'][2]['recommended']['tag'],
            'huihui_ai/qwen3-abliterated:8b')

    def test_qwen3_vl_instruct_q4_is_visible_as_office_mid_ocr_spotlight(self):
        tag = 'qwen3-vl:8b-instruct-q4_K_M'
        office = next(r for r in self.groups['roles'] if r['key'] == 'office')
        middle = office['tiers'][1]
        self.assertEqual(middle['level_label'], '중')
        self.assertEqual(middle['recommended']['tag'], 'gemma4:12b')
        self.assertEqual([row['tag'] for row in middle['featured']], [tag])
        self.assertIn(tag, [row['tag'] for row in middle['options']])
        self.assertIn('qwen3-vl:8b', [row['tag'] for row in middle['options']])
        self.assertNotIn(tag, self.catalog['recommended'])
        self.assertFalse(next(row for row in self.catalog['models']
                              if row['tag'] == tag)['installed'])
        self.assertEqual(office['optional_count'],
                         sum(len(t['options']) - len(t['featured'])
                             for t in office['tiers']))

    def test_ocr_spotlight_stays_separate_from_lean_default_installs(self):
        tag = 'qwen3-vl:8b-instruct-q4_K_M'
        entry = catalog.by_tag()[tag]
        self.assertEqual(entry.spotlight_for, 'office')
        self.assertTrue(entry.vision)
        self.assertEqual(entry.ctx_k, 256)
        self.assertAlmostEqual(entry.size_gb, 6.2)
        self.assertGreaterEqual(entry.memory_gb, entry.size_gb)
        self.assertEqual(catalog.level_of(tag), 'mid')
        self.assertIn('Q4_K_M', tag)
        self.assertNotIn(tag, catalog.core_tags())
        self.assertEqual(len(catalog.core_tags()), 5)
        self.assertNotIn(tag, catalog.recommended_for(20.0))
        self.assertNotIn(tag, catalog.plan_by_level(20.0)['mid'])

    def test_unassigned_models_are_still_in_optional_group(self):
        self.assertEqual(
            {x['tag'] for x in self.groups['extra'] if x['kind'] == 'embed'},
            {x.tag for x in catalog.all_entries() if x.kind == 'embed'})


if __name__ == '__main__':
    unittest.main()
