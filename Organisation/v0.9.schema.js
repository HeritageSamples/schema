const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('vocab');

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
    { path: 'names[].lang', queryTerm: 'Common-language', label: 'Name language' },
    {
        path: 'externalPids[].pidType',
        queryTerm: 'Common-persistentIdentifier',
        label: 'PID type',
    },
    {
        path: 'organisationType[]',
        queryTerm: 'Organisation-organisationType',
        label: 'Organisation type',
    },
];


async function beforeSchemaValidation(obj, context) {
    if (!context.useLegacyContentOnlyJavaScriptHooks) {
        obj.content = await beforeSchemaValidationLegacy(obj.content, context);
        return obj;
    }
    return beforeSchemaValidationLegacy(obj, context);
}


async function beforeSchemaValidationLegacy(content, context) {
    await validateVocabularyConceptReferences(content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return content;
}
