# GitHub Actions workflows

Four manually-triggered workflows. Run them from the **Actions** tab → pick the
workflow → **Run workflow**. None of them run automatically; nothing here is
triggered by a push.

| Workflow | Does | Run it when |
|---|---|---|
| **0 · Full pipeline** | all three steps in one job | a new spreadsheet export arrives |
| **1 · Rebuild RDF graph** | CSV → `impactful_datasets.jsonld` + column report | the source CSV changed |
| **2 · Graph statistics** | graph → statistics + conceptual model | you want the reports refreshed |
| **3 · Build site** | graph → published data file + static site | the site or the party rules changed |
| **4 · Preview on this repo's Pages** | publishes `site/` to *this* repository's Pages as a staging preview | you want to see a build on a real URL |
| **5 · Open a pull request on agu-data.github.io** | proposes `site/` as `impactful-datasets/` via a fork | the built site is ready to go live |

Step 2 is optional: it only produces reporting, and step 3 does not depend on it.
Steps 1 and 3 are required, in that order. Deployment is deliberately separate
from the build, so a rebuild can be inspected before anything goes live.

GitHub Pages needs one-time setup: **Settings → Pages → Source → "GitHub
Actions"**. The site is served from `site/`, including `site/data/`, because the
page fetches its data over HTTP and will not work from a `file://` path.

## Expected repository layout

```
.github/workflows/          the four files in this folder
restructure_impactful_datasets.py
analyze_graph.py
build_website.py
person_review.csv           reviewed party classifications; the DECISION column
                            overrides every heuristic
assets/
  AGU_Logo_H_CMYK.png       brand mark
  story-feature-source.jpg  full-resolution photo for the article callout
data/source/
  Impactful_Datasets_v1_June_16_-_CSV_Format.csv
impactful_datasets.jsonld   written by step 1
site/                       written by step 3 — this is what gets served
reports/                    written by steps 1, 2 and 3
```

Two paths are hard-coded in the workflows and are worth knowing about:
`assets/AGU_Logo_H_CMYK.png` and `assets/story-feature-source.jpg`. If either is
missing the build still succeeds, with a warning and an empty image slot.

## The identifier guard, and why it matters

`site/data/impactful_datasets.data.jsonld` is not only the published data — it is
the **identifier registry**. Every dataset URL (`#/dataset/agu-0004-argo`) depends
on the id in that file, and the build keeps ids stable by reading the existing
file and reusing what it finds.

So the workflows do two things before and after building:

1. **Seed** the committed data file into the build directory first. Without this
   the build has nothing to match against and mints a fresh id for every dataset.
2. **Fail the job** if any id was minted and `allow_new_ids` was not enabled.

That guard is not hypothetical. A build with no seeded registry reports
`133 new ids minted`, renumbers every dataset from `agu-0001` to `agu-0134`, and
breaks every published link. Tested both ways: seeded builds report `0 new ids
minted` and pass; unseeded builds trip the guard and stop.

**When you add new datasets**, some ids *should* be minted. Re-run with
`allow_new_ids` enabled. Check the count matches the number of datasets actually
added — if you added three and the log says 136, the registry was not read.

## Inputs

All four take a `commit` toggle. Leave it on to have the bot commit results back
to the branch; turn it off to inspect the artifacts first — every run uploads its
outputs whether or not it commits.

Step 3 and the full pipeline also take:

- `base_url` — the site address used for canonical page URLs in the data file
- `data_url` — where the page fetches its data from; blank uses the relative path,
  set it to an absolute URL once the data file has a permanent home
- `featured` — the dataset shown if someone lands on the detail page cold
- `allow_new_ids` — see above

## What each run reports

Every workflow writes a summary to the run page: rows read and encoding repairs
(step 1), triples and nominator counts with the multi-nominator table (step 2),
dataset counts and the party-type breakdown by confidence (step 3).

The encoding repair count is worth watching. The source spreadsheet is not valid
UTF-8 — sixteen bytes are Mac Roman — and the script repairs them. If that number
changes, the source encoding changed.
