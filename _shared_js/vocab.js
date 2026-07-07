/**
 * Shared helpers for validating VocabularyConcept handle references
 * against queryTerm subsets used by enum migrations.
 *
 * Handle rules mirror _scripts/upload-enums.py: concept @id tail becomes
 * {hdlPrefix}/voc.hsr.{tail}, independent of skos:prefLabel text.
 */

const DEFAULT_VOCABULARY_NOTATION = 'hsr';

function conceptTail(conceptId) {
    const tail = String(conceptId).replace(/\/$/, '').split('/').pop();
    if (!tail) {
        throw new Error(`Cannot derive tail from concept @id: ${conceptId}`);
    }
    return tail;
}

function conceptHandle(hdlPrefix, tail) {
    const prefix = String(hdlPrefix).replace(/\/$/, '');
    return `${prefix}/voc.${DEFAULT_VOCABULARY_NOTATION}.${tail}`;
}

function conceptHandleTail(handle) {
    const match = String(handle).match(new RegExp(`/voc\\.${DEFAULT_VOCABULARY_NOTATION}\\.([^/]+)$`));
    return match ? match[1] : null;
}

function isConceptHandle(value, tail) {
    return conceptHandleTail(value) === tail;
}

function queryTermsFromConcept(concept) {
    if (!concept || typeof concept !== 'object') {
        return [];
    }
    const terms = concept.queryTerms ?? concept.content?.queryTerms;
    return Array.isArray(terms) ? terms : [];
}

function collectValuesAtPath(root, path) {
    if (root === undefined || root === null) {
        return [];
    }

    const segments = String(path).split('.');
    let current = [root];

    for (const segment of segments) {
        const arraySegment = segment.endsWith('[]');
        const key = arraySegment ? segment.slice(0, -2) : segment;
        const next = [];

        for (const value of current) {
            if (value === undefined || value === null || typeof value !== 'object') {
                continue;
            }

            if (arraySegment) {
                const items = value[key];
                if (Array.isArray(items)) {
                    next.push(...items);
                }
                continue;
            }

            if (key in value) {
                next.push(value[key]);
            }
        }

        current = next;
        if (current.length === 0) {
            break;
        }
    }

    return current.filter((value) => typeof value === 'string' && value.trim().length > 0);
}

async function validateVocabularyConceptReferences(root, rules, { cordra, CordraError, cache = {} }) {
    for (const rule of rules) {
        const values = collectValuesAtPath(root, rule.path);
        for (const handle of values) {
            let concept = cache[handle];
            if (concept === undefined) {
                try {
                    concept = await cordra.get(handle);
                    cache[handle] = concept;
                } catch (error) {
                    cache[handle] = null;
                    throw new CordraError(
                        `${rule.label}: VocabularyConcept ${handle} was not found`,
                        400
                    );
                }
            }

            if (!concept) {
                throw new CordraError(
                    `${rule.label}: VocabularyConcept ${handle} was not found`,
                    400
                );
            }

            const queryTerms = queryTermsFromConcept(concept);
            if (!queryTerms.includes(rule.queryTerm)) {
                throw new CordraError(
                    `${rule.label}: ${handle} is not valid for query term ${rule.queryTerm}`,
                    400
                );
            }
        }
    }
}

module.exports = {
    DEFAULT_VOCABULARY_NOTATION,
    collectValuesAtPath,
    conceptHandle,
    conceptHandleTail,
    conceptTail,
    isConceptHandle,
    queryTermsFromConcept,
    validateVocabularyConceptReferences,
};
