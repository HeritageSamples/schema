const cordra = require('cordra');

exports.beforeSchemaValidation = beforeSchemaValidation;


async function beforeSchemaValidation(object, context) {
    // generate display title
    // rule: take the first title with primary custodian identifier, 
    // if no title with primary custodian identifier, take the first title with titleType "Title"
    // if no title with titleType "Title", take the first title
    if (object.content.titles && object.content.titles.length > 0) {
        const custodianTitle = object.content.titles.find(title => title.isCustodianIdentifier);
        const mainTitle = object.content.titles.find(title => title.titleType === "Title");
        if (custodianTitle) {
            object.content._displayTitle = custodianTitle.title;
        } else if (mainTitle) {
            object.content._displayTitle = mainTitle.title;
        } else {
            object.content._displayTitle = object.content.titles[0].title;
        }
    }

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