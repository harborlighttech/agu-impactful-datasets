#!/usr/bin/env python3
"""
Restructure the AGU "Impactful Datasets" nomination CSV into RDF (JSON-LD),
and emit a per-column multi-value statistics report.

Requirements
------------
    pip install pandas
    pip install rdflib      # optional: only used to validate + count triples

Usage
-----
    python restructure_impactful_datasets.py INPUT.csv [-o OUTDIR]

Outputs (written to OUTDIR, default ./out)
------------------------------------------
    impactful_datasets.jsonld   the RDF graph
    column_report.md            human-readable per-column report
    column_statistics.json      machine-readable stats
    _clean.csv                  encoding-repaired intermediate

Notes
-----
The source CSV is NOT valid UTF-8: 16 bytes are Mac Roman (0xD0 en-dash,
0x9A o-umlaut) inside one row's reference list, which makes a plain
pd.read_csv() raise UnicodeDecodeError. Step 0 repairs those bytes.

Parsing is heuristic. Every nomination keeps an agu:SourceRow node holding
the verbatim original cell values, so any guess can be checked or reversed.

Identifiers. Terms live under urn:org:agu:data:ns:. Every minted node is
urn:org:agu:data:impactful-datasets:id:{type}:{local}, with {type} one of
dataset, person, organization, nomination, theme, repository, sourcerow,
scheme or collection. People with an ORCID use the ORCID URI instead.
"""
import argparse, collections, json, re, statistics, unicodedata
from pathlib import Path

import pandas as pd

# Always resolves to the newest version of the nominations record.
ZENODO_CONCEPT_DOI_DEFAULT = "10.5281/zenodo.20722709"

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("csv", nargs="?", default=None,
                help="the nomination spreadsheet: a path, or an http(s) URL to "
                     "fetch. Omit it to use the single CSV in data/source/.")
ap.add_argument("--zenodo", nargs="?", const=ZENODO_CONCEPT_DOI_DEFAULT, default=None,
                metavar="DOI",
                help="build from the Zenodo record instead. With no value, uses "
                     "the collection's concept DOI, which always resolves to the "
                     "most recent version of the record.")
ap.add_argument("--zenodo-file", default=None, metavar="NAME",
                help="which file in the record to use, if it holds several CSVs")
ap.add_argument("-o", "--outdir", type=Path, default=Path("out"),
                help="output directory (default: ./out)")
args = ap.parse_args()


# The nominations live in a Zenodo record. Its concept DOI always resolves to the
# most recent version, so new nominations become a new version of the record and
# this DOI keeps pointing at the current data without anything here changing.
ZENODO_CONCEPT_DOI = ZENODO_CONCEPT_DOI_DEFAULT
ZENODO_API = "https://zenodo.org/api/records/%s"
RE_ZENODO = re.compile(
    r"(?:^|zenodo\.org/(?:records?|record)/|10\.5281/zenodo\.)(\d{4,})", re.I)


def _fetch(url, timeout=60):
    """Zenodo rejects the default urllib user agent, so identify ourselves."""
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "agu-impactful-datasets/1.0 (+https://data.agu.org)",
                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return fh.read()


def from_zenodo(ref, want=None):
    """The spreadsheet from a Zenodo record, resolved to its latest version.

    `ref` may be a concept DOI, a version DOI, a record URL or a bare record id.
    Requesting the concept record follows through to the newest version, which
    is the point: the DOI stays the same while the data behind it moves.

    Returns the bytes and what was actually used, so a build can record which
    version of the record it came from rather than just "Zenodo".
    """
    import json as _json
    m = RE_ZENODO.search(str(ref))
    if not m:
        raise SystemExit("could not find a Zenodo record id in %r" % ref)
    # Requesting a concept record redirects to its newest version, and
    # requesting a version record returns that version. So this does not chase
    # links.latest: doing so would silently upgrade a deliberately pinned
    # version DOI to the current one, which is the opposite of what pinning is
    # for. The concept DOI gives the latest because that is what it means.
    rec = _json.loads(_fetch(ZENODO_API % m.group(1)))

    files = rec.get("files") or []
    csvs = [f for f in files if str(f.get("key", "")).lower().endswith(".csv")]
    if want:
        csvs = [f for f in files if f.get("key") == want] or csvs
    if not csvs:
        raise SystemExit(
            "no CSV in Zenodo record %s. It holds: %s"
            % (rec.get("id"), ", ".join(f.get("key", "?") for f in files) or "nothing"))
    if len(csvs) > 1 and not want:
        raise SystemExit(
            "several CSVs in Zenodo record %s:\n  %s\nPass --zenodo-file to choose."
            % (rec.get("id"), "\n  ".join(f["key"] for f in csvs)))
    chosen = csvs[0]
    data = _fetch(chosen["links"]["self"])

    # Zenodo publishes a checksum for every file; a truncated download is a
    # silent corruption otherwise, and this costs nothing to check.
    want_sum = str(chosen.get("checksum") or "")
    if want_sum.startswith("md5:"):
        import hashlib
        got = hashlib.md5(data).hexdigest()
        if got != want_sum[4:]:
            raise SystemExit("checksum mismatch on %s: Zenodo says %s, got %s"
                             % (chosen["key"], want_sum[4:], got))

    meta = {"source": "zenodo",
            "record_id": rec.get("id"),
            "version_doi": rec.get("doi"),
            "concept_doi": rec.get("conceptdoi"),
            "published": rec.get("created") or (rec.get("metadata") or {}).get("publication_date"),
            "file": chosen.get("key"),
            "checksum": want_sum,
            "bytes": len(data)}
    print("source: Zenodo record %s — %s" % (rec.get("id"), chosen.get("key")))
    print("  version DOI: %s" % (rec.get("doi") or "unknown"))
    if rec.get("conceptdoi"):
        print("  concept DOI: %s (always the latest version)" % rec["conceptdoi"])
    print("  %d bytes%s" % (len(data), ", checksum verified" if want_sum else ""))
    return "%s (%s)" % (chosen.get("key"), rec.get("doi") or "Zenodo"), data, meta


def resolve_source(given, zenodo=None, zenodo_file=None):
    """Where to read the spreadsheet from, and the bytes it holds.

    In order of preference: an explicit --zenodo reference, then whatever was
    passed positionally (a Zenodo DOI or record URL, any other URL, or a path),
    then the single CSV in data/source/. That default is found by glob rather
    than by name, because the exported filename carries a date and changes with
    every new export.
    """
    if zenodo:
        return from_zenodo(zenodo, zenodo_file)

    if given and RE_ZENODO.search(str(given)) and re.search(r"zenodo", str(given), re.I):
        return from_zenodo(given, zenodo_file)

    if given and re.match(r"https?://", str(given), re.I):
        data = _fetch(str(given))
        print("source: %s (%d bytes fetched)" % (given, len(data)))
        return str(given), data, {"source": "url", "url": str(given), "bytes": len(data)}

    if given:
        path = Path(given)
        if not path.exists():
            raise SystemExit("no spreadsheet at %s" % path)
    else:
        found = sorted(Path("data/source").glob("*.csv"))
        if not found:
            raise SystemExit(
                "no CSV in data/source/ and none given. Pass a path, a URL, or "
                "--zenodo to build from the Zenodo record.")
        if len(found) > 1:
            raise SystemExit(
                "several CSVs in data/source/, so the default is ambiguous:\n  "
                + "\n  ".join(str(f) for f in found)
                + "\nPass the one to use.")
        path = found[0]
    print("source: %s" % path)
    return str(path), path.read_bytes(), {"source": "file", "path": str(path)}


SRC_NAME, SRC_BYTES, SRC_META = resolve_source(
    args.csv, args.zenodo, args.zenodo_file)
SRC = SRC_NAME
# What to call the source in the report. A Zenodo build names the file and the
# exact version DOI it came from, which is the whole point of building from a
# versioned record. A URL shows in full; a path shows its filename. Path().name
# is only safe for paths -- on "file.csv (10.5281/zenodo.123)" it would cut at
# the last dot and leave nonsense.
if SRC_META.get("source") == "zenodo":
    SRC_LABEL = "%s — Zenodo %s" % (SRC_META.get("file"),
                                    SRC_META.get("version_doi") or SRC_META.get("record_id"))
elif re.match(r"https?://", SRC_NAME, re.I):
    SRC_LABEL = SRC_NAME
else:
    SRC_LABEL = Path(SRC_NAME).name
OUTDIR = args.outdir
OUTDIR.mkdir(parents=True, exist_ok=True)
CLEAN = OUTDIR / "_clean.csv"

# ---------- 0. encoding repair -------------------------------------------------
raw = SRC_BYTES
txt = raw.decode("utf-8", errors="surrogateescape")
MACROMAN_FIX = {"\udcd0": "\u2013", "\udc9a": "\u00f6"}
enc_fixes = sum(txt.count(k) for k in MACROMAN_FIX)
for k, v in MACROMAN_FIX.items():
    txt = txt.replace(k, v)
CLEAN.write_text(txt, encoding="utf-8")

df = pd.read_csv(CLEAN, dtype=str)
ORIG = list(df.columns)
SHORT = ["discipline","name","authors","link","repo_name","repo_pid","curators",
         "description","justification","interaction","ref_pub","reuse",
         "nom_name","email","orcid","affiliation"]
df.columns = SHORT

# ---------- 1. regex toolkit ---------------------------------------------------
RE_URL   = re.compile(r'https?://[^\s,;)\]"<>]+')
RE_DOI   = re.compile(r'\b10\.\d{4,9}/[^\s,;)\]"<>]+', re.I)
RE_ORCID = re.compile(r'\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b')
RE_MAIL  = re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b')
RE_RRID  = re.compile(r'\bRRID:\s*\S+', re.I)
# Some rows sub-label a nominator slot with a letter -- "Nominator 1a:", "1b:",
# "1c:" -- to list several people under one number. Those are separate nominators
# and must not be merged, so the suffix is part of the key.
RE_NOM   = re.compile(r'^[ \t]*Nominator\s*(\d+)([a-z])?\s*:?[ \t]*$', re.M | re.I)
RE_NOM_INLINE = re.compile(r'Nominator\s*(\d+)([a-z])?\s*:', re.I)


def nom_key(m):
    return "%s%s" % (m.group(1), (m.group(2) or "").lower())


def nom_sort(k):
    m = re.match(r'(\d+)([a-z]*)', str(k))
    return (int(m.group(1)), m.group(2)) if m else (0, str(k))
RE_DIM   = re.compile(r'^[ \t]*(People|Planet|Prosperity)(\s+Dimension)?\s*:', re.I | re.M)

def clean(s):
    if s is None or (isinstance(s, float)):
        return None
    s = unicodedata.normalize("NFC", str(s))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.strip().strip('"').strip()
    return s or None

def strip_trailing_punct(u):
    return u.rstrip(".,;:)]}'\"")

def urls(s):    return [strip_trailing_punct(u) for u in RE_URL.findall(s or "")]
def dois(s):
    out = []
    for d in RE_DOI.findall(s or ""):
        d = strip_trailing_punct(d)
        d = re.sub(r'^.*?(10\.\d{4,9}/)', r'\1', d)
        out.append(d)
    return out
def orcids(s): return RE_ORCID.findall(s or "")
def mails(s):  return RE_MAIL.findall(s or "")

def dedupe(seq):
    seen, out = set(), []
    for x in seq:
        k = x.lower() if isinstance(x, str) else x
        if k not in seen:
            seen.add(k); out.append(x)
    return out

# ---------- 2. splitters -------------------------------------------------------
def split_generic(s):
    """Return (values, method). Conservative multi-value splitter for name-ish fields."""
    if not s: return [], "empty"
    if ";" in s:
        parts = [p.strip() for p in s.split(";") if p.strip()]
        if len(parts) > 1: return parts, "semicolon"
    if "\n" in s:
        parts = [p.strip() for p in s.split("\n") if p.strip()]
        if len(parts) > 1: return parts, "newline"
    return [s], "single"

def split_people(s):
    """Author/curator lists. Comma-splitting only when it is clearly a list, not 'Last, First'."""
    if not s: return [], "empty"
    vals, method = split_generic(s)
    if method != "single":
        return vals, method
    # single blob: decide whether commas delimit people
    if re.search(r",", s) and re.search(r"\band\b|&", s):
        parts = re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", s)
        parts = [p.strip(" .,") for p in parts if p.strip(" .,")]
        # reject if any part is a lone token (likely "Last, First" fragments)
        if len(parts) > 1 and all(len(p.split()) >= 2 or re.match(r"^[A-Z]\.", p) for p in parts):
            return parts, "comma+and (low confidence)"
    return [s], "single"

# Corrections applied to discipline group labels on the way into the graph. The
# source spreadsheet repeats a word in one option; the verbatim original is still
# kept on the agu:SourceRow node, so nothing is lost by fixing the label here.
DISCIPLINE_FIXES = {
    "Education, Geohealth, Society, Education":
        "Geohealth, Society, Education",
    # Safeguards. The current export already carries the full forms below, so these
    # are no-ops today; they exist so a future export that abbreviates a group name
    # is corrected on the way in rather than silently changing the vocabulary.
    "Global Environmental Change, Paleoclimatology, Biogeoscience":
        "Global Environmental Change, Paleoceanography and Paleoclimatology, Biogeoscience",
    "Earth Surface, Natural Hazards, Geology":
        "Earth Surface, Natural Hazards, Geology, Near Surface Geophysics",
}


def split_disciplines(s):
    """Original was a multi-select of quoted groups: "A, B", "C, D"."""
    if not s: return [], "empty"
    s = s.strip()
    groups = [g.strip().strip('"').strip() for g in re.split(r'"\s*,\s*"', s)]
    groups = [re.sub(r'\s+', ' ', g).strip(' ",') for g in groups if g.strip(' ",')]
    groups = [DISCIPLINE_FIXES.get(g, g) for g in groups]
    return groups, ("quoted-group" if len(groups) > 1 else "single-group")

def split_identifiers(s):
    """Landing pages / PIDs: URLs + bare DOIs."""
    if not s: return [], "empty"
    u = urls(s)
    d = dois(s)
    doi_urls = {x.lower() for x in u if "doi.org/" in x.lower()}
    bare = [f"https://doi.org/{x}" for x in d
            if not any(x.lower() in du for du in doi_urls)]
    vals = dedupe(u + bare)
    if vals:
        return vals, ("url/doi-extract" if len(vals) > 1 else "single-uri")
    return split_generic(s)

def split_nominator_blocks(s):
    """Parse 'Nominator N:' / 'Nominator Na:' blocks -> {key: text}."""
    if not s: return {}, "empty"
    if not RE_NOM_INLINE.search(s):
        return {"1": s}, "single"
    idx = [(m.start(), nom_key(m), m.end()) for m in RE_NOM_INLINE.finditer(s)]
    out = {}
    for i, (st, n, en) in enumerate(idx):
        nxt = idx[i + 1][0] if i + 1 < len(idx) else len(s)
        body = s[en:nxt].strip(" \n:")
        if body:
            out[n] = out.get(n, "") + ("\n\n" if n in out else "") + body
    return (out or {"1": s}), "labelled:Nominator N"

def split_dimensions(s):
    """People:/Planet:/Prosperity: sub-headers inside a justification block."""
    if not s: return {}, None
    ms = list(RE_DIM.finditer(s))
    if not ms: return {}, None
    out, preamble = {}, s[:ms[0].start()].strip()
    for i, m in enumerate(ms):
        nxt = ms[i + 1].start() if i + 1 < len(ms) else len(s)
        out[m.group(1).capitalize()] = s[m.end():nxt].strip(" \n")
    if preamble: out["_preamble"] = preamble
    return out, "labelled:People/Planet/Prosperity"

def split_citations(s):
    """Reference lists: blank-line or line separated citations."""
    if not s: return [], "empty"
    parts = [p.strip() for p in re.split(r"\n\s*\n", s) if p.strip()]
    method = "blank-line"
    if len(parts) == 1 and "\n" in s:
        parts = [p.strip() for p in s.split("\n") if p.strip()]
        method = "newline"
    if len(parts) == 1:
        # numbered list on one line?
        nb = re.split(r"(?:(?<=\.)|(?<=\)))\s+(?=\d+[\.\)]\s)", s)
        if len(nb) > 1:
            parts, method = [p.strip() for p in nb], "numbered"
        else:
            method = "single"
    return parts, method

# ---------- 3. row -> structured record ---------------------------------------
# AGU namespaces. Terms live under the ns URN; every minted record id is
# urn:org:agu:data:impactful-datasets:id:{type}:{local}, where {type} is dataset,
# person, organization, nomination, theme, repository, sourcerow, scheme or
# collection. URNs are location-independent, so ids survive the site moving.
NS_TERMS = "urn:org:agu:data:ns:"
NS_IDS   = "urn:org:agu:data:impactful-datasets:id:"
def slug(t, n=60):
    s = re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")
    return (s[:n].strip("-") or "unknown")

records, stat_hits = [], collections.defaultdict(lambda: collections.defaultdict(int))

for i, row in df.iterrows():
    r = {k: clean(row[k]) for k in SHORT}
    rec = {"row": int(i), "raw": r}

    rec["themes"], m = split_disciplines(r["discipline"]); stat_hits["discipline"][m] += 1
    rec["title"] = r["name"]
    rec["creators"], m = split_people(r["authors"]);        stat_hits["authors"][m] += 1
    rec["ids"], m = split_identifiers(r["link"]);           stat_hits["link"][m] += 1
    rec["repos"], m = split_generic(r["repo_name"]);        stat_hits["repo_name"][m] += 1
    rec["repo_ids"], m = split_identifiers(r["repo_pid"]);  stat_hits["repo_pid"][m] += 1
    rec["curators"], m = split_people(r["curators"]);       stat_hits["curators"][m] += 1
    rec["refs"], m = split_citations(r["ref_pub"]);         stat_hits["ref_pub"][m] += 1
    rec["reuse_items"], m = split_citations(r["reuse"]);    stat_hits["reuse"][m] += 1

    # --- nominator quartet: parallel labelled arrays -> zipped person records ---
    names, m1 = split_nominator_blocks(r["nom_name"]);   stat_hits["nom_name"][m1] += 1
    emls,  m2 = split_nominator_blocks(r["email"]);      stat_hits["email"][m2] += 1
    orcs,  m3 = split_nominator_blocks(r["orcid"]);      stat_hits["orcid"][m3] += 1
    affs,  m4 = split_nominator_blocks(r["affiliation"]);stat_hits["affiliation"][m4] += 1
    keys = sorted(set(names) | set(emls) | set(orcs) | set(affs), key=nom_sort)
    people = []
    for k in keys:
        nm = (names.get(k) or "").strip()
        oc = orcids(orcs.get(k, ""))
        em = mails(emls.get(k, ""))
        af = (affs.get(k) or "").strip()
        if not (nm or oc or em or af): continue
        people.append({"seq": k, "name": nm or None, "orcid": oc[0] if oc else None,
                       "email": em[0] if em else None,
                       "affiliations": [a.strip() for a in re.split(r"\n\s*\n", af) if a.strip()]})
    rec["nominators"] = people

    # --- narrative fields, per nominator, with impact dimensions ---------------
    just, mj = split_nominator_blocks(r["justification"]); stat_hits["justification"][mj] += 1
    rec["justifications"] = []
    for k, body in sorted(just.items(), key=lambda kv: nom_sort(kv[0])):
        dims, md = split_dimensions(body)
        rec["justifications"].append({"seq": k, "text": body, "dimensions": dims or None,
                                      "dimension_parse": md})
        if md: stat_hits["justification"]["+" + md] += 1
    inter, mi = split_nominator_blocks(r["interaction"]);  stat_hits["interaction"][mi] += 1
    rec["interactions"] = [{"seq": k, "text": v} for k, v in sorted(inter.items(), key=lambda kv: nom_sort(kv[0]))]
    desc, mdz = split_nominator_blocks(r["description"]);  stat_hits["description"][mdz] += 1
    rec["descriptions"] = [{"seq": k, "text": v} for k, v in sorted(desc.items(), key=lambda kv: nom_sort(kv[0]))]
    records.append(rec)

# ---------- 4. JSON-LD ---------------------------------------------------------
CONTEXT = {
    "@vocab": "https://schema.org/",
    "schema": "https://schema.org/", "dcat": "http://www.w3.org/ns/dcat#",
    "dct": "http://purl.org/dc/terms/", "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#", "foaf": "http://xmlns.com/foaf/0.1/",
    "xsd": "http://www.w3.org/2001/XMLSchema#", "agu": NS_TERMS, "id": NS_IDS,
    "title": {"@id": "dct:title"},
    "description": {"@id": "dct:description"},
    "theme": {"@id": "dct:subject", "@type": "@id"},
    "creator": {"@id": "dct:creator"},
    "landingPage": {"@id": "dcat:landingPage", "@type": "@id"},
    "identifier": {"@id": "dct:identifier"},
    "inCatalog": {"@id": "dcat:catalog", "@type": "@id"},
    "curator": {"@id": "agu:curator"},
    "isReferencedBy": {"@id": "dct:isReferencedBy"},
    "reuseExample": {"@id": "agu:reuseExample"},
    "nominates": {"@id": "agu:nominates", "@type": "@id"},
    "nominator": {"@id": "agu:nominator", "@type": "@id"},
    "justification": {"@id": "agu:justification"},
    "interactionStatement": {"@id": "agu:interactionStatement"},
    "impactDimension": {"@id": "agu:impactDimension"},
    # A plain string: the value is the nomination form's slot label, and some
    # rows label their nominators 1a, 1b, 1c. Typed xsd:integer, every consumer
    # would try to parse "1c" as a number and warn.
    "sequence": {"@id": "agu:nominatorSequence"},
    "affiliation": {"@id": "schema:affiliation", "@type": "@id"},
    "wasDerivedFrom": {"@id": "prov:wasDerivedFrom", "@type": "@id"},
    "sourceColumn": {"@id": "agu:sourceColumn"},
    "sourceValue": {"@id": "agu:sourceValue"},
    "parseMethod": {"@id": "agu:parseMethod"},
    "inScheme": {"@id": "skos:inScheme", "@type": "@id"},
    "prefLabel": {"@id": "skos:prefLabel"},
    "broader": {"@id": "skos:broader", "@type": "@id"},
}

graph, orgs, repos, themes, persons = [], {}, {}, {}, {}

def org_node(label):
    key = slug(label, 80)
    if key not in orgs:
        orgs[key] = {"@id": f"id:organization:{key}", "@type": ["schema:Organization", "foaf:Organization"],
                     "name": label}
        graph.append(orgs[key])
    return orgs[key]["@id"]

def theme_node(label):
    key = slug(label, 80)
    if key not in themes:
        members = [p.strip() for p in re.split(r",|\band\b(?![^()]*\))", label) if p.strip()]
        node = {"@id": f"id:theme:{key}", "@type": "skos:Concept", "prefLabel": label,
                "inScheme": "id:scheme:agu-discipline-groups"}
        if len(members) > 1:
            node["agu:memberDiscipline"] = dedupe(members)
        themes[key] = node
        graph.append(node)
    return themes[key]["@id"]

def repo_node(label, ids):
    key = slug(label, 80)
    if key not in repos:
        node = {"@id": f"id:repository:{key}",
                "@type": ["dcat:Catalog", "schema:DataCatalog"], "name": label}
        repos[key] = node
        graph.append(node)
    node = repos[key]
    if ids:
        node["identifier"] = dedupe(node.get("identifier", []) + ids)
    return node["@id"]

def person_node(p, fallback):
    pid = ("https://orcid.org/" + p["orcid"]) if p.get("orcid") else \
          f"id:person:{slug(p.get('name') or fallback, 70)}"
    if pid not in persons:
        node = {"@id": pid, "@type": ["schema:Person", "foaf:Person"]}
        if p.get("name"):  node["name"] = p["name"]
        if p.get("orcid"): node["identifier"] = {"@type": "schema:PropertyValue",
                                                 "propertyID": "ORCID",
                                                 "value": "https://orcid.org/" + p["orcid"]}
        if p.get("email"): node["schema:email"] = p["email"]
        persons[pid] = node
        graph.append(node)
    node = persons[pid]
    if p.get("affiliations"):
        node["affiliation"] = dedupe(node.get("affiliation", []) + [org_node(a) for a in p["affiliations"]])
    return pid

graph.append({"@id": "id:scheme:agu-discipline-groups", "@type": "skos:ConceptScheme",
              "title": "AGU discipline groups (as offered in the nomination form)"})

for rec in records:
    n = rec["row"] + 1
    ds_id, nm_id, src_id = f"id:dataset:{n:03d}", f"id:nomination:{n:03d}", f"id:sourcerow:{n:03d}"

    ds = {"@id": ds_id, "@type": ["dcat:Dataset", "schema:Dataset"],
          "title": rec["title"], "wasDerivedFrom": src_id}
    if rec["themes"]:
        ds["theme"] = [theme_node(t) for t in rec["themes"]]
    if rec["creators"]:
        ds["creator"] = [{"@type": "agu:CreatorStatement", "name": c} for c in rec["creators"]]
    lp = [u for u in rec["ids"] if u.startswith("http")]
    if lp:
        ds["landingPage"] = lp
        ds["identifier"] = [{"@type": "schema:PropertyValue", "propertyID": "DOI", "value": u}
                            for u in lp if "doi.org/" in u] or None
        if not ds["identifier"]: ds.pop("identifier")
    other = [u for u in rec["ids"] if not u.startswith("http")]
    if other: ds["agu:identifierLiteral"] = other
    if rec["repos"]:
        ds["inCatalog"] = [repo_node(rp, rec["repo_ids"] if len(rec["repos"]) == 1 else [])
                           for rp in rec["repos"]]
        if len(rec["repos"]) > 1 and rec["repo_ids"]:
            ds["agu:repositoryIdentifier"] = rec["repo_ids"]
    if rec["curators"]:
        ds["curator"] = [{"@type": "agu:CuratorStatement", "name": c} for c in rec["curators"]]
    if rec["descriptions"]:
        ds["description"] = [{"@type": "agu:Statement", "sequence": d["seq"],
                              "schema:text": d["text"]} for d in rec["descriptions"]] \
            if len(rec["descriptions"]) > 1 else rec["descriptions"][0]["text"]
    if rec["refs"]:
        ds["isReferencedBy"] = [
            {"@type": ["dct:BibliographicResource", "schema:CreativeWork"],
             "schema:citation": c,
             **({"identifier": [{"@type": "schema:PropertyValue", "propertyID": "DOI",
                                 "value": "https://doi.org/" + d} for d in dedupe(dois(c))]}
                if dois(c) else {}),
             **({"schema:url": dedupe(urls(c))} if urls(c) else {})}
            for c in rec["refs"]]
    if rec["reuse_items"]:
        ds["reuseExample"] = [
            {"@type": "agu:ReuseExample", "schema:text": c,
             **({"schema:url": dedupe(urls(c))} if urls(c) else {}),
             **({"identifier": dedupe(["https://doi.org/" + d for d in dois(c)])} if dois(c) else {})}
            for c in rec["reuse_items"]]
    graph.append(ds)

    nom = {"@id": nm_id, "@type": ["agu:Nomination", "prov:Entity"],
           "nominates": ds_id, "wasDerivedFrom": src_id}
    people_ids = [person_node(p, f"row{n}-nominator{p['seq']}") for p in rec["nominators"]]
    if people_ids: nom["nominator"] = people_ids
    if rec["justifications"]:
        js = []
        for j in rec["justifications"]:
            node = {"@type": "agu:JustificationStatement", "sequence": j["seq"], "schema:text": j["text"]}
            if j["dimensions"]:
                node["impactDimension"] = [
                    {"@type": "agu:ImpactDimension", "prefLabel": k, "schema:text": v}
                    for k, v in j["dimensions"].items() if k != "_preamble"]
            js.append(node)
        nom["justification"] = js
    if rec["interactions"]:
        nom["interactionStatement"] = [{"@type": "agu:Statement", "sequence": t["seq"],
                                        "schema:text": t["text"]} for t in rec["interactions"]]
    graph.append(nom)

    graph.append({"@id": src_id, "@type": "agu:SourceRow", "agu:rowNumber": rec["row"] + 2,
                  "sourceValue": [{"sourceColumn": ORIG[k], "schema:value": rec["raw"][SHORT[k]]}
                                  for k in range(len(SHORT)) if rec["raw"][SHORT[k]]]})

collection = {"@id": "id:collection:agu-impactful-datasets-v1",
              "@type": ["dcat:Catalog", "prov:Collection"],
              "title": "AGU Impactful Datasets nominations, v1 (2026-06-16 CSV export)",
              "agu:recordCount": len(records),
              "dcat:dataset": [{"@id": f"id:dataset:{r['row']+1:03d}"} for r in records],
              "agu:nomination": [{"@id": f"id:nomination:{r['row']+1:03d}"} for r in records]}
doc = {"@context": CONTEXT, "@graph": [collection] + graph}

JSONLD_PATH = OUTDIR / "impactful_datasets.jsonld"
json.dump(doc, open(JSONLD_PATH, "w"), indent=2, ensure_ascii=False)

# ---------- 5. column statistics ----------------------------------------------
def col_stats(short_i):
    c = SHORT[short_i]
    s = df[c].map(clean)
    nn = s.dropna()
    lens = nn.map(len)
    st = {"column": ORIG[short_i], "key": c, "non_null": int(len(nn)),
          "fill_pct": round(100 * len(nn) / len(df), 1),
          "unique": int(nn.nunique()),
          "len_min": int(lens.min()) if len(nn) else 0,
          "len_median": int(lens.median()) if len(nn) else 0,
          "len_max": int(lens.max()) if len(nn) else 0,
          "n_urls": int(nn.map(lambda v: len(urls(v))).sum()),
          "n_dois": int(nn.map(lambda v: len(dedupe(dois(v)))).sum()),
          "n_orcids": int(nn.map(lambda v: len(orcids(v))).sum()),
          "n_emails": int(nn.map(lambda v: len(mails(v))).sum()),
          "has_newline": int(nn.str.contains("\n").sum()),
          "has_semicolon": int(nn.str.contains(";").sum()),
          "has_nominator_label": int(nn.str.contains(RE_NOM_INLINE).sum()),
          "methods": dict(stat_hits.get(c, {}))}
    return st

VALUE_ACCESSOR = {
    "discipline": lambda r: r["themes"], "authors": lambda r: r["creators"],
    "link": lambda r: r["ids"], "repo_name": lambda r: r["repos"],
    "repo_pid": lambda r: r["repo_ids"], "curators": lambda r: r["curators"],
    "ref_pub": lambda r: r["refs"], "reuse": lambda r: r["reuse_items"],
    "nom_name": lambda r: r["nominators"], "email": lambda r: r["nominators"],
    "orcid": lambda r: r["nominators"], "affiliation": lambda r: r["nominators"],
    "justification": lambda r: r["justifications"], "interaction": lambda r: r["interactions"],
    "description": lambda r: r["descriptions"], "name": lambda r: [r["title"]] if r["title"] else [],
}

stats = []
for i, c in enumerate(SHORT):
    st = col_stats(i)
    counts = [len(VALUE_ACCESSOR[c](r)) for r in records]
    nz = [x for x in counts if x > 0]
    st["values_total"] = sum(counts)
    st["multi_cells"] = sum(1 for x in counts if x > 1)
    st["max_values_in_cell"] = max(counts) if counts else 0
    st["mean_values"] = round(statistics.mean(nz), 2) if nz else 0
    st["dist"] = dict(sorted(collections.Counter(counts).items()))
    stats.append(st)

STATS_DOC = {"source": SRC_META,
             "encoding_repairs": enc_fixes, "rows": len(df), "columns": len(SHORT),
             "column_stats": stats}
json.dump(STATS_DOC, open(OUTDIR / "column_statistics.json", "w"), indent=2, ensure_ascii=False)

print(f"encoding repairs: {enc_fixes}")
print(f"graph nodes: {len(graph)} | datasets {len(records)} | persons {len(persons)} "
      f"| repos {len(repos)} | themes {len(themes)} | orgs {len(orgs)}")
for st in stats:
    print(f"{st['key']:14s} fill {st['fill_pct']:5.1f}%  vals {st['values_total']:5d}  "
          f"multi {st['multi_cells']:3d}  max {st['max_values_in_cell']:3d}  {st['methods']}")

# ---------- 6. optional RDF validation ----------------------------------------
TRIPLE_NOTE = ""
try:
    from rdflib import Graph
    _g = Graph()
    _g.parse(JSONLD_PATH, format="json-ld")
    TRIPLE_NOTE = f"{len(_g):,} RDF triples across "
    print(f"rdflib validation OK: {len(_g):,} triples")
except ImportError:
    print("rdflib not installed - skipping triple-count validation")
except Exception as e:
    print(f"WARNING: JSON-LD failed to parse as RDF: {e}")


# ---------- 7. markdown report ------------------------------------------------
d = STATS_DOC
S = {s["key"]: s for s in d["column_stats"]}

NOTES = {
 "discipline": ("Multi-select of **quoted discipline groups**", "`\", \"` between groups; commas *inside* a group are part of one label",
   "8 canonical groups. One row survived as `Ocean Science, Hydrology, Cryosphere\", \"Atmospheric Science, Space Weather` — the leftover quotes prove the original field was a quoted multi-select that lost its quoting on export. Three other rows carry a stray trailing `\"`. Do **not** split on bare commas here: it would shatter `Ocean Science, Hydrology, Cryosphere` into three false themes."),
 "name": ("Single value", "none", "Fully unique (133/133). One outlier at 299 chars is a title plus a parenthetical product list."),
 "authors": ("**Multi-valued, mixed delimiters**", "`;` (12 cells) > newline (5) > `, ... and` (11, low confidence)", "The hard case. `Jochum, Klaus Peter` is *one* person in `Last, First` form, while `A. J. Newman, M. P. Clark, K. Sampson` is three. I split on comma only when an `and`/`&` is present and every fragment has ≥2 tokens. Two cells use their own sub-headers (`Part 1:` / `Part 2:`) and one uses `Global Estimates (V6.GL.02.04):` — these are version scopes, not authors, and are left unsplit."),
 "link": ("**Multi-valued**", "URL/DOI extraction; `;`, newline, and literal ` and ` all appear", "6 cells contain no URL at all — 4 are bare DOIs (`10.5067/...`), 2 are schemeless hosts (`georoc.eu`, `www.geonet.org.nz`). Bare DOIs are normalised to `https://doi.org/…`. Row 9 buries five product DOIs in a prose paragraph."),
 "repo_name": ("Mostly single", "`;`, newline", "111 distinct strings but only ~99 distinct repositories: `Zenodo`/`zenodo.org`, `GES DISC`/`GES-DISC`, and three spellings of the NASA GES name. 15 cells put a URL in the name field instead of the PID field."),
 "repo_pid": ("**Multi-valued, extreme skew**", "`;` + URL/DOI extraction", "The single worst cell in the file: 11,361 chars holding 299 AmeriFlux site DOIs. 39 rows are empty. Median cell is one DOI. This column and `repo_name` are frequently swapped by submitters."),
 "curators": ("Multi-valued", "`;`, newline, `, ... and`", "Heterogeneous by kind, not just by count — some cells name individuals, some name a team (`GES DISC User Services`), some give an email only. 24 emails embedded. One cell lists 13 people."),
 "description": ("Single, occasionally per-nominator", "`Nominator N:` (1 cell)", "Free text, median 1,100 chars. 79 embedded URLs and 21 DOIs are worth extracting as `schema:citation` links. Several cells open with `From https://…` — copied provenance."),
 "justification": ("**Two nested levels of multi-value**", "outer `Nominator N:`; inner `People:` / `Planet:` / `Prosperity:`", "The richest structure in the file. 12 rows split by nominator (up to 9 blocks); 18 blocks further subdivide into the three impact dimensions named in the column header itself — a case where the *header* documents the intended sub-schema. Variant spellings `People Dimension:` are handled."),
 "interaction": ("Multi-valued by nominator", "`Nominator N:`", "Same 12 rows and same block numbering as `justification` — they always co-vary."),
 "ref_pub": ("**Multi-valued citation list**", "blank line (38) > newline (3) > `1.` numbering (2)", "43 cells hold more than one citation; max 11. 161 DOIs recoverable. Blank-line splitting is safe here because citations wrap; splitting on every newline would fragment them."),
 "reuse": ("**Most multi-valued column**", "blank line (40) > numbering (6) > newline (3)", "62% filled but 397 extracted items — mean 4.8 per non-empty cell, max 36, longest cell ~20k chars. Some cells use their own sub-headers (`Scientific Publications:`, `Derived Data Products:`, `Educational Resources:`), which is the same header-inside-a-cell pattern as `justification`."),
 "nom_name": ("**Parallel labelled array**", "`Nominator N:`", "13 rows carry explicit `Nominator N:` labels, up to 9 people."),
 "email": ("**Parallel labelled array**", "`Nominator N:`", "173 addresses. Labels align perfectly with `nom_name`."),
 "orcid": ("**Parallel labelled array**", "`Nominator N:`", "168 ORCIDs. 3 rows empty; a few cells hold bare IDs rather than `https://orcid.org/…` URIs. Used as the person `@id` wherever present."),
 "affiliation": ("**Parallel labelled array**", "`Nominator N:`, plus blank lines for a person's *multiple* affiliations", "A third nesting level: one nominator can list two institutions separated by a blank line inside their own block. 157 distinct organisation strings, unnormalised (raw postal addresses included)."),
}

rows = []
for s in d["column_stats"]:
    k = s["key"]
    rows.append(f"| `{k}` | {s['fill_pct']}% | {s['unique']} | {s['len_max']:,} | "
                f"{s['values_total']} | {s['multi_cells']} | {s['max_values_in_cell']} | {s['mean_values']} |")

detail = []
for s in d["column_stats"]:
    k = s["key"]
    kind, delim, note = NOTES[k]
    ent = []
    for lbl, f in [("URLs","n_urls"),("DOIs","n_dois"),("ORCIDs","n_orcids"),("emails","n_emails")]:
        if s[f]: ent.append(f"{s[f]} {lbl}")
    detail.append(f"""### `{k}` — {s['column']}

- **Shape:** {kind}. Fill {s['fill_pct']}% ({s["non_null"]}/{d["rows"]}), {s['unique']} distinct raw strings.
- **Delimiter guessed:** {delim}
- **Length (chars):** min {s['len_min']}, median {s['len_median']:,}, max {s['len_max']:,}
- **Values after parsing:** {s['values_total']} total, {s['multi_cells']} multi-valued cells, max {s['max_values_in_cell']} in one cell, mean {s['mean_values']} per populated cell
- **Cardinality histogram** (values per cell): `{s['dist']}`
- **Entities extracted:** {', '.join(ent) if ent else 'none'}
- **Parse methods used:** `{s['methods']}`

{note}
""")

md = f"""# Column report — AGU *Impactful Datasets* v1

**Source:** `{SRC_LABEL}` · {len(df)} data rows × {len(SHORT)} columns
**Output:** `impactful_datasets.jsonld` — {TRIPLE_NOTE}{len(doc["@graph"])} nodes

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
{chr(10).join(rows)}

---

## The three multi-value patterns in this file

**1. Delimiter-separated lists.** `;` is the reliable one (`authors`, `link`, `repo_pid`). Commas are treacherous — see `authors` and `discipline` below. Newlines separate items in some cells and wrap text in others.

**2. Labelled parallel arrays.** Four columns (`nom_name`, `email`, `orcid`, `affiliation`) use `Nominator 1:` / `Nominator 2:` headers *inside* the cell. These are positional joins across columns: block *n* of `email` belongs to block *n* of `nom_name`. **The labels agree across all four columns in all 133 rows — zero disagreements** — so the zip is safe. This is the "headers for multiple values" pattern you flagged, and it is the single most important thing to get right, because a naive parse silently attributes one person's ORCID to another.

**3. Sub-schemas inside a cell.** `justification` nests two levels: `Nominator N:` blocks, each optionally divided into `People:`, `Planet:`, `Prosperity:` — the exact vocabulary from the column header. `reuse` does something similar ad hoc (`Scientific Publications:`, `Derived Data Products:`, `Educational Resources:`).

---

## Per-column detail

{chr(10).join(detail)}
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
"""
(OUTDIR / "column_report.md").write_text(md, encoding="utf-8")


print(f"\nwrote:\n  {JSONLD_PATH}\n  {OUTDIR / 'column_report.md'}"
      f"\n  {OUTDIR / 'column_statistics.json'}")
