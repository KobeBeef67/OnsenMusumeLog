# OnsenMusumeLog

Import manually collected character JSON into a local PostgreSQL database.
This importer does not scrape websites or download images.

## Prerequisites

- Python 3.10 or newer.
- PostgreSQL with the project tables and prefecture seed data already created
  in `public`. The SQL schema discussed during project setup is a separate step;
  this importer does not create or migrate tables.
- Verified character identifiers and onsen/unit associations. Never infer an
  identifier from an image filename or an onsen from a prefecture.

## Windows setup

Run these commands from the repository root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Save UTF-8 JSON as `data/raw/character.json` (create these directories first):

```json
{
  "source_id": "fictional-import-test-001",
  "source_url": "https://example.invalid/characters/test",
  "name_ja": "架空テストキャラクター",
  "illustrator": "架空テスト原案者",
  "voice_actor": "架空テスト声優",
  "prefecture": "岡山県",
  "birthday": "11月10日",
  "height": "143cm",
  "release_date": "2018年11月22日",
  "unit_names": [],
  "onsen_names": []
}
```

This fictional example is for testing and is not official character data.
An array of character objects is also accepted. Required fields are nonempty
text `source_id`, `source_url`, and `name_ja`. Other fields may be absent or null.

Validate without connecting to PostgreSQL:

```powershell
.\.venv\Scripts\python.exe importer/import_characters.py data/raw/character.json --validate-only
```

Import (this commits records):

```powershell
$env:PGUSER = "postgres"
$env:PGDATABASE = "onsen_musume"
.\.venv\Scripts\python.exe importer/import_characters.py data/raw/character.json --prompt-password
```

`PGHOST` defaults to `localhost` and `PGPORT` to `5432`. Without
`--prompt-password`, normal PostgreSQL/libpq authentication is used, including
`PGPASSWORD` or a password file. Never commit credentials. A `.env` file is not
loaded automatically. Raw JSON and exports are ignored by Git.

Run the same import again: it should report `duplicate`, leaving all existing
character data, credits, and memberships unchanged. Inspect it in pgAdmin:

```sql
SELECT * FROM public.characters
WHERE source_id = 'fictional-import-test-001';
```

## JSON conventions and safeguards

- Use the scraper's `illustrator` and `voice_actor` names. Reference records
  are reused by exact Japanese name; nonempty source text is preserved.
- `birthday_month` and `birthday_day` accept integers supplied together;
  otherwise `birthday` accepts `11月10日`. February 29 is supported.
- `height_cm` accepts a numeric value or numeric string with up to two decimal
  places; otherwise `height` accepts values such as `143cm`.
- `release_date` accepts `2018-11-22` or `2018年11月22日`.
- Normalized birthday/height fields take precedence over their original text.
- `unit_names` is an array of verified names. `未所属` is ignored. Original
  `unit` text is retained as `unit_lore` but is never split or guessed into
  memberships; missing structured membership produces a warning.
- `onsen_names` is an array of verified names. It requires an exact seeded
  `prefecture` name. All listed onsens use that prefecture in this initial
  format; cross-prefecture relationships require a future format extension.
  Missing onsens produce a warning and no association.
- Remaining supported profile fields are `name_en`, `color_code`, `school_year`,
  `club`, `blood_type`, `hobby`, `special_skill`, `likes`, `dislikes`,
  `description`, `main_img`, and `sd_img`. Other staging fields, including
  `constellation`, are not inserted. Artwork imports are outside this script.
- Each character is imported atomically. Failed imports roll back their new
  references and associations; later records are still attempted. Earlier
  successful imports remain committed. Exit status is nonzero if any record
  fails. Validation-only checks format, not database constraints or seed data.
- Duplicate IDs are checked before related rows are inserted. Advisory locks
  serialize matching source IDs between importer processes, and database
  conflict handling protects against other concurrent writers. Conflicting
  inserts roll back their new reference rows. Deadlocks or other transient
  database failures are reported; rerunning the file safely skips prior imports.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For database tests, first create a separate test database and run the schema SQL
there. Set `TEST_DATABASE_URL` using libpq connection-string syntax (use a
password file instead of putting a password in shell history), then rerun:

```powershell
$env:TEST_DATABASE_URL = "host=localhost dbname=onsen_musume_test user=postgres"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Without that variable, database tests are explicitly skipped. Database tests
roll back their rows, although PostgreSQL identity sequences may still advance.
They verify shared credits, many-to-many membership, unchanged duplicate data,
and complete rollback after an association error.
