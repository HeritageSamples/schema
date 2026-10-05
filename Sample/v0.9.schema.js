const cordra = require('cordra');
const { validateVocabularyConceptReferences } = require('vocab');
const { assignLabels, labelsFromTitles } = require('labels');

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
    {
        path: 'principalIdentifier.identifierType',
        queryTerm: 'Common-persistentIdentifier',
        label: 'Principal identifier type',
    },
    { path: 'types.resourceType', queryTerm: 'Sample-resourceType', label: 'Resource type' },
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


async function beforeSchemaValidation(object, context) {
    assignLabels(object.content, labelsFromTitles(object.content.titles, { priority: 'sample' }));

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
