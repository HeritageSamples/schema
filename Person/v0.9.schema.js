const cordra = require('cordra');
const schema = require('/cordra/schemas/Person.schema.json');
const { validateVocabularyConceptReferences } = require('vocab');
const { assignLabels, labelsFromNames } = require('labels');

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
    { path: 'title', queryTerm: 'Person-personalTitle', label: 'Personal title' },
    { path: 'names[].lang', queryTerm: 'Common-language', label: 'Name language' },
    {
        path: 'externalPids[].pidType',
        queryTerm: 'Common-persistentIdentifier',
        label: 'PID type',
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
    content.$schema = schema.$id;
    migrateLegacyPerson(content);
    assignLabels(content, labelsFromNames(content.names, {
        fields: ['firstName', 'lastName'],
    }));

    await validateVocabularyConceptReferences(content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return content;
}


function trimmed(value) {
    return typeof value === 'string' ? value.trim() : '';
}


function organisationPid(value) {
    if (typeof value === 'string') {
        const text = value.trim();
        if (!text) {
            return '';
        }
        if (text.charAt(0) === '{') {
            try {
                const parsed = JSON.parse(text);
                return trimmed(parsed.organisationPid || parsed.id || parsed.pid);
            } catch (err) {
                return text;
            }
        }
        return text;
    }
    if (value && typeof value === 'object') {
        return trimmed(value.organisationPid || value.id || value.pid);
    }
    return '';
}


function splitFullName(fullName) {
    const parts = fullName.split(/\s+/).filter(Boolean);
    if (parts.length === 0) {
        return { firstName: '', lastName: '' };
    }
    if (parts.length === 1) {
        return { firstName: parts[0], lastName: parts[0] };
    }
    const lastName = parts.pop();
    return { firstName: parts.join(' '), lastName };
}


function migrateLegacyPerson(content) {
    if (!content || typeof content !== 'object') {
        return;
    }

    if (Array.isArray(content.partOfOrganisation)) {
        const refs = content.partOfOrganisation.map(organisationPid).filter(Boolean);
        if (refs.length > 0) {
            content.partOfOrganisation = refs;
        } else {
            delete content.partOfOrganisation;
        }
    }

    const existing = Array.isArray(content.names) ? content.names : [];
    const usable = existing.filter(
        (entry) => entry && (trimmed(entry.firstName) || trimmed(entry.lastName))
    );
    if (usable.length > 0) {
        content.names = usable;
    } else {
        let firstName = trimmed(content.firstName);
        let lastName = trimmed(content.lastName);
        if (!firstName && !lastName) {
            const split = splitFullName(trimmed(content.fullName));
            firstName = split.firstName;
            lastName = split.lastName;
        }
        if (firstName || lastName) {
            content.names = [{
                firstName: firstName || lastName,
                lastName: lastName || firstName,
            }];
        }
    }

    delete content.firstName;
    delete content.lastName;
    delete content.fullName;
    delete content.displayName;
    delete content._displayTitle;
    delete content._mainTitle;
    delete content._custodianNames;
}
