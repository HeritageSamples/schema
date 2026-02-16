const cordra = require('cordra');

exports.beforeSchemaValidation = beforeSchemaValidation;


async function beforeSchemaValidation(object, context) {
    // generate display title
    // rule: take the first title with titleType "Title"
    // if no title with titleType "Title", take the first title
    if (object.titles && object.titles.length > 0) {
        const title = object.titles.find(title => title.titleType === "Title");
        if (title) {
            object._displayTitle = title.title;
        } else {
            object._displayTitle = object.titles[0].title;
        }
    }

    // validate material terms
    if (object.materialTerms) {
        for (const id of object.materialTerms) {
            const concept = await cordra.get(id);
            if (!('queryTerms' in concept && concept.queryTerms.includes('materials'))) {
                throw new Error(`Material term ${id} is not a valid material term`);
            }
        }
    }

    return object;
}
