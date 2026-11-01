-- For existing databases originally seeded with Japan's 47 prefectures.
-- Fresh databases already receive this entry from seed.sql; safe to rerun.
BEGIN;
INSERT INTO public.prefectures (name_ja)
VALUES ('台湾')
ON CONFLICT (name_ja) DO NOTHING;
COMMIT;
