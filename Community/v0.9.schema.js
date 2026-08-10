const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('vocab');

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
    { path: 'titles[].lang', queryTerm: 'Common-language', label: 'Title language' },
];


async function beforeSchemaValidation(object, context) {
    if (object.content.titles && object.content.titles.length > 0) {
        object.content._displayTitle = object.content.titles[0].title;
    }

    await validateVocabularyConceptReferences(object.content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return object;
}
