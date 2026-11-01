"""Exercise committed fixtures and views against a prepared test database."""

from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

import psycopg

from importer.import_characters import import_character, validate


FIXTURE = Path(__file__).parent / "fixtures" / "fictional_characters.json"


class FixtureTests(unittest.TestCase):
    def test_fictional_fixture_validates(self):
        records = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 3)
        self.assertEqual(len({r["source_id"] for r in records}), 3)
        for record in records:
            with self.subTest(source_id=record["source_id"]):
                validate(record)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL not set")
class ViewTests(unittest.TestCase):
    def test_profiles_and_detail_views(self):
        """Two onsens and two units must still produce one profile row."""
        records = deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
        suffix = uuid4().hex
        for record in records:
            record["source_id"] += suffix
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as conn:
            with conn.transaction(force_rollback=True):
                for record in records:
                    self.assertEqual(import_character(conn, record)[0], "imported")
                for record, expected in zip(records, [(1, 2, 2), (1, 1, 0), (0, 0, 0)]):
                    rows = conn.execute("""
                        SELECT cardinality(prefectures), cardinality(onsens), cardinality(units)
                        FROM public.character_profile WHERE source_id = %s
                    """, (record["source_id"],)).fetchall()
                    self.assertEqual(rows, [expected])
                    for view, count in (("character_onsen_details", expected[1]),
                                        ("character_unit_details", expected[2])):
                        actual = conn.execute(
                            psycopg.sql.SQL("SELECT count(*) FROM public.{} WHERE source_id = %s")
                            .format(psycopg.sql.Identifier(view)), (record["source_id"],)
                        ).fetchone()[0]
                        self.assertEqual(actual, count)
                self.assertEqual(conn.execute("""
                    SELECT illustrator_name_ja, voice_actor_name_ja
                    FROM public.character_profile WHERE source_id = %s
                """, (records[2]["source_id"],)).fetchone(), (None, None))

    def test_taiwan_location_can_be_imported(self):
        """The seed must resolve Taiwan without creating it as an import side effect."""
        record = {
            "source_id": "fictional-taiwan-" + uuid4().hex,
            "source_url": "https://example.invalid/fictional-taiwan",
            "name_ja": "架空海外テスト",
            "prefecture": "台湾",
            "onsen_names": ["架空海外温泉"],
            "unit_names": [],
        }
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as conn:
            with conn.transaction(force_rollback=True):
                self.assertEqual(import_character(conn, record)[0], "imported")
                self.assertEqual(conn.execute("""
                    SELECT prefecture_name_ja FROM public.character_onsen_details
                    WHERE source_id = %s
                """, (record["source_id"],)).fetchall(), [("台湾",)])


if __name__ == "__main__":
    unittest.main()
