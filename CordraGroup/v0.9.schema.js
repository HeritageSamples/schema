const schema = require('/cordra/schemas/CordraGroup.schema.json');

exports.beforeSchemaValidation = beforeSchemaValidation;


function beforeSchemaValidation(object, context) {
    if (!context.useLegacyContentOnlyJavaScriptHooks) {
        object.content.$schema = schema.$id;
        return object;
    }
    object.$schema = schema.$id;
    return object;
}
