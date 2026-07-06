const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('../lib/vocabularyConceptRefs');

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
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
        path: 'research_references[].reference_role',
        queryTerm: 'Common-referenceRole',
        label: 'Reference type',
    },
    {
        path: 'organisation_type[]',
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
    ensureDisplayName(content);

    await validateVocabularyConceptReferences(content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return content;
}


function ensureDisplayName(content) {
    const name = typeof content.name === 'string' ? content.name.trim() : '';
    const acronym = typeof content.acronym === 'string' ? content.acronym.trim() : '';

    if (name && acronym) {
        content.display_name = `${name} (${acronym})`;
    } else {
        content.display_name = name || acronym;
    }
}
