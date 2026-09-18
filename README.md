# Impactful Datasets — data pipeline and site prototype

Turns the AGU *Impactful Datasets* nomination spreadsheet into RDF, reports on the
messiness of the source, and builds the website from the result.

**Setting this up for the first time? Start with [SETUP.md](SETUP.md).** This
file explains what each script does and why the data is modelled the way it is.

Three scripts run in order. Each reads the previous one's output, so the chain is
reproducible from the original CSV with no manual steps in between.

```
Impactful_Datasets_v1_June_16_-_CSV_Format.csv        (source, 133 rows × 16 columns)
        │
        │  1. scripts/restructure_impactful_datasets.py
        ▼
data/output/impactful_datasets.jsonld   the RDF graph, 17,439 triples
column_report.md                 per-column multi-value analysis
column_statistics.json           the same, machine-readable
        │
        ├──── 2. scripts/analyze_graph.py ─────▶  graph_statistics.md
        │                                  graph_statistics.json
        │                                  conceptual_model.svg
        │
        └──── 3. scripts/build_website.py ────▶  index.html
                                           assets/css/*  assets/js/*  assets/img/*
                                           data/impactful_datasets.data.jsonld
```

---

## The site URL

The site is served from **`https://data.agu.org/impactful-datasets/`**. That
address is set in three places, all of them already updated:

| File | What holds it |
|---|---|
| `build_website.py` | the `--base-url` default |
| `.github/workflows/1-build-data-and-statistics.yml` | the `base_url` input default |

Everything else follows. The 133 `mainEntityOfPage` values in
`site/data/impactful_datasets.data.jsonld` are generated from it, and a rebuild
rewrites them all.

Identifiers are unaffected by any of this. They are URNs
(`urn:org:agu:data:impactful-datasets:id:dataset:agu-0004`), deliberately
independent of any host, so moving the site cannot break a permalink. A rebuild
after the change reported `0 new ids minted`.

If the address ever changes again:

```bash
grep -rl "data.agu.org/impactful-datasets" --include="*.py" --include="*.yml" .
# edit those three, then rebuild so the data file follows
mkdir -p build/data && cp site/data/impactful_datasets.data.jsonld build/data/
python scripts/build_website.py impactful_datasets.jsonld \
    --logo assets/AGU_Logo_H_CMYK.png \
    --feature-image assets/story-feature-source.jpg \
    --base-url "https://the-new-address/" -o build
```

Two related settings, both separate from this one:

- **`--data-url`** is where the page *fetches* its data, not where the page
  lives. It stays the relative path `data/impactful_datasets.data.jsonld`, which
  is what makes the site work under a subdirectory. Change it only if the data
  file moves to a different host.
- **Relative asset paths.** Every reference in the built page is relative, so it
  works under any prefix without a base-href — verified by serving it from
  `/impactful-datasets/`. The one consequence is that the URL needs its trailing
  slash; Pages redirects directory URLs to add it, so this only bites in
  hand-written links.

## Proposing changes to data.agu.org

The site is served from `https://data.agu.org/impactful-datasets/`, a directory
inside [`AGU-Data/agu-data.github.io`](https://github.com/AGU-Data/agu-data.github.io)
— a public Jekyll site (type-on-strap) owned by another organisation. This
repository builds the files; a pull request carries them across.

### The constraint that decides the design

**A deploy key cannot open a pull request.** Deploy keys are git transport only;
a pull request is an API call and needs a token. So the real question is which
credential, and each answer implies a different amount of coordination with
AGU-Data:

| Approach | What AGU-Data must do | Credential | Notes |
|---|---|---|---|
| **Fork and propose** *(implemented)* | nothing | classic PAT on a bot account, `public_repo` scope | The ordinary outside-contributor route. Works because their repo is public. |
| GitHub App | org admin installs the app | short-lived installation token | The most sustainable if they will do it: no account to expire, tokens last an hour, permissions are explicit and auditable. |
| Bot as outside collaborator | add the bot with write access | fine-grained PAT | Simplest API-wise, but grants write to their whole repository. |

The fork route is implemented because **coordination that never has to happen
cannot go stale.** Nobody at AGU-Data needs to install, approve or remember
anything, and no permission grant exists that someone might revoke during a
reorganisation. If AGU-Data are willing to install a GitHub App, that is the
better long-term answer and the workflow needs only its token step changed.

### One-time setup

**1. Make a bot account.** A machine account, not a person's — the whole point
is that it survives people changing roles. Give it a name that explains itself,
such as `agu-impactful-datasets-bot`.

**2. Fork the upstream repository** to that account, keeping the name
`agu-data.github.io`.

**3. Make a token.** Signed in as the bot: Settings → Developer settings →
Personal access tokens → **Tokens (classic)** → Generate, with the **`public_repo`**
scope only.

   It has to be a classic token. A fine-grained token can only grant pull-request
   write on repositories its owner administers, and the bot does not administer
   AGU-Data's. Granting a fine-grained token "public repositories (read-only)" is
   not enough to open a pull request — a detail that will otherwise cost an
   afternoon.

**4. Store it here.** Settings → Secrets and variables → Actions → New repository
secret named `AGU_DATA_BOT_TOKEN`.

### Running it

Locally, the same steps the workflow runs:

```bash
pip install -r requirements.txt

# the registry must be in place before the build, or identifiers are reissued
mkdir -p build/data
cp site/data/impactful_datasets.data.jsonld build/data/

# no argument: uses the spreadsheet in data/source/
python scripts/restructure_impactful_datasets.py -o build

python scripts/build_website.py build/impactful_datasets.jsonld \
    --logo assets/AGU_Logo_H_CMYK.png \
    --feature-image assets/story-feature-source.jpg \
    --base-url "https://data.agu.org/impactful-datasets/" -o build

python scripts/analyze_graph.py build/data/impactful_datasets.data.jsonld -o build
python scripts/document_schema_model.py build/data/impactful_datasets.data.jsonld \
    -o build/schema_model.svg
```

The spreadsheet can also come from elsewhere:

```bash
python scripts/restructure_impactful_datasets.py path/to/export.csv -o build
python scripts/restructure_impactful_datasets.py https://example.org/nominations.csv -o build
```

With no argument it takes the single CSV in `data/source/`, found by glob rather
than by name. The exported filename carries a date and changes with every new
export, so a hard-coded default would break the first time the sheet is
re-exported. Two CSVs there and it stops and asks which, rather than guessing.

Watch the `build_website.py` line. It should say **`0 new ids minted`**. Any
other number means the registry was not read, and publishing would break every
existing link.

## The GitHub Actions

Three workflows, all manual. Run them from the **Actions** tab; nothing fires on
push.

### 1 · Build data and statistics

The whole data side in one pass.

```
scripts/restructure_impactful_datasets.py   spreadsheet   → RDF working graph
scripts/build_website.py                    working graph → schema.org JSON-LD + site
scripts/analyze_graph.py                    schema.org    → statistics + model diagram
scripts/document_schema_model.py            schema.org    → full model diagram
```

The order is fixed by what each step reads. The statistics come last on purpose:
they are measured from the published file, so they describe what was actually
published rather than what the pipeline intended. This used to be two workflows,
which only created a way for the reports to describe a file that no longer
existed.

| Input | Default | What it does |
|---|---|---|
| `source_csv` | *(blank)* | a path, an `https://` URL, or blank to use the spreadsheet in `data/source/` |
| `base_url` | `https://data.agu.org/impactful-datasets/` | the address written into the canonical page URLs |
| `allow_new_ids` | off | permits minting identifiers; expected only when datasets are added |
| `commit` | on | commits `site/`, `reports/` and the graph back to the branch |

Writes a summary to the run page: dataset, nominator, nomination and
discipline-group counts, datasets per discipline group, and every class in the
file with its instance count.

It also refuses to finish if identifiers were reissued without `allow_new_ids`.
That guard exists because a rebuild that renumbers datasets breaks every
published URL, silently.

### 2 · Explain how the data was read

Writes `reports/interpretation.md` and `data/cleanup/person_review.csv`, and prints the
whole report to the run log so it can be read without downloading anything.

Run it between building and previewing. Everything upstream of the site involves
inference — which delimiter separates the names in a cell, whether a credited
party is a person or an institution — and the guesses are right often enough that
nobody notices the wrong ones unless pointed at them.

The report covers which columns needed a judgement call (the ones split on a
comma, where `Jochum, Klaus Peter` is one person and `A. Newman, M. Clark` is
two), which columns are sparse, which cells held the most values, and how
confidently each of the 518 credited parties was typed.

It never writes `person_review.csv` at the repository root. That file carries the
reviewer's `DECISION` column and is an input to the build, so running this
workflow cannot erase a decision.

### 3 · Preview on this repo's Pages

Publishes `site/` to *this* repository's Pages as a staging preview. Optional,
and worth a thought before switching on: it puts a second public copy of the
collection at a github.io address, while the data inside it says the canonical
home is `data.agu.org`. Serving locally with `python -m http.server` avoids that.

### 4 · Open a pull request on agu-data.github.io

Proposes `site/` as the `impactful-datasets/` directory of
`AGU-Data/agu-data.github.io`, from a fork, so nobody at AGU-Data has to install
or approve anything. `dry_run` is **on by default**: it assembles the change,
runs its checks and prints the diff without pushing.

Needs the secret `AGU_DATA_BOT_TOKEN`. See [SETUP.md](SETUP.md).

## The scripts

### 1. `restructure_impactful_datasets.py`

Spreadsheet in, RDF out. It can come from four places:

```bash
python scripts/restructure_impactful_datasets.py                    # the CSV in data/source/ — the default
python scripts/restructure_impactful_datasets.py --zenodo           # the Zenodo record, latest version
python scripts/restructure_impactful_datasets.py path/to/file.csv   # a path
python scripts/restructure_impactful_datasets.py https://…/file.csv # any URL
```

The committed CSV is the default, so an ordinary build uses a file that is in the
repository and has been through review rather than whatever a remote record holds
at the moment the job runs. Pulling from Zenodo is a deliberate choice. The
default finds the CSV in `data/source/` by glob rather than by name, since the
export filename carries a date and changes each time the sheet is re-exported.

**Zenodo is where the nominations are published.** The record's concept DOI,
[`10.5281/zenodo.20722709`](https://doi.org/10.5281/zenodo.20722709), always
resolves to its most recent version, so `--zenodo` picks up new nominations with
nothing here to change. A specific version DOI pins a build to one version.

Two things it does on the way:

- **Verifies the checksum.** Zenodo publishes an md5 for every file. A truncated
  download is otherwise a silent corruption, and checking costs nothing.
- **Records where the data came from.** Version DOI, record id, filename,
  checksum and byte count go into `column_statistics.json` and the column report,
  and the workflow puts the version DOI in the commit message.

It deliberately does **not** follow `links.latest` after fetching. Requesting a
concept record already redirects to the newest version, and chasing that link
would silently upgrade a build pinned to an older version DOI, which is the
opposite of what pinning is for.

The real work is guessing where a single spreadsheet cell holds more than one
value, which happens three different ways in this file:

- **delimiter-separated lists** — `;` is reliable; commas are not, since
  `Jochum, Klaus Peter` is one person and `A. J. Newman, M. P. Clark` is two
- **labelled parallel arrays** — four columns use `Nominator 1:` / `Nominator 2:`
  headers *inside* the cell, and block *n* of one column belongs to block *n* of
  the others (verified: the labels agree across all 133 rows)
- **sub-schemas inside a cell** — justifications nest `People:` / `Planet:` /
  `Prosperity:` blocks, the vocabulary named in the column header itself

It also repairs the file's encoding. The source is **not valid UTF-8**: 16 bytes
are Mac Roman, and a plain `pd.read_csv` raises `UnicodeDecodeError` until they
are fixed.

Every row keeps an `agu:SourceRow` node holding the verbatim original cells, so
each heuristic guess can be checked or reversed.

Outputs:

| File | What it is |
|---|---|
| `data/output/impactful_datasets.jsonld` | the full graph — 133 datasets, 161 nominators, 17,310 triples across 23 classes |
| `column_report.md` | per-column analysis: fill rate, cardinality histograms, which delimiter was guessed and why, and where the guesses are weakest |
| `column_statistics.json` | the same figures, for diffing against a future export |
| `_clean.csv` | the encoding-repaired intermediate, kept so you can see what changed |

### 2. `analyze_graph.py`

Reports on the **published** schema.org file, not the intermediate graph. That is
the point: the figures describe what was actually published rather than what the
pipeline intended, and they are measured with SPARQL each time rather than
carried forward.

| File | What it is |
|---|---|
| `graph_statistics.md` | datasets, nominators, nominations and discipline groups; datasets per discipline group; every class with its instance count |
| `graph_statistics.json` | the same, machine-readable |
| `conceptual_model.svg` | the model, with box labels filled from the same queries |

Two counting decisions worth knowing. Nominators are counted once each, so the
nomination total is higher than the nominator total because some people put
forward more than one dataset. And a discipline group with no datasets is listed
with a zero rather than omitted, since saying a group is empty is more useful
than leaving it out.

### 2b. `document_schema_model.py`

Draws `schema_model.svg`: the published schema.org graph, in full. Where
`conceptual_model.svg` is an orientation diagram — nine boxes, the shape of the
thing — this one is reference material. It measures all 13 classes and all 23
property-edge shapes in the data file and labels each connector with the property
that makes it:

```bash
python scripts/document_schema_model.py site/data/impactful_datasets.data.jsonld \
    -o schema_model.svg
```

Both the box counts and the edge labels come from the file, so neither can drift
from the data. If an edge shape measures zero the script says so on stderr rather
than drawing a relationship that no longer exists.

### 3. `build_website.py`

Builds the public data file and the site prototype from the graph.

Emits a static website as ordinary linked assets:

```
index.html                            markup, SEO/OpenGraph metadata, rel=alternate
                                      link to the machine-readable data
assets/css/tokens.css                 design tokens — brand colours, type, logo.
                                      The only file a rebrand needs to touch.
assets/css/site.css                   component styles
assets/js/config.js                   deployment settings (data URL, featured record)
assets/js/app.js                      application script
assets/img/agu-logo.png               brand mark
assets/img/story-feature.jpg          photo for the article callout on page 1
data/impactful_datasets.data.jsonld   the published collection, schema.org JSON-LD
data/cleanup/party_report.csv         every credited party, its assigned type,
                                      the rule that decided it, and a DECISION
                                      column for overriding it
```

`data/impactful_datasets.data.jsonld` is **the published data** — a schema.org
`DataCatalog` of 133 `Dataset` records, valid JSON-LD. Serve it at a stable URL
and anyone can consume it. It is also the id registry; see *Permanent identifiers*.

The page fetches its data over HTTP, so **the site must be served, not opened from
disk**. It says so on screen if the fetch fails. Any static host works:

```bash
cd out && python3 -m http.server
```

Useful flags: `--data-url` (where the page fetches its data once the file has a
permanent home), `--base-url` (host used in `mainEntityOfPage`), `--featured`
(which dataset page 2 opens on), `--logo`.

---

## Things to know

### The short display name is a placeholder

Every dataset in the data file carries an empty **`alternateName`**. That is the
short label shown on the book spines — schema.org's standard term for an
alternative name for the same thing. Fill these in (roughly 24 characters or
fewer fits a spine); the site falls back to `name` while they are blank, so
nothing breaks in the meantime.

### Permanent identifiers

Dataset URLs look like:

```
#/dataset/agu-0004-argo
```

Only `agu-0004` is authoritative. The trailing slug is decoration, ignored when
parsing, so a stale slug still resolves and is then rewritten — the pattern
Stack Overflow and Medium use.

Ids are **minted once and frozen**. Each build reads the ids already published in
the data file and reuses them, keyed on DOI plus title; only genuinely new
datasets get a number. A clean rebuild reports `0 new ids minted`. This is what
lets a URL survive a title edit, a re-sort, or rows being added or withdrawn.

Two rules follow: keep the data file in version control, and never renumber by
hand. Unknown ids fall back to the collection rather than erroring.

If a build ever reports `133 new ids minted` when the registry file exists, stop:
something has changed the shape the registry is read from, and publishing would
break every URL. The build now refuses to continue when a registry file exists but
yields no readable ids — that guard was added after exactly this happened during a
format change.

### The shape of the published data

`data/impactful_datasets.data.jsonld` is a flat JSON-LD graph — a `DataCatalog`,
a `DefinedTermSet` of discipline groups, two property definitions, 133 `Dataset`
nodes, and 133 `ItemList`s holding 174 `EndorseAction`s, all as siblings under
`@graph`.

**Nominations are endorsements.** A nomination is not authorship, so each one is
a `schema.org/EndorseAction` rather than a `creator` or `contributor` link:

```json
{ "@type": "EndorseAction",
  "identifier": { "@type": "PropertyValue", "propertyID": "AGU-Nominator-Slot", "value": "1" },
  "agent":  { "@type": "Person", "@id": "https://orcid.org/0000-...", "name": "..." },
  "object": { "@id": "urn:org:agu:data:impactful-datasets:id:dataset:agu-0004" },
  "description": "how this nominator works with the dataset",
  "result": { "@type": "CreativeWork", "text": "their justification",
              "about": [ { "@type": "DefinedTerm", "name": "People" } ] } }
```

The action points at its dataset with `object`; schema.org has no property for
hanging a *performed* action off the thing acted on, which is why the graph is
flat rather than nested. The interaction statement sits on the action, not the
agent: the same person can nominate several datasets and agent nodes share an
ORCID `@id`, so a description there would merge across datasets.

**Ordering is explicit.** A graph is unordered, so the two sequences that matter
are declared `"@container": "@list"` in the context — `dataset` on the catalog
(collection display order) and `itemListElement` (nominator order within a
dataset). Both parse as genuine `rdf:List`s.

**Counts are never stored.** Nominator, citation and reuse totals are derived by
measuring the lists at load time. A stored count drifts from the list it
describes; this pipeline has already shipped that bug once.

### Discipline vocabulary

The nine discipline groups are published as a schema.org `DefinedTermSet` under
`agu:themes`. Each `DefinedTerm` carries the short key as its `identifier` and the
full label as its `name`. Datasets reference the term by `@id` through `keywords`,
so the label is stated once and never repeated per dataset. A group can hold more
than one keyword: one dataset was nominated under two disciplines and appears
under both.

Labels are never retyped in the site builder — they are read from the RDF graph,
which carries them verbatim from the spreadsheet. Corrections to the source
wording live in `DISCIPLINE_FIXES` in `restructure_impactful_datasets.py`, and the
verbatim original survives on the `agu:SourceRow` node.

Note: schema.org has no singular `keyword` property — `keywords` is the correct
term, and it accepts a `DefinedTerm`, which is exactly this pattern.

### agu:ResponsibleParty

One class is declared: `agu:ResponsibleParty`, a subclass of `prov:Agent`. It
covers whoever answers for a dataset — an individual, an institution, a standing
team or a service desk — and exists mainly for parties that cannot honestly be
resolved to either `schema:Person` or `schema:Organization`. Typing a science
working group as `ResponsibleParty` records what is known; typing it `Person`
guesses wrong.

Subsumption is asserted only in the direction that is AGU's to assert. The file
does **not** say `schema:Person rdfs:subClassOf agu:ResponsibleParty`: that is a
global claim, and once graphs are merged it makes every `schema:Person` anywhere
an AGU responsible party. Tested with an RDFS reasoner — an unrelated novelist and
bakery in a merged graph get pulled in under that assertion, and are untouched
without it. `prov:Agent` supplies the shared supertype instead, since it already
means a party that bears responsibility.

Two `skos:narrowMatch` pointers to `schema:Person` and `schema:Organization`
record which classes a responsible party will usually turn out to be. The
relation runs that way because this concept is the broader one: it also covers
the teams, working groups and service desks that are neither. They are
documentation, not logic — SKOS mapping relations carry no entailment, so the
pointers describe the relationship without asserting anything about anybody
else's data. Verified: a foreign `schema:Person` is untouched after reasoning,
while `ResponsibleParty` instances still infer as `prov:Agent`.

Nothing is typed `ResponsibleParty` yet. See `person_review.csv` and
`review_person_types.py`: 191 entities currently typed `Person` are flagged, of
which 82 look like organisations, 62 hold several entities in one string, and 43
are parse artifacts rather than entities at all. That review is unresolved.

### How a credited party gets its type

Every person or body credited on a nomination is typed `schema:Person`,
`schema:Organization` or `agu:ResponsibleParty`. The source makes this harder than
it sounds: nominators come through a structured form with an ORCID field, but
creators and curators are free text, and a single cell may hold an individual, an
institution, a standing team, several people, or a fragment of a sentence.

The guiding principle is **assert only what the evidence supports**. Where the
evidence is weak, `agu:ResponsibleParty` is the honest answer — it says the party
is responsible for the dataset without claiming to know whether it is a human.
Guessing `Person` would be a stronger claim than the data can carry.

Decisions are made in one function, `party()` in `build_website.py`. Each branch
carries an inline `# RULE Rn` marker, and the `PARTY_RULES` table just above it
maps each id to its reason and confidence. Every build writes `party_report.csv`,
one row per distinct name, with the rule that decided it — so any row in the
report can be traced to the line of code that produced it.

| Rule | Condition | Type | Confidence | Rows |
|---|---|---|---|---|
| R1 | an ORCID was supplied | Person | high | 155 |
| R2 | agent of an `EndorseAction` | Person | medium | 6 |
| R3 | a reviewer filled the `DECISION` cell | as decided | high | 0 |
| R4 | named exception, ruled by hand | Person | high | 1 |
| R5 | worksheet: organisation, high confidence | Organization | high | 42 |
| R6 | worksheet: organisation, medium confidence | ResponsibleParty | medium | 35 |
| R7 | worksheet: organisation, low confidence | Person | low | 5 |
| R8 | worksheet: uncertain | ResponsibleParty | low | 3 |
| R9 | worksheet: not an entity | ResponsibleParty | low | 43 |
| R10 | worksheet: several entities in one string | ResponsibleParty | medium | 62 |
| R11 | no ORCID, not reviewed | ResponsibleParty | low | 166 |

Why some of these are shaped the way they are:

**R1 — an ORCID settles it.** An ORCID is issued to an individual researcher, so
its presence is direct evidence of personhood. Nothing else in the data is that
strong.

**R2 — the role can stand in for the identifier.** The nomination form asks for
one person's name, email, ORCID and affiliation, so the agent of an endorsement is
a person by construction; a blank ORCID means only that they did not supply one.
Without this rule, six named researchers who left the field empty would be demoted
to `ResponsibleParty`. The worksheet keeps a veto in case a future export puts an
institution in that field — it flags none of the current 161.

**R6 vs R5 — confidence changes the claim, not just the label.** A high-confidence
organisation becomes an `Organization`. A medium-confidence one becomes a
`ResponsibleParty`, because the evidence justifies "this is a responsible party"
but not "this is an institution". The type follows the strength of the evidence.

**R9 and R10 cannot be fixed by typing.** These rows are upstream parsing
failures: one cell holding several entities, or a sentence captured as a name.
Retyping them would put a formal class on something that is not an entity. They
are typed `ResponsibleParty` to keep the graph honest and flagged for repair in
`restructure_impactful_datasets.py`, which is where the parse went wrong.

**R11 is the default, and it is deliberately cautious.** A name with no ORCID and
no review has nothing behind it but a string. `ResponsibleParty` records that.

**R3 is the escape hatch.** Fill `DECISION` in `person_review.csv` or
`party_report.csv` with `person`, `organization` or `responsibleparty` and it
overrides every heuristic at high confidence. No rows use it yet, so nothing in
the current output is human-ruled.

Two smaller mechanics. A nominator who also created or curates the dataset they
nominated is reconciled to a single node keyed on their ORCID — the match is
confined to the same record, since an exact name match across the collection would
be far weaker evidence and names like "Yuan Li" recur. And node ids follow the
assigned type, so a party minted as an organisation gets an `…:id:organization:`
urn rather than a person one.

Current distribution: 167 `Person` (156 high confidence), 42 `Organization` (all
high), 309 `ResponsibleParty` (97 medium, 212 low). The 97 medium rows are the
best place to start a review.

### The two AGU properties, and why they are not aliased

Two keys stay in the AGU namespace: `agu:curator` and `agu:reuseExample`. Both are
declared as `rdf:Property` nodes in the graph, each carrying an `rdfs:comment`
that states precisely what AGU means by it, and an `owl:equivalentProperty` link
to its schema.org counterpart — `maintainer` and `subjectOf` respectively.

It is tempting to skip that and alias the keys directly in the context:

```json
"agu:curator": { "@id": "https://schema.org/maintainer" }     // DO NOT DO THIS
```

**That is invalid JSON-LD 1.1 and a conforming processor rejects the entire
document**, not just the term. The spec requires a term whose name is in
compact-IRI form to expand to the same IRI its prefix would give. `rdflib` accepts
it silently, which makes the mistake easy to ship; `pyld` refuses it with
`invalid IRI mapping`. Validate with a conforming processor before trusting a
context change:

```bash
python -c "from pyld import jsonld, json; jsonld.expand(json.load(open('out/data/impactful_datasets.data.jsonld')))"
```

The same rule blocks putting an `rdfs:comment` *inside* a term definition — only
JSON-LD keywords are allowed there. Hence the property nodes, where the
documentation is an ordinary triple any consumer can read.

Consumers wanting pure schema.org can apply the equivalence in three lines; it
yields 126 `maintainer` and 397 `subjectOf` triples:

```python
for p, q in g.subject_objects(OWL.equivalentProperty):
    for s, _, o in g.triples((None, p, None)):
        g.add((s, q, o))
```

### Namespaces

```
terms   urn:org:agu:data:ns:{term}
ids     urn:org:agu:data:impactful-datasets:id:{type}:{local}
```

`{type}` is `dataset`, `person`, `organization`, `nomination`, `repository`,
`theme`, `sourcerow`, `scheme` or `collection`. URNs are location-independent, so
identifiers survive the site moving; the resolvable web address travels alongside
on `schema.org/mainEntityOfPage`. People with an ORCID keep the ORCID URI as their
`@id` — a real global identifier beats a minted local one.

### Two live API calls on the dataset page

Both are called from the browser, both degrade gracefully:

- **DataCite** (`api.datacite.org`) — authors, publisher, year, related works.
  Shown only when the registry answers, so nothing is ever attributed to DataCite
  unless it came from DataCite. Appears for the 37 of 133 datasets with a DOI.
- **DOI Citation Formatter** (`citation.doi.org`, APA / en-US) — behind the
  "Cite this dataset" button. Falls back to showing the DOI if unreachable.
  *This endpoint has not been verified from a browser; check CORS before relying
  on it in a demo.*

### Credit

The footer shows the Harbor Light Technologies mark and "Designed and built by
Harbor Light Technologies". Hovering or tabbing to it opens a card with Adam
Shepherd's name, role, site, email and ORCID.

The card holds real links, so the trigger is not itself a link — an anchor inside
an anchor is invalid and unreachable by keyboard. It is a focusable element and
the card opens on `:hover` or `:focus-within`, which keeps it usable without a
mouse and lets the pointer travel into the card to click through.

The same attribution is recorded in the published data as `creator` on the
catalog, identified by ORCID exactly as the nominators are, so the credit
resolves and deduplicates against the wider graph instead of being a bare string.

The mark is **linked from harborlight.tech by default**, which costs a
third-party request on every page load. Since the page is served from AGU's
site, self-hosting is the better manner — put the file anywhere and pass:

```bash
--credit-logo path/to/harbor-light-logo.png
```

The build downscales it to 120px and writes `assets/img/harbor-light.png`,
exactly as it does the AGU logo, and prints which of the two it used.

The wording is "Designed and built by" rather than "Site by", because the work is
more than the page: the RDF model, the schema.org mapping and the identifier
scheme are the larger part of it. It is one string in `build_website.py` if you
want it read differently.

The build stamp that used to sit in the footer is now an HTML comment at the end
of the page. It is still there for checking which build you are looking at when
caching lies — view source — but it is not something a visitor should see.

### Known data-quality gaps

These are properties of the nominations, not bugs to fix in code:

- 37 of 133 datasets carry a DOI, so the DataCite panel and cite button appear on
  about a quarter of pages
- 107 of 133 have reference publications
- repository names are unnormalised — `Zenodo` and `zenodo.org` merge, but
  `GES DISC` and its full NASA name do not, so 117 nodes represent roughly 99 real
  repositories
- affiliations are raw strings including postal addresses, so one institution can
  appear several times
- ~15 rows put a URL in the repository *name* column
- the data contains 173 personal email addresses — strip or hash them before
  publishing anything derived from the full graph