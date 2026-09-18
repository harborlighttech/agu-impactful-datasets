# AGU Impactful Datasets

Turns the AGU *Impactful Datasets* nomination spreadsheet into a schema.org
knowledge graph and the website that presents it, published at
**[data.agu.org/impactful-datasets](https://data.agu.org/impactful-datasets/)**.

The published data is standard schema.org vocabulary that anyone can fetch and
reuse: a `DataCatalog` of `Dataset` records, each carrying the nominators who put
it forward and the case they made for it.

Figures throughout this file are deliberately absent. The nominations change, so
current counts live in [`reports/graph_statistics.md`](reports/graph_statistics.md),
regenerated on every build.

Setting this up for the first time? **[SETUP.md](SETUP.md)** is the path from an
empty repository to a live site. This file explains what everything is.

---

## How it fits together

Four workflows, run by hand from the **Actions** tab. Nothing fires on push.

```
data/source/*.csv                    the nominations, as exported
        │
        │  1 · Build the graph and cleanup worksheets
        ▼
data/output/impactful_datasets.jsonld        the RDF graph
data/cleanup/responsible_party.csv           ← you edit this
        │
        │  2 · Build the JSON-LD and report the changes
        ▼
data/output/impactful_datasets.data.jsonld   the published data, and the id registry
reports/changes_vs_published.md              what a visitor would notice
        │
        │  3 · Build the site
        ▼
site/                                        the website
        │
        │  4 · Open a pull request on agu-data.github.io
        ▼
data.agu.org/impactful-datasets/
```

Each step is separate because each has a moment where a human might want to
intervene: after step 1 to correct how parties were read, after step 2 to check
what would change, after step 3 to look at the site before proposing it.

---

## The workflows

### 1 · Build the graph and cleanup worksheets

Reads the spreadsheet, writes the RDF graph, and prepares the two worksheets in
`data/cleanup/`.

| Input | Default | What it does |
|---|---|---|
| `source` | `data/source` | `data/source` uses the committed CSV; `zenodo` fetches the record's latest version; `custom` takes whatever is in `source_ref` |
| `source_ref` | *(blank)* | a path, an `https://` URL, or a Zenodo DOI, used only when `source` is `custom` |
| `commit` | on | commit the graph, worksheets and column reports back to the branch |

The committed CSV is the default so an ordinary build uses a file that is in the
repository and has been reviewed, rather than whatever a remote record holds at
the moment the job runs.

**Re-running never destroys a decision.** Existing `DECISION` cells are carried
across, and the run reports how many were kept plus any that no longer match a
party.

### 2 · Build the JSON-LD and report the changes

Applies the reviewer's decisions and writes the published schema.org data, then
reports what a deploy would change.

| Input | Default | What it does |
|---|---|---|
| `published` | the live data URL | fetched **only** as the comparison baseline; blank skips the comparison |
| `base_url` | `https://data.agu.org/impactful-datasets/` | written into the canonical page URLs in the data |
| `allow_new_ids` | off | permits minting identifiers; expected only when datasets are added |
| `commit` | on | commit the data file and reports |

Two things this step protects.

**Identifiers.** `data/output/impactful_datasets.data.jsonld` is the registry:
the record of which dataset holds which id. The build reads it and reuses what it
finds. If any id is minted without `allow_new_ids`, the job fails, because a
rebuild that renumbers datasets breaks every published URL and nothing else would
say so.

The registry is the file in this repository, not the live site. Those are
different questions — what ids we have assigned, versus what visitors can
currently see — and conflating them would mean a failed deploy or a stale cache
could silently reassign identifiers.

**Visibility.** `reports/changes_vs_published.md` compares the build against the
live file, matching resources on `@id`. It reports meaning rather than text, so
reformatting produces no diff while a renamed dataset or a dropped nomination
does. Removals get the closest look: a dataset that disappears takes its
published URL with it.

### 3 · Build the site

Renders the website into `site/`, and publishes it to this repository's own
GitHub Pages so it can be opened in a browser before anyone proposes it to AGU.
The URL is printed at the end of the run, with links straight to the collection,
a dataset page and the data file.

| Input | Default | What it does |
|---|---|---|
| `base_url` | `https://data.agu.org/impactful-datasets/` | the address the site is served from |
| `featured` | `Argo` | the dataset shown if someone lands on the detail page cold |
| `commit` | on | commit `site/` back to the branch |
| `deploy_preview` | on | publish to this repository's Pages |

Needs one-time setup: **Settings → Pages → Source → "GitHub Actions"**.

The site is built from `data/output/impactful_datasets.data.jsonld`, not from the
RDF graph. The page fetches that same file in the browser, so building the markup
from it means the two cannot describe different collections. A site built either
way is byte-identical; this removes the possibility of them drifting.

This step mints nothing, so it has no identifier guard. It checks instead that
the data file shipped into `site/data/` is exactly the one step 2 published.

**The preview is not the live site.** It is a second public copy of the
collection at a github.io address, while the data inside it names data.agu.org as
its home — so left alone, a search engine would index both with nothing to say
which is authoritative. The deployed copy therefore carries a `robots.txt` asking
crawlers to stay out. That file is written into the deployment only, never into
`site/`, because the real site should be indexed. Everything else in the preview
is byte-identical to what step 4 proposes, which is the point of previewing it.

### 4 · Open a pull request on agu-data.github.io

Proposes `site/` as the `impactful-datasets/` directory of
`AGU-Data/agu-data.github.io`, from a fork.

| Input | Default |
|---|---|
| `upstream` | `AGU-Data/agu-data.github.io` |
| `fork` | `agu-impactful-datasets-bot/agu-data.github.io` |
| `target_path` | `impactful-datasets` |
| `base_branch` | `main` |
| `work_branch` | `impactful-datasets` |
| `dry_run` | **on** |

`dry_run` is on by default: it clones, assembles the change, runs its checks and
prints the diff without pushing.

That repository belongs to another organisation and is a Jekyll site, so this
workflow is built to fail rather than guess:

- **One directory.** The tree is emptied and rewritten beneath `target_path` and
  nowhere else, and the staged diff is checked before pushing. One path outside
  it and the job stops.
- **No `.nojekyll`.** Harmless on a plain Pages deploy; at the root of a Jekyll
  site it disables the build for every page they have.
- **Rebuilt from upstream each run,** so the pull request contains only our files
  even when their site has moved on.
- **Branches under review are never force-pushed,** which would dismiss stale
  approvals and destroy the "changes since your last review" diff.

It needs a bot account with a fork and a **classic** token carrying the
`public_repo` scope, stored as the secret `AGU_DATA_BOT_TOKEN`. See
[SETUP.md](SETUP.md) for why a fine-grained token cannot work.

---

## The code

All in `scripts/`. Four libraries: pandas, rdflib, pillow — see
`requirements.txt`.

### `restructure_impactful_datasets.py`

Spreadsheet in, RDF graph out. Also writes the column reports.

The real work is guessing where one spreadsheet cell holds more than one value,
which happens three different ways in this file: lists separated by semicolons or
newlines, labelled blocks (`Nominator 1:`, `Nominator 2:`) spread across four
parallel columns, and sub-schemas the form itself suggested (`People:`,
`Planet:`, `Prosperity:`) written inside the justification text.

Every guess is recorded rather than assumed. Each nomination keeps an
`agu:SourceRow` node holding its verbatim cells, so any parsed value can be
checked against what was actually typed.

It also repairs the file's encoding. The export has not been valid UTF-8: a
handful of bytes are Mac Roman, and without repair the file cannot be opened at
all. The count of repairs is reported on every run, and a change in it means the
source encoding has changed.

The source can be a path, an `https://` URL, a Zenodo DOI, or omitted — in which
case it takes the single CSV in `data/source/`, found by glob rather than by
name, because the export filename carries a date and changes every time.

### `prepare_cleanup.py`

RDF graph in, `data/cleanup/responsible_party.csv` out.

It runs before the published data is built, which is the point: the decisions it
collects are an input to that build, so they have to exist first and survive
being regenerated. Existing `DECISION` cells are carried across by party name,
and any that no longer match a party are reported rather than dropped in silence.

### `party_typing.py`

The rules deciding whether a credited party is a `Person`, an `Organization` or
an `agu:ResponsibleParty`. Shared, so they exist in one place: both
`prepare_cleanup.py` and `build_website.py` import them, and two copies would
drift until the worksheet stopped describing the build it explains.

### `build_website.py`

Two modes.

With the RDF graph and `--data-only`, it writes the published schema.org data —
this is step 2. With `--from-data` and that published file, it renders the
website — this is step 3. The identifier registry logic lives here.

### `analyze_graph.py`

The published data in; statistics and the conceptual model diagram out. It reads
the schema.org file rather than the RDF graph deliberately: the figures should
describe what was actually published, not what the pipeline intended.

### `document_schema_model.py`

Draws `reports/schema_model.svg`: every class and property in the published
graph, with counts, measured from the file itself.

### `compare_to_published.py`

Compares a build against the live file, matching resources on `@id` and reporting
them as added, removed or changed. If nothing is published yet it reports
everything as new, which is correct for a first deploy rather than an error.

---

## The data

### `data/source/Impactful_Datasets_v1_June_16_-_CSV_Format.csv`

The nominations as exported: one row per nomination, sixteen columns. The
original, untouched. Nominations are also published as a Zenodo record whose
concept DOI [`10.5281/zenodo.20722709`](https://doi.org/10.5281/zenodo.20722709)
always resolves to the most recent version.

### `data/output/impactful_datasets.jsonld`

The RDF graph: the spreadsheet restructured, with provenance. A working
intermediate — rich, verbose, and not what anyone consumes.

### `data/output/impactful_datasets.data.jsonld`

**The published data, and the identifier registry.** A schema.org `DataCatalog`
of `Dataset` records, using only standard vocabulary.

It is also the record of which dataset holds which identifier. Step 2 reads it to
keep every dataset URL stable across rebuilds. **Keep it in version control.**
Delete it and the next build renumbers every dataset, breaking every link anyone
has shared.

### `site/data/impactful_datasets.data.jsonld`

The same file, shipped beside the page. The site fetches it over HTTP at load, so
it has to travel with the markup. Step 3 checks the two match.

---

## The reports

Everything in `reports/` is generated. None of it is an input.

| File | What it reports |
|---|---|
| `column_report.md` | how each spreadsheet column was read: fill rate, how many cells held several values, which separator was inferred, and which splits were low-confidence |
| `column_statistics.json` | the same, machine-readable, plus the source provenance — for a Zenodo build, the exact version DOI the data came from |
| `graph_statistics.md` | datasets, nominators, nominations and discipline groups; datasets per discipline group; every class with its instance count |
| `graph_statistics.json` | the same, machine-readable |
| `conceptual_model.svg` | the model at a glance: nine boxes and the properties joining them |
| `schema_model.svg` | the full model: every class and property in the published graph, with counts |
| `changes_vs_published.md` | what a deploy would change, as added, removed and changed resources |

Two conventions worth understanding. **Nominators are counted once each**, so
the number of nominations exceeds the number of nominators — some people put
forward more than one dataset. And **a discipline group with no datasets is
listed with a zero** rather than omitted, because a group being empty is
information.

---

## The cleanup files, and how to change the published data

`data/cleanup/responsible_party.csv` is where you correct how the pipeline read
the nominations. It is the only file a human is expected to edit.

### Why it exists

The creator and curator columns are free text. Sometimes they name a person,
sometimes an institution, sometimes a standing working group or a service desk,
sometimes several at once. Typing all of them `schema:Person` would claim more
than the data supports, so parties resolve three ways:

- `schema:Person` where there is an ORCID, or the party is a nominator
- `schema:Organization` where the evidence is strong
- `agu:ResponsibleParty` where it genuinely is not clear — a subclass of
  `prov:Agent` that says the party is responsible for the dataset without
  claiming to know which kind of thing it is

The split between the three is reported in
[`data/cleanup/responsible_party.csv`](data/cleanup/responsible_party.csv) after
every build.

### `responsible_party.csv`

One row per credited party: how it was typed, the evidence, and your decision.

| Column | Meaning |
|---|---|
| `assigned_type` | `Person`, `Organization` or `agu:ResponsibleParty` |
| `name` | the party as written in the spreadsheet |
| `needs_review` | `yes` if something about the name looked wrong; `defaulted` if nothing was known and it fell to the default; blank if settled |
| `rule` | which rule decided it, `R1` to `R11` |
| `why` | that rule in words |
| `assertion_confidence` | confidence in the claim actually made |
| `flag_confidence` | how strongly the name reads as institutional |
| `suggested_kind` | what it looks like: organisation, team, several people in one string, not an entity at all |
| `suggested_action` | `Organization`, `split first`, `re-parse or drop`, `review`, `leave as Person` |
| `evidence_score`, `evidence` | the organisation words, acronyms and name shapes matched |
| `roles`, `occurrences`, `orcid`, `example_datasets` | context |
| **`DECISION`** | **yours to fill in** |
| **`CORRECTED_NAME`** | **yours to fill in** |

Rows are sorted so the ones wanting attention come first: flagged, then
defaulted, then settled.

**To change how a party is typed**, put one of these in `DECISION`:

```
person              →  schema:Person
organization        →  schema:Organization
responsibleparty    →  agu:ResponsibleParty
```

Then run **2 · Build the JSON-LD**. Your ruling overrides every heuristic, and
comes back in the next rebuild as rule `R3` at high confidence. Re-running step 1
never erases it: decisions are carried across by name, and any that no longer
match a party are reported rather than dropped in silence.

Two things a decision cannot fix. Rows marked `split first` hold several entities
in one string — a person and their institution together, say — and need splitting
in the source spreadsheet, not reclassifying. Rows marked `re-parse or drop` are
not entities at all: a sentence that landed in a name field. Giving those a formal
type would be worse than leaving them.

**Why two confidence columns.** They answer different questions and often
disagree: a name can look strongly institutional while the claim finally made
about it is weak. This was once two files that each called their own column
`confidence`, and they contradicted each other on most shared rows. The file a
reviewer edited also held only the flagged parties, hiding those typed
`ResponsibleParty` purely because nothing was known about them — which is exactly
where a human can help. Hence one file, two clearly named columns, and a
`needs_review` value that distinguishes *suspicious* from *unknown*.

### The rules

| Rule | Condition | Type | Confidence |
|---|---|---|---|
| R1 | an ORCID was supplied | Person | high |
| R2 | agent of a nomination | Person | medium |
| R3 | **your `DECISION`** | as decided | high |
| R4 | named exception, ruled by hand | Person | high |
| R5 | worksheet: organisation, high confidence | Organization | high |
| R6 | worksheet: organisation, medium confidence | ResponsibleParty | medium |
| R7 | worksheet: organisation, low confidence | Person | low |
| R8 | worksheet: uncertain | ResponsibleParty | low |
| R9 | worksheet: not an entity | ResponsibleParty | low |
| R10 | worksheet: several entities in one string | ResponsibleParty | medium |
| R11 | no ORCID, not reviewed | ResponsibleParty | low |

The principle throughout is to assert only what the evidence supports. R6 is the
clearest case: a medium-confidence organisation becomes a `ResponsibleParty`
rather than an `Organization`, because the evidence justifies "this is a
responsible party" but not "this is an institution".

---

## The rest

| Path | What it is |
|---|---|
| `assets/` | build inputs at full resolution: the AGU logo and the photo for the article callout. Both are downscaled at build time. |
| `site/` | the built website: markup, styles, script, images and the data file. What step 4 proposes. |
| `requirements.txt` | pandas, rdflib, pillow |
| `docs/` | writing about the project, not part of the pipeline |
| `.gitignore` | ignores `build/`, the scratch directory everything is written to first |

---

## Things worth knowing

**Identifiers are URNs.** `urn:org:agu:data:impactful-datasets:id:dataset:agu-0004`
does not encode where the dataset lives, so the site can move without breaking a
permalink. It already has, twice.

**Counts are never stored.** Nominator, citation and reuse totals are derived by
measuring the lists at load time. A stored count drifts from the list it
describes; this pipeline shipped that bug once and then removed the category.

**The short display name is unset.** Every dataset carries an empty
`alternateName`, intended as the short name on the book spines. The site falls
back to the full title until they are filled in.

**Two live API calls.** Dataset pages with a DOI call DataCite for registry
metadata and the DOI Citation Formatter for a formatted citation. Both fail
quietly: if the call does not answer, the panel is hidden rather than showing
something wrong.

**Known gaps in the source.** Not every dataset has a DOI, and reuse examples and
repository identifiers are filled on well under half the rows. Only a minority of
nominations used the People/Planet/Prosperity framing the form suggested, which
is why the site states that coverage on the page rather than implying the tags
are comprehensive. Current fill rates are in
[`reports/column_report.md`](reports/column_report.md).
