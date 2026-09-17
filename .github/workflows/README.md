# GitHub Actions workflows

Run them from the **Actions** tab → pick the workflow → **Run workflow**. 

| Workflow | Does | Run it when |
|---|---|---|
| **1 · Build data and statistics** | spreadsheet → schema.org JSON-LD → statistics, diagrams and site | the spreadsheet changed, or the pipeline did |
| **2 · Explain how the data was read** | writes and prints a plain-language account of how the spreadsheet was interpreted | before trusting a build, or before showing it to anyone |
| **3 · Preview on this repo's Pages** | publishes `site/` to *this* repository's Pages | you want to see a build on a real URL |
| **4 · Open a pull request on agu-data.github.io** | proposes `site/` as `impactful-datasets/` via a fork | the build is ready to go live |

Workflow 1 used to be two, one for the RDF graph and one for the statistics.
They were merged because the statistics are measured from the published
schema.org file, so they could never run without first producing it. Keeping them
apart only created a way for the reports to describe a file that no longer
existed.

## Reading workflow 2 before you trust a build
 
Everything upstream of the site involves inference: which delimiter separates the
names in a cell, whether a credited party is a person or an institution. The
guesses are right often enough that nobody notices the wrong ones unless pointed
at them. Workflow 2 does the pointing, and prints the whole report to the run log
so it can be read without downloading anything.
 
It writes two files to `reports/`:
 
- `interpretation.md` — which columns needed a judgement call, which are sparse,
  which cells held the most values, and how confidently each credited party was
  typed
- `person_review.csv` — the underlying row-by-row reasoning
`person_review.csv` **at the repository root is a different file**. That one
carries the reviewer's `DECISION` column and is an input to the build. Workflow 2
never writes it, so running the workflow cannot erase a decision.

## What workflow 1 does, in order

```
restructure_impactful_datasets.py   spreadsheet  -> RDF working graph
build_website.py                    working graph -> schema.org JSON-LD + site
analyze_graph.py                    schema.org    -> statistics + model diagram
document_schema_model.py            schema.org    -> full model diagram
```

Each step reads the previous one's output. The statistics describe what was 
actually published.

## Dataset Identifiers

`site/data/impactful_datasets.data.jsonld` is the published data **and** the
identifier registry. Workflow 1 seeds it into the build directory first, then
fails the job if any identifier was minted without `allow_new_ids` set.

Without that seeding a run reports `133 new ids minted`, renumbers every dataset
and breaks every published link. When you genuinely add datasets, re-run with
`allow_new_ids` and check the count matches the number added.

## Inputs

Workflow 1 builds from the CSV committed in `data/source/` by default, so a run
uses a file that is in the repository and has been reviewed.

Setting `source` to `zenodo` builds from the nominations record instead. Its
concept DOI [`10.5281/zenodo.20722709`](https://doi.org/10.5281/zenodo.20722709)
always resolves to the newest version, so once new nominations are published as a
new version of that record, that is how they reach the site. `custom` takes a
path, a URL or a specific version DOI in `source_ref`.

All three take a `commit` or `dry_run` toggle. Workflow 3 has `dry_run` **on by
default**: it assembles the change, runs its safety checks and prints the diff
without pushing.

Workflow 1 also takes `base_url`, the address the site is served from, which is
written into the canonical page URLs in the data file.

## Publishing to data.agu.org

Workflow 3 needs a bot account with a fork of `AGU-Data/agu-data.github.io` and a
**classic** personal access token with the `public_repo` scope, stored as the
secret `AGU_DATA_BOT_TOKEN`. See `SETUP.md` for why a fine-grained token cannot
work.
