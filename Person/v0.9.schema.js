const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('vocab');

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
    { path: 'title', queryTerm: 'Person-personalTitle', label: 'Personal title' },
    {
        path: 'externalPids[].pidType',
        queryTerm: 'Common-persistentIdentifier',
        label: 'PID type',
    },
    { path: 'basedIn', queryTerm: 'Common-country', label: 'Country of operation' },
    {
        path: 'researchDisciplines[]',
        queryTerm: 'Common-researchDiscipline',
        label: 'Research discipline',
    },
    {
        path: 'researchReference[].referenceType',
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
    const parts = [content.firstName, content.lastName]
        .map((value) => (typeof value === 'string' ? value.trim() : ''))
        .filter(Boolean);
    content.fullName = parts.join(' ');
}
