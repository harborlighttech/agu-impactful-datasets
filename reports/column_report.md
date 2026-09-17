# Column report — AGU *Impactful Datasets* v1

**Source:** `Impactful_Datasets_v1_June_16_-_CSV_Format.csv` · 133 data rows × 16 columns
**Output:** `impactful_datasets.jsonld` — 17,439 RDF triples across 846 nodes

---

## Before anything else: an encoding bug

The file is **not** valid UTF-8. Sixteen bytes are Mac Roman, so `pd.read_csv` fails outright:

| Byte | Mac Roman | Appears as | Occurrences |
|---|---|---|---|
| `0xD0` | en dash `–` | page ranges: `567–570` | 15 |
| `0x9A` | `ö` | `Gröcke, D.R.` | 1 |

All 16 sit in one row's reference list (row 87, the Eagle Ford / OAE-2 nomination) — almost certainly pasted from a Mac word processor. I repaired them before parsing. **Anyone else opening this file will hit the same error**, so it is worth fixing at source.

---

## Summary table

| Column | Fill | Distinct | Longest cell | Values parsed | Multi-valued cells | Max/cell | Mean/cell |
|---|---|---|---|---|---|---|---|
| `discipline` | 100.0% | 9 | 81 | 134 | 1 | 2 | 1.01 |
| `name` | 100.0% | 133 | 299 | 133 | 0 | 1 | 1 |
| `authors` | 100.0% | 130 | 592 | 262 | 28 | 12 | 1.97 |
| `link` | 100.0% | 133 | 577 | 163 | 18 | 5 | 1.23 |
| `repo_name` | 100.0% | 114 | 152 | 140 | 6 | 3 | 1.05 |
| `repo_pid` | 70.7% | 91 | 11,361 | 412 | 9 | 299 | 4.38 |
| `curators` | 72.9% | 90 | 434 | 126 | 11 | 13 | 1.3 |
| `description` | 100.0% | 133 | 6,786 | 134 | 1 | 2 | 1.01 |
| `justification` | 100.0% | 132 | 15,003 | 161 | 10 | 9 | 1.21 |
| `interaction` | 100.0% | 132 | 5,823 | 165 | 12 | 9 | 1.24 |
| `ref_pub` | 80.5% | 106 | 3,573 | 201 | 43 | 11 | 1.88 |
| `reuse` | 62.4% | 83 | 19,904 | 397 | 49 | 36 | 4.78 |
| `nom_name` | 100.0% | 123 | 246 | 174 | 15 | 9 | 1.31 |
| `email` | 100.0% | 124 | 326 | 174 | 15 | 9 | 1.31 |
| `orcid` | 97.7% | 120 | 470 | 174 | 15 | 9 | 1.31 |
| `affiliation` | 100.0% | 122 | 961 | 174 | 15 | 9 | 1.31 |

---

## The three multi-value patterns in this file

**1. Delimiter-separated lists.** `;` is the reliable one (`authors`, `link`, `repo_pid`). Commas are treacherous — see `authors` and `discipline` below. Newlines separate items in some cells and wrap text in others.

**2. Labelled parallel arrays.** Four columns (`nom_name`, `email`, `orcid`, `affiliation`) use `Nominator 1:` / `Nominator 2:` headers *inside* the cell. These are positional joins across columns: block *n* of `email` belongs to block *n* of `nom_name`. **The labels agree across all four columns in all 133 rows — zero disagreements** — so the zip is safe. This is the "headers for multiple values" pattern you flagged, and it is the single most important thing to get right, because a naive parse silently attributes one person's ORCID to another.

**3. Sub-schemas inside a cell.** `justification` nests two levels: `Nominator N:` blocks, each optionally divided into `People:`, `Planet:`, `Prosperity:` — the exact vocabulary from the column header. `reuse` does something similar ad hoc (`Scientific Publications:`, `Derived Data Products:`, `Educational Resources:`).

---

## Per-column detail

### `discipline` — Discipline Group

- **Shape:** Multi-select of **quoted discipline groups**. Fill 100.0% (133/133), 9 distinct raw strings.
- **Delimiter guessed:** `", "` between groups; commas *inside* a group are part of one label
- **Length (chars):** min 25, median 36, max 81
- **Values after parsing:** 134 total, 1 multi-valued cells, max 2 in one cell, mean 1.01 per populated cell
- **Cardinality histogram** (values per cell): `{1: 132, 2: 1}`
- **Entities extracted:** none
- **Parse methods used:** `{'single-group': 132, 'quoted-group': 1}`

8 canonical groups. One row survived as `Ocean Science, Hydrology, Cryosphere", "Atmospheric Science, Space Weather` — the leftover quotes prove the original field was a quoted multi-select that lost its quoting on export. Three other rows carry a stray trailing `"`. Do **not** split on bare commas here: it would shatter `Ocean Science, Hydrology, Cryosphere` into three false themes.

### `name` — Dataset Name

- **Shape:** Single value. Fill 100.0% (133/133), 133 distinct raw strings.
- **Delimiter guessed:** none
- **Length (chars):** min 4, median 42, max 299
- **Values after parsing:** 133 total, 0 multi-valued cells, max 1 in one cell, mean 1 per populated cell
- **Cardinality histogram** (values per cell): `{1: 133}`
- **Entities extracted:** none
- **Parse methods used:** `{}`

Fully unique (133/133). One outlier at 299 chars is a title plus a parenthetical product list.

### `authors` — Dataset Authors or Creators

- **Shape:** **Multi-valued, mixed delimiters**. Fill 100.0% (133/133), 130 distinct raw strings.
- **Delimiter guessed:** `;` (12 cells) > newline (5) > `, ... and` (11, low confidence)
- **Length (chars):** min 4, median 55, max 592
- **Values after parsing:** 262 total, 28 multi-valued cells, max 12 in one cell, mean 1.97 per populated cell
- **Cardinality histogram** (values per cell): `{1: 105, 2: 5, 3: 5, 4: 1, 5: 3, 6: 3, 7: 2, 8: 5, 9: 1, 10: 2, 12: 1}`
- **Entities extracted:** 3 URLs, 1 emails
- **Parse methods used:** `{'single': 105, 'comma+and (low confidence)': 11, 'semicolon': 12, 'newline': 5}`

The hard case. `Jochum, Klaus Peter` is *one* person in `Last, First` form, while `A. J. Newman, M. P. Clark, K. Sampson` is three. I split on comma only when an `and`/`&` is present and every fragment has ≥2 tokens. Two cells use their own sub-headers (`Part 1:` / `Part 2:`) and one uses `Global Estimates (V6.GL.02.04):` — these are version scopes, not authors, and are left unsplit.

### `link` — Dataset link or location (Persistent Identifier (PID) or URL of the landing page for the dataset)

- **Shape:** **Multi-valued**. Fill 100.0% (133/133), 133 distinct raw strings.
- **Delimiter guessed:** URL/DOI extraction; `;`, newline, and literal ` and ` all appear
- **Length (chars):** min 9, median 42, max 577
- **Values after parsing:** 163 total, 18 multi-valued cells, max 5 in one cell, mean 1.23 per populated cell
- **Cardinality histogram** (values per cell): `{1: 115, 2: 11, 3: 3, 4: 3, 5: 1}`
- **Entities extracted:** 145 URLs, 50 DOIs
- **Parse methods used:** `{'single-uri': 113, 'url/doi-extract': 18, 'single': 2}`

6 cells contain no URL at all — 4 are bare DOIs (`10.5067/...`), 2 are schemeless hosts (`georoc.eu`, `www.geonet.org.nz`). Bare DOIs are normalised to `https://doi.org/…`. Row 9 buries five product DOIs in a prose paragraph.

### `repo_name` — Repository Name where Dataset is hosted

- **Shape:** Mostly single. Fill 100.0% (133/133), 114 distinct raw strings.
- **Delimiter guessed:** `;`, newline
- **Length (chars):** min 4, median 23, max 152
- **Values after parsing:** 140 total, 6 multi-valued cells, max 3 in one cell, mean 1.05 per populated cell
- **Cardinality histogram** (values per cell): `{1: 127, 2: 5, 3: 1}`
- **Entities extracted:** 15 URLs, 1 DOIs
- **Parse methods used:** `{'single': 127, 'newline': 2, 'semicolon': 4}`

111 distinct strings but only ~99 distinct repositories: `Zenodo`/`zenodo.org`, `GES DISC`/`GES-DISC`, and three spellings of the NASA GES name. 15 cells put a URL in the name field instead of the PID field.

### `repo_pid` — Repository Persistent Identifier (RRID, DOI, other)

- **Shape:** **Multi-valued, extreme skew**. Fill 70.7% (94/133), 91 distinct raw strings.
- **Delimiter guessed:** `;` + URL/DOI extraction
- **Length (chars):** min 6, median 37, max 11,361
- **Values after parsing:** 412 total, 9 multi-valued cells, max 299 in one cell, mean 4.38 per populated cell
- **Cardinality histogram** (values per cell): `{0: 39, 1: 85, 2: 2, 3: 2, 4: 2, 5: 2, 299: 1}`
- **Entities extracted:** 369 URLs, 380 DOIs
- **Parse methods used:** `{'single-uri': 78, 'empty': 39, 'url/doi-extract': 8, 'single': 7, 'semicolon': 1}`

The single worst cell in the file: 11,361 chars holding 299 AmeriFlux site DOIs. 39 rows are empty. Median cell is one DOI. This column and `repo_name` are frequently swapped by submitters.

### `curators` — Repository Data managers or curators that support the dataset. 

- **Shape:** Multi-valued. Fill 72.9% (97/133), 90 distinct raw strings.
- **Delimiter guessed:** `;`, newline, `, ... and`
- **Length (chars):** min 4, median 32, max 434
- **Values after parsing:** 126 total, 11 multi-valued cells, max 13 in one cell, mean 1.3 per populated cell
- **Cardinality histogram** (values per cell): `{0: 36, 1: 86, 2: 5, 3: 3, 4: 2, 13: 1}`
- **Entities extracted:** 1 URLs, 24 emails
- **Parse methods used:** `{'single': 86, 'empty': 36, 'newline': 3, 'comma+and (low confidence)': 4, 'semicolon': 4}`

Heterogeneous by kind, not just by count — some cells name individuals, some name a team (`GES DISC User Services`), some give an email only. 24 emails embedded. One cell lists 13 people.

### `description` — Short description (1500 characters) of the dataset being nominated. 

- **Shape:** Single, occasionally per-nominator. Fill 100.0% (133/133), 133 distinct raw strings.
- **Delimiter guessed:** `Nominator N:` (1 cell)
- **Length (chars):** min 58, median 1,100, max 6,786
- **Values after parsing:** 134 total, 1 multi-valued cells, max 2 in one cell, mean 1.01 per populated cell
- **Cardinality histogram** (values per cell): `{1: 132, 2: 1}`
- **Entities extracted:** 79 URLs, 21 DOIs, 1 emails
- **Parse methods used:** `{'single': 132, 'labelled:Nominator N': 1}`

Free text, median 1,100 chars. 79 embedded URLs and 21 DOIs are worth extracting as `schema:citation` links. Several cells open with `From https://…` — copied provenance.

### `justification` — Justification for inclusion in AGU commentary. Why is the nominated dataset impactful “in your own words” or “in your opinion”.
People: education, training, disaster response and prediction
Planet: geophysical phenomena, conservation, climate, environmental indicators
Prosperity: economic good, social equity, humanitarian relief, community resilience

- **Shape:** **Two nested levels of multi-value**. Fill 100.0% (133/133), 132 distinct raw strings.
- **Delimiter guessed:** outer `Nominator N:`; inner `People:` / `Planet:` / `Prosperity:`
- **Length (chars):** min 47, median 2,247, max 15,003
- **Values after parsing:** 161 total, 10 multi-valued cells, max 9 in one cell, mean 1.21 per populated cell
- **Cardinality histogram** (values per cell): `{1: 123, 2: 3, 3: 4, 5: 1, 6: 1, 9: 1}`
- **Entities extracted:** 44 URLs, 22 DOIs
- **Parse methods used:** `{'single': 121, 'labelled:Nominator N': 12, '+labelled:People/Planet/Prosperity': 18}`

The richest structure in the file. 12 rows split by nominator (up to 9 blocks); 18 blocks further subdivide into the three impact dimensions named in the column header itself — a case where the *header* documents the intended sub-schema. Variant spellings `People Dimension:` are handled.

### `interaction` — Short description of how you interact with this dataset.  

- **Shape:** Multi-valued by nominator. Fill 100.0% (133/133), 132 distinct raw strings.
- **Delimiter guessed:** `Nominator N:`
- **Length (chars):** min 45, median 913, max 5,823
- **Values after parsing:** 165 total, 12 multi-valued cells, max 9 in one cell, mean 1.24 per populated cell
- **Cardinality histogram** (values per cell): `{1: 121, 2: 4, 3: 4, 4: 1, 5: 1, 6: 1, 9: 1}`
- **Entities extracted:** 27 URLs, 14 DOIs
- **Parse methods used:** `{'single': 120, 'labelled:Nominator N': 13}`

Same 12 rows and same block numbering as `justification` — they always co-vary.

### `ref_pub` — Reference publication that describes the dataset.

- **Shape:** **Multi-valued citation list**. Fill 80.5% (107/133), 106 distinct raw strings.
- **Delimiter guessed:** blank line (38) > newline (3) > `1.` numbering (2)
- **Length (chars):** min 55, median 296, max 3,573
- **Values after parsing:** 201 total, 43 multi-valued cells, max 11 in one cell, mean 1.88 per populated cell
- **Cardinality histogram** (values per cell): `{0: 26, 1: 64, 2: 20, 3: 13, 4: 3, 5: 2, 6: 3, 7: 1, 11: 1}`
- **Entities extracted:** 181 URLs, 161 DOIs
- **Parse methods used:** `{'empty': 26, 'single': 64, 'blank-line': 38, 'newline': 3, 'numbered': 2}`

43 cells hold more than one citation; max 11. 161 DOIs recoverable. Blank-line splitting is safe here because citations wrap; splitting on every newline would fragment them.

### `reuse` — Examples of how this dataset has been reused, any bibliographies listing instances of reuse, or any references to derived data products/datasets. 

- **Shape:** **Most multi-valued column**. Fill 62.4% (83/133), 83 distinct raw strings.
- **Delimiter guessed:** blank line (40) > numbering (6) > newline (3)
- **Length (chars):** min 34, median 564, max 19,904
- **Values after parsing:** 397 total, 49 multi-valued cells, max 36 in one cell, mean 4.78 per populated cell
- **Cardinality histogram** (values per cell): `{0: 50, 1: 34, 2: 13, 3: 5, 4: 2, 5: 4, 6: 6, 7: 4, 8: 3, 9: 2, 10: 1, 11: 2, 12: 2, 16: 1, 24: 1, 26: 1, 30: 1, 36: 1}`
- **Entities extracted:** 418 URLs, 313 DOIs
- **Parse methods used:** `{'empty': 50, 'single': 34, 'blank-line': 40, 'numbered': 6, 'newline': 3}`

62% filled but 397 extracted items — mean 4.8 per non-empty cell, max 36, longest cell ~20k chars. Some cells use their own sub-headers (`Scientific Publications:`, `Derived Data Products:`, `Educational Resources:`), which is the same header-inside-a-cell pattern as `justification`.

### `nom_name` — Nominator Name

- **Shape:** **Parallel labelled array**. Fill 100.0% (133/133), 123 distinct raw strings.
- **Delimiter guessed:** `Nominator N:`
- **Length (chars):** min 7, median 15, max 246
- **Values after parsing:** 174 total, 15 multi-valued cells, max 9 in one cell, mean 1.31 per populated cell
- **Cardinality histogram** (values per cell): `{1: 118, 2: 4, 3: 5, 4: 2, 5: 2, 6: 1, 9: 1}`
- **Entities extracted:** none
- **Parse methods used:** `{'single': 118, 'labelled:Nominator N': 15}`

13 rows carry explicit `Nominator N:` labels, up to 9 people.

### `email` — Email Address

- **Shape:** **Parallel labelled array**. Fill 100.0% (133/133), 124 distinct raw strings.
- **Delimiter guessed:** `Nominator N:`
- **Length (chars):** min 12, median 23, max 326
- **Values after parsing:** 174 total, 15 multi-valued cells, max 9 in one cell, mean 1.31 per populated cell
- **Cardinality histogram** (values per cell): `{1: 118, 2: 4, 3: 5, 4: 2, 5: 2, 6: 1, 9: 1}`
- **Entities extracted:** 173 emails
- **Parse methods used:** `{'single': 118, 'labelled:Nominator N': 15}`

173 addresses. Labels align perfectly with `nom_name`.

### `orcid` — Nominator ORCID

- **Shape:** **Parallel labelled array**. Fill 97.7% (130/133), 120 distinct raw strings.
- **Delimiter guessed:** `Nominator N:`
- **Length (chars):** min 3, median 37, max 470
- **Values after parsing:** 174 total, 15 multi-valued cells, max 9 in one cell, mean 1.31 per populated cell
- **Cardinality histogram** (values per cell): `{1: 118, 2: 4, 3: 5, 4: 2, 5: 2, 6: 1, 9: 1}`
- **Entities extracted:** 164 URLs, 168 ORCIDs
- **Parse methods used:** `{'single': 115, 'labelled:Nominator N': 15, 'empty': 3}`

168 ORCIDs. 3 rows empty; a few cells hold bare IDs rather than `https://orcid.org/…` URIs. Used as the person `@id` wherever present.

### `affiliation` — Nominator Affiliation or Organization

- **Shape:** **Parallel labelled array**. Fill 100.0% (133/133), 122 distinct raw strings.
- **Delimiter guessed:** `Nominator N:`, plus blank lines for a person's *multiple* affiliations
- **Length (chars):** min 21, median 80, max 961
- **Values after parsing:** 174 total, 15 multi-valued cells, max 9 in one cell, mean 1.31 per populated cell
- **Cardinality histogram** (values per cell): `{1: 118, 2: 4, 3: 5, 4: 2, 5: 2, 6: 1, 9: 1}`
- **Entities extracted:** none
- **Parse methods used:** `{'single': 118, 'labelled:Nominator N': 15}`

A third nesting level: one nominator can list two institutions separated by a blank line inside their own block. 157 distinct organisation strings, unnormalised (raw postal addresses included).

---

## RDF model

Nomination and dataset are kept as **separate resources**, because they are separate things: the dataset exists independently, the nomination is an assertion *about* it by particular people. Merging them would make it impossible to represent two nominations of the same dataset.

```
agu:Nomination ──agu:nominates──▶ dcat:Dataset ──dcat:catalog──▶ dcat:Catalog (repository)
      │                                 │
      ├─agu:nominator─▶ schema:Person   ├─dct:subject──▶ skos:Concept (discipline group)
      │      └─schema:affiliation─▶ schema:Organization
      ├─agu:justification─▶ agu:JustificationStatement
      │      └─agu:impactDimension─▶ agu:ImpactDimension (People|Planet|Prosperity)
      ├─agu:interactionStatement─▶ agu:Statement
      └─prov:wasDerivedFrom─▶ agu:SourceRow  (verbatim original cells)
```

| Decision | Why |
|---|---|
| ORCID URI as the person `@id` | 168 ORCIDs present; gives free deduplication and links out to the global graph. Falls back to a minted `id:person:…` slug. |
| `dcat:` + `schema:` dual typing | `dcat:Dataset` for data-catalogue interop, `schema:Dataset` for search-engine and Google Dataset Search pickup. |
| `agu:CreatorStatement` wrapper, not `schema:Person`, for dataset authors | Author cells are unreliable — some hold a person, some a team, some "Many site PIs (from more than 500 sites)". Asserting `foaf:Person` there would be a false claim. The literal is preserved and typed honestly. |
| Repositories deduplicated by slug | Collapses `Zenodo` and `zenodo.org` into one node, but *not* `GES DISC` vs the full NASA name — see caveats. |
| Every row keeps an `agu:SourceRow` | The parse is heuristic. Provenance means every guess is reversible against the original cell. |
| `skos:ConceptScheme` for disciplines | 8 groups, each carrying its component disciplines as `agu:memberDiscipline`. |

## Caveats — where the guesses are weakest

1. **Comma-split authors (11 cells).** Flagged `comma+and (low confidence)` in the parse methods. `Last, First` and `First Last, First Last` are genuinely ambiguous without a name authority. Review these before trusting author counts.
2. **Repository normalisation is incomplete.** Slug-matching won't merge `GES DISC` with `NASA Goddard Earth Sciences (GES) Data and Information Services Center`. ~111 raw strings → 117 nodes; the true count is nearer 99. A curated crosswalk (or ROR/re3data lookup) would fix this.
3. **Affiliations are raw strings**, postal addresses and all. `Jet Propulsion Laboratory, California Institute of Technology, 4800 Oak Grove Dr., …` and `Jet Propulsion Laboratory, 4800 Oak Grove Drive, Pasadena, CA 91109` become two organisations. ROR reconciliation is the obvious next step.
4. **`repo_name` / `repo_pid` are frequently confused** by submitters — 15 URLs live in the name column.
5. **Reference citations are unparsed strings.** DOIs and URLs are extracted, but author/year/journal are not. Crossref lookup on the 161 DOIs would yield proper `schema:ScholarlyArticle` nodes.
6. **The file contains 173 personal email addresses.** They are in the JSON-LD as `schema:email`. If this graph will be published, strip or hash them first.
