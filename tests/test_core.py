"""Behaviour regressions; these do not establish outside use or runtime compatibility."""
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from upgrade_check.core import (Installed, Release, compare, html_report,
    index_url, make_report, parse_index, qgis_version, target_version)


def release(version='1.0', minimum='3.0', maximum='4.99', exp=False, dep=False):
    return Release('sample','Sample',version,minimum,maximum,exp,dep)


def row(local=None, current=None, target=None, version='4.2'):
    local = local or Installed('sample','Sample','1.0','3.0','3.99')
    return compare([local],current or {},target or {},version)[0]


class CoreTests(unittest.TestCase):
    def test_target_is_explicit_and_patch_uses_major_minor_index(self):
        self.assertEqual(index_url('4.2.3'),'https://plugins.qgis.org/plugins/plugins.xml?qgis=4.2')
        self.assertEqual(target_version('4.2.3'),'4.2.3')
        for bad in ['4','4.2&other=1','4.2/../../','https://example.org','-4.2','2.18']:
            with self.assertRaises(ValueError):target_version(bad)

    def test_patch_range_is_not_silently_widened(self):
        self.assertEqual(row(target={'sample':[release(maximum='4.2.1')]},version='4.2.3').status,'NO_RELEASE')

    def test_available_target_does_not_require_an_upgrade(self):
        self.assertEqual(row(target={'sample':[release()]}).status,'DECLARED')

    def test_older_target_gets_warning_without_recommendation(self):
        r=row(Installed('sample','Sample','3.4.3'),target={'sample':[release('3.3.2')]})
        self.assertEqual(r.target_release,'3.3.2')
        self.assertTrue(any('Do not downgrade' in n for n in r.notes))

    def test_stable_preferred_to_newer_experimental(self):
        r=row(target={'sample':[release('2.0',exp=True),release('1.0')]})
        self.assertEqual((r.status,r.target_release),('DECLARED','1.0'))

    def test_experimental_and_deprecated_are_not_green(self):
        self.assertEqual(row(target={'sample':[release(exp=True)]}).status,'EXPERIMENTAL')
        self.assertEqual(row(target={'sample':[release(dep=True)]}).status,'DEPRECATED')

    def test_unknown_distinct_from_known_but_no_target(self):
        self.assertEqual(row().status,'UNKNOWN')
        self.assertEqual(row(current={'sample':[release(maximum='3.99')]}).status,'NO_RELEASE')

    def test_no_fuzzy_match_by_display_name(self):
        self.assertEqual(row(Installed('private_fork','Sample'),target={'sample':[release()]}).status,'UNKNOWN')

    def test_missing_saved_reference_is_not_bundled_or_ready(self):
        r=row(Installed('GdalTools','GdalTools',bundled=False,present=False))
        self.assertEqual(r.status,'MISSING')
        self.assertNotIn('nothing to install',' '.join(r.notes))

    def test_bundled_does_not_assert_target_inclusion(self):
        r=row(Installed('db_manager','DB Manager',bundled=True))
        self.assertEqual(r.status,'BUNDLED')
        self.assertIn('were not checked',' '.join(r.notes))

    def test_missing_index_bound_is_unverified(self):
        self.assertEqual(row(target={'sample':[release(maximum='')]}).status,'UNVERIFIED')
        self.assertEqual(row(target={'sample':[release(minimum='bad')]}).status,'UNVERIFIED')

    def test_missing_local_maximum_is_not_compatibility_proof(self):
        r=row(Installed('sample','Sample','1.0','3.0',''),current={'sample':[release(maximum='3.99')]})
        self.assertEqual(r.status,'NO_RELEASE')
        self.assertIn('absence is not proof',' '.join(r.notes))

    def test_index_local_conflict_and_normalized_equivalence(self):
        r=row(Installed('sample','Sample','1.0','3.0','4.99'),current={'sample':[release(maximum='3.99')]})
        self.assertIn('bounds differ',' '.join(r.notes))
        r=row(Installed('sample','Sample','1.0','3.0','3.99'),current={'sample':[release(minimum='3.0.0',maximum='3.99.0')]})
        self.assertNotIn('bounds differ',' '.join(r.notes))

    def test_version_order_and_unknown_scheme(self):
        self.assertEqual(row(target={'sample':[release('1.9'),release('1.10')]}).target_release,'1.10')
        r=row(target={'sample':[release('summer-release'),release('1.0')]})
        self.assertIn('ordering is unclear',' '.join(r.notes))

    def test_unreadable_local_metadata_not_green(self):
        self.assertEqual(row(Installed('sample','Sample',error='bad'),target={'sample':[release()]}).status,'UNVERIFIED')

    def test_empty_or_invalid_index_is_not_no_matches(self):
        for raw in [b'<plugins/>',b'<html>Blocked</html>',b'<plugins>',b'not xml']:
            with self.assertRaises(Exception):parse_index(raw)

    def test_xml_entities_and_utf16_are_rejected(self):
        for raw in [b'<!DOCTYPE plugins [<!ENTITY x "boom">]><plugins/>',
                    '<!DOCTYPE plugins><plugins/>'.encode('utf-16')]:
            with self.assertRaises(Exception):parse_index(raw)

    def test_public_report_escapes_metadata_and_has_no_local_paths(self):
        r=row(Installed('sample','<script>alert(1)</script>','1.0'),target={'sample':[release()]})
        report=make_report([r],'3.44.15','4.2','2026-10-04T00:00:00+00:00')
        html=html_report(report)
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotRegex(html, r'/[Uu]sers/')
        self.assertNotIn('profile_path',json.dumps(report))


if __name__ == "__main__":
    unittest.main()
