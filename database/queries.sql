-- Read-only examples. Replace the Japanese names with your desired filters.

-- All characters credited to an illustrator.
SELECT source_id, name_ja, illustrator_name_ja
FROM public.character_profile
WHERE illustrator_name_ja = '神岡ちろる'
ORDER BY name_ja;

-- Character counts by location, including locations with no associations yet.
-- DISTINCT avoids counting one character twice for two onsens in one location.
SELECT p.name_ja, count(DISTINCT co.character_id) AS character_count
FROM public.prefectures AS p
LEFT JOIN public.onsens AS o ON o.prefecture_id = p.id
LEFT JOIN public.character_onsens AS co ON co.onsen_id = o.id
GROUP BY p.id, p.name_ja
ORDER BY p.name_ja;

-- All characters associated with one onsen in a specific location.
SELECT * FROM public.character_onsen_details
WHERE onsen_name_ja = '有馬温泉' AND prefecture_name_ja = '兵庫県'
ORDER BY character_name_ja;

-- Characters with multiple unit memberships.
SELECT source_id, name_ja, units
FROM public.character_profile
WHERE cardinality(units) > 1
ORDER BY name_ja;

-- Characters with no structured unit membership.
SELECT source_id, name_ja, unit_lore
FROM public.character_profile
WHERE cardinality(units) = 0
ORDER BY name_ja;

-- Voice actors credited to more than one character.
SELECT v.name_ja AS voice_actor_name_ja,
       array_agg(c.name_ja ORDER BY c.name_ja) AS character_names
FROM public.voice_actors AS v
JOIN public.characters AS c ON c.voice_actor_id = v.id
GROUP BY v.id, v.name_ja
HAVING count(*) > 1
ORDER BY v.name_ja;

-- Characters with additional artwork.
SELECT c.source_id, c.name_ja, count(a.id) AS artwork_count
FROM public.characters AS c
JOIN public.character_artworks AS a ON a.character_id = c.id
GROUP BY c.id, c.source_id, c.name_ja
ORDER BY c.name_ja;
