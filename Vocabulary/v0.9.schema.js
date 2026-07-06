// BEGIN CONFIDENTIAL SECTION
const cordra = require('cordra');
const schema = require('/cordra/schemas/Vocabulary.schema.json');

const hdlShoulder = 'voc';
const DEFAULT_DISPLAY_LANG = 'en';


/**************************************************
                LIFECYCLE HOOKS
 **************************************************/

exports.beforeSchemaValidation = beforeSchemaValidation;
exports.beforeSchemaValidationWithId = beforeSchemaValidationWithId;
exports.generateId = generateId;
exports.isGenerateIdLoopable = false;
exports.objectForIndexing = objectForIndexing;


function beforeSchemaValidation(object, context) {
    try {
        normalizeVocabulary(object.content || {});
        return object;
    } catch (error) {
        throw new cordra.CordraError(
            'Error in lifecycle hook beforeSchemaValidation [2e4f0a61]: ' + error.message,
            400
        );
    }
}


function beforeSchemaValidationWithId(object, context) {
    try {
        normalizeVocabulary(object.content || {});
        return object;
    } catch (error) {
        throw new cordra.CordraError(
            'Error in lifecycle hook beforeSchemaValidationWithId [7c9f2b15]: ' + error.message,
            400
        );
    }
}


function generateId(object, context) {
    try {
        const prefix = cordra.get('design').content.handleMintingConfig.prefix;
        const notation = String(object.content.notation || object.content.code || '').trim().toLowerCase();

        if (!notation || !/^[a-z0-9_:-]+$/.test(notation)) {
            throw new Error('Invalid or missing notation for handle minting');
        }

        return `${prefix}/${hdlShoulder}.${notation.replace(/:/g, '.')}`;
    } catch (error) {
        throw new cordra.CordraError(
            'Error in lifecycle hook generateId [c43e7a90]: ' + error.message,
            400
        );
    }
}


function objectForIndexing(object) {
    try {
        delete object.metadata.hashes;
        delete object.userMetadata;
        return object;
    } catch (error) {
        throw new cordra.CordraError(
            'Error in lifecycle hook objectForIndexing [19cb4f58]: ' + error.message,
            400
        );
    }
}


/**************************************************
                HELPER FUNCTIONS
 **************************************************/

function normalizeVocabulary(content) {
    content.$schema = schema.$id;

    if (typeof content.notation === 'string') {
        content.notation = content.notation.trim().toLowerCase();
    }
    if (typeof content.curiePrefix === 'string') {
        content.curiePrefix = content.curiePrefix.trim().toLowerCase();
    }

    normalizeLexicalContent(content);
    sanitizeTerms(content);
    sanitizeDescriptions(content);
    ensureMainTitle(content);
}


function isLangKey(key) {
    return typeof key === 'string' && key.trim().length > 0;
}


function normalizeLexicalContent(content) {
    if (!content || typeof content !== 'object') {
        return;
    }

    const hasTerms = Array.isArray(content.terms) && content.terms.length > 0;
    const hasDescriptions = Array.isArray(content.descriptions) && content.descriptions.length > 0;
    const hasLegacyMaps = ['prefLabel', 'definition'].some((field) => content[field] && typeof content[field] === 'object');

    if (!hasTerms || hasLegacyMaps) {
        const maps = contentToLexicalMaps(content);
        applyLexicalMapsToContent(content, maps);
    }

    if (!hasDescriptions && content.definition && typeof content.definition === 'object') {
        const maps = contentToLexicalMaps(content);
        applyLexicalMapsToContent(content, maps);
    }

    delete content.prefLabel;
    delete content.definition;
}


function contentToLexicalMaps(content) {
    const maps = {};

    if (Array.isArray(content.terms)) {
        const { prefLabel } = termsToLexicalMaps(content.terms);
        if (Object.keys(prefLabel).length > 0) {
            maps.prefLabel = prefLabel;
        }
    } else if (content.prefLabel && typeof content.prefLabel === 'object') {
        const prefLabel = sanitizeLangStringMap(content.prefLabel);
        if (prefLabel) {
            maps.prefLabel = prefLabel;
        }
    }

    if (Array.isArray(content.descriptions)) {
        const { definition } = descriptionsToMaps(content.descriptions);
        if (Object.keys(definition).length > 0) {
            maps.definition = definition;
        }
    } else if (content.definition && typeof content.definition === 'object') {
        const definition = sanitizeLangStringMap(content.definition);
        if (definition) {
            maps.definition = definition;
        }
    }

    return maps;
}


function applyLexicalMapsToContent(content, maps) {
    const prefLabel = maps.prefLabel || {};
    const definition = maps.definition || {};
    const terms = lexicalMapsToTerms(prefLabel, {});
    if (terms.length > 0) {
        content.terms = terms;
    } else {
        delete content.terms;
    }

    const descriptions = mapsToDescriptions(definition, {});
    if (descriptions.length > 0) {
        content.descriptions = descriptions;
    } else {
        delete content.descriptions;
    }
}


function termsToLexicalMaps(terms) {
    const prefLabel = {};
    const altLabel = {};

    if (!Array.isArray(terms)) {
        return { prefLabel, altLabel };
    }

    for (const term of terms) {
        if (!term || typeof term !== 'object') {
            continue;
        }
        const lang = typeof term.lang === 'string' ? term.lang.trim() : '';
        const label = typeof term.label === 'string' ? term.label.trim() : '';
        if (!isLangKey(lang) || !label) {
            continue;
        }
        if (term.isAlternative === true) {
            if (!Array.isArray(altLabel[lang])) {
                altLabel[lang] = [];
            }
            if (!altLabel[lang].includes(label)) {
                altLabel[lang].push(label);
            }
        } else if (!(lang in prefLabel)) {
            prefLabel[lang] = label;
        }
    }

    return { prefLabel, altLabel };
}


function lexicalMapsToTerms(prefLabel, altLabel) {
    const terms = [];

    for (const lang of Object.keys(prefLabel || {}).filter(isLangKey).sort()) {
        const label = typeof prefLabel[lang] === 'string' ? prefLabel[lang].trim() : '';
        if (label) {
            terms.push({ label, lang: lang.trim(), isAlternative: false });
        }
    }

    for (const lang of Object.keys(altLabel || {}).filter(isLangKey).sort()) {
        const values = Array.isArray(altLabel[lang]) ? altLabel[lang] : [];
        const seen = new Set();
        for (const value of values) {
            const label = typeof value === 'string' ? value.trim() : '';
            if (!label || seen.has(label)) {
                continue;
            }
            seen.add(label);
            terms.push({ label, lang: lang.trim(), isAlternative: true });
        }
    }

    return terms;
}


function descriptionsToMaps(descriptions) {
    const definition = {};
    const scopeNote = {};

    if (!Array.isArray(descriptions)) {
        return { definition, scopeNote };
    }

    for (const item of descriptions) {
        if (!item || typeof item !== 'object') {
            continue;
        }
        const lang = typeof item.lang === 'string' ? item.lang.trim() : '';
        const text = typeof item.description === 'string' ? item.description.trim() : '';
        if (!isLangKey(lang) || !text) {
            continue;
        }
        const kind = typeof item.kind === 'string' ? item.kind.trim() : 'definition';
        if (kind === 'scopeNote') {
            scopeNote[lang] = text;
        } else {
            definition[lang] = text;
        }
    }

    return { definition, scopeNote };
}


function mapsToDescriptions(definition, scopeNote) {
    const descriptions = [];

    for (const lang of Object.keys(definition || {}).filter(isLangKey).sort()) {
        const text = typeof definition[lang] === 'string' ? definition[lang].trim() : '';
        if (text) {
            descriptions.push({ description: text, lang: lang.trim(), kind: 'definition' });
        }
    }

    for (const lang of Object.keys(scopeNote || {}).filter(isLangKey).sort()) {
        const text = typeof scopeNote[lang] === 'string' ? scopeNote[lang].trim() : '';
        if (text) {
            descriptions.push({ description: text, lang: lang.trim(), kind: 'scopeNote' });
        }
    }

    return descriptions;
}


function sanitizeLangStringMap(block) {
    if (!block || typeof block !== 'object') {
        return undefined;
    }
    const cleaned = {};
    for (const language of Object.keys(block)) {
        if (!isLangKey(language)) {
            continue;
        }
        const value = block[language];
        if (typeof value === 'string') {
            const trimmed = value.trim();
            if (trimmed) {
                cleaned[language] = trimmed;
            }
        }
    }
    return Object.keys(cleaned).length > 0 ? cleaned : undefined;
}


function sanitizeTerms(content) {
    if (!Array.isArray(content.terms)) {
        delete content.terms;
        return;
    }

    const { prefLabel, altLabel } = termsToLexicalMaps(content.terms);
    const cleaned = lexicalMapsToTerms(prefLabel, altLabel);
    if (cleaned.length > 0) {
        content.terms = cleaned;
    } else {
        delete content.terms;
    }
}


function sanitizeDescriptions(content) {
    if (!Array.isArray(content.descriptions)) {
        delete content.descriptions;
        return;
    }

    const { definition, scopeNote } = descriptionsToMaps(content.descriptions);
    const cleaned = mapsToDescriptions(definition, scopeNote);
    if (cleaned.length > 0) {
        content.descriptions = cleaned;
    } else {
        delete content.descriptions;
    }
}


function displayLabelFromTerms(terms) {
    const { prefLabel } = termsToLexicalMaps(terms);
    return displayLabel(prefLabel);
}


function displayLabel(prefLabel) {
    if (!prefLabel || typeof prefLabel !== 'object') {
        return '';
    }
    const en = prefLabel[DEFAULT_DISPLAY_LANG];
    if (typeof en === 'string' && en.trim().length > 0) {
        return en.trim();
    }
    for (const language of Object.keys(prefLabel).filter(isLangKey).sort()) {
        const value = prefLabel[language];
        if (typeof value === 'string' && value.trim().length > 0) {
            return value.trim();
        }
    }
    return '';
}


function ensureMainTitle(content) {
    const title = displayLabelFromTerms(content.terms)
        || content.sourceName
        || content.notation
        || '';
    content._mainTitle = title;
}
// END CONFIDENTIAL SECTION
