const cordra = require('cordra');
const schema = require('/cordra/schemas/JavaScriptDirectory.schema.json');

const hdlShoulder = "jsdir";


/**************************************************
                LIFECYCLE HOOKS
 **************************************************/

exports.beforeSchemaValidation = beforeSchemaValidation;
exports.generateId = generateId;
exports.isGenerateIdLoopable = false;


function beforeSchemaValidation(object, context) {
    if (!context.useLegacyContentOnlyJavaScriptHooks) {
        object.content.$schema = schema.$id;
        return object;
    }
    object.$schema = schema.$id;
    return object;
}


function generateId(object, context) {
    try {
        const randomAlphaNumeric = (n) => (Math.random().toString(36)+'00000000000000000').slice(2, n+2);

        const prefix = cordra.get('design').content.handleMintingConfig.prefix;
        const suffix = `${randomAlphaNumeric(4)}`;
        
        return `${prefix}/${hdlShoulder}.${suffix}`;
    } catch (error) {
        throw new cordra.CordraError("Error in lifecycle hook generateId [82aac688]", 400);
    }
}
