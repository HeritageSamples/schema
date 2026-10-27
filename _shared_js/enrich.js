/**
 * Index-time enrichment of handleReference fields.
 *
 * `enrichForIndexing` adds two fields to the indexed form of an object (it is
 * meant for `objectForIndexing`, so nothing is stored or returned on GET):
 *
 * - `_relatedIds`: flat list of all handles reachable through handleReference
 *   fields, up to MAX_DEPTH hops.
 * - `_index`: nested copies of referenced content, keyed by field path
 *   (`[]` removed, `.` replaced by `_`), e.g.
 *   `/_index/sampleSource_sourceId/_/_index/creators/_/content/names/_/lastName`.
 *
 * These are non-authoritative search aids; a reindex refreshes them.
 */

const { collectValuesAtPath } = require('vocab');

const MAX_DEPTH = 3;
const CONCEPT_TYPE = 'VocabularyConcept';
const ENRICH_TARGET_TYPES = new Set([
    'Sample',
    'HeritageObject',
    'Person',
    'Organisation',
    'Community',
    CONCEPT_TYPE,
]);
const CONCEPT_COPY_FIELDS = ['prefLabel', 'altLabel'];

const referencePathCache = {};


function loadSchema(type) {
    try {
        return require(`/cordra/schemas/${type}.schema.json`);
    } catch (error) {
        return null;
    }
}

function resolveLocalRef(rootSchema, ref) {
    if (typeof ref !== 'string' || !ref.startsWith('#/')) {
        return null;
    }
    let node = rootSchema;
    for (const part of ref.slice(2).split('/')) {
        if (!node || typeof node !== 'object') {
            return null;
        }
        node = node[part.replace(/~1/g, '/').replace(/~0/g, '~')];
    }
    return node && typeof node === 'object' ? node : null;
}

function collectReferencePaths(rootSchema, node, path, found, seenRefs) {
    if (!node || typeof node !== 'object') {
        return;
    }

    if (node.$ref) {
        if (seenRefs.has(node.$ref)) {
            return;
        }
        const target = resolveLocalRef(rootSchema, node.$ref);
        if (target) {
            collectReferencePaths(rootSchema, target, path, found, new Set([...seenRefs, node.$ref]));
        }
    }

    const handleReference = node.cordra?.type?.handleReference;
    if (handleReference && path) {
        const types = Array.isArray(handleReference.types) ? handleReference.types : [];
        if (!found.has(path)) {
            found.set(path, new Set());
        }
        types.forEach((type) => found.get(path).add(type));
    }

    if (node.properties && typeof node.properties === 'object') {
        for (const [key, child] of Object.entries(node.properties)) {
            if (key.startsWith('_')) {
                continue;
            }
            collectReferencePaths(rootSchema, child, path ? `${path}.${key}` : key, found, seenRefs);
        }
    }

    if (node.items && path) {
        const items = Array.isArray(node.items) ? node.items : [node.items];
        for (const item of items) {
            collectReferencePaths(rootSchema, item, `${path}[]`, found, seenRefs);
        }
    }

    for (const keyword of ['oneOf', 'anyOf', 'allOf']) {
        if (Array.isArray(node[keyword])) {
            for (const branch of node[keyword]) {
                collectReferencePaths(rootSchema, branch, path, found, seenRefs);
            }
        }
    }
}

function referencePathsForType(type) {
    if (!(type in referencePathCache)) {
        const schema = loadSchema(type);
        const found = new Map();
        if (schema) {
            collectReferencePaths(schema, schema, '', found, new Set());
        }
        referencePathCache[type] = [...found.entries()].map(([path, types]) => ({
            path,
            types: [...types],
        }));
    }
    return referencePathCache[type];
}

function indexKey(path) {
    return path.replace(/\[\]/g, '').replace(/\./g, '_');
}

function contentWithoutInternals(content) {
    const copy = {};
    if (!content || typeof content !== 'object') {
        return copy;
    }
    for (const [key, value] of Object.entries(content)) {
        if (key.startsWith('_') || key === '$schema') {
            continue;
        }
        copy[key] = value;
    }
    return JSON.parse(JSON.stringify(copy));
}

function conceptContent(content) {
    const copy = {};
    if (!content || typeof content !== 'object') {
        return copy;
    }
    for (const field of CONCEPT_COPY_FIELDS) {
        if (content[field] !== undefined) {
            copy[field] = JSON.parse(JSON.stringify(content[field]));
        }
    }
    return copy;
}

async function fetchTarget(handle, cordra, cache) {
    if (!(handle in cache)) {
        try {
            const target = await cordra.get(handle);
            cache[handle] = target && ENRICH_TARGET_TYPES.has(target.type) ? target : null;
        } catch (error) {
            cache[handle] = null;
        }
    }
    return cache[handle];
}

async function buildIndex(type, content, state, depth, visited) {
    const index = {};
    if (depth >= state.maxDepth) {
        return index;
    }

    for (const { path } of referencePathsForType(type)) {
        const entries = [];
        const seen = new Set();
        for (const raw of collectValuesAtPath(content, path)) {
            const handle = raw.trim();
            if (handle.includes('://') || seen.has(handle) || visited.has(handle)) {
                continue;
            }
            seen.add(handle);

            const target = await fetchTarget(handle, state.cordra, state.cache);
            if (!target) {
                continue;
            }
            state.relatedIds.add(handle);

            const targetContent = target.content || {};
            const entry = { id: handle, type: target.type };
            if (targetContent._labels) {
                entry.labels = JSON.parse(JSON.stringify(targetContent._labels));
            }

            if (target.type === CONCEPT_TYPE) {
                entry.content = conceptContent(targetContent);
            } else {
                entry.content = contentWithoutInternals(targetContent);
                const nested = await buildIndex(
                    target.type,
                    targetContent,
                    state,
                    depth + 1,
                    new Set([...visited, handle])
                );
                if (Object.keys(nested).length > 0) {
                    entry._index = nested;
                }
            }
            entries.push(entry);
        }
        if (entries.length > 0) {
            const key = indexKey(path);
            index[key] = (index[key] || []).concat(entries);
        }
    }
    return index;
}

async function enrichForIndexing(object, { cordra, type, maxDepth = MAX_DEPTH } = {}) {
    try {
        if (!object || !object.content || typeof object.content !== 'object') {
            return object;
        }
        delete object.content._index;
        delete object.content._relatedIds;

        const state = { cordra, maxDepth, cache: {}, relatedIds: new Set() };
        const visited = new Set(object.id ? [object.id] : []);
        const index = await buildIndex(object.type || type, object.content, state, 0, visited);

        if (state.relatedIds.size > 0) {
            object.content._relatedIds = [...state.relatedIds];
        }
        if (Object.keys(index).length > 0) {
            object.content._index = index;
        }
    } catch (error) {
        if (typeof console !== 'undefined' && console.warn) {
            console.warn(`enrichForIndexing failed for ${object && object.id}: ${error.message}`);
        }
    }
    return object;
}

module.exports = {
    ENRICH_TARGET_TYPES,
    MAX_DEPTH,
    enrichForIndexing,
    referencePathsForType,
};
