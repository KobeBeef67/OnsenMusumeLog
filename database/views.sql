-- Reading views. Reapply after changing their definitions.
-- Append new output columns when using CREATE OR REPLACE VIEW.
BEGIN;

CREATE OR REPLACE VIEW public.character_profile AS
SELECT
    c.id,
    c.source_id,
    c.source_url,
    i.name_ja AS illustrator_name_ja,
    v.name_ja AS voice_actor_name_ja,
    c.name_ja,
    c.name_en,
    c.color_code,
    c.school_year,
    c.club,
    c.birthday_month,
    c.birthday_day,
    c.blood_type,
    c.height_cm,
    c.hobby,
    c.special_skill,
    c.likes,
    c.dislikes,
    c.unit_lore,
    c.release_date,
    c.description,
    c.main_img,
    c.sd_img,
    COALESCE(loc.prefectures, ARRAY[]::text[]) AS prefectures,
    COALESCE(loc.onsens, ARRAY[]::text[]) AS onsens,
    COALESCE(membership.units, ARRAY[]::text[]) AS units
FROM public.characters AS c
LEFT JOIN public.illustrators AS i ON c.illustrator_id = i.id
LEFT JOIN public.voice_actors AS v ON c.voice_actor_id = v.id
LEFT JOIN (
    -- Aggregate independently of units to avoid multiplying relationships.
    SELECT
        co.character_id,
        array_agg(DISTINCT p.name_ja ORDER BY p.name_ja) AS prefectures,
        array_agg(DISTINCT o.name_ja ORDER BY o.name_ja) AS onsens
    FROM public.character_onsens AS co
    JOIN public.onsens AS o ON co.onsen_id = o.id
    JOIN public.prefectures AS p ON o.prefecture_id = p.id
    GROUP BY co.character_id
) AS loc ON c.id = loc.character_id
LEFT JOIN (
    SELECT
        cu.character_id,
        array_agg(DISTINCT u.name_ja ORDER BY u.name_ja) AS units
    FROM public.character_units AS cu
    JOIN public.units AS u ON cu.unit_id = u.id
    GROUP BY cu.character_id
) AS membership ON c.id = membership.character_id;

CREATE OR REPLACE VIEW public.character_onsen_details AS
SELECT
    c.id AS character_id,
    c.source_id,
    c.name_ja AS character_name_ja,
    c.name_en AS character_name_en,
    o.id AS onsen_id,
    o.name_ja AS onsen_name_ja,
    p.id AS prefecture_id,
    p.name_ja AS prefecture_name_ja
FROM public.character_onsens AS co
JOIN public.characters AS c ON co.character_id = c.id
JOIN public.onsens AS o ON co.onsen_id = o.id
JOIN public.prefectures AS p ON o.prefecture_id = p.id;

CREATE OR REPLACE VIEW public.character_unit_details AS
SELECT
    c.id AS character_id,
    c.source_id,
    c.name_ja AS character_name_ja,
    c.name_en AS character_name_en,
    u.id AS unit_id,
    u.name_ja AS unit_name_ja,
    u.unit_type
FROM public.character_units AS cu
JOIN public.characters AS c ON cu.character_id = c.id
JOIN public.units AS u ON cu.unit_id = u.id;

COMMIT;
