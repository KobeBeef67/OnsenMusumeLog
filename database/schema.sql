-- Onsen Musume: run once in a fresh PostgreSQL database using UTF-8.
-- In pgAdmin, select onsen_musume, open Query Tool, and execute this file.
-- With psql: psql -d onsen_musume -v ON_ERROR_STOP=1 -f database/schema.sql
-- This script creates tables in public; it does not create the database.
-- Existing tables are deliberately not dropped or silently reused.

BEGIN;

SET LOCAL search_path = public;

DO $$
BEGIN
    IF current_setting('server_encoding') <> 'UTF8' THEN
        RAISE EXCEPTION 'Create this database with UTF8 encoding before running schema.sql';
    END IF;
END;
$$;

CREATE TABLE prefectures (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name_ja text NOT NULL UNIQUE CHECK (btrim(name_ja) <> '')
);

CREATE TABLE illustrators (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name_ja text NOT NULL UNIQUE CHECK (btrim(name_ja) <> '')
);

CREATE TABLE voice_actors (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name_ja text NOT NULL UNIQUE CHECK (btrim(name_ja) <> '')
);

CREATE TABLE onsens (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name_ja text NOT NULL CHECK (btrim(name_ja) <> ''),
    prefecture_id integer NOT NULL REFERENCES prefectures (id),
    CONSTRAINT onsens_name_prefecture_unique UNIQUE (name_ja, prefecture_id)
);

CREATE TABLE characters (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Keep external identifiers as text: their format need not be numeric.
    source_id text NOT NULL UNIQUE CHECK (btrim(source_id) <> ''),
    source_url text NOT NULL CHECK (btrim(source_url) <> ''),
    name_ja text NOT NULL CHECK (btrim(name_ja) <> ''),
    name_en text,
    illustrator_id integer REFERENCES illustrators (id),
    voice_actor_id integer REFERENCES voice_actors (id),
    color_code text CHECK (color_code ~ '^#[0-9A-Fa-f]{6}$'),
    school_year text,
    club text,
    birthday_month smallint,
    birthday_day smallint,
    blood_type text,
    height_cm numeric(5, 2) CHECK (height_cm > 0),
    hobby text,
    special_skill text,
    likes text,
    dislikes text,
    unit_lore text,
    release_date date,
    description text,
    main_img text,
    sd_img text,
    -- Both birthday components must be present or both absent.
    -- February 29 is valid; no fictional birth year is stored.
    CONSTRAINT characters_birthday_valid CHECK (
        (birthday_month IS NULL AND birthday_day IS NULL)
        OR (
            birthday_month IS NOT NULL AND birthday_day IS NOT NULL
            AND birthday_month BETWEEN 1 AND 12
            AND birthday_day BETWEEN 1 AND CASE
                WHEN birthday_month = 2 THEN 29
                WHEN birthday_month IN (4, 6, 9, 11) THEN 30
                ELSE 31
            END
        )
    )
);

CREATE TABLE character_onsens (
    character_id integer NOT NULL REFERENCES characters (id) ON DELETE CASCADE,
    onsen_id integer NOT NULL REFERENCES onsens (id) ON DELETE CASCADE,
    PRIMARY KEY (character_id, onsen_id)
);

CREATE TABLE units (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name_ja text NOT NULL UNIQUE,
    unit_type text,
    CONSTRAINT units_name_valid CHECK (
        btrim(name_ja) <> '' AND btrim(name_ja) <> '未所属'
    )
);

CREATE TABLE character_units (
    character_id integer NOT NULL REFERENCES characters (id) ON DELETE CASCADE,
    unit_id integer NOT NULL REFERENCES units (id) ON DELETE CASCADE,
    PRIMARY KEY (character_id, unit_id)
);

CREATE TABLE character_artworks (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    character_id integer NOT NULL REFERENCES characters (id) ON DELETE CASCADE,
    image_url text NOT NULL CHECK (btrim(image_url) <> ''),
    artwork_type text,
    source_name text,
    source_url text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT character_artworks_metadata_object CHECK (
        jsonb_typeof(metadata) = 'object'
    )
);

-- Primary keys and UNIQUE constraints already create their own B-tree indexes.
-- These support exact-name searches, joins, and reverse relationship lookups.
CREATE INDEX characters_name_ja_idx ON characters (name_ja);
CREATE INDEX characters_name_en_idx ON characters (name_en);
CREATE INDEX characters_illustrator_idx ON characters (illustrator_id);
CREATE INDEX characters_voice_actor_idx ON characters (voice_actor_id);
CREATE INDEX onsens_prefecture_idx ON onsens (prefecture_id);
CREATE INDEX character_onsens_onsen_idx ON character_onsens (onsen_id, character_id);
CREATE INDEX character_units_unit_idx ON character_units (unit_id, character_id);
CREATE INDEX character_artworks_character_idx ON character_artworks (character_id);

COMMENT ON COLUMN characters.source_id IS
    'Verified identifier from the source website; do not infer from image filenames.';
COMMENT ON COLUMN characters.unit_lore IS
    'Original unit text; structured unit membership lives in character_units.';
COMMENT ON COLUMN characters.blood_type IS
    'Original Japanese text, for example A型; NULL when unknown.';
COMMENT ON COLUMN characters.main_img IS 'Main character image URL.';
COMMENT ON COLUMN characters.sd_img IS 'SD/chibi image URL.';
COMMENT ON TABLE character_onsens IS
    'Verified many-to-many onsen membership with no primary/secondary ordering.';
COMMENT ON TABLE characters IS
    'Import with ON CONFLICT (source_id) DO NOTHING RETURNING id. '
    'The importer must skip existing characters and their associations atomically. '
    'Manual updates remain permitted; uniqueness alone does not prevent UPDATE.';

COMMIT;
