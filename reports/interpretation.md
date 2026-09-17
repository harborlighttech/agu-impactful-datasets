# How the spreadsheet was read

Source: **Zenodo 10.5281/zenodo.20722710 — Impactful Datasets v1_June 16 - CSV Format.csv** — 133 rows, 16 columns.

The file is not valid UTF-8. **16 bytes** were Mac Roman and were repaired before parsing; without that, the file cannot be opened at all.

## Columns that needed a judgement call

A cell holding several values has to be split, and the separator is inferred. Semicolons and line breaks are unambiguous. Commas are not: `Jochum, Klaus Peter` is one person and `A. Newman, M. Clark` is two. These columns had cells split on a comma, and are the likeliest place for a wrong reading:

| Column | Cells split on a comma | Total cells |
|---|---|---|
| Dataset Authors or Creators | **11** | 133 |
| Repository Data managers or curators that support the datase | **4** | 97 |

## Columns that are not fully populated

Not an error, but worth knowing before quoting a total from them.

| Column | Filled |
|---|---|
| Examples of how this dataset has been reused, any bibliograp | 62.4% |
| Repository Persistent Identifier (RRID, DOI, other) | 70.7% |
| Repository Data managers or curators that support the datase | 72.9% |
| Reference publication that describes the dataset. | 80.5% |
| Nominator ORCID | 97.7% |

## Cells holding the most values

One cell held this many separate values. Large numbers are usually correct and simply unwieldy, but they are where a mis-split would hide.

| Column | Most values in one cell |
|---|---|
| Repository Persistent Identifier (RRID, DOI, other) | 299 |
| Examples of how this dataset has been reused, any bibliograp | 36 |
| Repository Data managers or curators that support the datase | 13 |
| Dataset Authors or Creators | 12 |
| Reference publication that describes the dataset. | 11 |

## Who gets credited, and how confidently

518 distinct credited parties. Where the evidence supports it they are typed as a person or an organisation; where it does not, they are typed `agu:ResponsibleParty`, which says the party is responsible for the dataset without claiming to know which.

| Type | High | Medium | Low |
|---|---|---|---|
| Person | 156 | 6 | 5 |
| Organization | 42 | 0 | 0 |
| agu:ResponsibleParty | 0 | 97 | 212 |

**217 parties were typed on weak evidence.** These are the rows most worth a human glance; `reports/person_review.csv` has the reasoning for every one.

## Entries that no amount of typing will fix

- **62** cells hold several entities in one string, such as a person and their institution together. They need splitting upstream, not reclassifying.
- **43** are not entities at all: a sentence or a fragment that landed in a name field. Giving these a formal type would be worse than leaving them.

Both are artefacts of the original spreadsheet, and both are listed in `reports/person_review.csv`.
