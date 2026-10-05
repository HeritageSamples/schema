/**
 * Generated display labels for Cordra content.
 *
 * `_labels.default` reuses the old display-title / name composition rules.
 * Language keys are ISO 639-2/B codes for a fixed UI set.
 */

const { conceptHandle, conceptHandleTail, isConceptHandle } = require('vocab');

const TITLE_TYPE_DEFAULT_HANDLE = 'HSR/voc.hsr.title';
const TITLE_TYPE_DEFAULT_TAIL = 'title';
const ENGLISH_TAIL = 'en-english';

const LABEL_LANG_KEYS = {
    'en-english': 'eng',
    'fr-french': 'fre',
    'de-german': 'ger',
    'nl-dutch': 'dut',
    'el-greek': 'gre',
};

const LANGUAGE_TAILS = {
    bg: 'bg-bulgarian',
    bulgarian: 'bg-bulgarian',
    'bg-bulgarian': 'bg-bulgarian',
    cz: 'cz-czech',
    cs: 'cz-czech',
    czech: 'cz-czech',
    'cz-czech': 'cz-czech',
    da: 'da-danish',
    danish: 'da-danish',
    'da-danish': 'da-danish',
    de: 'de-german',
    ger: 'de-german',
    deu: 'de-german',
    german: 'de-german',
    'de-german': 'de-german',
    el: 'el-greek',
    gre: 'el-greek',
    ell: 'el-greek',
    greek: 'el-greek',
    'el-greek': 'el-greek',
    en: 'en-english',
    eng: 'en-english',
    english: 'en-english',
    'en-english': 'en-english',
    es: 'es-spanish',
    spa: 'es-spanish',
    spanish: 'es-spanish',
    'es-spanish': 'es-spanish',
    et: 'et-estonian',
    estonian: 'et-estonian',
    'et-estonian': 'et-estonian',
    fi: 'fi-finnish',
    finnish: 'fi-finnish',
    'fi-finnish': 'fi-finnish',
    fr: 'fr-french',
    fre: 'fr-french',
    fra: 'fr-french',
    french: 'fr-french',
    'fr-french': 'fr-french',
    ga: 'ga-irish',
    irish: 'ga-irish',
    'ga-irish': 'ga-irish',
    hr: 'hr-croatian',
    croatian: 'hr-croatian',
    'hr-croatian': 'hr-croatian',
    hu: 'hu-hungarian',
    hungarian: 'hu-hungarian',
    'hu-hungarian': 'hu-hungarian',
    it: 'it-italian',
    ita: 'it-italian',
    italian: 'it-italian',
    'it-italian': 'it-italian',
    lt: 'lt-lithuanian',
    lithuanian: 'lt-lithuanian',
    'lt-lithuanian': 'lt-lithuanian',
    lv: 'lv-latvian',
    latvian: 'lv-latvian',
    'lv-latvian': 'lv-latvian',
    mt: 'mt-maltese',
    maltese: 'mt-maltese',
    'mt-maltese': 'mt-maltese',
    nl: 'nl-dutch',
    dut: 'nl-dutch',
    nld: 'nl-dutch',
    dutch: 'nl-dutch',
    flemish: 'nl-dutch',
    'nl-dutch': 'nl-dutch',
    no: 'no-norwegian',
    norwegian: 'no-norwegian',
    'no-norwegian': 'no-norwegian',
    pl: 'pl-polish',
    polish: 'pl-polish',
    'pl-polish': 'pl-polish',
    pt: 'pt-portugese',
    por: 'pt-portugese',
    portuguese: 'pt-portugese',
    portugese: 'pt-portugese',
    'pt-portugese': 'pt-portugese',
    ro: 'ro-romanian',
    romanian: 'ro-romanian',
    'ro-romanian': 'ro-romanian',
    sk: 'sk-slovak',
    slovak: 'sk-slovak',
    'sk-slovak': 'sk-slovak',
    sl: 'sl-slovenian',
    slovenian: 'sl-slovenian',
    'sl-slovenian': 'sl-slovenian',
    sv: 'sv-swedish',
    swedish: 'sv-swedish',
    'sv-swedish': 'sv-swedish',
};

function trimmedString(value) {
    return typeof value === 'string' ? value.trim() : '';
}

function languageLookupKey(value) {
    const text = trimmedString(value);
    if (!text) {
        return '';
    }
    const handleTail = conceptHandleTail(text);
    return (handleTail || text).toLowerCase();
}

function languageTail(value) {
    const key = languageLookupKey(value);
    if (!key) {
        return null;
    }
    if (LANGUAGE_TAILS[key]) {
        return LANGUAGE_TAILS[key];
    }
    const primary = key.split('-')[0];
    return LANGUAGE_TAILS[primary] || null;
}

function canonicalLanguageHandle(value, hdlPrefix) {
    const text = trimmedString(value);
    const tail = languageTail(text);
    const prefix = trimmedString(hdlPrefix);
    if (tail && prefix) {
        return conceptHandle(prefix, tail);
    }
    return text;
}

function bcp47FromLang(value) {
    const tail = languageTail(value);
    if (tail && tail.includes('-')) {
        return tail.split('-')[0];
    }
    const key = languageLookupKey(value);
    return key.split('-')[0] || key;
}

function labelsLangKey(value) {
    const tail = languageTail(value);
    return (tail && LABEL_LANG_KEYS[tail]) || null;
}

function isPrimaryTitleType(value) {
    return value === 'Title'
        || value === TITLE_TYPE_DEFAULT_HANDLE
        || isConceptHandle(value, TITLE_TYPE_DEFAULT_TAIL);
}

function titleEntries(titles) {
    if (!Array.isArray(titles)) {
        return [];
    }
    return titles.filter((entry) => entry && trimmedString(entry.title));
}

function addLanguageLabels(labels, entries) {
    for (const entry of entries) {
        const key = labelsLangKey(entry.lang);
        const title = trimmedString(entry.title || entry.label);
        if (key && title && !labels[key]) {
            labels[key] = title;
        }
    }
}

function labelsFromTitles(titles, options = {}) {
    const entries = titleEntries(titles);
    if (entries.length === 0) {
        return undefined;
    }

    const priority = options.priority;
    let ordered = entries;
    let defaultTitle = trimmedString(entries[0].title);

    if (priority === 'heritageObject') {
        const primary = entries.filter((entry) => isPrimaryTitleType(entry.titleType));
        const rest = entries.filter((entry) => !isPrimaryTitleType(entry.titleType));
        if (primary.length > 0) {
            ordered = primary.concat(rest);
            defaultTitle = trimmedString(primary[0].title);
        }
    } else if (priority === 'sample') {
        const custodian = entries.filter((entry) => entry.isCustodianIdentifier);
        const remaining = entries.filter((entry) => !entry.isCustodianIdentifier);
        const primary = remaining.filter((entry) => isPrimaryTitleType(entry.titleType));
        const rest = remaining.filter((entry) => !isPrimaryTitleType(entry.titleType));
        ordered = custodian.concat(primary, rest);
        if (custodian.length > 0) {
            defaultTitle = trimmedString(custodian[0].title);
        } else if (primary.length > 0) {
            defaultTitle = trimmedString(primary[0].title);
        }
    }

    const labels = { default: defaultTitle };
    addLanguageLabels(labels, ordered);
    return labels;
}

function prefLabelEntries(prefLabel) {
    if (!Array.isArray(prefLabel)) {
        return [];
    }
    return prefLabel.filter((entry) => entry && trimmedString(entry.label));
}

function labelsFromPrefLabels(prefLabel, options = {}) {
    const entries = prefLabelEntries(prefLabel);
    const english = entries.find((entry) => languageTail(entry.lang) === ENGLISH_TAIL);
    const first = entries[0];
    const fallback = trimmedString(options.fallback);
    const notation = trimmedString(options.notation);
    let defaultLabel = trimmedString(english && english.label)
        || trimmedString(first && first.label)
        || fallback;

    if (Object.prototype.hasOwnProperty.call(options, 'notation')) {
        defaultLabel = defaultLabel
            ? (notation ? `${defaultLabel} (${notation})` : defaultLabel)
            : (notation ? `(${notation})` : '');
    } else if (!defaultLabel) {
        defaultLabel = notation;
    }

    if (!defaultLabel) {
        return undefined;
    }

    const labels = { default: defaultLabel };
    addLanguageLabels(labels, entries);
    return labels;
}

function labelsFromText(text) {
    const value = trimmedString(text);
    if (!value) {
        return undefined;
    }
    return { default: value };
}

function assignLabels(content, labels) {
    if (!content || typeof content !== 'object') {
        return;
    }
    delete content._displayTitle;
    delete content._mainTitle;
    delete content.fullName;
    delete content.displayName;
    delete content._custodianNames;

    const defaultLabel = labels && trimmedString(labels.default);
    if (!defaultLabel) {
        delete content._labels;
        return;
    }

    const next = { default: defaultLabel };
    for (const key of Object.keys(LABEL_LANG_KEYS).map((tail) => LABEL_LANG_KEYS[tail])) {
        const value = trimmedString(labels[key]);
        if (value) {
            next[key] = value;
        }
    }
    content._labels = next;
}

function rewritePrefLabelLangs(content, hdlPrefix) {
    if (!content || !Array.isArray(content.prefLabel)) {
        return;
    }
    for (const entry of content.prefLabel) {
        if (!entry || typeof entry !== 'object') {
            continue;
        }
        const lang = trimmedString(entry.lang);
        if (!lang) {
            continue;
        }
        entry.lang = canonicalLanguageHandle(lang, hdlPrefix);
    }
}

module.exports = {
    ENGLISH_TAIL,
    LABEL_LANG_KEYS,
    assignLabels,
    bcp47FromLang,
    canonicalLanguageHandle,
    isPrimaryTitleType,
    labelsFromPrefLabels,
    labelsFromText,
    labelsFromTitles,
    languageTail,
    rewritePrefLabelLangs,
};
