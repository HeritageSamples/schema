# Heritage Samples Registry — JSON Schema Definitions

JSON Schema definitions for the pilot version of the [Heritage Samples Registry](https://heritagesamples.org/), an emerging international initiative to support the persistent identification, discovery, and sharing of information about material samples in the context of heritage science.

All schemas in this repository follow [JSON Schema Draft-07](https://json-schema.org/specification-links#draft-7) and include [Cordra](https://www.cordra.org/)-specific extensions for handle generation, object references, preview rendering, and authentication.

## Schema overview

| Schema | Description |
|---|---|
| **[Sample](Sample/)** | Material samples (cross-sections, fragments, scrapings, etc.) with IGSN-compatible metadata. The central record type of the registry. |
| **[HeritageObject](HeritageObject/)** | Heritage objects and fragments from which samples may originate (paintings, archaeological artefacts, etc.). |
| **[Material](Material/)** | Material vocabulary terms (extends VocabularyConcept). Used to describe the composition of samples and objects. |
| **[VocabularyConcept](VocabularyConcept/)** | Controlled vocabulary concepts with SKOS-like hierarchical relationships (broader/narrower) and external mappings. |
| **[Person](Person/)** | Researchers and other individuals linked to samples, objects, and organisations. |
| **[Organisation](Organisation/)** | Institutions and research organisations that act as custodians, publishers, or affiliations. |
| **[CordraUser](CordraUser/)** | User accounts for Cordra authentication, linked to Person records. |
| **[CordraGroup](CordraGroup/)** | User groups for access control within the Cordra platform. |
| **[Definitions](Definitions/)** | Shared GeoJSON geometry definitions reused by other schemas. |

## Versioning

All schemas are currently at **v0.9** (pilot). Schema files follow the naming convention `v{version}.schema.json`. JavaScript validation hooks, where present, use the corresponding `v{version}.schema.js` naming.

## Relationships between schemas

```
CordraUser ──────► Person ──────► Organisation
                                       ▲
                                       │
Sample ──► HeritageObject              │
  │              │                     │
  │              ├── creators ─► Person / Organisation
  │              ├── custodian ─► Organisation / Person
  │              ├── publisher ─► Organisation
  │              ├── materialTerms ─► VocabularyConcept
  │              └── parentObject ─► HeritageObject
  │
  ├── sampleSource ─► HeritageObject / Sample
  ├── creators ─► Person / Organisation
  ├── custodian ─► Organisation / Person
  ├── publisher ─► Organisation
  └── materialTerms ─► Material ─► VocabularyConcept

VocabularyConcept ──► broader / narrower ──► VocabularyConcept
Organisation ──► part_of_organisation ──► Organisation
CordraGroup ──► CordraUser / CordraGroup
```

## Identifiers

The registry aims to implement **IGSNs** (International Generic Sample Numbers) as persistent identifiers for samples, resolved via the global handle system. Samples and heritage objects also support DOI assignment and DataCite-compatible metadata fields such as `types`, `titles`, `creators`, `publisher`, `publicationYear`, `subjects`, `fundingReferences`, and `rightsList`.
