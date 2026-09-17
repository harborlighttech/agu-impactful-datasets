#!/usr/bin/env python3
"""
Analyse the AGU "Impactful Datasets" RDF graph and regenerate:

  * graph_statistics.json   machine-readable counts
  * graph_statistics.md     class table, multi-nominator table, repeat nominators
  * conceptual_model.svg    standalone conceptual-model diagram (light/dark)

All numbers come from SPARQL over the graph, and the diagram labels are
filled from those same query results -- so if the source CSV changes,
re-run restructure_impactful_datasets.py then this, and both the tables
and the drawing follow automatically.

Requirements
------------
    pip install rdflib

Usage
-----
    python analyze_graph.py impactful_datasets.jsonld [-o OUTDIR]
"""
import argparse
import collections
import json
from pathlib import Path

from rdflib import Graph

AGU = "urn:org:agu:data:ns:"
AGU_ID = "urn:org:agu:data:impactful-datasets:id:"
PREFIXES = f"""
PREFIX agu:  <{AGU}>
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct:  <http://purl.org/dc/terms/>
PREFIX s:    <https://schema.org/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

# ---------------------------------------------------------------- queries ----
Q_CLASSES = PREFIXES + """
SELECT ?c (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a ?c } GROUP BY ?c ORDER BY DESC(?n) ?c
"""

Q_COUNT = {
    "datasets":            "SELECT (COUNT(DISTINCT ?d) AS ?n) WHERE { ?d a dcat:Dataset }",
    "nominations":         "SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE { ?x a agu:Nomination }",
    "nominators_distinct": "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?x agu:nominator ?p }",
    "nominator_links":     "SELECT (COUNT(?p) AS ?n) WHERE { ?x agu:nominator ?p }",
    "nominators_orcid":    "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?x agu:nominator ?p "
                           'FILTER(STRSTARTS(STR(?p), "https://orcid.org/")) }',
    "repositories":        "SELECT (COUNT(DISTINCT ?r) AS ?n) WHERE { ?r a s:DataCatalog }",
    "organizations":       "SELECT (COUNT(DISTINCT ?o) AS ?n) WHERE { ?o a s:Organization }",
    "themes":              "SELECT (COUNT(DISTINCT ?t) AS ?n) WHERE { ?t a skos:Concept }",
    "justifications":      "SELECT (COUNT(DISTINCT ?j) AS ?n) WHERE { ?j a agu:JustificationStatement }",
    "impact_dimensions":   "SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE { ?i a agu:ImpactDimension }",
    "source_rows":         "SELECT (COUNT(DISTINCT ?r) AS ?n) WHERE { ?r a agu:SourceRow }",
}

Q_MULTI_NOMINATOR = PREFIXES + """
SELECT ?title (COUNT(?p) AS ?n) WHERE {
  ?nom agu:nominates ?d ; agu:nominator ?p .
  ?d dct:title ?title
} GROUP BY ?d ?title HAVING (COUNT(?p) > 1) ORDER BY DESC(?n) ?title
"""

Q_PER_NOMINATION = PREFIXES + """
SELECT ?nom (COUNT(?p) AS ?n) WHERE { ?nom agu:nominator ?p } GROUP BY ?nom
"""

Q_REPEAT_NOMINATORS = PREFIXES + """
SELECT ?name (COUNT(DISTINCT ?d) AS ?n) WHERE {
  ?nom agu:nominator ?p ; agu:nominates ?d .
  OPTIONAL { ?p s:name ?name }
} GROUP BY ?p ?name HAVING (COUNT(DISTINCT ?d) > 1) ORDER BY DESC(?n) ?name
"""

QNAME = [("agu:", AGU), ("id:", AGU_ID), ("dcat:", "http://www.w3.org/ns/dcat#"),
         ("dct:", "http://purl.org/dc/terms/"), ("schema:", "https://schema.org/"),
         ("skos:", "http://www.w3.org/2004/02/skos/core#"),
         ("prov:", "http://www.w3.org/ns/prov#"),
         ("foaf:", "http://xmlns.com/foaf/0.1/")]


def qname(uri):
    for pfx, ns in QNAME:
        if uri.startswith(ns):
            return pfx + uri[len(ns):]
    return uri


def scalar(g, where):
    for row in g.query(PREFIXES + where):
        return int(row.n)
    return 0


# ------------------------------------------------------------------- SVG ----
# Standalone: no host stylesheet, so colours are inlined and dark mode is an
# explicit media query. Ramp stops are the same ones used in the chat diagram.
RAMPS = {  # name: (light fill, light stroke, light title, light subtitle,
           #        dark fill,  dark stroke,  dark title,  dark subtitle)
    "teal":   ("#E1F5EE", "#0F6E56", "#085041", "#0F6E56", "#085041", "#9FE1CB", "#9FE1CB", "#5DCAA5"),
    "purple": ("#EEEDFE", "#534AB7", "#3C3489", "#534AB7", "#3C3489", "#CECBF6", "#CECBF6", "#AFA9EC"),
    "coral":  ("#FAECE7", "#993C1D", "#712B13", "#993C1D", "#712B13", "#F5C4B3", "#F5C4B3", "#F0997B"),
    "gray":   ("#F1EFE8", "#5F5E5A", "#444441", "#5F5E5A", "#444441", "#D3D1C7", "#D3D1C7", "#B4B2A9"),
}

COLS = {"L": (40, 175), "C": (252, 176), "R": (465, 175)}
ROWS = {1: 40, 2: 140, 3: 240}
BOX_H = 56

# (column, row, ramp, title, count-key, subtitle template)
# The published model. Slots follow the connector topology below: an endorsement
# links a party to a dataset, carries the justification as its result, and the
# justification carries the impact dimensions it was tagged with.
NODES_PUBLISHED = [
    ("L", 1, "teal",   "Person",           "person",           "{n} nominators"),
    ("C", 1, "purple", "EndorseAction",    "endorsements",     "{n} nominations"),
    ("R", 1, "purple", "CreativeWork",     "justifications",   "{n} justifications"),
    ("L", 2, "teal",   "Organization",     "organizations",    "{n} affiliations"),
    ("C", 2, "coral",  "Dataset",          "datasets",         "{n} datasets"),
    ("R", 2, "purple", "DefinedTerm",      "impact_dimensions","{n} impact tags"),
    ("L", 3, "coral",  "DefinedTerm",      "themes",           "{n} discipline groups"),
    ("C", 3, "coral",  "DataCatalog",      "repositories",     "{n} repositories"),
    ("R", 3, "gray",   "ResponsibleParty", "responsible",      "{n} unresolved parties"),
]

# The internal graph, drawn only when no published file is supplied.
NODES_INTERNAL = [
    ("L", 1, "teal",   "Person",          "nominators_distinct", "{n} nominators"),
    ("C", 1, "purple", "Nomination",      "nominations",         "{n} records"),
    ("R", 1, "purple", "Justification",   "justifications",      "{n} statements"),
    ("L", 2, "teal",   "Organization",    "organizations",       "{n} affiliations"),
    ("C", 2, "coral",  "Dataset",         "datasets",            "{n} datasets"),
    ("R", 2, "purple", "ImpactDimension", "impact_dimensions",   "{n} tagged blocks"),
    ("L", 3, "coral",  "Concept",         "themes",              "{n} discipline groups"),
    ("C", 3, "coral",  "Catalog",         "repositories",        "{n} repositories"),
    ("R", 3, "gray",   "SourceRow",       "source_rows",         "{n} verbatim rows"),
]
NODES = NODES_INTERNAL

# straight connectors: (x1, y1, x2, y2)
LINES = [(217, 68, 248, 68), (127, 98, 127, 138), (430, 68, 461, 68),
         (552, 98, 552, 138), (340, 98, 340, 138), (340, 198, 340, 238)]
# bent connectors routed around intervening boxes
PATHS = ["M217 268 L232 268 L232 168 L248 168",
         "M430 180 L446 180 L446 268 L461 268"]
LEGEND = [(40, "teal", "Agents"), (130, "purple", "Nomination and statements"),
          (330, "coral", "Data resources"), (470, "gray", "Provenance")]
LEGEND_PUBLISHED = [(40, "teal", "Agents"), (130, "purple", "Nomination and statements"),
                    (330, "coral", "Data resources"), (470, "gray", "Unresolved party")]


# Property names on the connectors. The relationships are the substance of the
# published model, so they are drawn rather than left to the caption.
EDGE_LABELS_PUBLISHED = [
    (232, 60, "middle", "agent"),
    (133, 120, "start", "affiliation"),
    (446, 60, "middle", "result"),
    (558, 120, "start", "about"),
    (346, 120, "start", "object"),
    (346, 220, "start", "includedInDataCatalog"),
    # both sit on the vertical leg of their bent connector, in the clear band
    # between the second and third rows, so neither overlaps a box
    (238, 214, "start", "keywords"),
    (452, 226, "start", "creator / maintainer"),
]
EDGE_LABELS_INTERNAL = []


def build_svg(counts, nodes=None, edge_labels=None, title=None, desc=None,
              legend=None):
    css = [".bx{stroke-width:.5}", ".t{font:14px sans-serif}",
           ".th{font:500 14px sans-serif}", ".ts{font:12px sans-serif}",
           ".arr{stroke:#5F5E5A;stroke-width:1.5;fill:none}"]
    dark = ["@media (prefers-color-scheme:dark){", ".arr{stroke:#B4B2A9}"]
    for name, v in RAMPS.items():
        css.append(f".f-{name}{{fill:{v[0]};stroke:{v[1]}}}")
        css.append(f".t-{name}{{fill:{v[2]}}}")
        css.append(f".s-{name}{{fill:{v[3]}}}")
        dark.append(f".f-{name}{{fill:{v[4]};stroke:{v[5]}}}")
        dark.append(f".t-{name}{{fill:{v[6]}}}")
        dark.append(f".s-{name}{{fill:{v[7]}}}")
    dark.append("}")

    nodes = nodes or NODES
    edge_labels = edge_labels or []
    css.append(".el{font:9px sans-serif;fill:#5F5E5A}")
    css.append(".elh{font:9px sans-serif;fill:none;stroke:#fff;stroke-width:3px;"
               "stroke-linejoin:round}")
    dark.insert(1, ".el{fill:#B4B2A9}")
    dark.insert(2, ".elh{stroke:#1B1B19}")

    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="680" height="348" '
           'viewBox="0 0 680 348" role="img">',
           "<title>%s</title>" % (title or
               "Conceptual model of the AGU Impactful Datasets RDF graph"),
           "<desc>%s</desc>" % (desc or
               "Nomination links people to datasets. Datasets sit in repository "
               "catalogs and carry discipline themes. Justifications break into "
               "impact dimensions. Every record keeps a source row for provenance."),
           "<style>" + "".join(css) + "".join(dark) + "</style>",
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" '
           'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
           '<path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" '
           'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
           "</marker></defs>"]

    for col, row, ramp, title, key, tmpl in nodes:
        x, w = COLS[col]
        y = ROWS[row]
        cx = x + w / 2
        sub = tmpl.format(n=counts[key])
        out.append(
            f'<rect class="bx f-{ramp}" x="{x}" y="{y}" width="{w}" height="{BOX_H}" rx="8"/>'
            f'<text class="th t-{ramp}" x="{cx:.0f}" y="{y + 20}" text-anchor="middle" '
            f'dominant-baseline="central">{title}</text>'
            f'<text class="ts s-{ramp}" x="{cx:.0f}" y="{y + 38}" text-anchor="middle" '
            f'dominant-baseline="central">{sub}</text>')

    for x1, y1, x2, y2 in LINES:
        out.append(f'<line class="arr" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                   'marker-end="url(#arrow)"/>')
    for d in PATHS:
        out.append(f'<path class="arr" d="{d}" marker-end="url(#arrow)"/>')
    for x, y, anchor, label in edge_labels:
        for cls in ("elh", "el"):          # halo first, then the glyphs on top
            out.append(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}" '
                       f'dominant-baseline="central">{label}</text>')

    for x, ramp, label in (legend or LEGEND):
        out.append(f'<rect class="bx f-{ramp}" x="{x}" y="322" width="10" height="10" rx="2"/>'
                   f'<text class="ts s-{ramp}" x="{x + 16}" y="327" '
                   f'dominant-baseline="central">{label}</text>')
    out.append("</svg>")
    return "\n".join(out)


# ------------------------------------------------------------------ main ----
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jsonld", type=Path, help="path to impactful_datasets.jsonld")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("out"))
    ap.add_argument("--published", type=Path, default=None,
                    help="published schema.org data file. The conceptual model is "
                         "drawn from this when given, since it is the model "
                         "consumers see; without it the diagram falls back to the "
                         "internal RDF graph.")
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    g = Graph()
    g.parse(args.jsonld, format="json-ld")
    print(f"parsed {len(g):,} triples")

    counts = {k: scalar(g, q) for k, q in Q_COUNT.items()}
    classes = [{"class": qname(str(r.c)), "uri": str(r.c), "instances": int(r.n)}
               for r in g.query(Q_CLASSES)]
    multi = [{"title": str(r.title), "nominators": int(r.n)}
             for r in g.query(Q_MULTI_NOMINATOR)]
    repeat = [{"name": str(r.name) if r.name else "(no name)", "datasets": int(r.n)}
              for r in g.query(Q_REPEAT_NOMINATORS)]
    dist = collections.Counter(int(r.n) for r in g.query(Q_PER_NOMINATION))
    dist = {k: dist[k] for k in sorted(dist)}

    stats = {"triples": len(g), "counts": counts, "classes": classes,
             "nominators_per_nomination": dist,
             "datasets_with_multiple_nominators": multi,
             "people_nominating_multiple_datasets": repeat}
    (args.outdir / "graph_statistics.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    # The conceptual model is drawn from the published data file when one is
    # available, because that is the model consumers actually read. The internal
    # graph is a build intermediate with a different shape -- nominations are
    # agu:Nomination there and schema:EndorseAction once published -- so drawing
    # the wrong one would document something nobody sees.
    pub = args.published
    if pub is None:
        for guess in (args.outdir / "data" / "impactful_datasets.data.jsonld",
                      Path("site/data/impactful_datasets.data.jsonld"),
                      Path("data/impactful_datasets.data.jsonld")):
            if guess.exists():
                pub = guess
                break

    if pub and pub.exists():
        pg = Graph()
        pg.parse(pub, format="json-ld")
        P = """PREFIX s:<https://schema.org/> PREFIX agu:<urn:org:agu:data:ns:> """

        def pcount(where):
            for row in pg.query(P + where):
                return int(row[0])
            return 0

        pcounts = {
            "person":            pcount("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {?x a s:Person}"),
            "organizations":     pcount("SELECT (COUNT(DISTINCT ?o) AS ?n) WHERE {?p s:affiliation ?o}"),
            "endorsements":      pcount("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {?x a s:EndorseAction}"),
            "justifications":    pcount("SELECT (COUNT(?r) AS ?n) WHERE {?a a s:EndorseAction; s:result ?r}"),
            "impact_dimensions": pcount("SELECT (COUNT(?d) AS ?n) WHERE {?r s:about ?d}"),
            "datasets":          pcount("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {?x a s:Dataset}"),
            "repositories":      pcount("SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {?d a s:Dataset; s:includedInDataCatalog ?c}"),
            "themes":            pcount("SELECT (COUNT(DISTINCT ?t) AS ?n) WHERE {?t a s:DefinedTerm; s:inDefinedTermSet ?s}"),
            "responsible":       pcount("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {?x a agu:ResponsibleParty}"),
        }
        svg = build_svg(
            pcounts, NODES_PUBLISHED, EDGE_LABELS_PUBLISHED,
            title="Conceptual model of the published Impactful Datasets data",
            desc="A nomination is a schema.org EndorseAction: its agent is the "
                 "nominator, its object the dataset, and its result the "
                 "justification, which is tagged with impact dimensions. Datasets "
                 "carry discipline terms as keywords and sit in repository "
                 "catalogs. Parties that resolve to neither a person nor an "
                 "organization are typed ResponsibleParty.",
            legend=LEGEND_PUBLISHED)
        print("conceptual model drawn from %s (published schema.org model)" % pub)
    else:
        svg = build_svg(counts, NODES_INTERNAL, EDGE_LABELS_INTERNAL)
        print("conceptual model drawn from the internal graph "
              "(no published data file found)")
    (args.outdir / "conceptual_model.svg").write_text(svg, encoding="utf-8")

    nl = "\n"
    md = f"""# Graph statistics — AGU Impactful Datasets

Source graph: `{args.jsonld.name}` — {len(g):,} triples.

## Headline counts

| Measure | Value |
|---|---|
| Datasets (`dcat:Dataset`) | {counts['datasets']} |
| Nominations (`agu:Nomination`) | {counts['nominations']} |
| Distinct nominators | {counts['nominators_distinct']} |
| Nominator links (non-distinct) | {counts['nominator_links']} |
| Nominators identified by ORCID | {counts['nominators_orcid']} |
| Repositories (`schema:DataCatalog`) | {counts['repositories']} |
| Organizations (affiliations) | {counts['organizations']} |
| Discipline groups (`skos:Concept`) | {counts['themes']} |

Nominators per nomination: `{dist}`

## Classes and instance counts

| Class | Instances |
|---|---|
{nl.join(f"| `{c['class']}` | {c['instances']} |" for c in classes)}

Several nodes are deliberately dual-typed (`dcat:Dataset` + `schema:Dataset`,
`schema:Person` + `foaf:Person`), so these rows are not disjoint and do not sum
to a node count.

## Datasets with more than one nominator ({len(multi)} of {counts['datasets']})

| Nominators | Dataset |
|---|---|
{nl.join(f"| {m['nominators']} | {m['title']} |" for m in multi)}

## People nominating more than one dataset ({len(repeat)})

| Datasets | Nominator |
|---|---|
{nl.join(f"| {p['datasets']} | {p['name']} |" for p in repeat)}
"""
    (args.outdir / "graph_statistics.md").write_text(md, encoding="utf-8")

    print(f"datasets {counts['datasets']} | distinct nominators "
          f"{counts['nominators_distinct']} | links {counts['nominator_links']} | "
          f"classes {len(classes)}")
    print(f"\nwrote:\n  {args.outdir / 'graph_statistics.md'}"
          f"\n  {args.outdir / 'graph_statistics.json'}"
          f"\n  {args.outdir / 'conceptual_model.svg'}")


if __name__ == "__main__":
    main()
