# GitHub Actions workflows

Three manually-triggered workflows. Run them from the **Actions** tab → pick the
workflow → **Run workflow**. Nothing runs on push.

| Workflow | Does | Run it when |
|---|---|---|
| **1 · Build data and statistics** | spreadsheet → schema.org JSON-LD → statistics, diagrams and site | the spreadsheet changed, or the pipeline did |
| **2 · Analyse the data** | how the spreadsheet was interpreted, and what a deploy would change in the live data | before trusting a build, and before proposing one |
| **3 · Preview on this repo's Pages** | publishes `site/` to *this* repository's Pages | you want to see a build on a real URL |
| **4 · Open a pull request on agu-data.github.io** | proposes `site/` as `impactful-datasets/` via a fork | the build is ready to go live |

Workflow 1 used to be two, one for the RDF graph and one for the statistics.
They were merged because the statistics are measured from the published
schema.org file, so they could never run without first producing it. Keeping them
apart only created a way for the reports to describe a file that no longer
existed.

## Workflow 2, before you trust a build

It answers two questions and prints both to the run log, so neither needs a
download.

**How was the spreadsheet interpreted?** Everything upstream of the site involves
inference: which delimiter separates the names in a cell, whether a credited
party is a person or an institution. The guesses are right often enough that
nobody notices the wrong ones unless pointed at them.
`reports/interpretation.md` does the pointing.

**What would change if this went live?** `reports/changes_vs_published.md`
compares the build against the file currently served at data.agu.org, matching
resources on `@id`. It reports meaning rather than text, so reformatting produces
no diff while a renamed dataset or a dropped nomination does. Removals deserve
the closest look: a dataset that disappears takes its published URL with it.

If nothing is published yet, the comparison still succeeds and reports everything
as new, which is the right answer for a first deploy rather than an error.

`person_review.csv` **in `data/cleanup/` is a different file**. That one carries
the reviewer's `DECISION` column and is an input to the build. Workflow 2 writes
only to `reports/`, so running it cannot erase a decision.

## What workflow 1 does, in order

```
scripts/restructure_impactful_datasets.py   spreadsheet   -> RDF working graph
scripts/build_website.py                    working graph -> schema.org JSON-LD + site
scripts/analyze_graph.py                    schema.org    -> statistics + model diagram
scripts/document_schema_model.py            schema.org    -> full model diagram
```

Each step reads the previous one's output, so the order is not a preference.
The statistics come last on purpose: they describe what was actually published
rather than what the pipeline intended.

Every run writes a summary to the Actions page with the dataset, nominator,
nomination and discipline-group counts, a table of datasets per discipline
group, and every class in the file with its instance count.

## The identifier guard

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
