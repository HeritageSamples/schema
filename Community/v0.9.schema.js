const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('vocab');
const { assignLabels, labelsFromTitles } = require('labels');
const { enrichForIndexing } = require('enrich');

exports.beforeSchemaValidation = beforeSchemaValidation;
exports.objectForIndexing = objectForIndexing;

const VOCABULARY_CONCEPT_RULES = [
    { path: 'titles[].lang', queryTerm: 'Common-language', label: 'Title language' },
];


async function beforeSchemaValidation(object, context) {
    assignLabels(object.content, labelsFromTitles(object.content.titles));

    await validateVocabularyConceptReferences(object.content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return object;
}


async function objectForIndexing(object, context) {
    return enrichForIndexing(object, { cordra, type: 'Community' });
}
