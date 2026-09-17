# Setting up this repository

Everything needed to build and publish the collection is in here. This is the
path from an empty GitHub repository to a pull request against the live site.

The whole pipeline is four Python scripts and three manually-triggered workflows.
There is no server, no database and no hosted service to pay for.

---

## 1. Create the repository

```bash
gh repo create agu-impactful-datasets --public \
    --description "Turns the AGU Impactful Datasets nominations into linked data and a website"
```

Then push this tree into it:

```bash
git init -b main
git add .
git commit -m "Pipeline, data and site for the Impactful Datasets collection"
git remote add origin git@github.com:YOUR-ORG/agu-impactful-datasets.git
git push -u origin main
```

Three directories are committed build products rather than sources, which is
deliberate:

| Path | Why it is committed |
| --- | --- |
| `site/` | what gets published, and what workflow 3 copies |
| `site/data/impactful_datasets.data.jsonld` | also the **identifier registry** — the next build reads it to keep URLs stable |
| `reports/` | so changes to the statistics show up in a pull request diff |
| `impactful_datasets.jsonld` | the working RDF graph, input to steps 2 and 3 |

Losing `site/data/impactful_datasets.data.jsonld` renumbers all 133 datasets and
breaks every published link. It matters more than its filename suggests.

---

## 2. Check it builds locally

Worth doing once before relying on Actions, because a local failure is far
easier to read than a failed job.

```bash
pip install -r requirements.txt

# the registry has to be in place before the build runs
mkdir -p build/data
cp site/data/impactful_datasets.data.jsonld build/data/

# no argument: uses the single CSV in data/source/
python scripts/restructure_impactful_datasets.py -o build
python scripts/build_website.py build/impactful_datasets.jsonld \
    --logo assets/AGU_Logo_H_CMYK.png \
    --feature-image assets/story-feature-source.jpg \
    --base-url "https://data.agu.org/impactful-datasets/" -o build
python scripts/analyze_graph.py build/data/impactful_datasets.data.jsonld -o build
python scripts/document_schema_model.py build/data/impactful_datasets.data.jsonld \
    -o build/schema_model.svg
```

The line to watch is the second one. It should say **`0 new ids minted`**. Any
other number means the registry was not read, and publishing would break every
existing link.

To look at the result:

```bash
cd build && python -m http.server
```

---

## 3. Set up publishing to data.agu.org

The live site is a directory inside
[`AGU-Data/agu-data.github.io`](https://github.com/AGU-Data/agu-data.github.io),
which belongs to another organisation. Workflow 3 proposes changes to it as a
pull request from a fork, so nobody at AGU-Data has to install or approve
anything.

**Make a bot account.** A machine account rather than a person's, so the
pipeline outlives anyone changing roles. Something self-explanatory, such as
`agu-impactful-datasets-bot`.

**Fork the upstream repository** to that account, keeping the name
`agu-data.github.io`.

**Make a token.** Signed in as the bot: Settings → Developer settings → Personal
access tokens → **Tokens (classic)** → Generate, with only the **`public_repo`**
scope.

It has to be a classic token. A fine-grained token can only grant pull-request
write on repositories its owner administers, and the bot does not administer
AGU-Data's. Granting a fine-grained token read access to public repositories is
not enough to open a pull request.

**Store it here.** Settings → Secrets and variables → Actions → New repository
secret, named `AGU_DATA_BOT_TOKEN`.

---

## 4. Optional: turn on the preview

Workflow 2 publishes `site/` to this repository's own Pages, which is useful for
looking at a build on a real URL before proposing it to AGU. Settings → Pages →
Source → **GitHub Actions**.

This is a staging preview. It is not the public site.

---

## 5. Run it

From the **Actions** tab. Nothing runs on push; every workflow is manual.

| When | Run |
| --- | --- |
| The spreadsheet changed, or the pipeline did | **1 · Build data and statistics** |
| You want to see a build on a real URL | **2 · Preview on this repo's Pages** |
| The build is ready to go live | **3 · Open a pull request on agu-data.github.io** |

Workflow 1 does the whole data side in one pass: spreadsheet to RDF, RDF to the
schema.org file, then statistics measured from that file. It writes a summary to
the run page with the dataset, nominator, nomination and discipline-group counts,
datasets per discipline group, and every class in the file with its count.

Workflow 3 has `dry_run` **on by default**. It clones, assembles the change, runs
its safety checks and prints the diff without pushing. Run it that way first.

## What protects the other organisation's repository

Workflow 3 writes into somebody else's site, so it is built to fail rather than
to guess:

- **One directory.** The tree is emptied and rewritten beneath
  `impactful-datasets/` and nowhere else.
- **Checked before pushing.** If the staged diff touches a single path outside
  that directory, the job stops. Tested against a replica: a run that also wrote
  a root `.nojekyll` and edited `CNAME` was blocked with both paths named.
- **No `.nojekyll`.** Harmless on a plain Pages deploy, but at the root of a
  Jekyll site it disables the build for every page they have.
- **Rebuilt from upstream each run,** so the pull request contains only our files
  even when their site has moved on.
- **Branches under review are never force-pushed,** which would dismiss stale
  approvals and destroy the "changes since your last review" diff.

---

## Adding new nominations later

Nominations arrive through the same form into the same spreadsheet. Nothing
about that has to change.

1. Either replace the file in `data/source/` with the new export, or publish a
   new version of the Zenodo record and run workflow 1 with `source` set to
   `zenodo`. The committed CSV is the default; the filename can change, since
   the default finds whichever CSV is in the directory.
2. Run **1 · Build data and statistics**. Existing datasets keep their identifiers; new ones
   are minted fresh.
3. If the run reports new identifiers and you did not add datasets, stop. Re-run
   with `allow_new_ids` only when the count matches the number genuinely added.
4. Run **3** to propose the update.

---

## Where to read next

- [`README.md`](README.md) — what each script does, how the data is modelled, and
  the decisions behind it
- [`.github/workflows/README.md`](.github/workflows/README.md) — the workflows in
  detail
- [`reports/`](reports/) — column analysis, graph statistics, the conceptual
  model diagrams and the party classification worksheet
