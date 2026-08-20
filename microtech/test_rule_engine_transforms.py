from django.test import TestCase
from microtech.rule_engine.transforms import apply_transform


class TransformTest(TestCase):
    def test_anrede_de_normalises_salutation(self):
        self.assertEqual(apply_transform("anrede_de", "mrs"), "Frau")
        self.assertEqual(apply_transform("anrede_de", "hr"), "Herr")
        self.assertEqual(apply_transform("anrede_de", "xyz"), "")

    def test_anrede_kontakt_uses_accusative_for_herr(self):
        self.assertEqual(apply_transform("anrede_kontakt", "herr"), "Herrn")
        self.assertEqual(apply_transform("anrede_kontakt", "frau"), "Frau")

    def test_split_returns_indexed_token(self):
        self.assertEqual(apply_transform("split", "Max Mustermann", "0"), "Max")
        self.assertEqual(apply_transform("split", "Max Mustermann", "1"), "Mustermann")
        self.assertEqual(apply_transform("split", "Max", "1"), "")

    def test_unknown_transform_raises(self):
        with self.assertRaises(KeyError):
            apply_transform("nope", "x")
