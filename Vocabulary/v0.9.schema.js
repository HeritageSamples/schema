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

    sanitizeLangText(content, 'prefLabel');
    sanitizeLangText(content, 'definition');
    ensureMainTitle(content);
}


function isLangKey(key) {
    return typeof key === 'string' && key.trim().length > 0;
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


function sanitizeLangText(content, property) {
    const block = content[property];
    if (!block || typeof block !== 'object') {
        delete content[property];
        return;
    }

    const cleaned = {};
    for (const language of Object.keys(block)) {
        if (!isLangKey(language)) {
            continue;
        }
        const value = block[language];
        if (typeof value !== 'string') {
            continue;
        }
        const trimmed = value.trim();
        if (trimmed) {
            cleaned[language] = trimmed;
        }
    }

    if (Object.keys(cleaned).length > 0) {
        content[property] = cleaned;
    } else {
        delete content[property];
    }
}


function ensureMainTitle(content) {
    const title = displayLabel(content.prefLabel)
        || content.sourceName
        || content.notation
        || '';
    content._mainTitle = title;
}
// END CONFIDENTIAL SECTION
