const cordra = require('cordra');
const {
    isConceptHandle,
    validateVocabularyConceptReferences,
} = require('../lib/vocabularyConceptRefs');

exports.beforeSchemaValidation = beforeSchemaValidation;

const TITLE_TYPE_DEFAULT_HANDLE = 'HSR/voc.hsr.title';
const TITLE_TYPE_DEFAULT_TAIL = 'title';

const VOCABULARY_CONCEPT_RULES = [
    { path: 'titles[].titleType', queryTerm: 'Sample-titleType', label: 'Title type' },
    { path: 'otherDescriptions[].descriptionType', queryTerm: 'Sample-descriptionType', label: 'Description type' },
    {
        path: 'documentationIdentifier.relatedIdentifierType',
        queryTerm: 'Sample-relatedIdentifierType',
        label: 'Documentation related identifier type',
    },
    {
        path: 'documentationIdentifier.relationType',
        queryTerm: 'Sample-relationType',
        label: 'Documentation relation type',
    },
    {
        path: 'documentationIdentifier.resourceTypeGeneral',
        queryTerm: 'Sample-resourceTypeGeneral',
        label: 'Documentation resource type general',
    },
    { path: 'sampleType', queryTerm: 'Sample-sampleType', label: 'Sample type' },
    {
        path: 'fundingReferences[].funderIdentifierType',
        queryTerm: 'Sample-funderIdentifierType',
        label: 'Funder identifier type',
    },
    {
        path: 'relatedIdentifiers[].relatedIdentifierType',
        queryTerm: 'Sample-relatedIdentifierType',
        label: 'Related identifier type',
    },
    {
        path: 'relatedIdentifiers[].relationType',
        queryTerm: 'Sample-relatedIdentifiers-relationType',
        label: 'Relation type',
    },
    {
        path: 'relatedIdentifiers[].resourceTypeGeneral',
        queryTerm: 'Sample-relatedIdentifiers-resourceTypeGeneral',
        label: 'Resource type general',
    },
];


function isPrimaryTitleType(value) {
    return value === 'Title'
        || value === TITLE_TYPE_DEFAULT_HANDLE
        || isConceptHandle(value, TITLE_TYPE_DEFAULT_TAIL);
}


async function beforeSchemaValidation(object, context) {
    const content = object.content;

    if (content.titles && content.titles.length > 0) {
        const custodianTitle = content.titles.find((title) => title.isCustodianIdentifier);
        const mainTitle = content.titles.find((title) => isPrimaryTitleType(title.titleType));
        if (custodianTitle) {
            content._displayTitle = custodianTitle.title;
        } else if (mainTitle) {
            content._displayTitle = mainTitle.title;
        } else {
            content._displayTitle = content.titles[0].title;
        }
    }

    await validateVocabularyConceptReferences(content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    // validate material terms
    // TODO: queryTerms are not yet set for AAT materials
    //if (content.materialTerms) {
    //    for (const id of content.materialTerms) {
    //        const concept = await cordra.get(id);
    //        if (!('queryTerms' in concept && concept.queryTerms.includes('materials'))) {
    //            throw new cordra.CordraError(`Material term ${id} is not a valid material term`, 400);
    //        }
    //    }
    //}

    return object;
}
