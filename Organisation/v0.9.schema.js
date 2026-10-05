const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('vocab');
const { assignLabels, labelsFromText } = require('labels');

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
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
        path: 'researchReferences[].referenceRole',
        queryTerm: 'Common-referenceRole',
        label: 'Reference type',
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
    ensureLabels(content);
    cleanResearchDisciplines(content);

    await validateVocabularyConceptReferences(content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return content;
}


function ensureLabels(content) {
    const name = typeof content.name === 'string' ? content.name.trim() : '';
    const acronym = typeof content.acronym === 'string' ? content.acronym.trim() : '';

    const displayName = name && acronym ? `${name} (${acronym})` : (name || acronym);
    assignLabels(content, labelsFromText(displayName));
}


function cleanResearchDisciplines(content) {
    if (!Array.isArray(content.researchDisciplines)) {
        return;
    }
    const cleaned = content.researchDisciplines.filter(
        (value) => typeof value === 'string' && value.trim().length > 0
    );
    if (cleaned.length > 0) {
        content.researchDisciplines = cleaned;
    } else {
        delete content.researchDisciplines;
    }
}
