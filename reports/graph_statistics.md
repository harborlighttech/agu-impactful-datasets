# Statistics

Measured from `impactful_datasets.data.jsonld`, the schema.org file the site serves and other
systems harvest. 9,616 triples.

| | |
|---|---|
| Datasets | **133** |
| Nominators | **161** |
| Nominations | **174** |
| Discipline groups | **9** |

Nominators are counted once each, so there are more nominations than nominators:
some people put forward more than one dataset.

## Datasets per discipline group

| Discipline group | Datasets |
|---|---|
| Ocean Science, Hydrology, Cryosphere | 31 |
| Atmospheric Science, Space Weather | 30 |
| Global Environmental Change, Paleoceanography and Paleoclimatology, Biogeoscience | 30 |
| Earth’s Interior, Geodesy | 12 |
| Earth Surface, Natural Hazards, Geology, Near Surface Geophysics | 10 |
| Geohealth, Society, Education | 10 |
| Space and Planetary Science | 9 |
| Earth & Planetary Materials | 2 |
| Nonlinear Geophysics, Machine Learning, Informatics | 0 |

A dataset nominated under two groups counts in both, so the column can total
more than the number of datasets. Groups with no datasets are listed rather than
dropped.

## Classes

Every type asserted in the file, and how many nodes carry it.

| Class | Namespace | Instances |
|---|---|---|
| `schema:CreativeWork` | schema | 759 |
| `schema:PropertyValue` | schema | 478 |
| `agu:ResponsibleParty` | agu | 308 |
| `schema:Organization` | schema | 188 |
| `schema:EndorseAction` | schema | 174 |
| `schema:Person` | schema | 168 |
| `schema:Dataset` | schema | 133 |
| `schema:ItemList` | schema | 133 |
| `schema:DataCatalog` | schema | 111 |
| `schema:DefinedTerm` | schema | 60 |
| `rdf:Property` | rdf | 2 |
| `owl:Class` | owl | 1 |
| `schema:DefinedTermSet` | schema | 1 |

- **agu** — 1 class
- **owl** — 1 class
- **rdf** — 1 class
- **schema** — 10 classes

A node can carry more than one type, so these do not sum to a node count.
