const cordra = require('cordra');
const schema = require('/cordra/schemas/VocabularyConcept.schema.json');

const hdlShoulder = 'voc';

const SKOS = 'http://www.w3.org/2004/02/skos/core#';
const GEOJSON = 'https://purl.org/geojson/vocab#';
const TRACKED_PROPERTIES = ['prefLabel', 'altLabel', 'definition', 'scopeNote'];
const RELATIONSHIP_FIELDS = ['broader', 'related', 'equivalent', 'use', 'usedFor'];
const DEFAULT_DISPLAY_LANG = 'en';
const PROTECTED_STATUSES = new Set(['pending', 'submitted', 'rejected']);
const UM_SNAPSHOT = 'vocabHarvestSnapshot';
const UM_SNAPSHOT_AT = 'vocabSnapshotAt';
const UM_EDITS = 'vocabEdits';
const UM_HARVEST_UPDATE = 'vocabHarvestUpdate';
const UM_HARVEST_ENRICHMENT_UPDATE = 'vocabHarvestEnrichmentUpdate';
const UM_RESET_HARVEST_PROTECTION = 'vocabResetHarvestProtection';


/**************************************************
                LIFECYCLE HOOKS
 **************************************************/

exports.beforeSchemaValidation = beforeSchemaValidation;
exports.beforeSchemaValidationWithId = beforeSchemaValidationWithId;
exports.generateId = generateId;
exports.isGenerateIdLoopable = false;
exports.objectForIndexing = objectForIndexing;


async function beforeSchemaValidation(object, context) {
    try {
        object.content.$schema = schema.$id;

        sanitizeTrackedLexical(object.content);
        await filterExistingRelationshipRefs(object.content);
        ensureMainTitle(object.content);
        removeContentInternals(object.content);

        if (isMirroredConcept(object.content)) {
            const hasHarvestUpdateMarker = object.content
                && (object.content[UM_HARVEST_UPDATE] || object.content[UM_HARVEST_ENRICHMENT_UPDATE]);
            if (!hasHarvestUpdateMarker) {
                clearHarvestUpdateMarker(object);
            }
        } else {
            clearNativeRecord(object);
        }

        return object;
    } catch (error) {
        throw new cordra.CordraError(
            'Error in lifecycle hook beforeSchemaValidation [a4f2c9e1]: ' + error.message,
            400
        );
    }
}


async function beforeSchemaValidationWithId(object, context) {
    try {
        object.content.$schema = schema.$id;

        sanitizeTrackedLexical(object.content);
        if (object.userMetadata !== undefined) {
            object.userMetadata = flattenUserMetadata(object.userMetadata);
        }

        if (isMirroredConcept(object.content)) {
            if (object.content && object.content[UM_HARVEST_ENRICHMENT_UPDATE]) {
                const incomingContent = object.content || {};
                const existingObject = await readExistingObject(object.id);
                if (!existingObject) {
                    throw new Error(`Cannot apply VocabularyConcept harvest enrichment; existing object ${object.id} was not found`);
                }
                const existingContent = existingObject.content && typeof existingObject.content === 'object'
                    ? existingObject.content
                    : {};
                const existingUserMetadata = flattenUserMetadata(existingObject.userMetadata);
                const content = JSON.parse(JSON.stringify(existingContent));

                for (const field of RELATIONSHIP_FIELDS) {
                    if (!(field in incomingContent)) {
                        continue;
                    }
                    const values = Array.isArray(incomingContent[field])
                        ? JSON.parse(JSON.stringify(incomingContent[field]))
                        : [];
                    if (values.length > 0) {
                        content[field] = values;
                    } else {
                        delete content[field];
                    }
                }

                const resetHarvestProtection = Boolean(incomingContent[UM_RESET_HARVEST_PROTECTION]);
                const protectedPaths = resetHarvestProtection ? new Set() : protectedPathsFromExisting(existingObject);
                const protectedAltLangs = new Set();
                for (const path of protectedPaths) {
                    if (String(path).startsWith('altLabel.')) {
                        protectedAltLangs.add(String(path).split('.', 2)[1]);
                    }
                }

                normalizeLexicalContent(content);
                const existingMaps = contentToLexicalMaps(content);
                const incomingMaps = contentToLexicalMaps(incomingContent);
                if (incomingMaps.altLabel && typeof incomingMaps.altLabel === 'object') {
                    const mergedAlt = existingMaps.altLabel && typeof existingMaps.altLabel === 'object'
                        ? JSON.parse(JSON.stringify(existingMaps.altLabel))
                        : {};
                    for (const [language, entries] of Object.entries(incomingMaps.altLabel)) {
                        if (protectedAltLangs.has(language) || !isLangKey(language) || !Array.isArray(entries)) {
                            continue;
                        }
                        if (!Array.isArray(mergedAlt[language])) {
                            mergedAlt[language] = [];
                        }
                        const seen = new Set();
                        for (const item of mergedAlt[language]) {
                            const entry = normalizeAltLabelEntry(item);
                            if (entry) {
                                seen.add(`${entry.label}\0${entry.AxiellId || ''}`);
                            }
                        }
                        for (const item of entries) {
                            const entry = normalizeAltLabelEntry(item);
                            if (!entry) {
                                continue;
                            }
                            const key = `${entry.label}\0${entry.AxiellId || ''}`;
                            if (seen.has(key)) {
                                continue;
                            }
                            seen.add(key);
                            mergedAlt[language].push(entry);
                        }
                    }

                    const cleanedAlt = {};
                    for (const [language, entries] of Object.entries(mergedAlt)) {
                        if (isLangKey(language) && Array.isArray(entries) && entries.length > 0) {
                            cleanedAlt[language] = entries;
                        }
                    }
                    if (Object.keys(cleanedAlt).length > 0) {
                        existingMaps.altLabel = cleanedAlt;
                    } else {
                        delete existingMaps.altLabel;
                    }
                }
                applyLexicalMapsToContent(content, existingMaps);

                content.harvestedDate = typeof incomingContent.harvestedDate === 'string' && incomingContent.harvestedDate.trim()
                    ? incomingContent.harvestedDate.trim()
                    : new Date().toISOString().slice(0, 10);

                const userMetadata = {
                    ...existingUserMetadata,
                };
                delete userMetadata[UM_HARVEST_UPDATE];
                delete userMetadata[UM_HARVEST_ENRICHMENT_UPDATE];
                delete userMetadata[UM_RESET_HARVEST_PROTECTION];
                if (resetHarvestProtection) {
                    delete userMetadata[UM_EDITS];
                }
                userMetadata[UM_SNAPSHOT] = lexicalSnapshot(content);
                userMetadata[UM_SNAPSHOT_AT] = content.harvestedDate;
                delete content[UM_HARVEST_UPDATE];
                delete content[UM_HARVEST_ENRICHMENT_UPDATE];
                delete content[UM_RESET_HARVEST_PROTECTION];
                removeContentInternals(content);
                object.content = content;
                object.userMetadata = userMetadata;
            } else if (object.content && object.content[UM_HARVEST_UPDATE]) {
                const incomingContent = object.content || {};
                const resetHarvestProtection = Boolean(incomingContent[UM_RESET_HARVEST_PROTECTION]);
                const incomingUserMetadata = flattenUserMetadata(object.userMetadata);
                const existingObject = await readExistingObject(object.id);
                const existingContent = existingObject && existingObject.content && typeof existingObject.content === 'object'
                    ? existingObject.content
                    : {};
                const existingUserMetadata = flattenUserMetadata(existingObject && existingObject.userMetadata);

                const mergedUserMetadata = {
                    ...existingUserMetadata,
                    ...incomingUserMetadata,
                };
                delete mergedUserMetadata[UM_HARVEST_UPDATE];
                delete mergedUserMetadata[UM_RESET_HARVEST_PROTECTION];
                mergedUserMetadata[UM_SNAPSHOT] = lexicalSnapshot(incomingContent);
                mergedUserMetadata[UM_SNAPSHOT_AT] = typeof incomingContent.harvestedDate === 'string' && incomingContent.harvestedDate.trim()
                    ? incomingContent.harvestedDate.trim()
                    : new Date().toISOString().slice(0, 10);
                if (resetHarvestProtection) {
                    delete mergedUserMetadata[UM_EDITS];
                } else if (existingUserMetadata[UM_EDITS] && typeof existingUserMetadata[UM_EDITS] === 'object') {
                    mergedUserMetadata[UM_EDITS] = existingUserMetadata[UM_EDITS];
                }

                const protectedPaths = resetHarvestProtection ? new Set() : protectedPathsFromExisting(existingObject);
                normalizeLexicalContent(existingContent);
                normalizeLexicalContent(incomingContent);
                const existingMaps = contentToLexicalMaps(existingContent);
                const incomingMaps = contentToLexicalMaps(incomingContent);
                for (const path of protectedPaths) {
                    const [property, language] = String(path).split('.', 2);
                    if (!TRACKED_PROPERTIES.includes(property) || !isLangKey(language)) {
                        continue;
                    }
                    const block = existingMaps[property];
                    if (!block || typeof block !== 'object' || !(language in block)) {
                        continue;
                    }
                    if (!incomingMaps[property] || typeof incomingMaps[property] !== 'object') {
                        incomingMaps[property] = {};
                    }
                    const value = block[language];
                    incomingMaps[property][language] = value && typeof value === 'object'
                        ? JSON.parse(JSON.stringify(value))
                        : value;
                }
                applyLexicalMapsToContent(incomingContent, incomingMaps);

                delete incomingContent[UM_HARVEST_UPDATE];
                delete incomingContent[UM_HARVEST_ENRICHMENT_UPDATE];
                delete incomingContent[UM_RESET_HARVEST_PROTECTION];
                object.userMetadata = mergedUserMetadata;
            } else {
                const content = object.content;
                object.userMetadata = flattenUserMetadata(object.userMetadata);
                const userMetadata = object.userMetadata;
                const snapshot = userMetadata[UM_SNAPSHOT] && typeof userMetadata[UM_SNAPSHOT] === 'object'
                    ? userMetadata[UM_SNAPSHOT]
                    : {};
                const edits = userMetadata[UM_EDITS] && typeof userMetadata[UM_EDITS] === 'object'
                    ? { ...userMetadata[UM_EDITS] }
                    : {};
                const modifiedBy = (context && context.userId) || undefined;
                const modifiedAt = new Date().toISOString().slice(0, 10);
                const currentMaps = contentToLexicalMaps(content);

                for (const property of TRACKED_PROPERTIES) {
                    const currentBlock = currentMaps[property];
                    const snapshotBlock = snapshot[property];
                    for (const language of langKeys(currentBlock, snapshotBlock)) {
                        const path = `${property}.${language}`;
                        const currentValue = currentBlock && typeof currentBlock === 'object'
                            ? currentBlock[language]
                            : undefined;
                        const snapshotValue = snapshotBlock && typeof snapshotBlock === 'object'
                            ? snapshotBlock[language]
                            : undefined;
                        const existing = edits[path];

                        const hasCurrentValue = Array.isArray(currentValue)
                            ? currentValue.length > 0
                            : typeof currentValue === 'string'
                                ? currentValue.trim().length > 0
                                : currentValue !== undefined && currentValue !== null;
                        if (!hasCurrentValue) {
                            if (existing && existing.status === 'pending') {
                                delete edits[path];
                            }
                            continue;
                        }

                        const matchesSnapshot = Array.isArray(currentValue) || Array.isArray(snapshotValue)
                            ? JSON.stringify(currentValue || []) === JSON.stringify(snapshotValue || [])
                            : (currentValue || '') === (snapshotValue || '');
                        if (matchesSnapshot) {
                            if (existing && (existing.status === 'pending' || existing.status === 'accepted' || existing.status === 'superseded')) {
                                delete edits[path];
                            }
                            continue;
                        }

                        const nextEdit = {
                            status: existing && PROTECTED_STATUSES.has(existing.status) ? existing.status : 'pending',
                            modifiedAt,
                        };
                        if (modifiedBy) {
                            nextEdit.modifiedBy = modifiedBy;
                        }
                        if (existing && existing.note) {
                            nextEdit.note = existing.note;
                        }
                        edits[path] = nextEdit;
                    }
                }

                if (Object.keys(edits).length > 0) {
                    userMetadata[UM_EDITS] = edits;
                } else {
                    delete userMetadata[UM_EDITS];
                }
            }
            await filterExistingRelationshipRefs(object.content);
            ensureMainTitle(object.content);
            removeContentInternals(object.content);
            clearHarvestUpdateMarker(object);
        } else {
            await filterExistingRelationshipRefs(object.content);
            ensureMainTitle(object.content);
            removeContentInternals(object.content);
            clearNativeRecord(object);
        }

        return object;
    } catch (error) {
        throw new cordra.CordraError(
            'Error in lifecycle hook beforeSchemaValidationWithId [6b3d8f0a]: ' + error.message,
            400
        );
    }
}


function generateId(object, context) {
    try {
        const prefix = cordra.get('design').content.handleMintingConfig.prefix;
        const notation = String(object.content.notation || object.content.label || '').trim().toLowerCase();

        if (!notation || !/^[a-z0-9_:-]+$/.test(notation)) {
            throw new Error('Invalid or missing notation for handle minting');
        }

        return `${prefix}/${hdlShoulder}.${notation.replace(/:/g, '.')}`;
    } catch (error) {
        throw new cordra.CordraError(
            'Error in lifecycle hook generateId [d91e5c7b]: ' + error.message,
            400
        );
    }
}


function objectForIndexing(object) {
    try {
        delete object.content.howToCite;
        delete object.metadata.hashes;
        delete object.userMetadata;
        return object;
    } catch (error) {
        throw new cordra.CordraError(
            'Error in lifecycle hook objectForIndexing [0f8a2d6c]: ' + error.message,
            400
        );
    }
}


/**************************************************
                TYPE METHODS
 **************************************************/

exports.methods = {};
exports.methods.asSkosJsonLd = asSkosJsonLd;
exports.methods.asSkosJsonLd.allowGet = true;


/**
 * Return this VocabularyConcept as SKOS JSON-LD.
 * Cordra serialises the returned object as application/json.
 */
async function asSkosJsonLd(object, context) {
    try {
        const c = object.content || {};
        const vocabularyContent = await readVocabularyContent(c.vocabulary);
        const conceptUri = c.uri || handleToUri(object.id);
        const schemeUri = vocabularyContent?.uri
            || (Array.isArray(c.inScheme) && c.inScheme.length > 0 ? c.inScheme[0] : undefined);

        const concept = {
            '@id': conceptUri,
            '@type': 'skos:Concept',
        };

        if (c.notation) concept['skos:notation'] = c.notation;
        const lexicalMaps = contentToLexicalMaps(c);
        addLangMap(concept, 'skos:prefLabel', lexicalMaps.prefLabel);
        addLangMap(concept, 'skos:definition', lexicalMaps.definition);
        addLangMap(concept, 'skos:scopeNote', lexicalMaps.scopeNote);

        if (lexicalMaps.altLabel && typeof lexicalMaps.altLabel === 'object') {
            for (const [lang, values] of Object.entries(lexicalMaps.altLabel)) {
                for (const value of (Array.isArray(values) ? values : [values])) {
                    let literal;
                    if (typeof value === 'string') {
                        literal = value.trim() || undefined;
                    } else if (value && typeof value === 'object' && typeof value.label === 'string') {
                        literal = value.label.trim() || undefined;
                    }
                    if (!literal) continue;
                    if (!concept['skos:altLabel']) concept['skos:altLabel'] = [];
                    concept['skos:altLabel'].push({ '@language': lang, '@value': literal });
                }
            }
        }

        if (schemeUri) {
            concept['skos:inScheme'] = { '@id': schemeUri };
        }

        for (const matchField of ['exactMatch', 'closeMatch']) {
            const skosField = matchField === 'exactMatch' ? 'skos:exactMatch' : 'skos:closeMatch';
            const matches = Array.isArray(c[matchField]) ? c[matchField] : [];
            const refs = matches
                .map((m) => (m && typeof m.uri === 'string' ? { '@id': m.uri } : null))
                .filter(Boolean);
            setOneOrMany(concept, skosField, refs);
        }

        for (const [field, skosField] of [['broader', 'skos:broader'], ['related', 'skos:related']]) {
            const refs = await relationshipRefs(c[field]);
            setOneOrMany(concept, skosField, refs);
        }

        const graph = [concept];

        if (schemeUri) {
            const scheme = {
                '@id': schemeUri,
                '@type': 'skos:ConceptScheme',
            };
            if (vocabularyContent && typeof vocabularyContent === 'object') {
                const vocabularyMaps = contentToLexicalMaps(vocabularyContent);
                addLangMap(scheme, 'skos:prefLabel', vocabularyMaps.prefLabel);
                addLangMap(scheme, 'skos:definition', vocabularyMaps.definition);
            }
            graph.push(scheme);
        }

        const geometry = c.geometry;
        if (geometry && typeof geometry === 'object' && geometry.type === 'Point') {
            const coordinates = Array.isArray(geometry.coordinates) ? geometry.coordinates : [];
            if (coordinates.length === 2
                && coordinates.every((value) => typeof value === 'number' && Number.isFinite(value))
                && (!geometry.crs || geometry.crs === 'EPSG:4326')) {
                concept['geojson:geometry'] = { '@id': `${conceptUri}#geometry` };
                graph.push({
                    '@id': `${conceptUri}#geometry`,
                    '@type': 'geojson:Point',
                    'geojson:coordinates': coordinates,
                });
            }
        }

        return {
            '@context': {
                skos: SKOS,
                geojson: GEOJSON,
            },
            '@graph': graph,
        };
    } catch (error) {
        throw new cordra.CordraError(
            'Error in type method asSkosJsonLd [c7e4b1a9]: ' + error.message,
            400
        );
    }
}


/**************************************************
                HELPER FUNCTIONS
 **************************************************/

function isMirroredConcept(content) {
    return Boolean(
        content
        && typeof content.harvestedSource === 'string'
        && content.harvestedSource.trim().length > 0
    );
}


function flattenUserMetadata(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return {};
    }
    const nested = raw.userMetadata;
    const flat = { ...raw };
    delete flat.userMetadata;
    delete flat.content;
    delete flat[UM_HARVEST_UPDATE];
    delete flat[UM_HARVEST_ENRICHMENT_UPDATE];
    delete flat[UM_RESET_HARVEST_PROTECTION];
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
        return { ...flattenUserMetadata(nested), ...flat };
    }
    return flat;
}


function clearNativeRecord(object) {
    const content = object.content;
    if (!content || typeof content !== 'object') {
        return;
    }
    delete content[UM_HARVEST_UPDATE];
    delete content[UM_HARVEST_ENRICHMENT_UPDATE];
    delete content[UM_RESET_HARVEST_PROTECTION];
    delete content.harvestProtection;
    delete content.harvestedDate;
    delete content.queryTerms;
    delete content.harvestBaseline;
    delete content.localContributions;
    delete content.harvestedSource;

    if (!object.userMetadata || typeof object.userMetadata !== 'object') {
        return;
    }
    delete object.userMetadata[UM_SNAPSHOT];
    delete object.userMetadata[UM_SNAPSHOT_AT];
    delete object.userMetadata[UM_EDITS];
    delete object.userMetadata[UM_HARVEST_UPDATE];
    delete object.userMetadata[UM_HARVEST_ENRICHMENT_UPDATE];
    delete object.userMetadata[UM_RESET_HARVEST_PROTECTION];
    if (Object.keys(object.userMetadata).length === 0) {
        delete object.userMetadata;
    }
}


function clearHarvestUpdateMarker(object) {
    if (object.content && typeof object.content === 'object') {
        delete object.content[UM_HARVEST_UPDATE];
        delete object.content[UM_HARVEST_ENRICHMENT_UPDATE];
        delete object.content[UM_RESET_HARVEST_PROTECTION];
    }
    if (!object.userMetadata || typeof object.userMetadata !== 'object') {
        return;
    }
    delete object.userMetadata[UM_HARVEST_UPDATE];
    delete object.userMetadata[UM_HARVEST_ENRICHMENT_UPDATE];
    delete object.userMetadata[UM_RESET_HARVEST_PROTECTION];
    if (Object.keys(object.userMetadata).length === 0) {
        delete object.userMetadata;
    }
}


function lexicalSnapshot(content) {
    const maps = contentToLexicalMaps(content);
    const snapshot = {};
    for (const property of TRACKED_PROPERTIES) {
        const cleaned = sanitizeLexicalProperty(property, maps[property]);
        if (cleaned) {
            snapshot[property] = cleaned;
        }
    }
    return snapshot;
}


function protectedPathsFromExisting(existingObject) {
    const paths = new Set();
    const userMetadata = flattenUserMetadata(existingObject && existingObject.userMetadata);
    const edits = userMetadata[UM_EDITS] && typeof userMetadata[UM_EDITS] === 'object'
        ? userMetadata[UM_EDITS]
        : {};
    for (const [path, edit] of Object.entries(edits)) {
        if (edit && PROTECTED_STATUSES.has(edit.status)) {
            paths.add(path);
        }
    }
    return paths;
}


async function filterExistingRelationshipRefs(content) {
    if (!content || typeof content !== 'object') {
        return;
    }
    const cache = {};
    for (const field of RELATIONSHIP_FIELDS) {
        const values = Array.isArray(content[field]) ? content[field] : [];
        const filtered = [];
        const seen = new Set();
        for (const value of values) {
            const handle = typeof value === 'string' ? value.trim() : '';
            if (!handle || seen.has(handle)) {
                continue;
            }
            let targetExists = false;
            if (handle.includes('://')) {
                targetExists = true;
            } else if (Object.prototype.hasOwnProperty.call(cache, handle)) {
                targetExists = cache[handle];
            } else {
                try {
                    cache[handle] = Boolean(await cordra.get(handle));
                } catch (error) {
                    cache[handle] = false;
                }
                targetExists = cache[handle];
            }
            if (targetExists) {
                seen.add(handle);
                filtered.push(handle);
            }
        }
        if (filtered.length > 0) {
            content[field] = filtered;
        } else {
            delete content[field];
        }
    }
}


async function readVocabularyContent(vocabularyHandle) {
    const handle = typeof vocabularyHandle === 'string' ? vocabularyHandle.trim() : '';
    if (!handle) {
        return null;
    }
    try {
        const vocabulary = await cordra.get(handle);
        return vocabulary && vocabulary.content && typeof vocabulary.content === 'object'
            ? vocabulary.content
            : null;
    } catch (error) {
        return null;
    }
}


function removeContentInternals(content) {
    if (!content || typeof content !== 'object') {
        return;
    }
    delete content.inScheme;
    delete content.harvestProtection;
    delete content.sourceRecord;
}


async function readExistingObject(id) {
    if (!id) {
        return null;
    }
    try {
        const existing = await cordra.get(id);
        if (existing && existing.userMetadata !== undefined) {
            existing.userMetadata = flattenUserMetadata(existing.userMetadata);
        }
        return existing;
    } catch (error) {
        return null;
    }
}


function sanitizeTrackedLexical(content) {
    if (!content || typeof content !== 'object') {
        return;
    }

    normalizeLexicalContent(content);
    sanitizeTerms(content);
    sanitizeDescriptions(content);
    removeLegacyLexicalMaps(content);

    delete content.harvestBaseline;
    delete content.localContributions;
}


function removeLegacyLexicalMaps(content) {
    delete content.prefLabel;
    delete content.altLabel;
    delete content.definition;
    delete content.scopeNote;
}


function normalizeLexicalContent(content) {
    if (!content || typeof content !== 'object') {
        return;
    }

    const hasTerms = Array.isArray(content.terms) && content.terms.length > 0;
    const hasDescriptions = Array.isArray(content.descriptions) && content.descriptions.length > 0;
    const hasLegacyMaps = ['prefLabel', 'altLabel', 'definition', 'scopeNote'].some(
        (field) => content[field] && typeof content[field] === 'object'
    );

    if (!hasTerms || !hasDescriptions || hasLegacyMaps) {
        const maps = contentToLexicalMaps(content);
        applyLexicalMapsToContent(content, maps);
    }
}


function contentToLexicalMaps(content) {
    const maps = {};

    if (Array.isArray(content.terms)) {
        const { prefLabel, altLabel } = termsToLexicalMaps(content.terms);
        if (Object.keys(prefLabel).length > 0) {
            maps.prefLabel = prefLabel;
        }
        if (Object.keys(altLabel).length > 0) {
            maps.altLabel = {};
            for (const [lang, labels] of Object.entries(altLabel)) {
                maps.altLabel[lang] = labels.map((label) => ({ label }));
            }
        }
    } else {
        const prefLabel = sanitizeLexicalProperty('prefLabel', content.prefLabel);
        if (prefLabel) {
            maps.prefLabel = prefLabel;
        }
        const altLabel = sanitizeLexicalProperty('altLabel', content.altLabel);
        if (altLabel) {
            maps.altLabel = altLabel;
        }
    }

    if (Array.isArray(content.descriptions)) {
        const { definition, scopeNote } = descriptionsToMaps(content.descriptions);
        if (Object.keys(definition).length > 0) {
            maps.definition = definition;
        }
        if (Object.keys(scopeNote).length > 0) {
            maps.scopeNote = scopeNote;
        }
    } else {
        const definition = sanitizeLexicalProperty('definition', content.definition);
        if (definition) {
            maps.definition = definition;
        }
        const scopeNote = sanitizeLexicalProperty('scopeNote', content.scopeNote);
        if (scopeNote) {
            maps.scopeNote = scopeNote;
        }
    }

    return maps;
}


function applyLexicalMapsToContent(content, maps) {
    const prefLabel = maps.prefLabel || {};
    const altLabel = {};
    if (maps.altLabel && typeof maps.altLabel === 'object') {
        for (const [lang, entries] of Object.entries(maps.altLabel)) {
            if (!Array.isArray(entries)) {
                continue;
            }
            altLabel[lang] = entries
                .map((entry) => normalizeAltLabelEntry(entry))
                .filter(Boolean)
                .map((entry) => entry.label);
        }
    }
    const definition = maps.definition || {};
    const scopeNote = maps.scopeNote || {};

    const terms = lexicalMapsToTerms(prefLabel, altLabel);
    if (terms.length > 0) {
        content.terms = terms;
    } else {
        delete content.terms;
    }

    const descriptions = mapsToDescriptions(definition, scopeNote);
    if (descriptions.length > 0) {
        content.descriptions = descriptions;
    } else {
        delete content.descriptions;
    }
}


function termsToLexicalMaps(terms) {
    const prefLabel = {};
    const altLabel = {};

    if (!Array.isArray(terms)) {
        return { prefLabel, altLabel };
    }

    for (const term of terms) {
        if (!term || typeof term !== 'object') {
            continue;
        }
        const lang = typeof term.lang === 'string' ? term.lang.trim() : '';
        const label = typeof term.label === 'string' ? term.label.trim() : '';
        if (!isLangKey(lang) || !label) {
            continue;
        }
        if (term.isAlternative === true) {
            if (!Array.isArray(altLabel[lang])) {
                altLabel[lang] = [];
            }
            if (!altLabel[lang].includes(label)) {
                altLabel[lang].push(label);
            }
        } else if (!(lang in prefLabel)) {
            prefLabel[lang] = label;
        }
    }

    return { prefLabel, altLabel };
}


function lexicalMapsToTerms(prefLabel, altLabel) {
    const terms = [];

    for (const lang of Object.keys(prefLabel || {}).filter(isLangKey).sort()) {
        const label = typeof prefLabel[lang] === 'string' ? prefLabel[lang].trim() : '';
        if (label) {
            terms.push({ label, lang: lang.trim(), isAlternative: false });
        }
    }

    for (const lang of Object.keys(altLabel || {}).filter(isLangKey).sort()) {
        const values = Array.isArray(altLabel[lang]) ? altLabel[lang] : [];
        const seen = new Set();
        for (const value of values) {
            const label = typeof value === 'string' ? value.trim() : '';
            if (!label || seen.has(label)) {
                continue;
            }
            seen.add(label);
            terms.push({ label, lang: lang.trim(), isAlternative: true });
        }
    }

    return terms;
}


function descriptionsToMaps(descriptions) {
    const definition = {};
    const scopeNote = {};

    if (!Array.isArray(descriptions)) {
        return { definition, scopeNote };
    }

    for (const item of descriptions) {
        if (!item || typeof item !== 'object') {
            continue;
        }
        const lang = typeof item.lang === 'string' ? item.lang.trim() : '';
        const text = typeof item.description === 'string' ? item.description.trim() : '';
        if (!isLangKey(lang) || !text) {
            continue;
        }
        const kind = typeof item.kind === 'string' ? item.kind.trim() : 'definition';
        if (kind === 'scopeNote') {
            scopeNote[lang] = text;
        } else {
            definition[lang] = text;
        }
    }

    return { definition, scopeNote };
}


function mapsToDescriptions(definition, scopeNote) {
    const descriptions = [];

    for (const lang of Object.keys(definition || {}).filter(isLangKey).sort()) {
        const text = typeof definition[lang] === 'string' ? definition[lang].trim() : '';
        if (text) {
            descriptions.push({ description: text, lang: lang.trim(), kind: 'definition' });
        }
    }

    for (const lang of Object.keys(scopeNote || {}).filter(isLangKey).sort()) {
        const text = typeof scopeNote[lang] === 'string' ? scopeNote[lang].trim() : '';
        if (text) {
            descriptions.push({ description: text, lang: lang.trim(), kind: 'scopeNote' });
        }
    }

    return descriptions;
}


function sanitizeTerms(content) {
    if (!Array.isArray(content.terms)) {
        delete content.terms;
        return;
    }

    const { prefLabel, altLabel } = termsToLexicalMaps(content.terms);
    const cleaned = lexicalMapsToTerms(prefLabel, altLabel);
    if (cleaned.length > 0) {
        content.terms = cleaned;
    } else {
        delete content.terms;
    }
}


function sanitizeDescriptions(content) {
    if (!Array.isArray(content.descriptions)) {
        delete content.descriptions;
        return;
    }

    const { definition, scopeNote } = descriptionsToMaps(content.descriptions);
    const cleaned = mapsToDescriptions(definition, scopeNote);
    if (cleaned.length > 0) {
        content.descriptions = cleaned;
    } else {
        delete content.descriptions;
    }
}


function isLangKey(key) {
    return typeof key === 'string' && key.trim().length > 0;
}


function langKeys(...blocks) {
    const keys = new Set();
    for (const block of blocks) {
        if (!block || typeof block !== 'object') {
            continue;
        }
        for (const key of Object.keys(block)) {
            if (isLangKey(key)) {
                keys.add(key);
            }
        }
    }
    return keys;
}


function displayLabelFromTerms(terms) {
    const { prefLabel } = termsToLexicalMaps(terms);
    return displayLabel(prefLabel);
}


function displayLabel(prefLabel) {
    if (!prefLabel || typeof prefLabel !== 'object') {
        return '';
    }
    const en = prefLabel[DEFAULT_DISPLAY_LANG];
    if (typeof en === 'string' && en.trim().length > 0) {
        return en.trim();
    }
    for (const language of Object.keys(prefLabel).filter(isLangKey).sort()) {
        const value = prefLabel[language];
        if (typeof value === 'string' && value.trim().length > 0) {
            return value.trim();
        }
    }
    return '';
}


function normalizeAltLabelEntry(value) {
    if (typeof value === 'string') {
        const label = value.trim();
        return label.length > 0 ? { label } : undefined;
    }
    if (!value || typeof value !== 'object') {
        return undefined;
    }
    const label = typeof value.label === 'string' ? value.label.trim() : '';
    if (!label) {
        return undefined;
    }
    const entry = { label };
    const axiellId = typeof value.AxiellId === 'string' ? value.AxiellId.trim() : '';
    if (axiellId) {
        entry.AxiellId = axiellId;
    }
    return entry;
}


function sanitizeLexicalProperty(property, block) {
    if (!block || typeof block !== 'object') {
        return undefined;
    }

    if (property === 'altLabel') {
        const cleaned = {};
        for (const language of Object.keys(block)) {
            if (!isLangKey(language)) {
                continue;
            }
            const values = block[language];
            if (!Array.isArray(values)) {
                continue;
            }
            const labels = [];
            const seen = new Set();
            for (const value of values) {
                const entry = normalizeAltLabelEntry(value);
                if (!entry) {
                    continue;
                }
                const key = `${entry.label}\0${entry.AxiellId || ''}`;
                if (seen.has(key)) {
                    continue;
                }
                seen.add(key);
                labels.push(entry);
            }
            if (labels.length > 0) {
                cleaned[language] = labels;
            }
        }
        return Object.keys(cleaned).length > 0 ? cleaned : undefined;
    }

    const cleaned = {};
    for (const language of Object.keys(block)) {
        if (!isLangKey(language)) {
            continue;
        }
        const value = block[language];
        if (typeof value === 'string') {
            const trimmed = value.trim();
            if (trimmed.length > 0) {
                cleaned[language] = trimmed;
            }
        }
    }
    return Object.keys(cleaned).length > 0 ? cleaned : undefined;
}


function ensureMainTitle(content) {
    let title = displayLabelFromTerms(content.terms);

    const notation = (content.notation || content.label || '').trim();
    if (notation) {
        title = title ? `${title} (${notation})` : `(${notation})`;
    }
    content._mainTitle = title;
}


function handleToUri(handle) {
    if (!handle) {
        return undefined;
    }
    return String(handle).includes('://') ? String(handle) : `https://hdl.handle.net/${handle}`;
}


function addLangMap(target, property, block) {
    if (!block || typeof block !== 'object') {
        return;
    }
    for (const [lang, value] of Object.entries(block)) {
        if (!value) continue;
        if (!target[property]) target[property] = [];
        target[property].push({ '@language': lang, '@value': value });
    }
}


function setOneOrMany(target, property, refs) {
    if (!Array.isArray(refs) || refs.length === 0) {
        return;
    }
    target[property] = refs.length === 1 ? refs[0] : refs;
}


async function relationshipRefs(handles) {
    if (!Array.isArray(handles) || handles.length === 0) {
        return [];
    }
    const refs = [];
    const seen = new Set();
    for (const handle of handles) {
        if (!handle || seen.has(handle)) continue;
        seen.add(handle);
        if (String(handle).includes('://')) {
            refs.push({ '@id': handle });
            continue;
        }
        try {
            const linked = await cordra.get(handle);
            const linkedContent = linked && linked.content ? linked.content : {};
            refs.push({
                '@id': linkedContent.uri
                    || linkedContent.harvestedSource?.conceptUri
                    || handleToUri(handle),
            });
        } catch (error) {
            refs.push({ '@id': handleToUri(handle) });
        }
    }
    return refs;
}
