const cordra = require('cordra');
const schema = require('/cordra/schemas/Organisation.schema.json');
const { validateVocabularyConceptReferences } = require('vocab');
<<<<<<< HEAD
const { assignLabels, labelsFromNames } = require('labels');
=======
const { assignLabels, labelsFromOrganisationNames } = require('labels');
>>>>>>> 04f95492efc447e3515dd58b50a0798b87b8fe63

exports.beforeSchemaValidation = beforeSchemaValidation;

const VOCABULARY_CONCEPT_RULES = [
    { path: 'names[].lang', queryTerm: 'Common-language', label: 'Name language' },
    {
        path: 'externalPids[].pidType',
        queryTerm: 'Common-persistentIdentifier',
        label: 'PID type',
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
<<<<<<< HEAD
    content.$schema = schema.$id;
    migrateLegacyOrganisation(content);
    assignLabels(content, labelsFromNames(content.names, {
        fields: ['name'],
        suffix: content.acronym,
    }));
=======
    assignLabels(content, labelsFromOrganisationNames(content.names, content.acronym));
>>>>>>> 04f95492efc447e3515dd58b50a0798b87b8fe63

    await validateVocabularyConceptReferences(content, VOCABULARY_CONCEPT_RULES, {
        cordra,
        CordraError: cordra.CordraError,
    });

    return content;
}
<<<<<<< HEAD


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


function migrateLegacyOrganisation(content) {
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
    const usable = existing.filter((entry) => entry && trimmed(entry.name));
    if (usable.length > 0) {
        content.names = usable;
    } else {
        const name = trimmed(content.name) || trimmed(content.displayName);
        if (name) {
            content.names = [{ name }];
        }
    }

    delete content.name;
    delete content.displayName;
    delete content._displayTitle;
    delete content._mainTitle;
    delete content.fullName;
    delete content._custodianNames;
}
=======
>>>>>>> 04f95492efc447e3515dd58b50a0798b87b8fe63
