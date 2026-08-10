const cordra = require('cordra');
const {
    isConceptHandle,
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
    { path: 'titles[].titleType', queryTerm: 'Sample-titleType', label: 'Title type' },
    { path: 'titles[].lang', queryTerm: 'Common-language', label: 'Title language' },
    { path: 'otherDescriptions[].descriptionType', queryTerm: 'Sample-descriptionType', label: 'Description type' },
    { path: 'otherDescriptions[].lang', queryTerm: 'Common-language', label: 'Description language' },
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
        queryTerm: 'Sample-relatedIdentifiers-resourceTypeGeneral',
        label: 'Documentation resource type general',
    },
    { path: 'sampleType', queryTerm: 'Sample-sampleType', label: 'Sample type' },
    {
        path: 'alternateIdentifiers[].alternateIdentifierType',
        queryTerm: 'Common-persistentIdentifier',
        label: 'Alternate identifier type',
    },
    { path: 'subjects[].lang', queryTerm: 'Common-language', label: 'Subject language' },
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
    { path: 'rightsList[].lang', queryTerm: 'Common-language', label: 'Rights language' },
];


function isPrimaryTitleType(value) {
    return value === 'Title'
        || value === TITLE_TYPE_DEFAULT_HANDLE
        || isConceptHandle(value, TITLE_TYPE_DEFAULT_TAIL);
}


async function beforeSchemaValidation(object, context) {
    if (object.content.titles && object.content.titles.length > 0) {
        const custodianTitle = object.content.titles.find((title) => title.isCustodianIdentifier);
        const mainTitle = object.content.titles.find((title) => isPrimaryTitleType(title.titleType));
        if (custodianTitle) {
            object.content._displayTitle = custodianTitle.title;
        } else if (mainTitle) {
            object.content._displayTitle = mainTitle.title;
        } else {
            object.content._displayTitle = object.content.titles[0].title;
        }
    }

    cleanPrincipalIdentifier(object.content);

    await validateVocabularyConceptReferences(object.content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    // validate material terms
    // TODO: queryTerms are not yet set for AAT materials
    //if (object.content.materialTerms) {
    //    for (const id of object.content.materialTerms) {
    //        const concept = await cordra.get(id);
    //        if (!('queryTerms' in concept && concept.queryTerms.includes('materials'))) {
    //            throw new cordra.CordraError(`Material term ${id} is not a valid material term`, 400);
    //        }
    //    }
    //}

    return object;
}


function cleanPrincipalIdentifier(content) {
    const principalIdentifier = content.principalIdentifier;
    if (principalIdentifier === null || typeof principalIdentifier !== 'object') {
        return;
    }
    const identifier = typeof principalIdentifier.identifier === 'string'
        ? principalIdentifier.identifier.trim()
        : '';
    const identifierType = typeof principalIdentifier.identifierType === 'string'
        ? principalIdentifier.identifierType.trim()
        : '';
    if (!identifier && !identifierType) {
        delete content.principalIdentifier;
    }
}
