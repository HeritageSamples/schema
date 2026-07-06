const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('../lib/vocabularyConceptRefs');

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
    { path: 'title', queryTerm: 'Person-personalTitle', label: 'Personal title' },
    {
        path: 'external_pids[].pid_type',
        queryTerm: 'Common-persistentIdentifier',
        label: 'PID type',
    },
    { path: 'based_in', queryTerm: 'Common-country', label: 'Country of operation' },
    {
        path: 'research_disciplines[]',
        queryTerm: 'Common-researchDiscipline',
        label: 'Research discipline',
    },
    {
        path: 'research_reference[].reference_type',
        queryTerm: 'Common-referenceRole',
        label: 'Reference type',
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
    ensureFullName(content);

    await validateVocabularyConceptReferences(content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return content;
}


function ensureFullName(content) {
    const parts = [content.first_name, content.last_name]
        .map((value) => (typeof value === 'string' ? value.trim() : ''))
        .filter(Boolean);
    content.full_name = parts.join(' ');
}
