"""Run with python -m unittest discover -s tests -v.

Set TEST_DATABASE_URL to a test database with the project schema installed.
Database tests run inside transactions that are always rolled back.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal
import os
import unittest
from uuid import uuid4

import psycopg

from importer.import_characters import import_character, validate


def fixture():
    return {
        "source_id": f"test-{uuid4().hex}",
        "source_url": "https://example.invalid/characters/test",
        "name_ja": "架空テストキャラクター",
        "birthday": "2月29日",
        "height": "143cm",
        "release_date": "2018年11月22日",
        "unit_names": [],
        "onsen_names": [],
    }


class ValidationTests(unittest.TestCase):
    def test_japanese_values(self):
        values = validate(fixture())[0]
        self.assertEqual((values["birthday_month"], values["birthday_day"]), (2, 29))
        self.assertEqual(values["height_cm"], Decimal("143"))
        self.assertEqual(values["release_date"], date(2018, 11, 22))

    def test_invalid_values(self):
        for changes in (
            {"birthday": "2月30日"}, {"birthday_month": 2},
            {"height_cm": "NaN"}, {"height_cm": "1.234"},
            {"release_date": "2018-02-30"}, {"color_code": "red"},
            {"source_id": 111}, {"name_ja": " "},
            {"unit_names": "unit"}, {"onsen_names": ["温泉"]},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(fixture() | changes)

    def test_normalized_fields(self):
        values = validate(fixture() | {
            "birthday_month": 11, "birthday_day": 10,
            "height_cm": 143.5, "release_date": "2018-11-22",
        })[0]
        self.assertEqual(values["birthday_month"], 11)
        self.assertEqual(values["height_cm"], Decimal("143.5"))

    def test_no_guessed_memberships(self):
        result = validate(fixture() | {"unit": "Ａ / Ｂ", "unit_names": None})
        self.assertEqual(result[0]["unit_lore"], "Ａ / Ｂ")
        self.assertEqual(result[3], [])
        self.assertTrue(any("unit_names" in warning for warning in result[-1]))

    def test_deduplicate_names_and_ignore_unassigned(self):
        result = validate(fixture() | {"unit_names": ["Ａ", "Ａ", "未所属"]})
        self.assertEqual(result[3], ["Ａ"])


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL not set")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)
        self.addCleanup(self.conn.close)
        self.outer = self.conn.transaction(force_rollback=True)
        self.outer.__enter__()
        self.addCleanup(self.outer.__exit__, None, None, None)
        self.record = fixture()
        self.marker = self.record["source_id"]
        self.conn.execute("""INSERT INTO public.prefectures (name_ja) VALUES ('岡山県')
                             ON CONFLICT (name_ja) DO NOTHING""")

    def test_relations_and_duplicate_leave_everything_unchanged(self):
        record = self.record | {
            "illustrator": self.marker, "voice_actor": self.marker,
            "prefecture": "岡山県",
            "onsen_names": [self.marker + "a", self.marker + "b"],
            "unit_names": [self.marker + "a", self.marker + "b", "未所属"],
        }
        self.assertEqual(import_character(self.conn, record)[0], "imported")
        character_id = self.conn.execute(
            "SELECT id FROM public.characters WHERE source_id = %s", (self.marker,)
        ).fetchone()[0]
        tables = ("characters", "illustrators", "voice_actors", "onsens", "units",
                  "character_onsens", "character_units")

        def snapshot():
            return {table: self.conn.execute(
                psycopg.sql.SQL("SELECT * FROM public.{} ORDER BY 1, 2")
                .format(psycopg.sql.Identifier(table))
            ).fetchall() for table in tables}

        before = snapshot()
        duplicate = deepcopy(record)
        duplicate.update(name_ja="変更禁止", illustrator="新規作成禁止",
                         voice_actor="新規作成禁止", birthday="invalid",
                         unit_names=["新規作成禁止"], onsen_names=["新規作成禁止"])
        self.assertEqual(import_character(self.conn, duplicate)[0], "duplicate")
        self.assertEqual(snapshot(), before)
        for table in ("character_onsens", "character_units"):
            count = self.conn.execute(
                psycopg.sql.SQL("SELECT count(*) FROM public.{} WHERE character_id = %s")
                .format(psycopg.sql.Identifier(table)), (character_id,)
            ).fetchone()[0]
            self.assertEqual(count, 2)

    def test_failed_import_rolls_back_reference_data_then_next_import_succeeds(self):
        bad = self.record | {"illustrator": self.marker, "voice_actor": self.marker,
                             "unit_names": [self.marker], "onsen_names": [self.marker],
                             "prefecture": "存在しない都道府県"}
        with self.assertRaisesRegex(ValueError, "Unknown prefecture"):
            import_character(self.conn, bad)
        for table, column in (("characters", "source_id"), ("illustrators", "name_ja"),
                              ("voice_actors", "name_ja"), ("units", "name_ja"),
                              ("onsens", "name_ja")):
            row = self.conn.execute(
                psycopg.sql.SQL("SELECT count(*) FROM public.{} WHERE {} = %s")
                .format(psycopg.sql.Identifier(table), psycopg.sql.Identifier(column)),
                (self.marker,),
            ).fetchone()
            self.assertEqual(row[0], 0)
        self.assertEqual(import_character(self.conn, self.record)[0], "imported")

    def test_shared_credits(self):
        first = self.record | {"illustrator": self.marker, "voice_actor": self.marker}
        second = first | {"source_id": self.marker + "-second"}
        import_character(self.conn, first)
        import_character(self.conn, second)
        rows = self.conn.execute("""SELECT illustrator_id, voice_actor_id
                                   FROM public.characters WHERE source_id IN (%s, %s)""",
                                 (first["source_id"], second["source_id"])).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], rows[1])


if __name__ == "__main__":
    unittest.main()
