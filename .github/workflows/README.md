# GitHub Actions workflows

Three manually-triggered workflows. Run them from the **Actions** tab → pick the
workflow → **Run workflow**. Nothing runs on push.

| Workflow | Does | Run it when |
|---|---|---|
| **1 · Build data and statistics** | spreadsheet → schema.org JSON-LD → statistics, diagrams and site | the spreadsheet changed, or the pipeline did |
| **2 · Preview on this repo's Pages** | publishes `site/` to *this* repository's Pages | you want to see a build on a real URL |
| **3 · Open a pull request on agu-data.github.io** | proposes `site/` as `impactful-datasets/` via a fork | the build is ready to go live |

Workflow 1 used to be two, one for the RDF graph and one for the statistics.
They were merged because the statistics are measured from the published
schema.org file, so they could never run without first producing it. Keeping them
apart only created a way for the reports to describe a file that no longer
existed.

## What workflow 1 does, in order

```
restructure_impactful_datasets.py   spreadsheet  -> RDF working graph
build_website.py                    working graph -> schema.org JSON-LD + site
analyze_graph.py                    schema.org    -> statistics + model diagram
document_schema_model.py            schema.org    -> full model diagram
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

## Expected repository layout

```
.github/workflows/      these files
restructure_impactful_datasets.py
build_website.py
analyze_graph.py
document_schema_model.py
review_person_types.py
requirements.txt        pandas, rdflib, pillow
person_review.csv       reviewed party classifications; DECISION overrides
assets/                 AGU_Logo_H_CMYK.png, story-feature-source.jpg
data/source/            the nomination spreadsheet
impactful_datasets.jsonld    written by workflow 1
site/                        written by workflow 1, published by 2 and 3
reports/                     written by workflow 1
```

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
