const cordra = require('cordra');
const {
    isConceptHandle,
    queryTermsFromConcept,
    validateVocabularyConceptReferences,
} = require('vocab');

exports.beforeSchemaValidation = beforeSchemaValidation;

const TITLE_TYPE_DEFAULT_HANDLE = 'HSR/voc.hsr.title';
const TITLE_TYPE_DEFAULT_TAIL = 'title';

const VOCABULARY_CONCEPT_RULES = [
    {
        path: 'principalIdentifier.identifierType',
        queryTerm: 'Common-persistentIdentifier',
        label: 'Principal identifier type',
    },
    { path: 'types.resourceType', queryTerm: 'HeritageObject-resourceType', label: 'Resource type' },
    { path: 'titles[].titleType', queryTerm: 'HeritageObject-titleType', label: 'Title type' },
    { path: 'titles[].lang', queryTerm: 'Common-language', label: 'Title language' },
    { path: 'descriptions[].descriptionType', queryTerm: 'HeritageObject-descriptionType', label: 'Description type' },
    { path: 'descriptions[].lang', queryTerm: 'Common-language', label: 'Description language' },
    { path: 'objectType', queryTerm: 'HeritageObject-objectType', label: 'Object type' },
    {
        path: 'alternateIdentifiers[].alternateIdentifierType',
        queryTerm: 'Common-persistentIdentifier',
        label: 'Alternate identifier type',
    },
    { path: 'subjects[].lang', queryTerm: 'Common-language', label: 'Subject language' },
    {
        path: 'fundingReferences[].funderIdentifierType',
        queryTerm: 'HeritageObject-funderIdentifierType',
        label: 'Funder identifier type',
    },
    {
        path: 'relatedIdentifiers[].relatedIdentifierType',
        queryTerm: 'HeritageObject-relatedIdentifierType',
        label: 'Related identifier type',
    },
    {
        path: 'relatedIdentifiers[].relationType',
        queryTerm: 'HeritageObject-relationType',
        label: 'Relation type',
    },
    {
        path: 'relatedIdentifiers[].resourceTypeGeneral',
        queryTerm: 'HeritageObject-resourceTypeGeneral',
        label: 'Resource type general',
    },
    { path: 'rightsList[].lang', queryTerm: 'Common-language', label: 'Rights language' },
];


function isPrimaryTitleType(value) {
    return value === 'Title'
        || value === TITLE_TYPE_DEFAULT_HANDLE
        || isConceptHandle(value, TITLE_TYPE_DEFAULT_TAIL);
}


async function beforeSchemaValidation(object, context) {
    if (object.titles && object.titles.length > 0) {
        const title = object.titles.find((entry) => isPrimaryTitleType(entry.titleType));
        if (title) {
            object._displayTitle = title.title;
        } else {
            object._displayTitle = object.titles[0].title;
        }
    }

    await validateVocabularyConceptReferences(object, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    if (object.materialTerms) {
        for (const id of object.materialTerms) {
            const concept = await cordra.get(id);
            const queryTerms = queryTermsFromConcept(concept);
            if (!queryTerms.includes('materials')) {
                throw new cordra.CordraError(`Material term ${id} is not a valid material term`, 400);
            }
        }
    }

    return object;
}
