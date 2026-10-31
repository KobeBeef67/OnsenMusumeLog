"""Import local character JSON into PostgreSQL without updating existing records."""

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
from getpass import getpass
import json
import os
from pathlib import Path
import re
import sys

import psycopg
from psycopg import sql


class DuplicateCharacter(Exception):
    """Roll back reference data when a concurrent writer wins an insert."""


def text(record, key, required=False):
    value = record.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{key} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value  # Preserve Japanese text exactly, including meaningful spacing.


def names(record, key):
    values = record.get(key)
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{key} must be an array")
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError(f"{key} must contain nonempty names")
    return list(dict.fromkeys(values))


def birthday(record):
    month, day = record.get("birthday_month"), record.get("birthday_day")
    if month is None and day is None:
        raw = text(record, "birthday")
        if raw is None:
            return None, None
        match = re.fullmatch(r"\s*(\d{1,2})月(\d{1,2})日\s*", raw)
        if not match:
            raise ValueError("birthday must use 月 and 日")
        month, day = map(int, match.groups())
    elif type(month) is not int or type(day) is not int:
        raise ValueError("birthday_month and birthday_day must both be integers")
    date(2000, month, day)  # Validate February 29 without storing a birth year.
    return month, day


def height(record):
    raw = record.get("height_cm")
    if raw is None:
        raw = text(record, "height")
        if raw is None:
            return None
        match = re.fullmatch(r"\s*(\d+(?:\.\d{1,2})?)\s*cm\s*", raw, re.I)
        if not match:
            raise ValueError("height must be a number followed by cm")
        raw = match.group(1)
    try:
        value = Decimal(str(raw))
        if not value.is_finite() or not 0 < value < 1000:
            raise ValueError("height_cm must be positive and below 1000")
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("height_cm must have at most two decimal places")
    except InvalidOperation:
        raise ValueError("Invalid height_cm") from None
    return value


def release_date(record):
    raw = text(record, "release_date")
    if raw is None:
        return None
    match = re.fullmatch(r"\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*", raw)
    if match:
        return date(*map(int, match.groups()))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("release_date must be YYYY-MM-DD or YYYY年M月D日")
    return date.fromisoformat(raw)


def validate(record):
    if not isinstance(record, dict):
        raise ValueError("Each character must be a JSON object")
    values = {key: text(record, key, required=True)
              for key in ("source_id", "source_url", "name_ja")}
    for key in (
        "name_en", "color_code", "school_year", "club", "blood_type", "hobby",
        "special_skill", "likes", "dislikes", "description", "main_img", "sd_img",
    ):
        values[key] = text(record, key)
    if values["color_code"] is not None and not re.fullmatch(
        r"#[0-9a-fA-F]{6}", values["color_code"]
    ):
        raise ValueError("color_code must look like #AABBCC")
    values["birthday_month"], values["birthday_day"] = birthday(record)
    values["height_cm"] = height(record)
    values["release_date"] = release_date(record)
    values["unit_lore"] = text(record, "unit_lore") or text(record, "unit")

    # Structured membership only: never guess how to split raw unit text.
    units = [name for name in names(record, "unit_names")
             if name.strip() != "未所属"]
    onsens = names(record, "onsen_names")
    prefecture = text(record, "prefecture")
    if onsens and prefecture is None:
        raise ValueError("prefecture is required with onsen_names")
    illustrator = text(record, "illustrator")
    voice_actor = text(record, "voice_actor")
    warnings = []
    if record.get("unit_names") is None and text(record, "unit") not in (None, "未所属"):
        warnings.append("raw unit text retained as unit_lore; supply verified unit_names for membership")
    if not onsens:
        warnings.append("no verified onsen_names; no onsen membership will be inserted")
    return values, illustrator, voice_actor, units, onsens, prefecture, warnings


def resolve_name(conn, table, name):
    if name is None:
        return None
    if table not in {"illustrators", "voice_actors", "units"}:
        raise ValueError("Unsupported reference table")
    table_sql = sql.Identifier("public", table)
    row = conn.execute(sql.SQL("""
        INSERT INTO {} (name_ja) VALUES (%s)
        ON CONFLICT (name_ja) DO NOTHING RETURNING id
    """).format(table_sql), (name,)).fetchone()
    if row is None:
        row = conn.execute(sql.SQL("SELECT id FROM {} WHERE name_ja = %s")
                           .format(table_sql), (name,)).fetchone()
    if row is None:
        raise RuntimeError("Reference record disappeared; retry this character")
    return row[0]


def import_character(conn, record):
    if not isinstance(record, dict):
        raise ValueError("Each character must be a JSON object")
    source_id = text(record, "source_id", required=True)
    try:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (source_id,))
            if conn.execute("SELECT id FROM public.characters WHERE source_id = %s",
                            (source_id,)).fetchone():
                return "duplicate", []
            values, illustrator, actor, units, onsens, prefecture, warnings = validate(record)
            values["illustrator_id"] = resolve_name(conn, "illustrators", illustrator)
            values["voice_actor_id"] = resolve_name(conn, "voice_actors", actor)
            query = sql.SQL("""
                INSERT INTO public.characters ({}) VALUES ({})
                ON CONFLICT (source_id) DO NOTHING RETURNING id
            """).format(
                sql.SQL(", ").join(map(sql.Identifier, values)),
                sql.SQL(", ").join(sql.Placeholder() for _ in values),
            )
            row = conn.execute(query, list(values.values())).fetchone()
            if row is None:
                raise DuplicateCharacter()
            character_id = row[0]
            for name in units:
                unit_id = resolve_name(conn, "units", name)
                conn.execute("""INSERT INTO public.character_units (character_id, unit_id)
                                VALUES (%s, %s)""", (character_id, unit_id))
            if onsens:
                row = conn.execute("SELECT id FROM public.prefectures WHERE name_ja = %s",
                                   (prefecture,)).fetchone()
                if row is None:
                    raise ValueError(f"Unknown prefecture: {prefecture!r}; check seed data")
                prefecture_id = row[0]
                for name in onsens:
                    row = conn.execute("""
                        INSERT INTO public.onsens (name_ja, prefecture_id) VALUES (%s, %s)
                        ON CONFLICT (name_ja, prefecture_id) DO NOTHING RETURNING id
                    """, (name, prefecture_id)).fetchone()
                    if row is None:
                        row = conn.execute("""SELECT id FROM public.onsens
                                              WHERE name_ja = %s AND prefecture_id = %s""",
                                           (name, prefecture_id)).fetchone()
                    if row is None:
                        raise RuntimeError("Onsen record disappeared; retry this character")
                    conn.execute("""INSERT INTO public.character_onsens (character_id, onsen_id)
                                    VALUES (%s, %s)""", (character_id, row[0]))
    except DuplicateCharacter:
        return "duplicate", []
    return "imported", warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate JSON without connecting to PostgreSQL")
    parser.add_argument("--prompt-password", action="store_true",
                        help="Prompt securely instead of using libpq authentication")
    args = parser.parse_args()
    try:
        payload = json.loads(args.json_file.read_text(encoding="utf-8-sig"))
        records = payload if isinstance(payload, list) else [payload]
        if not records:
            raise ValueError("The JSON array is empty")
    except (OSError, ValueError) as error:
        print(f"Cannot read input: {error}", file=sys.stderr)
        return 1

    counts = {"imported": 0, "duplicate": 0, "validated": 0, "failed": 0}

    def process(conn=None):
        for number, record in enumerate(records, 1):
            try:
                if conn is None:
                    warnings = validate(record)[-1]
                    result = "validated"
                else:
                    result, warnings = import_character(conn, record)
            except (ValueError, RuntimeError, psycopg.Error) as error:
                counts["failed"] += 1
                print(f"Record {number}: FAILED — {error}", file=sys.stderr)
                continue
            counts[result] += 1
            print(f"Record {number}: {result}")
            for warning in warnings:
                print(f"  WARNING: {warning}")

    if args.validate_only:
        process()
    else:
        options = dict(host=os.environ.get("PGHOST", "localhost"),
                       port=os.environ.get("PGPORT", "5432"),
                       dbname=os.environ.get("PGDATABASE", "onsen_musume"),
                       user=os.environ.get("PGUSER", "postgres"), autocommit=True)
        if args.prompt_password:
            options["password"] = getpass("PostgreSQL password: ")
        try:
            with psycopg.connect(**options) as conn:
                process(conn)
        except psycopg.Error:
            print("Database connection failed; check PGHOST, PGPORT, PGDATABASE, PGUSER "
                  "and authentication. Try --prompt-password.", file=sys.stderr)
            return 1
    print("; ".join(f"{key}: {value}" for key, value in counts.items()))
    return int(counts["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
