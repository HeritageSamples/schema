const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('vocab');
const { assignLabels, labelsFromOrganisationNames } = require('labels');
const { enrichForIndexing } = require('enrich');

exports.beforeSchemaValidation = beforeSchemaValidation;
exports.objectForIndexing = objectForIndexing;

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
    assignLabels(content, labelsFromOrganisationNames(content.names, content.acronym));

    await validateVocabularyConceptReferences(content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return content;
}


async function objectForIndexing(object, context) {
    return enrichForIndexing(object, { cordra, type: 'Organisation' });
}
