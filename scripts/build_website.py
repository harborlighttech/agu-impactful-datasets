#!/usr/bin/env python3
"""
Build the two-page "Impactful Datasets" site prototype as one standalone HTML file,
in AGU brand: Montserrat + Lora, primary #244C5A, secondary #007DBA, white ground.

Reads the RDF graph produced by restructure_impactful_datasets.py and inlines a
compact payload for all 133 datasets, plus the AGU logo as a base64 CSS token,
so the result is a single file with no external assets.

Requirements:
    pip install pillow      # only to downscale + embed the logo

Usage:
    python build_website.py impactful_datasets.jsonld --logo AGU_Logo_H_CMYK.png [-o OUTDIR]

Notes
-----
A static website is produced, as ordinary linked assets rather than one bundle:

    index.html                          markup, with SEO/OpenGraph metadata and a
                                        rel=alternate link to the machine-readable data
    assets/css/tokens.css               design tokens: brand colours, type, logo.
                                        The only file a rebrand needs to touch.
    assets/css/site.css                 component styles
    assets/js/config.js                 deployment settings (data URL, featured record).
                                        Hand-editable after a build.
    assets/js/app.js                    application script
    assets/img/agu-logo.png             brand mark
    data/impactful_datasets.data.jsonld the published collection as schema.org JSON-LD.
                                        This is also the id registry -- keep it in
                                        version control.

The page loads its data over HTTP from data/, so the site must be served, not opened
from disk; it says so on screen if the fetch fails. Serve the output folder with any
static host:  cd out && python3 -m http.server

Each dataset carries an empty "alternateName" -- the short display name shown on the
book spines. Fill those in; the site falls back to "name" while they are blank.

Identifiers. Terms live under urn:org:agu:data:ns:. Records are
urn:org:agu:data:impactful-datasets:id:{type}:{local}, where {type} is dataset,
person, organization or collection. URNs are location-independent, so identifiers
survive the site moving; the resolvable web address is carried alongside on
schema.org/mainEntityOfPage. Nominators keep their ORCID as @id where they have
one -- a real global identifier always beats a minted local one.

Permanent URLs. Every dataset is addressable at #/dataset/agu-0096-optional-slug.
Only the agu-#### id is authoritative; the slug is decoration and is ignored when
parsing, so a stale slug still resolves and is then rewritten. Ids are MINTED ONCE:
each build reads the ids already in the data file and reuses them, so ids survive
title edits, re-sorting and added or withdrawn rows. Never hand-edit or renumber
them -- keep the data file in version control and let it carry the ids forward.

Page 1 groups the books by discipline and lays each group out in uniform rows:
20 books per row on desktop, 14 on tablets, 10 on phones. Rows are rebuilt when the
viewport crosses a breakpoint; edit ROW_SIZES in the embedded JS to change them.

Search runs entirely client-side over a haystack built per book from title,
discipline group, repository, nominators, creators and curators. Matching
normalises accents, apostrophes and dashes. Results are re-packed into full rows,
so a search never leaves half-empty rows behind.

The DataCite panel on page 2 appears only when the registry answers. "Cite this
dataset" calls the DOI Citation Formatter (APA, en-US) and appears for datasets
with a DOI.

The eight discipline colours are anchored on the two brand colours and every one
clears 4.5:1 against the white spine text.
"""
import argparse, base64, collections, csv, hashlib, io, json, re
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("jsonld", type=Path, nargs="?",
                help="the RDF graph; omit it when using --from-data")
ap.add_argument("--logo", type=Path, default=None,
                help="AGU logo PNG; omitted = logo slots render empty")
ap.add_argument("-o", "--outdir", type=Path, default=Path("out"))
ap.add_argument("--featured", default="Argo",
                help="title of the dataset shown on page 2 (default: Argo)")
ap.add_argument("--nominators", type=int, default=0,
                help="distinct nominator count for the tally; 0 = count from the data")
ap.add_argument("--from-data", type=Path, default=None, metavar="FILE",
                help="build the site from a published schema.org file instead of "
                     "the RDF graph. The page fetches the same file at runtime, "
                     "so the markup and the data cannot describe different "
                     "collections.")
ap.add_argument("--data-only", action="store_true",
                help="write the schema.org data file and stop, without building "
                     "the site. Used by the step that produces the JSON-LD.")
ap.add_argument("--credit-logo", type=Path, default=None,
                help="Harbor Light Technologies mark. A local file is embedded "
                     "like the AGU logo; without one the page links the hosted "
                     "copy, which costs a third-party request on every load.")
ap.add_argument("--credit-logo-url", default="https://harborlight.tech/images/logo.png",
                help="used when --credit-logo is not supplied")
ap.add_argument("--feature-image", type=Path, default=None,
                help="photo for the article callout on page 1")
ap.add_argument("--feature-width", type=int, default=360,
                help="px width the feature image is downscaled to; the callout "
                     "renders it at 112px square, so this covers 3x displays")
ap.add_argument("--responsible-party", "--person-review", type=Path,
                default=Path("data/cleanup/responsible_party.csv"),
                help="reviewed classification of Person-typed names "
                     "(from prepare_cleanup.py); absent = every decision ignored")
ap.add_argument("--logo-width", type=int, default=620,
                help="px width the logo is downscaled to before embedding")
ap.add_argument("--data-file", default="impactful_datasets.data.jsonld",
                help="filename for the public schema.org data file")
ap.add_argument("--data-url", default=None,
                help="URL the page fetches the data file from. Defaults to the "
                     "filename above, i.e. served next to the HTML. Set this to an "
                     "absolute https URL once the data file has a permanent home.")
ap.add_argument("--base-url", default="https://data.agu.org/impactful-datasets/",
                help="site URL used to build canonical @id values in the data file")
args = ap.parse_args()
JSONLD = args.jsonld
args.outdir.mkdir(parents=True, exist_ok=True)
OUT = args.outdir / "impactful_datasets_wireframe.html"


def _credit_png():
    """Downscale the credit mark, as for the AGU logo. Self-hosting it keeps the
    page free of third-party requests -- worth having when the page is served
    from somebody else's site."""
    if not args.credit_logo:
        return b""
    from PIL import Image
    im = Image.open(args.credit_logo).convert("RGBA")
    w = 120
    im = im.resize((w, max(1, round(w * im.size[1] / im.size[0]))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _feature_jpg():
    """Downscale the callout photo. The source is a 6048px camera original;
    shipping that would be 4.8 MB for a slot a couple of hundred pixels wide."""
    if not args.feature_image:
        return b""
    from PIL import Image
    im = Image.open(args.feature_image).convert("RGB")
    w = args.feature_width
    im = im.resize((w, round(w * im.size[1] / im.size[0])), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    return buf.getvalue()


def _logo_png():
    """Downscale the brand logo so the embedded copy stays small."""
    if not args.logo:
        return b""
    from PIL import Image
    im = Image.open(args.logo).convert("RGBA")
    w = args.logo_width
    im = im.resize((w, round(w * im.size[1] / im.size[0])), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- inputs ----
# Two ways in. Normally the RDF graph is read and the schema.org data derived
# from it. With --from-data the published schema.org file is the input instead,
# and the site is rendered from that: the page fetches the same file at runtime,
# so building from it guarantees the markup and the data describe one collection
# rather than two derivations that could drift.
if not args.from_data:
    d = json.load(open(JSONLD))
    g = d['@graph']; by = {n['@id']: n for n in g}

    # Discipline groups. Labels are NEVER retyped here -- they are read from the graph,
    # which carries them verbatim from the source spreadsheet, so an abbreviation can
    # never creep in. This map only assigns each group a short key, used to pick its
    # colour in CSS.
    THEME_KEYS = {
        "id:theme:atmospheric-science-space-weather": "atmos",
        "id:theme:ocean-science-hydrology-cryosphere": "ocean",
        "id:theme:global-environmental-change-paleoceanography-and-paleoclimatology-biogeoscience": "biosphere",
        "id:theme:earth-s-interior-geodesy": "interior",
        "id:theme:earth-surface-natural-hazards-geology-near-surface-geophysics": "surface",
        "id:theme:geohealth-society-education": "society",
        "id:theme:space-and-planetary-science": "space",
        "id:theme:earth-planetary-materials": "materials",
        "id:theme:nonlinear-geophysics-machine-learning-informatics": "nonlinear",
    }

    # Groups that are part of the AGU vocabulary but that no nomination has used yet.
    # They belong in the published DefinedTermSet so the taxonomy is complete; the page
    # simply has no shelf to draw for them until a dataset arrives.
    EXTRA_THEMES = [
        ("id:theme:nonlinear-geophysics-machine-learning-informatics",
         "Nonlinear Geophysics, Machine Learning, Informatics", "nonlinear"),
    ]

    # display order: the sequence the groups appear in on the page
    THEME_SEQUENCE = ["atmos", "ocean", "biosphere", "interior", "surface",
                      "society", "space", "materials", "nonlinear"]

    _theme_nodes = {n["@id"]: n.get("prefLabel") for n in g if n.get("@type") == "skos:Concept"}
    unmapped = set(_theme_nodes) - set(THEME_KEYS)
    if unmapped:
        raise SystemExit("discipline group(s) in the graph with no colour key assigned:\n  "
                         + "\n  ".join(sorted(unmapped)))

    THEME_ORDER = [(tid, label, THEME_KEYS[tid]) for tid, label in _theme_nodes.items()]
    THEME_ORDER += [(tid, label, key) for tid, label, key in EXTRA_THEMES
                    if tid not in _theme_nodes]
    THEME_ORDER.sort(key=lambda r: THEME_SEQUENCE.index(r[2]))
    tkey = {t[0]: t[2] for t in THEME_ORDER}
    # verify every theme id resolves
    real = {n['@id'] for n in g if n.get('@type')=='skos:Concept'}
    missing = real - set(tkey)
    assert not missing, f"unmapped themes: {missing}"

    nom_of = {}
    for n in g:
        if 'agu:Nomination' in (n.get('@type') or []):
            nom_of[n['nominates']] = n

    def txt(v, cap=None):
        if v is None: return None
        if isinstance(v, list):
            v = " ".join(txt(x) or "" for x in v)
        elif isinstance(v, dict):
            v = v.get('schema:text') or v.get('name') or ""
        v = str(v).replace('\r\n', '\n').replace('\r', '\n')
        v = re.sub(r'[ \t]+', ' ', v)          # collapse runs of spaces
        v = re.sub(r' *\n *', '\n', v)         # trim around line breaks
        v = re.sub(r'\n{3,}', '\n\n', v).strip()
        return (v[:cap].rsplit(' ', 1)[0] + '…') if cap and len(v) > cap else v

    out = []
    for x in g:
        if 'dcat:Dataset' not in (x.get('@type') or []): continue
        nm = nom_of.get(x['@id'], {})
        # "Short description of how you interact with this dataset", one statement per
        # nominator, carrying the same Nominator N: key as the justification blocks.
        inter = {}
        for s in (nm.get('interactionStatement') or []):
            v = txt(s.get('schema:text'))
            if v:
                inter[str(s.get('sequence') or '')] = v

        # The nominator list is ordered by those same keys, so recover the key for each
        # person from the statements rather than assuming a plain 1..n numbering -- some
        # rows label their nominators 1a, 1b, 1c.
        stmt_keys = {str(s.get('sequence')) for s in (nm.get('justification') or [])
                     if s.get('sequence') is not None}
        stmt_keys |= {k for k in inter}
        ordered = sorted(stmt_keys, key=lambda k: (int(re.match(r'\d+', k).group()) if re.match(r'\d+', k) else 0,
                                                   re.sub(r'^\d+', '', k)))

        # Only attribute a statement to an individual when the labels line up exactly.
        # Four rows write one combined statement for a group of nominators; guessing by
        # position there would put words in the wrong person's mouth.
        roster = nm.get('nominator') or []
        aligned = len(ordered) == len(roster)

        people = []
        for i, pid in enumerate(roster):
            p = by.get(pid, {})
            affs = [by[a]['name'] for a in (p.get('affiliation') or []) if a in by]
            key = ordered[i] if aligned else str(i + 1)
            people.append({"seq": key, "name": p.get('name'),
                           "orcid": pid if pid.startswith('http') else None,
                           "affil": affs[0] if affs else None,
                           "interaction": inter.get(key) if aligned else None})
        just = []
        for j in (nm.get('justification') or []):
            dims = [{"label": dd.get('prefLabel'), "text": txt(dd.get('schema:text'))}
                    for dd in (j.get('impactDimension') or [])]
            just.append({"seq": j.get('sequence'), "text": txt(j.get('schema:text')), "dims": dims})
        lp = x.get('landingPage') or []
        doi = next((u for u in lp if 'doi.org/' in u), None)
        repos = [by[r] for r in (x.get('inCatalog') or []) if r in by]
        refs = [txt(r.get('schema:citation')) for r in (x.get('isReferencedBy') or [])]
        reuse = [txt(r.get('schema:text')) for r in (x.get('reuseExample') or [])]
        out.append({
            "title": x.get('title'),
            # a nomination can name more than one group; keep all of them
            "themes": [tkey[tid] for tid in (x.get('theme') or []) if tid in tkey],
            "nomCount": len(people),
            "nominators": people,
            "doi": doi,
            "links": [u for u in lp if u != doi],
            "repo": repos[0].get('name') if repos else None,
            "repoIds": (repos[0].get('identifier') if repos else None) or [],
            "creators": [c.get('name') for c in (x.get('creator') or [])],
            "curators": [c.get('name') for c in (x.get('curator') or [])],
            "desc": txt(x.get('description')),
            "just": just,
            "refs": refs,
            "reuse": reuse,
            "reuseTotal": len(x.get('reuseExample') or []),
            "refsTotal": len(x.get('isReferencedBy') or []),
        })

    out.sort(key=lambda r: (-r['nomCount'], r['title'].lower()))

    # ---------------------------------------------------------------- permanent ids ----
    # URLs must survive edits, re-ordering and re-runs, so ids are MINTED ONCE and then
    # frozen. Every build reads the ids already published in the data file and reuses
    # them; only genuinely new datasets get a new number, taken from one past the highest
    # ever issued. Ids are never re-used, even if a dataset is withdrawn.
    DATA_PATH = args.outdir / "data" / args.data_file
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)


    def stable_key(rec):
        # Identity of a nomination record, not of the underlying data: three separate
        # nominations can share one DOI (OCO-2/-3 does), and each still needs its own
        # page and its own URL. DOI plus title is therefore the key.
        title = re.sub(r"\s+", " ", (rec.get("title") or "")).strip().lower()
        if rec.get("doi"):
            return "doi:" + rec["doi"].replace("https://doi.org/", "").lower() + "|" + title
        return "title:" + title


    def published_key(item):
        """The stable key of an already-published record.

        Read from its PropertyValue identifier where present. Older files stored it as
        agu:stableKey, and older still not at all, so fall back to recomputing it from
        the DOI and title -- both of which are in the record either way.
        """
        for ident in (item.get("identifier") or []):
            if isinstance(ident, dict) and ident.get("propertyID") == "AGU-Impactful-Datasets-ID-StableKey":
                v = ident.get("value")
                if v:
                    return v
        if item.get("agu:stableKey"):
            return item["agu:stableKey"]
        doi = ""
        for ident in (item.get("identifier") or []):
            if isinstance(ident, dict) and ident.get("propertyID") == "DOI":
                doi = str(ident.get("value") or "")
                break
        if not doi:
            url = str(item.get("url") or "")
            if "doi.org/" in url:
                doi = url
        title = re.sub(r"\s+", " ", str(item.get("name") or "")).strip().lower()
        if doi:
            return "doi:" + doi.replace("https://doi.org/", "").lower() + "|" + title
        return "title:" + title


    known, highest = {}, 0
    if DATA_PATH.exists():
        try:
            prev = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            # The published file is a flat @graph; older ones nested datasets under a
            # "dataset" key. Read both, or a format change silently reissues every id.
            prev_items = [n for n in prev.get("@graph", []) if n.get("@type") == "Dataset"]
            prev_items += [n for n in prev.get("dataset", []) if isinstance(n, dict)]
            for item in prev_items:
                pid = None
                for ident in (item.get("identifier") or []):
                    if isinstance(ident, dict) and ident.get("propertyID") == "AGU-Impactful-Datasets-ID":
                        pid = ident.get("value")
                        break
                if not pid:
                    continue
                highest = max(highest, int(re.sub(r"\D", "", pid) or 0))
                # honour a stored key if an older file has one, else derive it
                known[published_key(item)] = pid
        except Exception as e:                      # a corrupt file must not silently remint
            raise SystemExit("could not read existing ids from %s: %s" % (DATA_PATH, e))
        if not known:
            raise SystemExit(
                "%s exists but no ids could be read from it. Refusing to continue: a "
                "rebuild would reissue every id and break every published URL. Check "
                "the file's shape before re-running." % DATA_PATH)

    # Collisions would silently point two pages at one URL, so fail loudly instead.
    seen_keys = collections.Counter(stable_key(r) for r in out)
    clashes = [k for k, n in seen_keys.items() if n > 1]
    if clashes:
        raise SystemExit("identical stable keys for %d record(s); ids would collide:\n  %s"
                         % (len(clashes), "\n  ".join(clashes[:5])))

    minted = 0
    for rec in out:
        key = stable_key(rec)
        if key in known:
            rec["id"] = known[key]
        else:
            highest += 1
            minted += 1
            rec["id"] = "agu-%04d" % highest
            known[key] = rec["id"]
        rec["stableKey"] = key

    payload = {"themes": [{"key": k, "label": l} for _, l, k in THEME_ORDER], "datasets": out}

    # ------------------------------------------------- public schema.org data file ----
    # One file, fetched by the site and re-usable by anyone else at the same URL.
    # schema.org core terms carry the bibliographic fields; nomination-specific content
    # sits under an "agu:" prefix so the document stays valid JSON-LD.
    THEME_LABELS = {k: l for _, l, k in THEME_ORDER}
    BASE = args.base_url if args.base_url.endswith("/") else args.base_url + "/"

    # AGU term and identifier namespaces. URNs are location-independent, so the
    # identifiers stay valid if the site ever moves; the resolvable web address is
    # carried separately on mainEntityOfPage.
    NS_URN = "urn:org:agu:data:ns:"
    THEME_SET_ID = "urn:org:agu:data:impactful-datasets:id:scheme:discipline-groups"


    def theme_id(key):
        return "urn:org:agu:data:impactful-datasets:id:theme:" + key



    # ---------------------------------------------------------- party typing ----
    # Whether a credited party is a Person, an Organization or an agu:ResponsibleParty
    # is decided here, from the reviewed worksheet. The rules, in order:
    #   * an ORCID means a person, full stop
    #   * otherwise the worksheet decides: a high-confidence organisation becomes an
    #     Organization; a medium-confidence one becomes a ResponsibleParty, because
    #     the evidence does not justify the stronger claim; a low-confidence one stays
    #     a Person; everything else -- uncertain, unparsed, or several entities in one
    #     string -- becomes a ResponsibleParty
    #   * a name absent from the worksheet and lacking an ORCID becomes a
    #     ResponsibleParty: without an identifier there is nothing to support the
    #     stronger claim that it names an individual
    # A filled-in DECISION cell overrides all of it, so the worksheet stays the place
    # where a human ruling is recorded.
    # The rules live in party_typing.py, shared with prepare_cleanup.py. Two copies
    # would drift, and the worksheet would stop describing the build it explains.
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from party_typing import (PARTY_RULES, PARTY_KIND, classify,  # noqa: E402
                              confidence_of, load_review, reason_of)

    REVIEW = load_review(args.responsible_party)
    if REVIEW:
        _decided = sum(1 for _r in REVIEW.values() if (_r.get("DECISION") or "").strip())
        print("party types: %d parties from %s, %d with a recorded decision"
              % (len(REVIEW), args.responsible_party, _decided))
    else:
        # Not fatal, and that is exactly the danger: the build succeeds and the
        # data validates. Only the crediting is worse than intended, which no
        # later step can detect.
        print("party types: no worksheet at %s. Falling back to the heuristics "
              "alone -- every recorded decision is ignored, identified "
              "organisations stay unresolved, and any party without an ORCID "
              "becomes agu:ResponsibleParty. Run prepare_cleanup.py to recreate "
              "the worksheet." % args.responsible_party)

    party_tally = collections.Counter()


    PARTY_LOG = []


    def party(name, orcid=None, is_nominator=False, role="creator", dataset=None):
        """A credited party as a typed node.

        `is_nominator` marks the agent of an EndorseAction. The nomination form asks
        for one person's name, email, ORCID and affiliation, so that agent is a
        person by construction; a missing ORCID means only that they did not supply
        one. Without it, six named researchers who left the field blank would be
        demoted to ResponsibleParty.
        """
        kind, rule = classify(name, orcid, is_nominator, REVIEW)
        row = REVIEW.get(name)

        party_tally[kind] += 1
        node = {"@type": kind, "@id": orcid or urn(PARTY_KIND[kind], name), "name": name}
        PARTY_LOG.append({"name": name, "type": kind, "rule": rule, "role": role,
                          "dataset": dataset, "id": node["@id"],
                          "orcid": orcid or "",
                          "worksheet_action": (row or {}).get("suggested_action", ""),
                          "worksheet_kind": (row or {}).get("suggested_kind", ""),
                          "worksheet_evidence": (row or {}).get("evidence", "")})
        return node


    def urn(kind, local):
        """urn:org:agu:data:impactful-datasets:id:{type}:{local}"""
        s = re.sub(r"[^a-z0-9]+", "-", (local or "").lower()).strip("-")[:70].strip("-")
        return ID_URN + kind + ":" + (s or "unknown")

    ID_URN = "urn:org:agu:data:impactful-datasets:id:"


    def sd_dataset(rec):
        d = {
            "@type": "Dataset",
            "@id": ID_URN + "dataset:" + rec["id"],
            # where this record is actually readable on the web
            "mainEntityOfPage": BASE + "#/dataset/" + rec["id"],
            "identifier": [
                {"@type": "PropertyValue", "propertyID": "AGU-Impactful-Datasets-ID",
                 "value": rec["id"]},
                # The key this record is matched on when ids are reissued: DOI plus
                # title. Published so a rebuild can recover the mapping from the file
                # itself rather than from a side channel.
                {"@type": "PropertyValue", "propertyID": "AGU-Impactful-Datasets-ID-StableKey",
                 "value": rec["stableKey"]},
            ],
            "name": rec["title"],
            # ------------------------------------------------------------------
            # PLACEHOLDER, intentionally empty. This is the short display name used
            # on the book spines on the home page. schema.org/alternateName is the
            # right field: it is the standard term for an additional, alternative
            # name for the same thing, and (unlike "name") it may repeat and may be
            # shorter or longer. Fill it in per dataset -- roughly 24 characters or
            # fewer is what a spine can show. The site falls back to "name" while
            # this is empty, so nothing breaks until it is populated.
            # ------------------------------------------------------------------
            "alternateName": "",
            # schema.org's keywords accepts a DefinedTerm, so each discipline is a
            # reference to a term rather than a repeated free-text label. A nomination
            # can name more than one group, so this is always a list.
            "keywords": [{"@id": theme_id(k)} for k in rec["themes"]],
        }
        if rec.get("desc"):
            d["description"] = rec["desc"]
        if rec.get("doi"):
            d["url"] = rec["doi"]
            d["identifier"].append({"@type": "PropertyValue", "propertyID": "DOI",
                                    "value": rec["doi"]})
        elif rec.get("links"):
            d["url"] = rec["links"][0]
        extra = [u for u in (rec.get("links") or []) if u != d.get("url")]
        if extra:
            d["sameAs"] = extra
        # A nominator often also produced or stewards the dataset they put forward.
        # Where the credited name matches a nominator of this same dataset who gave an
        # ORCID, reuse that ORCID: it is one human, and should be one node. The match
        # is deliberately confined to the same record -- an exact name match across
        # the collection would be far weaker evidence, and names like "Yuan Li" recur.
        orcid_here = {p["name"]: p["orcid"] for p in rec["nominators"]
                      if p.get("name") and p.get("orcid")}
        if rec.get("creators"):
            d["creator"] = [party(n, orcid_here.get(n), role="creator", dataset=rec["title"])
                            for n in rec["creators"] if n]
        if rec.get("curators"):
            # key stays agu:curator; the @context maps it to schema.org/maintainer
            d["agu:curator"] = [party(n, orcid_here.get(n), role="curator", dataset=rec["title"])
                                for n in rec["curators"] if n]
        if rec.get("repo"):
            d["includedInDataCatalog"] = {"@type": "DataCatalog",
                                          "@id": urn("organization", rec["repo"]),
                                          "name": rec["repo"]}
        if rec.get("refs"):
            d["citation"] = [{"@type": "CreativeWork", "text": c} for c in rec["refs"]]
        if rec.get("reuse"):
            # key stays agu:reuseExample; the @context maps it to schema.org/subjectOf
            d["agu:reuseExample"] = [{"@type": "CreativeWork", "text": c} for c in rec["reuse"]]
        return d


    def sd_endorsements(rec):
        """One EndorseAction per nominator, wrapped in an ordered ItemList.

        A nomination is an endorsement: a person vouching for a dataset. Modelling it
        as schema.org/EndorseAction collapses three things that used to be separate
        custom properties -- the nominator, their justification and their description
        of how they use the data -- into the single event they actually describe.

        schema.org has no property linking a Thing to actions already performed on it
        (potentialAction means the opposite), so the actions live as siblings in the
        graph and point back with `object`. Order is carried by an ItemList whose
        itemListElement is an @list, since a plain graph is unordered.
        """
        if not rec.get("nominators"):
            return None
        just = {str(j.get("seq")): j for j in (rec.get("just") or [])}
        ds_id = ID_URN + "dataset:" + rec["id"]
        actions = []
        for n, p in enumerate(rec["nominators"], start=1):
            j = just.get(str(p.get("seq")))
            # a real ORCID beats a minted id, and is what marks the agent a Person
            agent = party(p.get("name"), p.get("orcid"), is_nominator=True,
                          role="nominator", dataset=rec["title"])
            if p.get("affil"):
                agent["affiliation"] = {"@type": "Organization",
                                        "@id": urn("organization", p["affil"]),
                                        "name": p["affil"]}
            # The justification is what this endorsement produced, so it hangs off the
            # action as `result`; its People/Planet/Prosperity tags become `about`,
            # which retires agu:impactDimension.
            result = None
            if j and j.get("text"):
                result = {"@type": "CreativeWork", "text": j["text"]}
                if j.get("dims"):
                    result["about"] = [{"@type": "DefinedTerm", "name": x["label"],
                                        "description": x["text"]} for x in j["dims"]]
            action = {k: v for k, v in {
                "@type": "EndorseAction",
                "@id": "%sendorsement:%s-%d" % (ID_URN, rec["id"], n),
                # The form's own slot label ("1", "1a"): an identifier, not a ranking.
                "identifier": ({"@type": "PropertyValue", "propertyID": "AGU-Nominator-Slot",
                                "value": str(p["seq"])} if p.get("seq") is not None else None),
                "agent": agent,
                "object": {"@id": ds_id},
                # This nominator's account of how they work with this dataset. It belongs
                # on the action, not the agent: the same person can nominate several
                # datasets, and agent nodes share an ORCID @id, so a description there
                # would merge across datasets and become ambiguous.
                "description": p.get("interaction"),
                "result": result,
            }.items() if v is not None}
            actions.append(action)
        return {
            "@type": "ItemList",
            "@id": ID_URN + "endorsements:" + rec["id"],
            "name": "Nominations for " + (rec.get("title") or rec["id"]),
            "itemListOrder": "https://schema.org/ItemListOrderAscending",
            "numberOfItems": len(actions),
            "itemListElement": actions,
        }


    catalog = {
        "@type": "DataCatalog",
        "@id": ID_URN + "collection:impactful-datasets",
        "name": "Impactful Datasets in the Earth, Space, and Environmental Sciences",
        "publisher": {"@type": "Organization", "name": "American Geophysical Union",
                      "url": "https://www.agu.org/"},
        # Who built the collection as a published thing -- the data model, the
        # identifier scheme and the site. Recorded here so the attribution travels
        # with the data rather than living only in a page footer.
        "creator": {"@type": "Person",
                    # identified the same way the nominators are: a real ORCID as the
                    # @id, so the credit resolves and deduplicates against the wider
                    # graph rather than being a bare string
                    "@id": "https://orcid.org/0000-0003-4486-9448",
                    "name": "Adam Shepherd",
                    "email": "adam@harborlight.tech",
                    "identifier": {"@type": "PropertyValue", "propertyID": "ORCID",
                                   "value": "https://orcid.org/0000-0003-4486-9448"},
                    "affiliation": {"@type": "Organization",
                                    "name": "Harbor Light Technologies",
                                    "url": "https://harborlight.tech"}},
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "dateModified": __import__("datetime").date.today().isoformat(),
        # display order of the collection, preserved as an @list (see @context)
        "dataset": [{"@id": ID_URN + "dataset:" + r["id"]} for r in out],
    }

    theme_set = {
        "@type": "DefinedTermSet",
        "@id": THEME_SET_ID,
        "name": "AGU discipline groups",
        "hasDefinedTerm": [
            {"@type": "DefinedTerm",
             "@id": theme_id(k),
             "identifier": k,
             "name": l,
             "inDefinedTermSet": {"@id": THEME_SET_ID}}
            for _, l, k in THEME_ORDER
        ],
    }

    # The two AGU-flavoured keys are documented as real vocabulary terms rather than
    # with a comment inside their @context entry: JSON-LD 1.1 forbids anything but its
    # own keywords in a term definition, and a strict processor rejects the whole
    # document if one appears. Declared here, the definitions are ordinary triples that
    # any consumer can read, and they state the schema.org term each one resolves to.
    vocab = [
        # A single type for whoever answers for a dataset, whether that is an
        # individual, an institution, a standing team or a service desk. Declared a
        # subclass of prov:Agent, which already means "something that bears
        # responsibility for an activity", so consumers reasoning over PROV pick it
        # up without AGU having to redefine anything.
        #
        # Note what is deliberately NOT asserted here: schema:Person and
        # schema:Organization are left alone. Declaring them subclasses of this class
        # would be a global claim -- every Person in every graph, anywhere, would
        # become an AGU responsible party once the graphs were merged. Subsumption is
        # stated only in the direction that is ours to state.
        {"@id": NS_URN + "ResponsibleParty",
         "@type": "owl:Class",
         "rdfs:label": "Responsible Party",
         "rdfs:comment": (
             "A person or organization that has responsibility for a resource. Used "
             "for the parties credited on a nomination \u2014 those who produced a "
             "dataset and those who steward it \u2014 and, in particular, for parties "
             "that cannot be resolved to either a person or an organization: standing "
             "teams, science working groups, service desks and similar collective "
             "bodies named in the nomination form. Typing such a party as "
             "ResponsibleParty records what is actually known instead of guessing "
             "between schema.org/Person and schema.org/Organization."),
         "rdfs:isDefinedBy": {"@id": NS_URN[:-1]},
         "rdfs:subClassOf": {"@id": "http://www.w3.org/ns/prov#Agent"},
         # Pointers to the two schema.org classes a responsible party will usually
         # turn out to be. narrowMatch, not closeMatch: this concept is the broader
         # one -- it also covers the teams, working groups and service desks that are
         # neither a person nor an organization. SKOS mapping relations are
         # documentation, not logic: they carry no entailment, so unlike
         # rdfs:subClassOf this says nothing about anybody else's data. A
         # schema:Person in an unrelated graph is untouched by it.
         "skos:narrowMatch": [{"@id": "https://schema.org/Person"},
                              {"@id": "https://schema.org/Organization"}]},
        {"@id": NS_URN + "curator",
         "@type": "rdf:Property",
         "rdfs:label": "curator",
         "rdfs:comment": (
             "The person, team or programme responsible for stewarding a nominated "
             "dataset: preparing, documenting, quality-checking and maintaining it, and "
             "answering for it over time. Recorded from the nomination form's "
             "\u201cData curator(s)\u201d field, so it names whoever the nominator "
             "credited, which may be an individual, a group or a service desk rather "
             "than a single person. It does not imply authorship of the data. Declared "
             "equivalent to schema.org/maintainer, whose definition \u2014 the party "
             "that manages a dataset and responds to questions about it \u2014 matches "
             "this sense."),
         "rdfs:isDefinedBy": {"@id": NS_URN[:-1]},
         "owl:equivalentProperty": {"@id": "https://schema.org/maintainer"}},
        {"@id": NS_URN + "reuseExample",
         "@type": "rdf:Property",
         "rdfs:label": "reuse example",
         "rdfs:comment": (
             "A documented instance of the nominated dataset being used again beyond "
             "its original purpose: a paper, derived product, operational system, "
             "teaching resource or policy application that a nominator offered as "
             "evidence of the dataset's reach. Each is free text as supplied, "
             "sometimes with a DOI or URL, and is evidence of impact rather than a "
             "formal citation record. Declared equivalent to schema.org/subjectOf, "
             "since each example is a work about the dataset."),
         "rdfs:isDefinedBy": {"@id": NS_URN[:-1]},
         "owl:equivalentProperty": {"@id": "https://schema.org/subjectOf"}},
    ]

    # A flat graph: catalog, discipline vocabulary, datasets, and the endorsement lists
    # as siblings. Endorsements point back at their dataset with `object`, which is how
    # schema.org expects a performed action to relate to the thing acted on -- there is
    # no property for hanging one off the Thing itself.
    nodes = [catalog, theme_set] + vocab
    nodes += [sd_dataset(r) for r in out]
    nodes += [e for e in (sd_endorsements(r) for r in out) if e]

    data_doc = {
        "@context": {
            "@vocab": "https://schema.org/",
            "agu": NS_URN,
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "owl": "http://www.w3.org/2002/07/owl#",
            "prov": "http://www.w3.org/ns/prov#",
            "skos": "http://www.w3.org/2004/02/skos/core#",
            # agu:curator and agu:reuseExample are deliberately NOT aliased here.
            # JSON-LD 1.1 requires a term whose name is in compact-IRI form to expand
            # to the same IRI its prefix would give, so mapping "agu:curator" to
            # schema:maintainer in the context makes the whole document invalid and a
            # conforming processor rejects it. The schema.org equivalence is stated
            # instead on the property definitions in the graph, as a real triple.
            # ordering is not implied by a graph, so the sequences that matter are
            # declared as lists: the collection's display order, and the order of
            # nominators within each dataset's endorsement list
            "dataset": {"@id": "https://schema.org/dataset", "@container": "@list"},
            "itemListElement": {"@id": "https://schema.org/itemListElement",
                                "@container": "@list"},
        },
        "@graph": nodes,
    }
    DATA_PATH.write_text(json.dumps(data_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    # responsible_party.csv is written by prepare_cleanup.py in step 1, from the
    # same shared rules. Writing it here too would change the file under a
    # reviewer mid-review.

    for _k, _n in party_tally.most_common():
        print("party types: %-22s %4d" % (_k, _n))
    print("data file: %s  (%d datasets, %d new id%s minted)"
          % (DATA_PATH, len(out), minted, "" if minted == 1 else "s"))

    if args.data_only:
        # The JSON-LD is the deliverable for this step. The site is built from the
        # same records in a later one, so stopping here keeps the two concerns in
        # separate runs and separate commits.
        raise SystemExit(0)




    DATA = payload
    DATA['featured'] = next((d['id'] for d in DATA['datasets'] if d['title'] == args.featured),
                            DATA['datasets'][0]['id'])
    DATA['nominatorCount'] = args.nominators

else:
    # The site needs remarkably little from Python: four counts for the page
    # metadata and the id of the dataset to open cold. Everything a visitor
    # reads is fetched from the data file by the browser. So these are derived
    # from the published file rather than recomputed from the graph.
    _doc = json.loads(Path(args.from_data).read_text(encoding='utf-8'))
    _nodes = _doc.get('@graph', [])

    def _typed(n, t):
        v = n.get('@type')
        return t in (v if isinstance(v, list) else [v])

    _sets = [n for n in _nodes if _typed(n, 'DefinedTermSet')]
    _terms = _sets[0].get('hasDefinedTerm', []) if _sets else []
    _ds = [n for n in _nodes if _typed(n, 'Dataset')]

    def _agu_id(node):
        for i in (node.get('identifier') or []):
            if isinstance(i, dict) and i.get('propertyID') == 'AGU-Impactful-Datasets-ID':
                return i.get('value')
        return None

    _people = set()
    for _l in _nodes:
        if not _typed(_l, 'ItemList'):
            continue
        for _a in (_l.get('itemListElement') or []):
            _ag = _a.get('agent') or {}
            _k = _ag.get('@id') or (_ag.get('name') or '').strip().lower()
            if _k:
                _people.add(_k)

    payload = {'themes': [{'key': t.get('identifier'), 'label': t.get('name')}
                          for t in _terms],
               'datasets': [{'id': _agu_id(n), 'title': n.get('name')} for n in _ds]}
    out = payload['datasets']
    DATA = payload
    DATA['featured'] = next(
        (x['id'] for x in out if x['title'] == args.featured),
        out[0]['id'] if out else None)
    DATA['nominatorCount'] = len(_people)
    print('site source: %s (%d datasets, %d discipline groups, %d nominators)'
          % (args.from_data, len(out), len(_terms), len(_people)))



HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Impactful Datasets — wireframe</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&family=Lora:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<style>
:root{
  /* AGU brand: primary #244C5A, secondary #007DBA, white ground */
  --primary:#244C5A; --secondary:#007DBA;
  --paper:#FFF; --surface:#FFF; --surface-2:#F5F7F8;
  --ink:#244C5A; --ink-2:#587380; --ink-3:#5E7682;
  --rule:#D5DFE3; --rule-2:#E8EEF0;
  --mark:#007DBA; --mark-bg:#E4F2FA;
  /* discipline ramp, anchored on the two brand colours; all >=4.5:1 vs white */
  --atmos:#007DBA; --ocean:#00778A; --biosphere:#2F7D5C; --interior:#A24B2E;
  --surface-c:#8C6410; --society:#6B4C93; --space:#244C5A; --materials:#6B5B4B;
  --nonlinear:#8E3B63;
  --f-display:'Montserrat','Helvetica Neue',Arial,sans-serif;
  --f-body:'Lora',Georgia,'Times New Roman',serif;
  --f-label:'Montserrat','Helvetica Neue',Arial,sans-serif;
  --f-code:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  --shell:1180px;
  --logo:url("__LOGO_URL__");
}
/* @@END_TOKENS@@ */
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--f-display);
  font-size:15px;line-height:1.6;font-weight:400;-webkit-font-smoothing:antialiased}
h1,h2,h3,h4{margin:0;font-weight:800;letter-spacing:-.024em;line-height:1.14}
p{margin:0 0 .9em}
a{color:inherit}
.shell{max-width:var(--shell);margin:0 auto;padding:0 32px}
.mono{font-family:var(--f-label);font-size:11px;letter-spacing:.06em;text-transform:uppercase}
[class*="label"],.pagemark,.dl dt,.tip dt,.sec>h2,.card>h2,.dc-bar h2,.legend button,
.searchbar .count,.searchbar .clear,.linklist .k,.dim,.just .who,.more,.dc-status,
.group-head .n,.tally span,.readlink,.back{
  font-weight:600}
/* prose runs in Lora */
.masthead .lede,.callout p,.btn-nominate p,.sec p,.just p,.reuse li,.refs li,
.people .aff,.dl dd,.tip dd,.empty p,.repo-sub{font-family:var(--f-body);letter-spacing:0}
.endpoint,.people .oid{font-family:var(--f-code)}

/* ---------- brand header / footer ---------- */
.site{background:#fff;border-bottom:1px solid var(--rule)}
.site .shell{display:flex;align-items:center;gap:32px;height:82px}
.brand{display:flex;align-items:center;text-decoration:none;flex:none}
.logo{display:block;background:var(--logo) no-repeat left center;background-size:contain;
  height:38px;width:128px;print-color-adjust:exact;-webkit-print-color-adjust:exact}
.logo.foot{height:30px;width:101px;opacity:.92}
.site-nav{display:flex;align-items:center;gap:28px;margin-left:auto}
.site-nav a{font-family:var(--f-label);font-size:12px;font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ink-2);text-decoration:none;padding:4px 0;
  border-bottom:2px solid transparent}
.site-nav a:hover{color:var(--primary);border-bottom-color:var(--secondary)}
.site-nav a[aria-current="page"]{color:var(--primary);border-bottom-color:var(--primary)}
.site-foot{border-top:3px solid var(--primary);background:var(--surface-2);margin-top:60px}
.site-foot .shell{display:flex;align-items:center;gap:28px;padding-top:28px;padding-bottom:28px}

.site-foot .credit{margin-left:auto;position:relative}
.site-foot .credit-trigger{display:inline-flex;align-items:center;gap:11px;cursor:pointer}
.site-foot .credit-trigger:focus-visible{outline:2px solid var(--secondary);outline-offset:4px;
  border-radius:4px}
.site-foot .credit-mark{max-width:30px;height:auto;display:block;flex:none}
.site-foot .credit-text{font-family:var(--f-label);font-size:10.5px;font-weight:500;
  letter-spacing:.05em;text-transform:uppercase;color:var(--ink-2);line-height:1.5;text-align:left}
.site-foot .credit-text b{font-weight:600;color:var(--primary)}
.site-foot .credit-trigger:hover .credit-text b{color:var(--secondary)}

/* Opens on hover or on keyboard focus anywhere inside, so the card is reachable
   without a mouse and the pointer can travel into it to use the links. */
.site-foot .credit-card{position:absolute;right:0;bottom:calc(100% + 12px);z-index:70;
  width:252px;display:flex;flex-direction:column;gap:3px;padding:14px 16px;
  background:var(--primary);color:#fff;border-radius:7px;
  box-shadow:0 12px 30px rgba(22,32,42,.3);
  opacity:0;visibility:hidden;transform:translateY(4px);
  transition:opacity .13s ease,transform .13s ease,visibility .13s}
.site-foot .credit:hover .credit-card,
.site-foot .credit:focus-within .credit-card{opacity:1;visibility:visible;transform:none}
.site-foot .credit-card::after{content:"";position:absolute;right:26px;bottom:-5px;
  width:11px;height:11px;background:var(--primary);transform:rotate(45deg)}
.site-foot .credit-card b{font-family:var(--f-display);font-size:15px;font-weight:600;
  letter-spacing:-.01em;text-transform:none}
.site-foot .credit-card .role{font-family:var(--f-body);font-size:12.5px;color:#BBD2DC;
  margin-bottom:7px;text-transform:none;letter-spacing:0}
.site-foot .credit-card a{font-family:var(--f-label);font-size:11px;color:#9CC3D4;
  text-decoration:none;letter-spacing:.02em;text-transform:none;word-break:break-all}
.site-foot .credit-card a:hover{color:#fff;text-decoration:underline}
.site-foot .credit-card a:focus-visible{outline:2px solid #7FC4EA;outline-offset:2px;
  border-radius:3px}
.site-foot p{margin:0;font-family:var(--f-label);font-size:11px;font-weight:500;
  letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);text-align:right}

/* ---------- page frame ---------- */
.page{display:none;padding:44px 0 80px}
.page.active{display:block}
.pagemark{font-family:var(--f-label);font-size:10px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--ink-3);display:flex;align-items:center;gap:10px;margin-bottom:26px}
.pagemark::after{content:"";flex:1;height:1px;background:var(--rule)}

/* ---------- page 1 header ---------- */
.masthead{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:56px;align-items:end;
  padding-bottom:26px;border-bottom:3px solid var(--primary)}
.masthead h1{font-size:clamp(29px,4.1vw,45px);letter-spacing:-.028em;max-width:19ch}
.masthead .lede{margin:18px 0 0;font-size:16.5px;line-height:1.65;color:var(--ink-2);max-width:58ch}
.tally{display:flex;flex-direction:column;gap:12px}
.tally div{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
  border-bottom:1px solid var(--rule-2);padding-bottom:7px}
.tally b{font-size:29px;font-weight:800;letter-spacing:-.025em;color:var(--primary)}
.tally span{font-family:var(--f-label);font-size:10px;letter-spacing:.09em;text-transform:uppercase;
  color:var(--ink-2);text-align:right}

/* ---------- actions ---------- */
.actions{position:relative;display:grid;grid-template-columns:290px minmax(0,1fr);gap:22px;margin:30px 0 46px}
.act{position:relative;background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:22px}
.btn-nominate{display:flex;flex-direction:column;justify-content:space-between;gap:16px;
  background:var(--primary);border-color:var(--primary);color:#fff}
.btn-nominate .cta{display:inline-flex;align-items:center;justify-content:center;gap:9px;width:100%;
  text-decoration:none;box-sizing:border-box;
  background:#fff;color:var(--ink);border:none;border-radius:4px;padding:13px 16px;cursor:pointer;
  font-family:var(--f-display);font-size:15px;font-weight:600;letter-spacing:-.01em}
.btn-nominate .cta{color:var(--primary);font-weight:700}
.btn-nominate .cta:hover{background:#D9E7EE}
.btn-nominate .cta:focus-visible{outline:2px solid #4FB3E8;outline-offset:3px}
.btn-nominate p{color:#BBD2DC;font-size:13.5px;margin:0}
.callout{display:grid;grid-template-columns:112px minmax(0,1fr);gap:22px;align-items:center}
.callout .thumb{width:112px;height:112px;flex:none;display:block;
  border:1px solid var(--rule);border-radius:4px;background:var(--surface-2);
  object-fit:cover;object-position:60% 50%}
.callout h3{font-size:21px;letter-spacing:-.022em;margin-bottom:7px}
.callout p{font-size:14px;color:var(--ink-2);margin-bottom:11px}
.readlink{font-family:var(--f-label);font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--mark);text-decoration:none;border-bottom:1px solid currentColor;padding-bottom:2px}

/* ---------- collection ---------- */
.group{margin-bottom:34px;scroll-margin-top:16px}
.group-head{display:flex;align-items:baseline;gap:12px;margin-bottom:10px}
.group-swatch{width:11px;height:11px;border-radius:2px;flex:none;transform:translateY(1px)}
.group-head h3{font-size:15px;font-weight:600;letter-spacing:-.012em}
.group-empty{margin:0;padding:20px 2px 22px;border-bottom:5px solid var(--rule);
  border-radius:2px;color:var(--ink-3);font-size:14px}

.books{display:grid;grid-template-columns:repeat(20,1fr);gap:5px;align-items:end;
  padding:18px 7px 0;background:linear-gradient(180deg,transparent 0 58%,var(--surface-2) 58%);
  border-bottom:5px solid var(--primary);border-radius:2px;margin-bottom:9px}
.books:last-child{margin-bottom:0}
.book{min-width:0;position:relative;height:190px;border:none;border-radius:3px 3px 0 0;cursor:pointer;
  padding:13px 0 13px;display:flex;align-items:flex-end;justify-content:center;
  transition:transform .13s ease;color:#fff;font-family:var(--f-label);font-size:11.5px;
  font-weight:600;letter-spacing:.012em;overflow:hidden;
  box-shadow:inset -1px 0 0 rgba(0,0,0,.15),inset 1px 0 0 rgba(255,255,255,.13)}
.book span{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;max-height:100%;opacity:1;
  text-shadow:0 1px 2px rgba(0,0,0,.24)}
.book:hover,.book:focus-visible{transform:translateY(-9px);outline:none;
  box-shadow:0 5px 14px rgba(22,32,42,.26)}
.book:focus-visible{box-shadow:0 0 0 2px var(--mark),0 5px 14px rgba(22,32,42,.26)}
.book::after{content:"";position:absolute;left:0;right:0;top:0;height:8px;
  background:rgba(255,255,255,.17);border-radius:3px 3px 0 0}
.legend{display:flex;flex-wrap:wrap;gap:9px;margin:0 0 28px}
.legend button{display:inline-flex;align-items:center;gap:10px;cursor:pointer;border:none;
  border-radius:5px;padding:10px 11px 10px 14px;font-family:var(--f-label);font-size:12px;
  font-weight:600;letter-spacing:.035em;text-transform:uppercase;color:#fff;line-height:1.15;
  box-shadow:0 1px 0 rgba(0,0,0,.13);transition:transform .12s ease,box-shadow .12s ease}
.legend button:hover{transform:translateY(-2px);box-shadow:0 5px 14px rgba(36,76,90,.28)}
.legend button:focus-visible{outline:2px solid var(--primary);outline-offset:3px}
.legend button .c{background:rgba(255,255,255,.24);border-radius:3px;padding:2px 7px;
  font-size:11px;font-variant-numeric:tabular-nums}

/* ---------- impact dimension filter ---------- */
.dimfilter{margin:0 0 22px}
.dimfilter-head{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:9px}
.dimfilter-label{font-family:var(--f-label);font-size:11px;font-weight:600;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink-2)}
.dimfilter-note{font-family:var(--f-body);font-size:12.5px;color:var(--ink-3)}
.dimfilter-row{display:flex;flex-wrap:wrap;gap:9px;align-items:center}
.dimbtn{display:inline-flex;align-items:center;gap:9px;cursor:pointer;border:1px solid var(--rule);
  background:var(--surface);color:var(--ink-2);border-radius:5px;padding:9px 12px;
  font-family:var(--f-label);font-size:12px;font-weight:600;letter-spacing:.035em;
  text-transform:uppercase;line-height:1.15;transition:border-color .12s,color .12s}
.dimbtn:hover{border-color:var(--primary);color:var(--primary)}
.dimbtn:focus-visible{outline:2px solid var(--secondary);outline-offset:3px}
.dimbtn .c{background:var(--surface-2);border:1px solid var(--rule);border-radius:3px;
  padding:2px 7px;font-size:11px;font-variant-numeric:tabular-nums}
.dimbtn[aria-pressed="true"]{background:var(--primary);border-color:var(--primary);color:#fff;
  padding-left:14px}
.dimbtn[aria-pressed="true"] .c{background:rgba(255,255,255,.24);border-color:transparent;color:#fff}
.dimbtn .tick{display:none;font-size:13px;line-height:1}
.dimbtn[aria-pressed="true"] .tick{display:inline}
.dimbtn[disabled]{opacity:.45;cursor:default}
.dimclear{border:none;background:none;cursor:pointer;color:var(--secondary);padding:9px 4px;
  font-family:var(--f-label);font-size:11px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase}
.dimclear:hover{text-decoration:underline}
.dimclear[hidden]{display:none}

/* ---------- search ---------- */
.searchbar{display:flex;align-items:center;gap:14px;height:54px;padding:0 8px 0 17px;
  background:var(--surface);border:1px solid var(--rule);border-radius:6px;margin:0 0 16px}
.searchbar:focus-within{border-color:var(--ink);box-shadow:0 0 0 3px rgba(27,77,184,.11)}
.searchbar input{flex:1;min-width:0;border:none;background:none;outline:none;
  font-family:var(--f-display);font-size:16px;letter-spacing:-.01em;color:var(--ink)}
.searchbar input::placeholder{color:var(--ink-3)}
.searchbar .glyph{font-size:15px;color:var(--ink-3);flex:none;line-height:1}
.searchbar .count{font-family:var(--f-label);font-size:10px;letter-spacing:.07em;
  text-transform:uppercase;color:var(--ink-2);white-space:nowrap;flex:none;
  font-variant-numeric:tabular-nums}
.searchbar .clear{flex:none;border:1px solid var(--rule);background:var(--surface-2);
  border-radius:4px;padding:6px 11px;cursor:pointer;font-family:var(--f-label);font-size:10px;
  letter-spacing:.07em;text-transform:uppercase;color:var(--ink-2)}
.searchbar .clear:hover{border-color:var(--ink);color:var(--ink)}
.searchbar .clear[hidden]{display:none}
.empty{padding:44px 8px;text-align:center;border:1px dashed var(--rule);border-radius:6px;
  background:var(--surface-2)}
.empty p{font-size:15px;color:var(--ink-2);max-width:44ch;margin:0 auto .9em}
.empty b{color:var(--ink);font-weight:600}
[hidden]{display:none!important}

/* ---------- hover bubble ---------- */
.tip.prose{width:360px}
.tip.prose dd{font-size:13px;line-height:1.55;max-height:15em;overflow:hidden}
.tip .hint{display:block;margin-top:10px;font-family:var(--f-label);font-size:9px;
  font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:#9CC3D4}
.people .who-name{background:none;border:none;padding:0;cursor:pointer;text-align:left;
  font:inherit;color:inherit;display:inline-flex;align-items:baseline;gap:7px}
.people .who-name b{border-bottom:1px dashed var(--ink-3)}
.people .who-name:hover b,.people .who-name[aria-expanded="true"] b{border-bottom-color:var(--secondary);color:var(--secondary)}
.people .who-name:focus-visible{outline:2px solid var(--secondary);outline-offset:3px;border-radius:3px}
.people .interaction{margin:9px 0 0;padding:10px 12px;background:var(--surface-2);
  border-left:2px solid var(--secondary);border-radius:0 4px 4px 0;font-family:var(--f-body);
  font-size:13px;line-height:1.55;color:#31505C}
.people .interaction[hidden]{display:none}
.tip{position:fixed;z-index:80;width:310px;background:var(--primary);color:#fff;border-radius:7px;
  padding:14px 16px;box-shadow:0 12px 34px rgba(22,32,42,.32);pointer-events:none;
  opacity:0;transform:translateY(5px);transition:opacity .12s ease,transform .12s ease}
.tip.on{opacity:1;transform:none}
.tip.note{width:360px}
.tip-body{display:none}
.tip.note .tip-body{display:block;max-height:52vh;overflow:hidden;
  -webkit-mask-image:linear-gradient(180deg,#000 86%,transparent);
  mask-image:linear-gradient(180deg,#000 86%,transparent)}
.tip.note dl{display:none}
.tip-body p{margin:0 0 .65em;font-family:var(--f-body);font-size:13px;line-height:1.55;color:#E4EBF0}
.tip-body p:last-child{margin-bottom:0}
.tip-more{margin-top:10px;font-family:var(--f-label);font-size:9.5px;font-weight:600;
  letter-spacing:.08em;text-transform:uppercase;color:#9CC3D4}
.tip h4{font-size:14.5px;font-weight:600;letter-spacing:-.012em;line-height:1.32;margin:0 0 11px}
.tip dl{margin:0;display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 13px}
.tip dt{font-family:var(--f-label);font-size:9px;font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;color:#9CC3D4;padding-top:2px;white-space:nowrap}
.tip dd{margin:0;font-size:12.5px;line-height:1.45;color:#E4EBF0}
.tip .tail{position:absolute;width:11px;height:11px;background:var(--primary);transform:rotate(45deg)}

/* ---------- page 2 ---------- */
.back{display:inline-flex;align-items:center;gap:8px;background:none;border:none;cursor:pointer;
  font-family:var(--f-label);font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-2);padding:0;margin-bottom:24px}
.back:hover{color:var(--mark)}
.d-head{padding-bottom:24px;border-bottom:3px solid var(--primary)}
.d-head h1{font-size:clamp(32px,4.4vw,50px);letter-spacing:-.03em}
.d-head h1[data-len="medium"]{font-size:clamp(28px,3.4vw,38px);letter-spacing:-.026em}
.d-head h1[data-len="long"]{font-size:clamp(24px,2.6vw,30px);letter-spacing:-.02em;
  line-height:1.22;max-width:62ch}
.d-head h1[data-len="xlong"]{font-size:clamp(21px,2vw,25px);letter-spacing:-.014em;
  line-height:1.3;max-width:74ch}
.d-meta{display:flex;flex-wrap:wrap;gap:8px 26px;margin-top:16px;font-family:var(--f-label);
  font-size:11px;color:var(--ink-2)}
.d-meta b{color:var(--ink);font-weight:500}
.d-grid{position:relative;display:grid;grid-template-columns:minmax(0,1.65fr) minmax(0,1fr);
  gap:44px;margin-top:34px;align-items:start}
.sec{margin-bottom:38px}
.sec > h2{font-size:12px;font-family:var(--f-label);font-weight:500;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);padding-bottom:9px;margin-bottom:16px;
  border-bottom:1px solid var(--rule)}
.sec p{font-size:15.5px;color:#31505C;max-width:74ch}
.sec p+p,.just p+p{margin-top:.2em}
.card{position:relative;background:var(--surface);border:1px solid var(--rule);border-radius:6px;
  padding:20px;margin-bottom:20px}
.card > h2{font-size:11px;font-family:var(--f-label);font-weight:500;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:14px}
.just{border-left:2px solid var(--rule);padding:2px 0 2px 18px;margin-bottom:20px;
  scroll-margin-top:20px;transition:border-color .3s ease}
.just.lit{border-left-color:var(--secondary)}
.just-body[hidden]{display:none}
.just-head{display:flex;align-items:baseline;gap:12px;margin-bottom:7px}
.just-more{margin-left:auto;padding:0;background:none;border:none;cursor:pointer;flex:none;
  font-family:var(--f-label);font-size:10px;font-weight:600;letter-spacing:.08em;
  text-transform:uppercase;color:var(--secondary);white-space:nowrap}
.just-more:hover{text-decoration:underline}
.just-more:focus-visible{outline:2px solid var(--secondary);outline-offset:3px;border-radius:3px}
.just .who{font-family:var(--f-label);font-size:10px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--mark);margin-bottom:7px}
.just p{font-size:14.5px;color:#31505C;margin-bottom:.7em}
.dims{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.dim{font-family:var(--f-label);font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;
  background:var(--surface-2);border:1px solid var(--rule);border-radius:99px;padding:3px 10px;color:var(--ink-2)}
.people{list-style:none;margin:0;padding:0}
.people li{padding:12px 0;border-top:1px solid var(--rule-2)}
.people li:first-child{border-top:none;padding-top:0}
.people b{display:block;font-size:14.5px;font-weight:600;letter-spacing:-.01em}
.people .aff{font-size:12.5px;color:var(--ink-2);line-height:1.45;margin-top:2px}
.people .oid{font-family:var(--f-label);font-size:10px;color:var(--ink-3);margin-top:4px;display:block;
  word-break:break-all}
.linklist{list-style:none;margin:0;padding:0}
.linklist li{border-top:1px solid var(--rule-2)}
.linklist li:first-child{border-top:none}
.linklist a{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 0;
  text-decoration:none;font-size:13.5px;word-break:break-all}
.linklist a:hover{color:var(--mark)}
.linklist .k{font-family:var(--f-label);font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;
  color:var(--ink-3);flex:none}
.reuse{list-style:none;margin:0;padding:0;counter-reset:r}
.reuse li{position:relative;padding:0 0 14px 30px;font-size:14px;color:#31505C;counter-increment:r}
.reuse li::before{content:counter(r,decimal-leading-zero);position:absolute;left:0;top:1px;
  font-family:var(--f-label);font-size:10px;color:var(--ink-3)}
.refs{list-style:none;margin:0;padding:0}
.refs li{padding:11px 0;border-top:1px solid var(--rule-2);font-size:13px;color:var(--ink-2);line-height:1.5}
.refs li:first-child{border-top:none}
.refs a{color:var(--secondary);text-decoration:none;word-break:break-all}
.refs a:hover{text-decoration:underline}
.more{font-family:var(--f-label);font-size:10px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-3);margin-top:10px}

/* ---------- nominator cross-links ---------- */
.just .who{display:inline-flex;align-items:center;gap:7px;background:none;border:none;padding:0;
  cursor:pointer;text-align:left}
.just .who .nm{color:var(--secondary);border-bottom:1px dotted var(--secondary)}
.just .who:hover .nm,.just .who:focus-visible .nm{border-bottom-color:currentColor}
.just .who:focus-visible{outline:2px solid var(--secondary);outline-offset:3px;border-radius:3px}
.just .who .seq{font-size:9.5px;background:var(--surface-2);border:1px solid var(--rule);
  border-radius:99px;padding:1px 7px;color:var(--ink-2)}
.people li{transition:background .3s ease,box-shadow .3s ease;border-radius:5px;
  scroll-margin-top:20px}
.people li.lit{background:var(--mark-bg);box-shadow:0 0 0 6px var(--mark-bg)}
.people .jump{display:inline-block;margin-top:6px;font-family:var(--f-label);font-size:10px;
  font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--secondary);
  background:none;border:none;padding:0;cursor:pointer}
.people .jump:hover{text-decoration:underline}

/* ---------- cite button + modal ---------- */
.citebtn{display:inline-flex;align-items:center;justify-content:center;gap:8px;width:100%;
  margin-top:14px;padding:11px 14px;cursor:pointer;background:var(--primary);color:#fff;border:none;
  border-radius:5px;font-family:var(--f-label);font-size:11px;font-weight:600;letter-spacing:.08em;
  text-transform:uppercase}
.citebtn:hover{background:#1B3B47}
.citebtn:focus-visible{outline:2px solid var(--secondary);outline-offset:3px}
.modal[hidden]{display:none}
.modal{position:fixed;inset:0;z-index:90;display:flex;align-items:center;justify-content:center;
  padding:24px;background:rgba(20,44,54,.55)}
.modal-box{background:#fff;border-radius:8px;width:min(620px,100%);max-height:82vh;overflow:auto;
  box-shadow:0 24px 60px rgba(16,40,50,.34);padding:26px 28px}
.modal-box h3{font-size:19px;letter-spacing:-.02em;margin-bottom:4px}
.modal-src{font-family:var(--f-label);font-size:10px;font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:16px}
.cite-out{font-family:var(--f-body);font-size:15px;line-height:1.62;color:var(--ink);
  background:var(--surface-2);border:1px solid var(--rule);border-radius:6px;padding:16px 18px;
  word-break:break-word}
.cite-out a{color:var(--secondary)}
.modal-acts{display:flex;gap:9px;margin-top:16px}
.modal-acts button{cursor:pointer;border-radius:5px;padding:9px 15px;font-family:var(--f-label);
  font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase}
.btn-copy{background:var(--secondary);color:#fff;border:none}
.btn-close{background:#fff;color:var(--ink-2);border:1px solid var(--rule);margin-left:auto}
.btn-copy:focus-visible,.btn-close:focus-visible{outline:2px solid var(--primary);outline-offset:2px}

/* ---------- datacite panel ---------- */
.dc{border-color:var(--mark);background:#FBFCFE}
.dc-bar{display:flex;align-items:center;gap:9px;margin-bottom:13px}
.dc-bar h2{font-size:11px;font-family:var(--f-label);font-weight:500;letter-spacing:.12em;
  text-transform:uppercase;color:var(--mark);margin:0}
.dc-status{margin-left:auto;font-family:var(--f-label);font-size:9px;letter-spacing:.08em;
  text-transform:uppercase;padding:2px 7px;border-radius:99px;border:1px solid var(--rule);color:var(--ink-3)}
.dc-status[data-s="live"]{color:#0B6B4F;border-color:#9AD3BE;background:#EAF7F1}
.endpoint{font-family:var(--f-label);font-size:10px;color:var(--ink-2);background:var(--surface-2);
  border:1px solid var(--rule-2);border-radius:4px;padding:7px 9px;margin-bottom:14px;word-break:break-all}
.dl{margin:0;font-size:13.5px}
.dl div{display:grid;grid-template-columns:96px minmax(0,1fr);gap:12px;padding:8px 0;
  border-top:1px solid var(--rule-2)}
.dl div:first-child{border-top:none}
.dl dt{font-family:var(--f-label);font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-3);padding-top:3px}
.dl dd{margin:0;line-height:1.5}

@media (max-width:940px){
  .masthead,.actions,.d-grid{grid-template-columns:minmax(0,1fr);gap:26px}
  .shell{padding:0 20px}
  .callout{grid-template-columns:70px minmax(0,1fr);gap:16px}
  .site-foot .shell{flex-wrap:wrap;gap:18px}
  .site-foot .tally-line{width:100%;order:3}
  .site-foot .credit{margin-left:auto}
  .callout .thumb{width:70px;height:70px}
  .books{gap:4px;padding:16px 5px 0}
  .book{height:158px;font-size:11px}
  .tip{width:min(310px,calc(100vw - 32px))}
  .tip.note{width:min(360px,calc(100vw - 32px))}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media print{
  .site{border-bottom:2px solid var(--primary)}
  .page{display:block!important;padding:0 0 40px;break-after:page}
  body{background:#fff}
}
</style>
</head>
<body>

<header class="site">
  <div class="shell">
    <a class="brand" href="#" data-go="collection" onclick="return false"
       aria-label="American Geophysical Union — home">
      <span class="logo" role="img" aria-label="AGU — Advancing Earth and Space Sciences"></span>
    </a>
    <nav class="site-nav">
      <a href="#" id="nav-collection" data-go="collection" aria-current="page"
         onclick="return false">Impactful Datasets</a>
      <a href="https://data.agu.org/2026/08/19/Impactful-Datasets.html"
         target="_blank" rel="noopener">About the project</a>
      <a href="https://docs.google.com/forms/d/e/1FAIpQLSf0Tlb1a29C2I-lNyl8qf_1oG1tFBosYW5qGBBj70D42Nhn_w/viewform" target="_blank" rel="noopener">Nominate</a>
    </nav>
  </div>
</header>

<!-- ============ PAGE 1 ============ -->
<main class="page active" id="page-collection">
<div class="shell">

  <header class="masthead">
    <div>
      <h1>Impactful Datasets in the Earth, Space, and Environmental Sciences</h1>
      <p class="lede">The American Geophysical Union (AGU) is celebrating and highlighting the
      many impactful datasets that support the broad spectrum of research, analysis, and decision
      making by our community. The creation, stewardship, and use of these impactful datasets
      should be broadly recognized.</p>
    </div>
    <div class="tally">
      <div><b id="t-ds">0</b><span>Datasets</span></div>
      <div><b id="t-th">0</b><span>Discipline groups</span></div>
      <div><b id="t-nm">0</b><span>Nominators</span></div>
    </div>
  </header>

  <section class="actions">
    <div class="act btn-nominate">
      <div>
        <h3 style="font-size:18px;margin-bottom:8px">Know one we're missing?</h3>
        <p>Nominations stay open. It takes about ten minutes.</p>
      </div>
      <a class="cta" href="https://docs.google.com/forms/d/e/1FAIpQLSf0Tlb1a29C2I-lNyl8qf_1oG1tFBosYW5qGBBj70D42Nhn_w/viewform" target="_blank" rel="noopener">Nominate a dataset →</a>
    </div>
    <div class="act callout">
      <img class="thumb" src="assets/img/story-feature.jpg"
           alt="A researcher points to energy-balance closure plots on a conference poster.">
      <div>
        <h3>The Story Behind the Nominations</h3>
        <p>How a community took a simple idea and manifested a global effort recognizing
        Earth, space, and environmental science datasets that are impactful for research,
        decision makers, and everyday life.</p>
        <a class="readlink" href="https://doi.org/10.1029/2026AV002623"
           target="_blank" rel="noopener">Read the article →</a>
      </div>
    </div>
  </section>

  <div class="searchbar">
      <span class="glyph" aria-hidden="true">&#9906;</span>
      <input id="q" type="search" autocomplete="off" spellcheck="false"
        aria-label="Search datasets by title, discipline, repository or nominator"
        placeholder="Search titles, disciplines, repositories, nominators…">
      <span class="count" id="q-count"></span>
      <button class="clear" id="q-clear" hidden>Clear</button>
  </div>
  <div class="dimfilter" id="dimfilter" hidden>
    <div class="dimfilter-head">
      <span class="dimfilter-label">Nominated for its effect on</span>
      <span class="dimfilter-note" id="dim-note"></span>
    </div>
    <div class="dimfilter-row" id="dim-row"></div>
  </div>
  <div class="legend" id="legend"></div>
  <div id="groups"></div>
    <div class="empty" id="empty" hidden>
      <p>No datasets match <b id="empty-q"></b>.</p>
      <p style="font-size:13.5px">Try a discipline group, a repository, or a nominator's name.</p>
      <button class="clear" style="margin-top:4px" onclick="document.getElementById('q-clear').click()">Clear search</button>
  </div>
</div>
</main>

<!-- ============ PAGE 2 ============ -->
<main class="page" id="page-detail">
<div class="shell">
  <button class="back" data-go="collection">← Back to the collection</button>

  <header class="d-head">
    <h1 id="d-title"></h1>
    <div class="d-meta" id="d-meta"></div>
  </header>

  <div class="d-grid">
    <div>
      <section class="sec">
        <h2>What it is</h2>
        <div id="d-desc"></div>
      </section>

      <section class="sec">
        <h2>Why it was nominated</h2>
        <div id="d-just"></div>
      </section>

      <section class="sec" id="d-reuse-sec">
        <h2>How it has been reused</h2>
        <ol class="reuse" id="d-reuse"></ol>
        <div class="more" id="d-reuse-more"></div>
      </section>

      <section class="sec" id="d-refs-sec">
        <h2>Where It Is Described (Data Paper)</h2>
        <ul class="refs" id="d-refs"></ul>
        <div class="more" id="d-refs-more"></div>
      </section>
    </div>

    <aside>
      <div class="card">
        <h2>Get the data</h2>
        <ul class="linklist" id="d-links"></ul>
        <button class="citebtn" id="citebtn" hidden>Cite this dataset</button>
      </div>

      <div class="card">
        <h2>Held by</h2>
        <div id="d-repo"></div>
      </div>

      <div class="card">
        <h2>Nominated by</h2>
        <ul class="people" id="d-people"></ul>
      </div>

      <div class="card dc" id="d-dc">
        <div class="dc-bar">
          <h2>DataCite record</h2>
          <span class="dc-status" id="dc-status" data-s="idle">idle</span>
        </div>
        <div class="endpoint" id="dc-endpoint"></div>
        <dl class="dl" id="dc-body"></dl>
      </div>
    </aside>
  </div>
</div>
</main>

<footer class="site-foot">
  <div class="shell">
    <span class="logo foot" aria-hidden="true"></span>
    <p class="tally-line">%(datasets)d datasets &middot; %(nominators)d nominators
       &middot; %(themes)d discipline groups</p>
    <div class="credit">
      <span class="credit-trigger" tabindex="0" role="button" aria-describedby="credit-card"
            aria-label="About the builder of this site">
        <img class="credit-mark" src="%(credit_src)s" alt="">
        <span class="credit-text">Designed and built by<br><b>Harbor Light Technologies</b></span>
      </span>
      <div class="credit-card" id="credit-card" role="tooltip">
        <b>Adam Shepherd</b>
        <span class="role">Founder, Harbor Light Technologies</span>
        <a href="https://harborlight.tech" target="_blank" rel="noopener">harborlight.tech</a>
        <a href="mailto:adam@harborlight.tech">adam@harborlight.tech</a>
        <a href="https://orcid.org/0000-0003-4486-9448" target="_blank" rel="noopener">
          orcid.org/0000-0003-4486-9448</a>
      </div>
    </div>
  </div>
</footer>
<!-- build %(build)s -->

<div class="modal" id="citemodal" role="dialog" aria-modal="true"
     aria-labelledby="cite-h" hidden>
  <div class="modal-box">
    <h3 id="cite-h">Cite this dataset</h3>
    <div class="modal-src" id="cite-src"></div>
    <div class="cite-out" id="cite-out"></div>
    <div class="modal-acts">
      <button class="btn-copy" id="cite-copy">Copy citation</button>
      <button class="btn-close" id="cite-close">Close</button>
    </div>
  </div>
</div>

<div class="tip" id="tip" role="tooltip" aria-hidden="true">
  <span class="tail"></span>
  <h4></h4>
  <dl></dl>
  <div class="tip-body"></div>
</div>

<script>
/* The collection is published as a standalone schema.org file so other sites can
   consume it at a stable URL. The page fetches that file; the embedded copy below is
   a fallback so the prototype still opens straight from disk (a file:// page cannot
   fetch a sibling file in most browsers) and so a network blip never blanks the page. */
const DATA_URL = (window.SITE_CONFIG || {}).dataUrl || "__DATA_URL__";
const DATA = {
  themes: [],
  datasets: [],
  featured: (window.SITE_CONFIG || {}).featured || null,
};

/* Discipline comes through as a reference to a DefinedTerm; resolve it to the short
   key the page groups and colours by. THEME_IDS is filled from the DefinedTermSet
   when the published file loads, with the urn tail as a fallback. */
const THEME_IDS = {};
function themeKeysOf(kw){
  const refs = Array.isArray(kw) ? kw : (kw ? [kw] : []);
  return refs.map(ref => {
    const id = ref && (ref["@id"] || ref.identifier || ref);
    if (typeof id !== "string") return null;
    return THEME_IDS[id] || id.split(":").pop() || null;
  }).filter(Boolean);
}

/* The published file is a flat JSON-LD graph: the catalog, the discipline
   vocabulary, the datasets, and one ItemList of EndorseActions per dataset, all as
   siblings. Nominations are endorsements, so each action carries its nominator as
   `agent`, their justification as `result`, and their account of how they use the
   data as `description`; the action points back at the dataset with `object`.
   This walks the graph and rebuilds the per-dataset shape the page renders. */
function attachEndorsements(nodes, rows){
  const byId = {};
  rows.forEach(r => { byId[r.urn] = r; });
  const lists = nodes.filter(n => typeOf(n) === "ItemList");
  const loose = nodes.filter(n => typeOf(n) === "EndorseAction");
  const ordered = [];
  lists.forEach(l => {
    const items = l.itemListElement;
    (Array.isArray(items) ? items : (items && items["@list"]) || []).forEach(a => ordered.push(a));
  });
  (ordered.length ? ordered : loose).forEach(a => {
    const target = a.object && (a.object["@id"] || a.object);
    const row = byId[target];
    if (!row) return;
    const agent = a.agent || {};
    const slot = (a.identifier || {}).value || String(row.nominators.length + 1);
    row.nominators.push({
      seq: slot,
      name: agent.name || null,
      orcid: (agent["@id"] || "").startsWith("http") ? agent["@id"] : null,
      affil: (agent.affiliation || {}).name || null,
      interaction: a.description || null,
    });
    const res = a.result;
    if (res && res.text){
      row.just.push({
        seq: slot,
        text: res.text,
        dims: (Array.isArray(res.about) ? res.about : (res.about ? [res.about] : []))
          .map(x => ({label: x.name, text: x.description})),
      });
    }
  });
  rows.forEach(r => {
    r.nomCount = r.nominators.length;
    r.refsTotal = r.refs.length;
    r.reuseTotal = r.reuse.length;
  });
}

const asArray = v => Array.isArray(v) ? v : (v ? [v] : []);

function typeOf(n){
  const t = n && n["@type"];
  return Array.isArray(t) ? t[0] : t;
}

/* Map a schema.org Dataset from the public file onto the shape the page renders. */
function adopt(sd){
  const idOf = v => (v || []).find(x => x && x.propertyID === "AGU-Impactful-Datasets-ID");
  const doiOf = v => (v || []).find(x => x && x.propertyID === "DOI");
  const doi = doiOf(sd.identifier) ? doiOf(sd.identifier).value : null;
  const links = [];
  if (sd.url && sd.url !== doi) links.push(sd.url);
  (sd.sameAs || []).forEach(u => { if (u !== doi) links.push(u); });
  return {
    id: (idOf(sd.identifier) || {}).value,
    urn: sd["@id"],
    title: sd.name,
    shortName: (sd.alternateName || "").trim(),   // spine label; blank falls back to title
    themes: themeKeysOf(sd.keywords),
    nomCount: 0,                                  // counted from the endorsements
    doi, links: links.slice(0, 3),
    repo: (sd.includedInDataCatalog || {}).name || null,
    creators: (sd.creator || []).map(c => c.name).filter(Boolean),
    curators: asArray(sd["agu:curator"]).map(c => c.name).filter(Boolean),
    desc: sd.description || null,
    // counts are derived, never stored: a stored count can drift from the list
    // it describes, and both lists are complete in the file
    refs: asArray(sd.citation).map(c => c.text).filter(Boolean),
    reuse: asArray(sd["agu:reuseExample"]).map(c => c.text).filter(Boolean),
    // filled in from the endorsement actions once the whole graph is indexed
    nominators: [],
    just: [],
  };
}
const THEME_VAR = {atmos:'--atmos',ocean:'--ocean',biosphere:'--biosphere',
  interior:'--interior',surface:'--surface-c',society:'--society',space:'--space',
  materials:'--materials',nonlinear:'--nonlinear'};
const css = k => getComputedStyle(document.documentElement).getPropertyValue(THEME_VAR[k]).trim();
const esc = s => (s==null?'':String(s)).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
/* Source prose keeps its paragraph breaks; render them as paragraphs rather than one
   wall of text, linkifying bare URLs on the way through. */
const paras = s => (s == null ? '' : String(s)).split(/\n\s*\n|\n/)
  .map(x => x.trim()).filter(Boolean)
  .map(x => `<p>${linkify(esc(x))}</p>`).join('');
// Turn URLs inside already-escaped citation text into links. Safe because esc()
// has removed every angle bracket and quote before this runs.
const linkify = s => s.replace(/https?:\/\/[^\s,;)\]]+/g, u => {
  const trimmed = u.replace(/[.,;:)\]]+$/, '');
  const tail = u.slice(trimmed.length);
  return `<a href="${trimmed}" target="_blank" rel="noopener">${trimmed}</a>${tail}`;
});

/* ---- page 1 ---- */
function paintTally(){
  document.getElementById('t-ds').textContent = DATA.datasets.length;
  document.getElementById('t-th').textContent = DATA.themes.length;
  document.getElementById('t-nm').textContent = countNominators();
}
function countNominators(){
  const seen = new Set();
  DATA.datasets.forEach(d => (d.nominators||[]).forEach(p => {
    const k = p.orcid || (p.name||'').toLowerCase().trim();
    if (k) seen.add(k);
  }));
  return seen.size;
}
paintTally();

/* Books per shelf, by viewport. Phones get 10 so the spines stay wide enough to
   read and tap; the rows are rebuilt when the breakpoint changes. */
const ROW_SIZES = [[640, 10], [940, 14]];
const DEFAULT_ROW = 20;
const perRow = () => (ROW_SIZES.find(([w]) => window.innerWidth <= w) || [0, DEFAULT_ROW])[1];
const groups = document.getElementById('groups');
const INDEX = [];   // one entry per discipline: {key, sec, rows:[{row, books:[{el,hay}]}], chip}
const norm = s => (s==null?'':String(s))
  .normalize('NFD').replace(/[\u0300-\u036f]/g,'')      // fold accents: Martinez == Martínez
  .replace(/[\u2018\u2019\u02bc']/g,'')                 // drop apostrophes: earths == Earth's
  .replace(/[\u2013\u2014]/g,'-')                       // en/em dash -> hyphen
  .toLowerCase();

/* Each discipline is its own section. Books are uniform width, perRow() to a row;
   a group of 29 fills one row of 20 and a second of 9 on desktop, and the short row
   is left short rather than stretched or filled from the next discipline. */
function rebuildBooks(){
  groups.textContent = '';
  INDEX.length = 0;
  legend.textContent = '';
  buildGroups();
  buildLegend();
  buildDimFilter();
}

function buildGroups(){
DATA.themes.forEach(t => {
  const items = DATA.datasets.filter(d => (d.themes || []).includes(t.key));
  const c = css(t.key);
  const sec = document.createElement('section');
  sec.className = 'group';
  sec.id = 'group-' + t.key;
  const entry = {key:t.key, sec, rows:[], books:[], chip:null, label:t.label};
  sec.innerHTML = `<div class="group-head"><span class="group-swatch" style="background:${c}"></span>
    <h3>${esc(t.label)}</h3></div>`;
  {
    items.forEach(d => {
      const b = document.createElement('button');
      b.className = 'book';
      b.style.background = c;
      b.setAttribute('aria-label', `${d.title} — open dataset`);
      b.innerHTML = `<span>${esc(d.shortName || d.title)}</span>`;
      b.addEventListener('click', () => openDataset(d.id));
      b.addEventListener('mouseenter', () => showTip(b, d));
      b.addEventListener('focus', () => showTip(b, d));
      b.addEventListener('mouseleave', hideTip);
      b.addEventListener('blur', hideTip);
      const hay = norm([
        d.title, labelsFor(d), d.repo,
        (d.nominators||[]).map(p => p.name).join(' '),
        (d.creators||[]).join(' '), (d.curators||[]).join(' ')
      ].filter(Boolean).join(' \u00b7 '));
      const dims = new Set();
      (d.just || []).forEach(j => (j.dims || []).forEach(x => {
        if (x && x.label) dims.add(x.label);
      }));
      entry.books.push({el:b, hay, dims});
    });
  }
  if (!entry.books.length){
    const note = document.createElement('p');
    note.className = 'group-empty';
    note.textContent = 'No datasets have been nominated in this group yet.';
    sec.appendChild(note);
  }
  groups.appendChild(sec);
  INDEX.push(entry);
});
}

/* Lay out one discipline's books into rows of `n`, reusing the same button elements
   so listeners survive. `list` is the books to show, which during a search is the
   matching subset -- results are re-packed into full rows from the top, rather than
   left scattered across the rows they happened to start in. */
function buildRows(entry, list, n){
  entry.sec.querySelectorAll('.books').forEach(r => r.remove());
  entry.rows = [];
  for (let i = 0; i < list.length; i += n){
    const row = document.createElement('div');
    row.className = 'books';
    row.style.gridTemplateColumns = `repeat(${n},1fr)`;
    list.slice(i, i + n).forEach(bk => row.appendChild(bk.el));
    entry.rows.push(row);
    entry.sec.appendChild(row);
  }
}

let currentRow = perRow();
window.addEventListener('resize', () => {
  const n = perRow();
  if (n === currentRow) return;   // only relayout when the breakpoint actually changes
  currentRow = n;
  applyFilter();
  hideTip();
});

/* ---- discipline index doubles as navigation ---- */
const legend = document.getElementById('legend');
function buildLegend(){
DATA.themes.forEach(t => {
  const n = DATA.datasets.filter(d => (d.themes || []).includes(t.key)).length;
  const b = document.createElement('button');
  b.style.background = css(t.key);
  b.innerHTML = `${esc(t.label)}<span class="c">${n}</span>`;
  const ie = INDEX.find(e => e.key === t.key);
  if (ie) ie.chip = b;
  b.addEventListener('click', () => {
    const sec = document.getElementById('group-' + t.key);
    if (!sec || sec.hidden) return;
    sec.scrollIntoView({behavior:'smooth', block:'start'});
    const first = sec.querySelector('.book');
    if (first) setTimeout(() => first.focus({preventScroll:true}), 380);
  });
  legend.appendChild(b);
});
}
buildGroups();
buildLegend();

/* ---- impact dimension filter -------------------------------------------
   Three toggles for the People / Planet / Prosperity tags. Only 18 of the 133
   nominations used that scaffolding, so the control states its own coverage
   rather than implying the tags are comprehensive: a reader who filters to 16
   results should understand they are seeing a tagged subset, not a verdict on
   the rest of the collection. Selecting more than one is a union -- "tagged
   People or Planet" -- which is the usual reading of a facet. */
const DIM_ORDER = ['People', 'Planet', 'Prosperity'];
const dimFilter = document.getElementById('dimfilter');
const dimRow = document.getElementById('dim-row');
const dimNote = document.getElementById('dim-note');
const dimOn = new Set();
const DIM_BTN = {};
let dimClearBtn = null;

function buildDimFilter(){
  dimRow.textContent = '';
  const present = DIM_ORDER.filter(d =>
    INDEX.some(e => e.books.some(b => b.dims.has(d))));
  if (!present.length){ dimFilter.hidden = true; return; }
  dimFilter.hidden = false;

  const tagged = new Set();
  INDEX.forEach(e => e.books.forEach(b => { if (b.dims.size) tagged.add(b); }));
  dimNote.textContent = `— tagged on ${tagged.size} of ${total()} nominations`;

  present.forEach(d => {
    const b = document.createElement('button');
    b.className = 'dimbtn';
    b.type = 'button';
    b.setAttribute('aria-pressed', 'false');
    b.innerHTML = `<span class="tick" aria-hidden="true">✓</span>${esc(d)}<span class="c"></span>`;
    b.addEventListener('click', () => {
      if (dimOn.has(d)) dimOn.delete(d); else dimOn.add(d);
      applyFilter();
    });
    DIM_BTN[d] = b;
    dimRow.appendChild(b);
  });

  dimClearBtn = document.createElement('button');
  dimClearBtn.className = 'dimclear';
  dimClearBtn.type = 'button';
  dimClearBtn.textContent = 'Clear';
  dimClearBtn.hidden = true;
  dimClearBtn.addEventListener('click', () => { dimOn.clear(); applyFilter(); });
  dimRow.appendChild(dimClearBtn);
}

/* ---- client-side search ---- */
const qEl = document.getElementById('q'), qCount = document.getElementById('q-count'),
      qClear = document.getElementById('q-clear'), emptyEl = document.getElementById('empty'),
      emptyQ = document.getElementById('empty-q');
const total = () => DATA.datasets.length;

function applyFilter(){
  const raw = qEl.value.trim();
  const terms = norm(raw).split(/\s+/).filter(Boolean);
  const textActive = terms.length > 0;
  const dimActive = dimOn.size > 0;
  const active = textActive || dimActive;
  const n = currentRow;
  let shown = 0;

  const matchesText = bk => !textActive || terms.every(term => bk.hay.includes(term));
  const matchesDims = bk => !dimActive || [...dimOn].some(d => bk.dims.has(d));

  // Facet counts describe what the text search has already narrowed to, not the
  // dimension selection itself -- otherwise selecting People would show 0 next
  // to Planet and the control would look broken.
  const perDim = {};
  DIM_ORDER.forEach(d => { perDim[d] = 0; });
  INDEX.forEach(entry => entry.books.forEach(bk => {
    if (matchesText(bk)) DIM_ORDER.forEach(d => { if (bk.dims.has(d)) perDim[d]++; });
  }));
  Object.entries(DIM_BTN).forEach(([d, btn]) => {
    btn.querySelector('.c').textContent = perDim[d];
    btn.setAttribute('aria-pressed', String(dimOn.has(d)));
    btn.disabled = perDim[d] === 0 && !dimOn.has(d);
  });
  if (dimClearBtn) dimClearBtn.hidden = !dimActive;

  INDEX.forEach(entry => {
    const hits = active
      ? entry.books.filter(bk => matchesText(bk) && matchesDims(bk))
      : entry.books;
    if (entry.books.length) buildRows(entry, hits, n);  // re-packed: results start a new row
    // during a search an empty group drops out; with no search a group with no
    // nominations yet stays visible, so the taxonomy reads as complete
    entry.sec.hidden = active && hits.length === 0;
    if (entry.chip){
      entry.chip.hidden = active && hits.length === 0;
      entry.chip.querySelector('.c').textContent = hits.length;
    }
    shown += hits.length;
  });

  qClear.hidden = !textActive;
  emptyQ.textContent = raw || [...dimOn].join(' or ');
  emptyEl.hidden = shown > 0;
  qCount.textContent = active
    ? `${shown} of ${total()} ${shown === 1 ? 'dataset' : 'datasets'}`
    : `${total()} datasets`;
  hideTip();
}

qEl.addEventListener('input', applyFilter);
qEl.addEventListener('keydown', e => { if (e.key === 'Escape'){ qEl.value=''; applyFilter(); } });
qClear.addEventListener('click', () => { qEl.value=''; applyFilter(); qEl.focus(); });

/* ---- hover bubble ---- */
const tip = document.getElementById('tip');
const tipTitle = tip.querySelector('h4'), tipList = tip.querySelector('dl'),
      tipBody = tip.querySelector('.tip-body'), tipTail = tip.querySelector('.tail');
function showTip(el, d){
  tip.classList.remove('note');
  const names = (d.nominators||[]).map(p => p.name).filter(Boolean);
  const repo = !d.repo ? 'Not recorded'
    : (/^https?:\/\//.test(d.repo) ? d.repo.replace(/^https?:\/\/(www\.)?/,'').replace(/\/$/,'') : d.repo);
  tipTitle.textContent = d.title;
  tipList.innerHTML =
    `<dt>Discipline</dt><dd>${esc(labelsFor(d))}</dd>` +
    `<dt>Repository</dt><dd>${esc(repo)}</dd>` +
    `<dt>Nominated by</dt><dd>${names.length ? esc(names.join(', ')) : 'Not recorded'}</dd>`;
  placeTip(el);
}

function placeTip(el){
  tip.classList.add('on');
  tip.setAttribute('aria-hidden','false');
  const r = el.getBoundingClientRect(), t = tip.getBoundingClientRect();
  const M = 12;
  let left = r.left + r.width/2 - t.width/2;
  left = Math.max(M, Math.min(left, window.innerWidth - t.width - M));
  const above = r.top - t.height - 12;
  const below = r.bottom + 12;
  const placeBelow = above < 60;
  tip.style.left = left + 'px';
  tip.style.top = (placeBelow ? below : above) + 'px';
  const tailX = Math.max(10, Math.min(r.left + r.width/2 - left - 5.5, t.width - 21));
  tipTail.style.left = tailX + 'px';
  tipTail.style.top = placeBelow ? '-5px' : 'auto';
  tipTail.style.bottom = placeBelow ? 'auto' : '-5px';
}
/* Same bubble, prose layout: the nominator's own "short description of how you
   interact with this dataset". Distinct from their justification, which stays
   in full beneath their name in the left column. */
function showProseTip(el, p){
  if (!p || !p.interaction) return;
  tip.classList.add('note');
  tipTitle.textContent = p.name ? `${p.name} — how they use it` : 'How they use it';
  tipBody.innerHTML = paras(p.interaction)
    + (p.interaction.length > 700
        ? '<div class="tip-more">Click the name to read it all</div>' : '');
  placeTip(el);
}
function hideTip(){
  tip.classList.remove('on');
  tip.classList.remove('note');
  tip.setAttribute('aria-hidden','true');
}
window.addEventListener('scroll', hideTip, {passive:true});

/* ---- page 2 ---- */
function openDataset(id, opts){
  const d = DATA.datasets.find(x => x.id === id) || DATA.datasets[0];
  if (!d) return;
  const want = hashFor(d);
  if (location.hash !== want){
    // replace when arriving via a link so Back leaves the site as the user expects;
    // push when the user clicked a book, so Back returns to the collection
    if (opts && opts.fromHash) history.replaceState(null, '', want);
    else history.pushState(null, '', want);
  }
  // long titles step down a size tier so they stay scannable instead of filling
  // the viewport; the tiers roughly track the distribution of titles in the data
  const h1 = document.getElementById('d-title');
  h1.textContent = d.title;
  const n = (d.title || '').length;
  h1.dataset.len = n <= 40 ? 'short' : n <= 90 ? 'medium' : n <= 160 ? 'long' : 'xlong';

  const meta = [];
  if (d.doi) meta.push(`<span>DOI &nbsp;<b>${esc(d.doi.replace('https://doi.org/',''))}</b></span>`);
  meta.push(`<span>Nominated by &nbsp;<b>${d.nomCount}</b></span>`);
  if (d.refsTotal) meta.push(`<span>Cited in &nbsp;<b>${d.refsTotal}</b>&nbsp; publications</span>`);
  if (d.reuseTotal) meta.push(`<span>Reuse examples &nbsp;<b>${d.reuseTotal}</b></span>`);
  document.getElementById('d-meta').innerHTML = meta.join('');
  document.getElementById('d-desc').innerHTML =
    d.desc ? paras(d.desc) : '<p>No description supplied in the nomination.</p>';

  // Match each justification block to the nominator who wrote it, so the reader
  // sees a name rather than "Nominator 2".
  const bySeq = {};
  (d.nominators||[]).forEach(p => { if (p.seq != null) bySeq[p.seq] = p; });
  const multi = (d.nominators||[]).length > 1;
  document.getElementById('d-just').innerHTML = (d.just||[]).map((j,i) => {
    const seq = j.seq || i+1;
    const who = bySeq[seq];
    const dims = (j.dims||[]).map(x => `<span class="dim">${esc(x.label)}</span>`).join('');
    const head = who && who.name
      ? `<button class="who" data-seq="${seq}" aria-label="Show ${esc(who.name)} under Nominated by">
           <span class="nm">${esc(who.name)}</span>${multi?`<span class="seq">Nominator ${seq}</span>`:''}
         </button>`
      : `<div class="who"><span class="nm">Nominator ${seq}</span></div>`;
    // Every block gets the same control. An earlier version only made long ones
    // collapsible, which meant two identical-looking buttons behaved differently
    // depending on a character count the reader could not see.
    return `<div class="just" id="just-${seq}" data-seq="${seq}">
      <div class="just-head">${head}
        <button class="just-more" data-more="${seq}" aria-expanded="true"
                aria-controls="just-body-${seq}">Hide ↑</button>
      </div>
      <div class="just-body" id="just-body-${seq}">${paras(j.text)}</div>
      ${dims?`<div class="dims">${dims}</div>`:''}</div>`;
  }).join('') || '<p>No justification recorded.</p>';

  const rs = document.getElementById('d-reuse-sec');
  if ((d.reuse||[]).length){
    rs.style.display='';
    document.getElementById('d-reuse').innerHTML = d.reuse.map(r => `<li>${esc(r)}</li>`).join('');
    document.getElementById('d-reuse-more').textContent =
      d.reuseTotal > d.reuse.length ? `+ ${d.reuseTotal - d.reuse.length} more in the record` : '';
  } else rs.style.display='none';

  const rf = document.getElementById('d-refs-sec');
  if ((d.refs||[]).length){
    rf.style.display='';
    document.getElementById('d-refs').innerHTML =
      d.refs.map(r => `<li>${linkify(esc(r))}</li>`).join('');
    document.getElementById('d-refs-more').textContent =
      d.refsTotal > d.refs.length ? `+ ${d.refsTotal - d.refs.length} more in the record` : '';
  } else rf.style.display='none';

  const links = [];
  if (d.doi) links.push(['DOI', d.doi]);
  (d.links||[]).forEach(u => links.push(['Site', u]));
  document.getElementById('d-links').innerHTML = links.length
    ? links.map(([k,u]) => `<li><a href="${esc(u)}" target="_blank" rel="noopener">
        <span>${esc(u.replace(/^https?:\/\//,''))}</span><span class="k">${k}</span></a></li>`).join('')
    : '<li style="padding:11px 0;color:var(--ink-3);font-size:13px">No link recorded</li>';

  const repoName = !d.repo ? 'Not recorded'
    : (/^https?:\/\//.test(d.repo) ? d.repo.replace(/^https?:\/\/(www\.)?/,'').replace(/\/$/,'') : d.repo);
  document.getElementById('d-repo').innerHTML =
    `<div style="font-size:15px;font-weight:600;letter-spacing:-.01em">${esc(repoName)}</div>`
    + ((d.curators||[]).length ? `<div style="font-size:12.5px;color:var(--ink-2);margin-top:6px">
        Curated by ${esc(d.curators.join('; '))}</div>` : '')
    + ((d.creators||[]).length ? `<div style="font-size:12.5px;color:var(--ink-2);margin-top:6px">
        Produced by ${esc(d.creators.join('; '))}</div>` : '');

  const hasJust = {};
  (d.just||[]).forEach((j,i) => { hasJust[j.seq || i+1] = true; });
  // A nominator who told us how they use the dataset gets their name turned into a
  // control: hover or focus previews the statement, click pins it open underneath.
  // Hover alone would hide it from keyboard and touch users entirely.
  document.getElementById('d-people').innerHTML = (d.nominators||[]).map((p, i) => {
    const nameHtml = `<b>${esc(p.name || 'Name withheld')}</b>`;
    const head = p.interaction
      ? `<button class="who-name" data-interaction="${i}" aria-expanded="false"
                 aria-controls="interaction-${i}">${nameHtml}</button>`
      : nameHtml;
    return `<li id="nominator-${p.seq}">${head}
      ${p.affil ? `<span class="aff">${esc(p.affil)}</span>` : ''}
      ${p.orcid ? `<span class="oid">${esc(p.orcid)}</span>` : ''}
      ${hasJust[p.seq] ? `<button class="jump" data-jump="${p.seq}">Read their Nomination →</button>` : ''}
      ${p.interaction ? `<div class="interaction" id="interaction-${i}" hidden>${paras(p.interaction)}</div>` : ''}
    </li>`;
  }).join('')
    || '<li style="color:var(--ink-3);font-size:13px">No nominator recorded</li>';

  document.querySelectorAll('#d-people .who-name').forEach(btn => {
    const person = (d.nominators || [])[Number(btn.dataset.interaction)];
    const panel = document.getElementById('interaction-' + btn.dataset.interaction);
    btn.addEventListener('mouseenter', () => { if (panel.hidden) showProseTip(btn, person); });
    btn.addEventListener('focus', () => { if (panel.hidden) showProseTip(btn, person); });
    btn.addEventListener('mouseleave', hideTip);
    btn.addEventListener('blur', hideTip);
    btn.addEventListener('click', () => {
      const open = panel.hidden;
      panel.hidden = !open;
      btn.setAttribute('aria-expanded', String(open));
      hideTip();
    });
  });

  // wire both directions of the link
  document.querySelectorAll('#d-just .who[data-seq]').forEach(b => {
    b.addEventListener('click', () => spotlight(document.getElementById('nominator-' + b.dataset.seq)));
    // the same name in the justification header carries the same hover note
    const person = (d.nominators || []).find(x => String(x.seq) === String(b.dataset.seq));
    if (person && person.interaction){
      b.addEventListener('mouseenter', () => showProseTip(b, person));
      b.addEventListener('focus', () => showProseTip(b, person));
      b.addEventListener('mouseleave', hideTip);
      b.addEventListener('blur', hideTip);
    }
  });

  document.querySelectorAll('#d-just .just-more').forEach(b =>
    b.addEventListener('click', () => setJustOpen(b.dataset.more, !isJustOpen(b.dataset.more), false)));

  // "Read their Nomination" is a one-way link to that nominator's entry in
  // "Why it was nominated". It expands the block first if the reader had collapsed
  // it, so the link never lands on a closed section, then scrolls and highlights.
  // A plain <a href="#just-1"> is deliberately not used: the page routes on the URL
  // fragment, so writing a bare anchor there would knock it back to the collection.
  document.querySelectorAll('#d-people .jump').forEach(b =>
    b.addEventListener('click', () => setJustOpen(b.dataset.jump, true, true)));

  citeDoi = d.doi ? d.doi.replace('https://doi.org/','') : null;
  citeBtn.hidden = !citeDoi;
  if (!citeModal.hidden) closeCite();

  loadDataCite(d);
  show('detail');
  window.scrollTo({top:0});
}

/* One open/close state per justification, shared by the control inside the block and
   the "Read their justification" button in the nominator list, so the two can never
   disagree about whether it is open. A block short enough not to be clamped counts as
   permanently open. */
function justBody(seq){
  const sec = document.getElementById('just-' + seq);
  return sec ? sec.querySelector('.just-body') : null;
}
function isJustOpen(seq){
  const body = justBody(seq);
  return body ? !body.hidden : false;
}
function setJustOpen(seq, open, scroll){
  const sec = document.getElementById('just-' + seq);
  const body = justBody(seq);
  if (!sec || !body) return;
  body.hidden = !open;
  const more = sec.querySelector('.just-more');
  if (more){
    more.textContent = open ? 'Hide ↑' : 'Show ↓';
    more.setAttribute('aria-expanded', String(open));
  }
  if (open && scroll) spotlight(sec);
  else if (!open && scroll) sec.scrollIntoView({behavior:'smooth', block:'center'});
}

/* Full labels for every group a dataset was nominated under. */
function labelsFor(d){
  const by = {};
  DATA.themes.forEach(t => { by[t.key] = t.label; });
  return (d.themes || []).map(k => by[k] || k).join(' · ') || 'Not recorded';
}

/* ---- scroll to a linked element and flash it ---- */
let litTimer;
function spotlight(el, focusEl){
  if (!el) return;
  el.scrollIntoView({behavior:'smooth', block:'center'});
  el.classList.add('lit');
  clearTimeout(litTimer);
  litTimer = setTimeout(() => el.classList.remove('lit'), 1800);
  if (focusEl) setTimeout(() => focusEl.focus({preventScroll:true}), 360);
}

/* ---- Cite this dataset (DOI Citation Formatter, APA / en-US) ---- */
const citeBtn = document.getElementById('citebtn'),
      citeModal = document.getElementById('citemodal'),
      citeOut = document.getElementById('cite-out'),
      citeSrc = document.getElementById('cite-src');
let citeDoi = null, lastFocus = null;

function openCite(){
  if (!citeDoi) return;
  lastFocus = document.activeElement;
  citeModal.hidden = false;
  citeSrc.textContent = 'APA · en-US · via citation.doi.org';
  citeOut.textContent = 'Building citation…';
  document.getElementById('cite-close').focus();
  const url = 'https://citation.doi.org/format?doi=' + encodeURIComponent(citeDoi)
            + '&style=apa&lang=en-US';
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  fetch(url, {signal: ctl.signal})
    .then(r => r.ok ? r.text() : Promise.reject(new Error('HTTP ' + r.status)))
    .then(txt => {
      clearTimeout(timer);
      const clean = txt.trim();
      citeOut.innerHTML = clean ? linkify(esc(clean)) : esc('No citation returned for this DOI.');
    })
    .catch(() => {
      clearTimeout(timer);
      citeSrc.textContent = 'Citation service unavailable';
      citeOut.innerHTML = `The citation formatter could not be reached. The DOI is
        <a href="https://doi.org/${esc(citeDoi)}" target="_blank" rel="noopener">${esc(citeDoi)}</a>.`;
    });
}
function closeCite(){
  citeModal.hidden = true;
  if (lastFocus) lastFocus.focus();
}
citeBtn.addEventListener('click', openCite);
document.getElementById('cite-close').addEventListener('click', closeCite);
citeModal.addEventListener('click', e => { if (e.target === citeModal) closeCite(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !citeModal.hidden) closeCite(); });
document.getElementById('cite-copy').addEventListener('click', e => {
  const txt = citeOut.textContent;
  const done = () => { e.target.textContent = 'Copied'; setTimeout(() => e.target.textContent = 'Copy citation', 1600); };
  if (navigator.clipboard) navigator.clipboard.writeText(txt).then(done).catch(() => {});
  else done();
});

/* ---- DataCite ---- */
function loadDataCite(d){
  const panel = document.getElementById('d-dc');
  if (!d.doi){ panel.style.display='none'; return; }
  panel.style.display='';
  const doi = d.doi.replace('https://doi.org/','');
  const url = 'https://api.datacite.org/dois/' + doi;
  const status = document.getElementById('dc-status');
  const body = document.getElementById('dc-body');
  document.getElementById('dc-endpoint').textContent = 'GET ' + url;
  status.dataset.s = 'idle'; status.textContent = 'fetching…';
  body.innerHTML = '<div><dt>Status</dt><dd>Calling the DataCite registry…</dd></div>';

  const rows = (pairs) => body.innerHTML = pairs
    .filter(([,v]) => v)
    .map(([k,v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join('');

  // If the registry can't be reached, drop the panel entirely rather than
  // falling back to our own record — the page should not imply registry
  // data it does not actually have.
  const fallback = () => { panel.style.display = 'none'; };

  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 6000);
  fetch(url, {headers:{'Accept':'application/vnd.api+json'}, signal:ctl.signal})
    .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
    .then(j => {
      clearTimeout(timer);
      const a = j.data.attributes;
      status.dataset.s = 'live'; status.textContent = 'live from datacite';
      const authors = (a.creators||[]).map(c => esc(c.name)).slice(0,12);
      const relAll = (a.relatedIdentifiers||[])
        .filter(r => /Cites|IsCitedBy|IsReferencedBy|IsSupplementTo/i.test(r.relationType||''));
      const related = relAll.slice(0,6)
        .map(r => `<li>${esc(r.relationType)} · ${esc(r.relatedIdentifier)}</li>`);
      if (relAll.length > related.length)
        related.push(`<li style="color:var(--ink-3)">+ ${relAll.length - related.length} more in the registry</li>`);
      rows([
        ['Title', esc((a.titles||[{}])[0].title || d.title)],
        ['Authors', authors.length
          ? authors.join(', ') + ((a.creators||[]).length > 12 ? ` <span style="color:var(--ink-3)">+${a.creators.length-12} more</span>` : '')
          : '—'],
        ['Publisher', esc(a.publisher && a.publisher.name ? a.publisher.name : a.publisher)],
        ['Published', esc(a.publicationYear)],
        ['Type', esc((a.types||{}).resourceTypeGeneral)],
        ['Version', esc(a.version)],
        ['Citations', a.citationCount != null ? a.citationCount : null],
        [`Related works${relAll.length ? ` (${relAll.length})` : ''}`,
         related.length ? `<ul class="refs" style="margin-top:2px">${related.join('')}</ul>` : null],
      ]);
    })
    .catch(() => { clearTimeout(timer); fallback(); });
}

/* ---- addressable datasets -------------------------------------------------
   Every dataset has a permanent URL of the form

       .../#/dataset/agu-0096
       .../#/dataset/agu-0096-argo      <- same page, slug is decoration

   Only the agu-#### id is authoritative. It is minted once, never re-used and
   never re-derived from position or title, so a URL keeps working when the title
   is edited, the collection is re-sorted, or rows are added or withdrawn. The
   trailing slug is generated for readability and is ignored on the way back in;
   if it is stale or missing the page still resolves, then rewrites the address
   bar to the current slug. Unknown ids fall back to the collection.            */
const ID_RE = /^(agu-\d{4,})/i;

function slugify(s){
  return (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'')
    .replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,48).replace(/-+$/,'');
}
function hashFor(d){
  const slug = slugify(d.shortName || d.title);
  return '#/dataset/' + d.id + (slug ? '-' + slug : '');
}
function parseHash(){
  const m = (location.hash || '').match(/^#\/dataset\/(.+)$/);
  if (!m) return null;
  const id = decodeURIComponent(m[1]).match(ID_RE);
  return id ? id[1].toLowerCase() : null;
}
function routeFromHash(){
  const id = parseHash();
  if (!id){ show('collection'); return; }
  const d = DATA.datasets.find(x => (x.id || '').toLowerCase() === id);
  if (!d){ show('collection'); return; }   // withdrawn or mistyped id
  openDataset(d.id, {fromHash: true});
}
window.addEventListener('hashchange', routeFromHash);

/* ---- routing ---- */
function show(which){
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + which));
  const onCollection = which === 'collection';
  if (onCollection && location.hash)
    history.pushState(null, '', location.pathname + location.search);
  const navHome = document.getElementById('nav-collection');
  if (navHome) navHome.setAttribute('aria-current', onCollection ? 'page' : 'false');
}
document.querySelectorAll('[data-go]').forEach(b => b.addEventListener('click', () => {
  show(b.dataset.go);
  window.scrollTo({top:0});
}));
/* Prefer the published file; fall back to the embedded copy without blocking render. */
function boot(){
  buildDimFilter();
  applyFilter();
  routeFromHash();
}

fetch(DATA_URL, {cache: "no-cache"})
  .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
  .then(doc => {
    // a flat graph, so gather the nodes by type before doing anything with them
    const nodes = doc["@graph"] || (doc.dataset ? [doc] : []);

    // discipline vocabulary first: adopt() needs it to resolve keywords
    const termSet = nodes.find(n => typeOf(n) === "DefinedTermSet")
                 || (doc["agu:themes"] || {});
    const terms = termSet.hasDefinedTerm || [];
    terms.forEach(x => { if (x["@id"]) THEME_IDS[x["@id"]] = x.identifier; });
    if (terms.length)
      DATA.themes = terms.map(x => ({key: x.identifier, label: x.name}));

    const rows = nodes.filter(n => typeOf(n) === "Dataset").map(adopt)
                      .filter(d => d.id && d.title);
    if (!rows.length) throw new Error("no datasets in " + DATA_URL);
    attachEndorsements(nodes, rows);

    // the catalog carries the intended display order as an @list
    const catalog = nodes.find(n => typeOf(n) === "DataCatalog" && n.dataset);
    const listed = catalog ? (catalog.dataset["@list"] || catalog.dataset) : null;
    if (Array.isArray(listed) && listed.length){
      const rank = {};
      listed.forEach((ref, i) => { rank[ref["@id"] || ref] = i; });
      rows.sort((a, b) => (rank[a.urn] ?? 1e6) - (rank[b.urn] ?? 1e6));
    }
    DATA.datasets = rows;
    rebuildBooks();
    paintTally();
  })
  .catch(err => {
    const box = document.getElementById('empty');
    document.getElementById('empty-q').textContent = '';
    box.hidden = false;
    box.innerHTML = `<p><b>The collection could not be loaded.</b></p>
      <p style="font-size:13.5px">Tried <code>${DATA_URL}</code> — ${String(err.message || err)}.
      This page reads its data over HTTP, so it needs to be served rather than opened
      straight from disk. From the site folder, run
      <code>python3 -m http.server</code> and visit the address it prints.</p>`;
  })
  .finally(boot);
</script>
</body>
</html>
"""



LOGO = base64.b64encode(_logo_png()).decode()
# ------------------------------------------------------------- emit the site ----
# The bundle above is one string; split it into linked assets so the result is a
# normal static site: markup, stylesheets, script, image and data as separate files
# that a CDN can cache independently.
SITE = args.outdir
for sub in ("assets/css", "assets/js", "assets/img", "data"):
    (SITE / sub).mkdir(parents=True, exist_ok=True)

if args.from_data:
    # The page fetches this at load, so it has to ship beside the markup.
    import shutil as _shutil
    _dest = SITE / "data" / args.data_file
    if Path(args.from_data).resolve() != _dest.resolve():
        _shutil.copyfile(args.from_data, _dest)

bundle = (HTML
          .replace("__DATA_URL__", args.data_url or ("data/" + args.data_file))
          .replace("__LOGO_URL__", "../img/agu-logo.png"))

style = re.search(r"<style>(.*?)</style>", bundle, re.S).group(1)
script = re.search(r"<script>(.*?)</script>", bundle, re.S).group(1)

# design tokens split from component styles: the tokens file is the brand surface
# anyone rebranding the site needs to touch, and nothing else
tokens, site_css = style.split("/* @@END_TOKENS@@ */", 1)
banner = ("/* Impactful Datasets — %s\n   Generated by build_website.py; edit the "
          "builder, not this file. */\n")
(SITE / "assets/css/tokens.css").write_text(
    banner % "design tokens (brand colours, type, logo)" + tokens.strip() + "\n", encoding="utf-8")
(SITE / "assets/css/site.css").write_text(
    banner % "component styles" + site_css.strip() + "\n", encoding="utf-8")

# deployment-time settings live apart from behaviour, so the data file can be
# repointed at a CDN without touching app.js
config = (
    "/* Deployment settings. Safe to edit by hand after a build.\n"
    "   Counts are deliberately NOT here: they are derived from the data file at\n"
    "   load time, so they can never go stale against it. */\n"
    "window.SITE_CONFIG = {\n"
    '  dataUrl: %s,\n'
    '  featured: %s,   // dataset shown if someone lands on the detail page cold\n'
    "};\n" % (json.dumps(args.data_url or ("data/" + args.data_file)),
               json.dumps(DATA["featured"]))
)
(SITE / "assets/js/config.js").write_text(config, encoding="utf-8")
(SITE / "assets/js/app.js").write_text(
    banner % "application script" + script.strip() + "\n", encoding="utf-8")

logo_bytes = _logo_png()
if logo_bytes:
    (SITE / "assets/img/agu-logo.png").write_bytes(logo_bytes)

feature_bytes = _feature_jpg()
if feature_bytes:
    (SITE / "assets/img/story-feature.jpg").write_bytes(feature_bytes)

credit_bytes = _credit_png()
if credit_bytes:
    (SITE / "assets/img/harbor-light.png").write_bytes(credit_bytes)
    CREDIT_SRC = "assets/img/harbor-light.png"
    print("credit mark: self-hosted (%.0f KB)" % (len(credit_bytes) / 1024))
else:
    CREDIT_SRC = args.credit_logo_url
    print("credit mark: linked from %s -- pass --credit-logo to self-host it"
          % CREDIT_SRC)

body = bundle.split("</head>", 1)[1]
body = re.sub(r"<script>.*?</script>", "", body, flags=re.S).replace("</body>\n</html>", "")

# Distinct nominators, counted here only for the page metadata. The figure the
# visitor sees is computed in the browser from the same data file, so the two
# cannot drift apart.
if args.from_data:
    # already counted from the published file
    NOMINATORS = DATA["nominatorCount"]
else:
    _people = set()
    for _r in out:
        for _p in _r["nominators"]:
            _k = _p.get("orcid") or (_p.get("name") or "").strip().lower()
            if _k:
                _people.add(_k)
    NOMINATORS = len(_people)


# Fingerprint each asset so a rebuild busts whatever the browser is holding.
# Without this a cached script silently outlives the data it was built against --
# exactly the failure that leaves a stale figure on screen.
def fingerprint(rel):
    return hashlib.sha1((SITE / rel).read_bytes()).hexdigest()[:8]


head = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- index.html carries no fingerprint of its own, so ask for revalidation:
     a stale copy would keep pointing at superseded assets. -->
<meta http-equiv="Cache-Control" content="no-cache, must-revalidate">
<title>Impactful Datasets in the Earth, Space, and Environmental Sciences — AGU</title>
<meta name="description" content="A community-nominated collection of the Earth, space and
environmental science datasets that researchers say reshaped their field. Browse %(datasets)d
datasets across %(themes)d discipline groups, nominated by %(nominators)d researchers.">
<meta property="og:title" content="Impactful Datasets — AGU">
<meta property="og:description" content="%(datasets)d datasets nominated by the Earth and space science community.">
<meta property="og:type" content="website">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&family=Lora:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/css/tokens.css?v=%(v_tokens)s">
<link rel="stylesheet" href="assets/css/site.css?v=%(v_site)s">
<link rel="alternate" type="application/ld+json" href="%(data)s" title="Collection metadata (schema.org)">
</head>'''

tail = '''
<script src="assets/js/config.js?v=%(v_config)s"></script>
<script src="assets/js/app.js?v=%(v_app)s" defer></script>
</body>
</html>
'''

BUILD = hashlib.sha1(
    (fingerprint("assets/js/app.js") + fingerprint("assets/css/site.css")
     + (SITE / "data" / args.data_file).read_text(encoding="utf-8")).encode()).hexdigest()[:8]

index = (head + body + tail) % {
    "build": BUILD,
    "datasets": len(out),
    "themes": len(payload["themes"]),
    "credit_src": CREDIT_SRC,
    "nominators": NOMINATORS,
    "data": args.data_url or ("data/" + args.data_file),
    "v_tokens": fingerprint("assets/css/tokens.css"),
    "v_site": fingerprint("assets/css/site.css"),
    "v_config": fingerprint("assets/js/config.js"),
    "v_app": fingerprint("assets/js/app.js"),
}
(SITE / "index.html").write_text(index, encoding="utf-8")

sizes = [("index.html", index.encode()),
         ("assets/css/tokens.css", (SITE / "assets/css/tokens.css").read_bytes()),
         ("assets/css/site.css", (SITE / "assets/css/site.css").read_bytes()),
         ("assets/js/config.js", config.encode()),
         ("assets/js/app.js", (SITE / "assets/js/app.js").read_bytes()),
         ("assets/img/agu-logo.png", logo_bytes),
         ("data/" + args.data_file, (SITE / "data" / args.data_file).read_bytes())]
print("site: %s" % SITE)
for name, blob in sizes:
    print("  %-40s %6.0f KB" % (name, len(blob) / 1024))
print("  serve with:  cd %s && python3 -m http.server" % SITE)
