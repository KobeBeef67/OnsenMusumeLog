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
    """Read one text field, returning None for missing optional values.

    Required fields must contain nonblank text. Nonempty values are returned
    unchanged so Japanese names and descriptions retain their original text.
    """
    value = record.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{key} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value  # Preserve Japanese text exactly, including meaningful spacing.


def names(record, key):
    """Read an optional array of names and remove exact duplicates.

    Missing arrays become empty lists. Each supplied name must be nonblank
    text. dict.fromkeys preserves the order of the first occurrence of a name.
    """
    values = record.get(key)
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{key} must be an array")
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError(f"{key} must contain nonempty names")
    return list(dict.fromkeys(values))


def birthday(record):
    """Return (month, day), preferring explicit integer birthday fields.

    Otherwise parse Japanese text such as '11月10日'. Return (None, None)
    when no birthday was supplied, and reject incomplete or impossible dates.
    """
    # Prefer normalized fields; fall back to raw text only when both are absent.
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
    """Return height as Decimal centimeters, or None when it is missing.

    Prefer height_cm; otherwise parse text such as '143cm'. Reject values
    that cannot fit the database's positive numeric(5, 2) height column.
    """
    # Remove the unit from the original text only when height_cm is unavailable.
    raw = record.get("height_cm")
    if raw is None:
        raw = text(record, "height")
        if raw is None:
            return None
        match = re.fullmatch(r"\s*(\d+(?:\.\d{1,2})?)\s*cm\s*", raw, re.I)
        if not match:
            raise ValueError("height must be a number followed by cm")
        raw = match.group(1)
    # Decimal avoids float rounding when checking the database's precision.
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
    """Convert Japanese or ISO release-date text into a Python date.

    Missing values return None. The date constructor also rejects impossible
    dates such as February 30, even when the text matches the expected format.
    """
    raw = text(record, "release_date")
    if raw is None:
        return None
    # Accept the source website's Japanese format first, then YYYY-MM-DD.
    match = re.fullmatch(r"\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*", raw)
    if match:
        return date(*map(int, match.groups()))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("release_date must be YYYY-MM-DD or YYYY年M月D日")
    return date.fromisoformat(raw)


def validate(record):
    """Prepare one JSON object for import without accessing the database.

    Return character column values, illustrator name, voice actor name,
    unit names, onsen names, prefecture name, and warnings, in that order.
    Invalid supplied values raise ValueError instead of being silently dropped.
    Reference names stay separate because their database IDs are resolved later.
    """
    if not isinstance(record, dict):
        raise ValueError("Each character must be a JSON object")
    # Collect identity fields first, then optional text columns.
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
    # Convert raw measurements and dates into values PostgreSQL can store.
    values["birthday_month"], values["birthday_day"] = birthday(record)
    values["height_cm"] = height(record)
    values["release_date"] = release_date(record)
    values["unit_lore"] = text(record, "unit_lore") or text(record, "unit")

    # Structured membership only: never guess how to split raw unit text.
    units = [name for name in names(record, "unit_names")
             if name.strip() != "未所属"]
    # This JSON format assigns all listed onsens to one verified prefecture.
    onsens = names(record, "onsen_names")
    prefecture = text(record, "prefecture")
    if onsens and prefecture is None:
        raise ValueError("prefecture is required with onsen_names")
    illustrator = text(record, "illustrator")
    voice_actor = text(record, "voice_actor")
    # Missing verified memberships are allowed, but must be visible to the user.
    warnings = []
    if record.get("unit_names") is None and text(record, "unit") not in (None, "未所属"):
        warnings.append("raw unit text retained as unit_lore; supply verified unit_names for membership")
    if not onsens:
        warnings.append("no verified onsen_names; no onsen membership will be inserted")
    return values, illustrator, voice_actor, units, onsens, prefecture, warnings


def resolve_name(conn, table, name):
    """Find or create a credit/unit by exact name and return its database ID.

    Return None for an unknown optional name. This function uses the caller's
    transaction, so newly created references roll back if the character fails.
    """
    if name is None:
        return None
    if table not in {"illustrators", "voice_actors", "units"}:
        raise ValueError("Unsupported reference table")
    # SQL identifiers need identifier quoting; names use bound %s parameters.
    table_sql = sql.Identifier("public", table)
    row = conn.execute(sql.SQL("""
        INSERT INTO {} (name_ja) VALUES (%s)
        ON CONFLICT (name_ja) DO NOTHING RETURNING id
    """).format(table_sql), (name,)).fetchone()
    # A name conflict means the existing row should be reused, never updated.
    if row is None:
        row = conn.execute(sql.SQL("SELECT id FROM {} WHERE name_ja = %s")
                           .format(table_sql), (name,)).fetchone()
    if row is None:
        raise RuntimeError("Reference record disappeared; retry this character")
    return row[0]


def import_character(conn, record):
    """Import one character atomically and return (status, warnings).

    Status is 'imported' or 'duplicate'. Existing characters are skipped before
    any references are created. Other failures propagate to the batch handler,
    after this character's database changes have been rolled back.
    """
    if not isinstance(record, dict):
        raise ValueError("Each character must be a JSON object")
    source_id = text(record, "source_id", required=True)
    try:
        # The CLI uses autocommit: this block commits one complete character
        # on success, or rolls back all its rows if an exception leaves it.
        with conn.transaction():
            # Importer processes with the same source ID wait for one another.
            # PostgreSQL releases this advisory lock when the transaction ends.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (source_id,))
            # Skip duplicates before validating optional fields or adding names.
            if conn.execute("SELECT id FROM public.characters WHERE source_id = %s",
                            (source_id,)).fetchone():
                return "duplicate", []
            # Validate the new record and replace credit names with foreign keys.
            values, illustrator, actor, units, onsens, prefecture, warnings = validate(record)
            values["illustrator_id"] = resolve_name(conn, "illustrators", illustrator)
            values["voice_actor_id"] = resolve_name(conn, "voice_actors", actor)
            # Build columns from our validated dictionary, binding values safely.
            # DO NOTHING also protects against writers that don't use our lock.
            query = sql.SQL("""
                INSERT INTO public.characters ({}) VALUES ({})
                ON CONFLICT (source_id) DO NOTHING RETURNING id
            """).format(
                sql.SQL(", ").join(map(sql.Identifier, values)),
                sql.SQL(", ").join(sql.Placeholder() for _ in values),
            )
            row = conn.execute(query, list(values.values())).fetchone()
            if row is None:
                # Raising here rolls back any references created before the
                # conflicting insert, preventing unused reference records.
                raise DuplicateCharacter()
            character_id = row[0]
            # Connect the new character to each verified unit.
            for name in units:
                unit_id = resolve_name(conn, "units", name)
                conn.execute("""INSERT INTO public.character_units (character_id, unit_id)
                                VALUES (%s, %s)""", (character_id, unit_id))
            if onsens:
                # Prefectures must already exist in the seed data. A misspelled
                # name must fail rather than create a new prefecture silently.
                row = conn.execute("SELECT id FROM public.prefectures WHERE name_ja = %s",
                                   (prefecture,)).fetchone()
                if row is None:
                    raise ValueError(f"Unknown prefecture: {prefecture!r}; check seed data")
                prefecture_id = row[0]
                for name in onsens:
                    # Reuse onsens by the pair (name, prefecture), then add
                    # their many-to-many associations with this character.
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
        # This handler runs after the transaction has rolled back the conflict.
        return "duplicate", []
    return "imported", warnings


def main():
    """Read command-line options, process the JSON file, and return an exit code.

    Validation-only mode needs no database. Import mode commits successful
    characters individually and continues after record-level failures.
    Return 0 on success, or 1 for input, connection, or record failures.
    """
    # Parse the filename and optional validation/authentication switches.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate JSON without connecting to PostgreSQL")
    parser.add_argument("--prompt-password", action="store_true",
                        help="Prompt securely instead of using libpq authentication")
    args = parser.parse_args()
    # utf-8-sig accepts UTF-8 files both with and without a Windows-style BOM.
    # Wrap a single object in a list so both input formats use the same loop.
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
        """Process the loaded records and update the enclosing summary counts.

        Without a connection, only validate. Catch errors per record so one
        failure does not prevent later characters from being attempted.
        """
        for number, record in enumerate(records, 1):
            try:
                if conn is None:
                    warnings = validate(record)[-1]
                    result = "validated"
                else:
                    result, warnings = import_character(conn, record)
            except (ValueError, RuntimeError, psycopg.Error) as error:
                # import_character has already rolled back this failed record.
                counts["failed"] += 1
                print(f"Record {number}: FAILED — {error}", file=sys.stderr)
                continue
            counts[result] += 1
            print(f"Record {number}: {result}")
            for warning in warnings:
                print(f"  WARNING: {warning}")

    # Select offline validation or an authenticated PostgreSQL import.
    if args.validate_only:
        process()
    else:
        # Connection settings come from environment variables with local defaults.
        # Autocommit leaves transaction boundaries to import_character.
        options = dict(host=os.environ.get("PGHOST", "localhost"),
                       port=os.environ.get("PGPORT", "5432"),
                       dbname=os.environ.get("PGDATABASE", "onsen_musume"),
                       user=os.environ.get("PGUSER", "postgres"), autocommit=True)
        if args.prompt_password:
            # getpass hides typed characters; the password is never printed.
            options["password"] = getpass("PostgreSQL password: ")
        try:
            with psycopg.connect(**options) as conn:
                process(conn)
        except psycopg.Error:
            # Avoid printing connection details that might contain credentials.
            print("Database connection failed; check PGHOST, PGPORT, PGDATABASE, PGUSER "
                  "and authentication. Try --prompt-password.", file=sys.stderr)
            return 1
    # A nonzero exit code lets shell scripts detect any failed record.
    print("; ".join(f"{key}: {value}" for key, value in counts.items()))
    return int(counts["failed"] > 0)


if __name__ == "__main__":
    # Execute the CLI only when run directly, not when imported by the tests.
    raise SystemExit(main())
