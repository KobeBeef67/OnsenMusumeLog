# OnsenMusumeLog

Import manually collected character JSON into a local PostgreSQL database.
This importer does not scrape websites or download images.

## Prerequisites

- Python 3.10 or newer.
- PostgreSQL with the project tables, location seed data, and views created
  in `public` using the instructions below. The importer does not create or
  migrate tables.
- Verified character identifiers and onsen/unit associations. Never infer an
  identifier from an image filename or an onsen from a prefecture.

## Repository layout

The checkout folder may be named `OnsenMusume`, `OnsenMusumeLog`, or another name.
All commands below run from its root, where this README and `requirements.txt` live.

```text
database/                  SQL schema, reference data, views, and example queries
  migrations/              Changes for an existing database
importer/                  Python JSON importer
scraper/                   Manual browser-console extraction
tests/fixtures/            Fictional JSON safe to commit
docs/schema.md             Relationships, field rules, and design limits
```

Local directories `data/raw/`, `data/reviewed/`, `data/exports/`, and `backups/`
are ignored by Git. Create them as needed; ignored data directories and their
contents are not part of the checkout. Keep the five reviewed JSON batches in
`data/reviewed/`. Git tracks code, SQL, documentation, and fictional fixtures.

## Create the database

In pgAdmin, create a database named `onsen_musume` with UTF-8 encoding. Open its
Query Tool and run the following files in order:

1. `database/schema.sql` — tables, constraints, and indexes; run once on a fresh database.
2. `database/seed.sql` — Japan's 47 prefectures plus the source location label 台湾.
3. `database/views.sql` — `character_profile`, `character_onsen_details`, and `character_unit_details`.

Alternatively, with `psql` available and authentication configured:

```bash
psql -h localhost -U postgres -d onsen_musume -v ON_ERROR_STOP=1 -f database/schema.sql
psql -h localhost -U postgres -d onsen_musume -v ON_ERROR_STOP=1 -f database/seed.sql
psql -h localhost -U postgres -d onsen_musume -v ON_ERROR_STOP=1 -f database/views.sql
```

For the existing database created during setup, **do not rerun schema.sql**.
You may reapply `seed.sql` and `views.sql`; they preserve character data.
The Taiwan-only addition is also available as `database/migrations/001_add_taiwan.sql`.
See [the schema notes](docs/schema.md) and `database/queries.sql` for exploration.

## Git Bash setup on Windows

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
export PGHOST="localhost"
export PGPORT="5432"
export PGDATABASE="onsen_musume"
export PGUSER="postgres"
mkdir -p data/raw data/reviewed data/exports backups
```

If `python` is unavailable, try `py -m venv .venv`. No virtual-environment
activation is required when using its Python executable directly.

Validate the committed fictional fixture without accessing PostgreSQL:

```bash
./.venv/Scripts/python.exe importer/import_characters.py tests/fixtures/fictional_characters.json --validate-only
```

After saving your reviewed batches locally, validate and import one batch:

```bash
./.venv/Scripts/python.exe importer/import_characters.py data/reviewed/batch_01.json --validate-only
./.venv/Scripts/python.exe importer/import_characters.py data/reviewed/batch_01.json --prompt-password
```

The second command commits records. Enter your local PostgreSQL password at the
hidden prompt. Repeat for batches 02–05. Existing IDs are skipped, not updated.
For Linux/WSL use `python3 -m venv .venv` and `.venv/bin/python` instead of the
Windows executable. In WSL, `localhost` refers to the WSL environment; PostgreSQL
running on Windows may require its Windows host address as `PGHOST`.

## Manual scraper

Open one source character profile in your browser, open DevTools Console, and
run the contents of `scraper/character_scraper.js`. It prints JSON and attempts
to copy it. Save your local output under `data/raw/`, inspect every value and
warning, then save the approved version under `data/reviewed/` for importing.

The script reads the current page only; it does not crawl or fetch other pages.
It preserves the working body-text label extraction and prefecture DOM traversal.
Source IDs come from the matching slug in embedded page data, not image names.
Missing or changed page structure is reported through warnings.

Onsen associations require review, including compound surnames and regional
names. Populate `onsen_names` explicitly, sharing names consistently across
characters. The script leaves that array empty rather than guessing. Review
actual memberships for special characters or source classification labels.
If a future website change breaks extraction, preserve your local working script
and compare the page DOM before changing selectors.

The importer ignores staging-only fields such as `source_birthday`, `source_height`,
`source_release_date`, `constellation`, and `warnings`. Read warnings before import;
they are not an automatic import veto. An omitted `description` becomes SQL NULL
for a new character. Never commit real local credentials or collected datasets.

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

For database tests, first create a separate test database and run `schema.sql`,
`seed.sql`, and `views.sql` there in that order. Set `TEST_DATABASE_URL` using
libpq connection-string syntax (use a
password file instead of putting a password in shell history), then rerun:

```powershell
$env:TEST_DATABASE_URL = "host=localhost dbname=onsen_musume_test user=postgres"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Without that variable, database tests are explicitly skipped. Database tests
roll back their rows, although PostgreSQL identity sequences may still advance.
They verify shared credits, many-to-many membership, unchanged duplicate data,
and complete rollback after an association error.
