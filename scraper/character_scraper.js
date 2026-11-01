/* Paste this entire script into DevTools Console on one character profile.
 * It extracts that page only, prints JSON, and attempts to copy it.
 * Review warnings and onsen membership before importing. No database writes.
 */
(async () => {
    const warnings = [];
    const pageText = document.body.innerText || "";

    // Preserve the previously working body-text label extraction method.
    // Labels need not occur at the beginning of a line.
    function extractField(label) {
        const escapedLabel = label.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
        const regex = new RegExp(escapedLabel + "[：:\\s]+(.*)");
        const match = pageText.match(regex);
        if (match && match[1]) {
            const rawLine = match[1].split('\n')[0];
            return rawLine ? rawLine.trim() : "";
        }
        return "";
    }

    // Convert missing text to null and report it rather than guessing.
    function field(label) {
        const value = extractField(label);
        if (!value) warnings.push(`Missing field: ${label}`);
        return value || null;
    }

    // Read known profile selectors; surrounding layout whitespace is removed.
    function elementText(selector) {
        const value = document.querySelector(selector)?.innerText?.trim();
        if (!value) warnings.push(`Missing element text: ${selector}`);
        return value || null;
    }

    // Standard main/SD image URLs stay separate from promotional artwork.
    function imageUrl(selector) {
        const value = document.querySelector(selector)?.getAttribute("src");
        if (!value) {
            warnings.push(`Missing image: ${selector}`);
            return null;
        }
        return new URL(value, location.href).href;
    }

    // Preserve the confirmed prefecture traversal: first element, then children.
    function prefectureName() {
        const badge = document.querySelector('.prefecture-badge');
        let parent = badge?.firstElementChild;
        let y = '';
        if (parent) {
            Array.from(parent.children).forEach(e => y += e.innerText);
        }
        const value = y.trim();
        if (!value) warnings.push("No prefecture badge; inspect source location manually.");
        // Special characters have no geographical prefecture.
        return value && value !== "特別キャラクター" ? value : null;
    }

    // Read a verified page-data ID, never the number in an image filename.
    // The page's embedded directory and current profile repeat the same ID.
    // Match the current URL slug, and require those matches to agree.
    function sourceId() {
        const slug = location.pathname.match(/^\/character\/([^/]+)\/?$/)?.[1];
        if (!slug) {
            warnings.push("Not a character profile URL.");
            return null;
        }
        const entries = [...document.scripts].map(s => s.textContent).join("\n");
        const pattern = /\{id:(\d+),name:"(?:\\.|[^"\\])*",enName:"(?:\\.|[^"\\])*",kana:"(?:\\.|[^"\\])*",slug:"([^"\\]+)"/g;
        const ids = new Set();
        for (const match of entries.matchAll(pattern)) {
            if (match[2] === slug) ids.add(match[1]);
        }
        if (ids.size !== 1) {
            warnings.push("Could not verify one source ID from page data; do not import yet.");
            return null;
        }
        return [...ids][0];
    }

    // Ignore age annotations when extracting month/day; retain the raw text.
    function birthdayParts(raw) {
        const match = raw?.match(/^(\d{1,2})月(\d{1,2})日(?:（.*）)?$/);
        if (match) {
            const month = Number(match[1]);
            const day = Number(match[2]);
            const lastDay = new Date(Date.UTC(2000, month, 0)).getUTCDate();
            if (month >= 1 && month <= 12 && day >= 1 && day <= lastDay) {
                return [month, day];
            }
        }
        warnings.push(`Unknown or invalid birthday: ${raw}`);
        return [null, null];
    }

    // Both 'cm' and the single-character '㎝' occur on actual profiles.
    function heightCm(raw) {
        const match = raw?.match(/^(\d+(?:\.\d{1,2})?)\s*(?:cm|㎝)$/i);
        const value = match ? Number(match[1]) : null;
        if (value !== null && value > 0 && value < 1000) return value;
        warnings.push(`Unknown or invalid height: ${raw}`);
        return null;
    }

    // Validate the displayed Japanese release date before converting to ISO.
    function isoDate(raw) {
        const match = raw?.match(/^(\d{4})年(\d{1,2})月(\d{1,2})日$/);
        if (match) {
            const [, year, month, day] = match.map(Number);
            const value = new Date(Date.UTC(year, month - 1, day));
            if (value.getUTCFullYear() === year && value.getUTCMonth() === month - 1
                && value.getUTCDate() === day) return value.toISOString().slice(0, 10);
        }
        warnings.push(`Unknown or invalid release date: ${raw}`);
        return null;
    }

    // Classifications are not named units. Multiple-name text needs review.
    function unitNames(raw) {
        if (!raw || ["未所属", "特別キャラクター", "ソロプロジェクト"].includes(raw)) return [];
        if (/[、,／/\n]/.test(raw)) {
            warnings.push("Review multiple unit names manually before setting unit_names.");
            return [];
        }
        return [raw];
    }

    const rawBirthday = field("誕生日");
    const rawHeight = field("身長");
    const rawReleaseDate = field("公開日");
    const rawUnit = field("所属ユニット");
    const [month, day] = birthdayParts(rawBirthday);
    const badgeLabel = document.querySelector('.prefecture-badge')?.innerText?.trim() || null;
    const record = {
        source_id: sourceId(),
        source_url: location.origin + location.pathname.replace(/\/$/, ""),
        name_ja: elementText('h1'),
        name_en: elementText('.character-en-name'),
        prefecture: prefectureName(),
        illustrator: field("キャラ原案"),
        voice_actor: field("CV"),
        color_code: field("カラー"),
        school_year: field("学年"),
        club: field("部活動"),
        source_birthday: rawBirthday,
        birthday_month: month,
        birthday_day: day,
        constellation: field("星座"),
        blood_type: field("血液型"),
        source_height: rawHeight,
        height_cm: heightCm(rawHeight),
        hobby: field("趣味"),
        special_skill: field("特技"),
        likes: field("好きなもの"),
        dislikes: field("苦手なもの"),
        unit_lore: rawUnit,
        unit_names: unitNames(rawUnit),
        onsen_names: [],
        source_release_date: rawReleaseDate,
        release_date: isoDate(rawReleaseDate),
        description: elementText('.description'),
        main_img: imageUrl('.character-main-image'),
        sd_img: imageUrl('.sd-img'),
        warnings
    };
    if (badgeLabel === "特別キャラクター") record.source_prefecture_label = badgeLabel;
    warnings.push("Review onsen_names manually; none are inferred from the prefecture or surname.");
    if (rawUnit === "特別キャラクター") {
        warnings.push("Special-character classification; review any actual unit membership separately.");
    }

    // DevTools copy() is preferred. A failed clipboard attempt still leaves
    // the complete JSON in the console and the record as this script's result.
    const json = JSON.stringify(record, null, 2);
    console.log(json);
    warnings.forEach(message => console.warn(message));
    try {
        if (typeof copy === "function") copy(json);
        else if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(json);
        else console.info("Clipboard unavailable; copy the JSON printed above.");
    } catch {
        console.info("Clipboard unavailable; copy the JSON printed above.");
    }
    return record;
})();
