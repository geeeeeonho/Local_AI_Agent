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
            'hf.co/TrevorJS/gemma-4-12B-it-uncensored-GGUF:Q4_K_M')
        self.assertIn('huihui_ai/qwen3-abliterated:14b',
                      [x['tag'] for x in role['tiers'][1]['options']])
        self.assertEqual(
            role['tiers'][2]['recommended']['tag'],
            'huihui_ai/qwen3-abliterated:8b')

    def test_unassigned_models_are_still_in_optional_group(self):
        self.assertEqual(
            {x['tag'] for x in self.groups['extra'] if x['kind'] == 'embed'},
            {x.tag for x in catalog.all_entries() if x.kind == 'embed'})


if __name__ == '__main__':
    unittest.main()
