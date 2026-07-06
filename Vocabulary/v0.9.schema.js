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

    sanitizeLexicalArrays(content);
    stripLegacyLexicalArrays(content);
    ensureMainTitle(content);
}


function stripLegacyLexicalArrays(content) {
    delete content.terms;
    delete content.descriptions;
}


function sanitizeLexicalArrays(content) {
    if (!content || typeof content !== 'object') {
        return;
    }

    const prefLabel = sanitizeLabelArray(content.prefLabel, { uniqueLang: true });
    if (prefLabel) {
        content.prefLabel = prefLabel;
    } else {
        delete content.prefLabel;
    }

    const definition = sanitizeTextArray(content.definition, { uniqueLang: true });
    if (definition) {
        content.definition = definition;
    } else {
        delete content.definition;
    }
}


function sanitizeLabelArray(entries, options = {}) {
    if (!Array.isArray(entries)) {
        return undefined;
    }
    const uniqueLang = options.uniqueLang === true;
    const cleaned = [];
    const seenLangs = new Set();
    for (const entry of entries) {
        if (!entry || typeof entry !== 'object') {
            continue;
        }
        const lang = typeof entry.lang === 'string' ? entry.lang.trim() : '';
        const label = typeof entry.label === 'string' ? entry.label.trim() : '';
        if (!isLangKey(lang) || !label) {
            continue;
        }
        if (uniqueLang) {
            if (seenLangs.has(lang)) {
                continue;
            }
            seenLangs.add(lang);
        }
        cleaned.push({ label, lang });
    }
    return cleaned.length > 0 ? cleaned : undefined;
}


function sanitizeTextArray(entries, options = {}) {
    if (!Array.isArray(entries)) {
        return undefined;
    }
    const uniqueLang = options.uniqueLang === true;
    const cleaned = [];
    const seenLangs = new Set();
    for (const entry of entries) {
        if (!entry || typeof entry !== 'object') {
            continue;
        }
        const lang = typeof entry.lang === 'string' ? entry.lang.trim() : '';
        const text = typeof entry.text === 'string' ? entry.text.trim() : '';
        if (!isLangKey(lang) || !text) {
            continue;
        }
        if (uniqueLang) {
            if (seenLangs.has(lang)) {
                continue;
            }
            seenLangs.add(lang);
        }
        cleaned.push({ text, lang });
    }
    return cleaned.length > 0 ? cleaned : undefined;
}


function isLangKey(key) {
    return typeof key === 'string' && key.trim().length > 0;
}


function displayLabel(prefLabel) {
    if (!Array.isArray(prefLabel)) {
        return '';
    }
    const en = prefLabel.find((entry) => entry && entry.lang === DEFAULT_DISPLAY_LANG && typeof entry.label === 'string');
    if (en && en.label.trim()) {
        return en.label.trim();
    }
    for (const entry of prefLabel) {
        if (entry && typeof entry.label === 'string' && entry.label.trim()) {
            return entry.label.trim();
        }
    }
    return '';
}


function ensureMainTitle(content) {
    const title = displayLabel(content.prefLabel)
        || content.sourceName
        || content.notation
        || '';
    content._mainTitle = title;
}
// END CONFIDENTIAL SECTION
