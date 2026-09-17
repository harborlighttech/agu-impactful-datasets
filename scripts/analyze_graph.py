#!/usr/bin/env python3
"""
Report on the published schema.org collection, and draw its conceptual model.

Reads impactful_datasets.data.jsonld -- the file the site serves and other
systems harvest -- and counts what is actually in it. Every figure is measured
with SPARQL over that file rather than carried forward from an earlier stage, so
the numbers describe what was published rather than what the pipeline intended.

Writes:
    graph_statistics.md      headline counts, datasets per discipline, classes
    graph_statistics.json    the same, machine-readable
    conceptual_model.svg     the model, with counts filled in from the queries

Requirements:
    pip install rdflib

Usage:
    python analyze_graph.py site/data/impactful_datasets.data.jsonld -o reports
"""
import argparse
import collections
import json
from pathlib import Path

from rdflib import Graph, RDF

SCHEMA = "https://schema.org/"
AGU = "urn:org:agu:data:ns:"
PREFIXES = [(SCHEMA, "schema:"), (AGU, "agu:"),
            ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"),
            ("http://www.w3.org/2000/01/rdf-schema#", "rdfs:"),
            ("http://www.w3.org/2002/07/owl#", "owl:"),
            ("http://www.w3.org/2004/02/skos/core#", "skos:"),
            ("http://www.w3.org/ns/prov#", "prov:")]
Q = "PREFIX schema:<%s> PREFIX agu:<%s> " % (SCHEMA, AGU)


def short(uri):
    u = str(uri)
    for full, pre in PREFIXES:
        if u.startswith(full):
            return u.replace(full, pre)
    return u


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

NODES = NODES_PUBLISHED

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
    ap.add_argument("jsonld", type=Path, help="the published schema.org file")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("reports"))
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    g = Graph()
    g.parse(args.jsonld, format="json-ld")

    def one(where):
        for row in g.query(Q + where):
            return int(row[0])
        return 0

    datasets = one("SELECT (COUNT(DISTINCT ?d) AS ?n) WHERE {?d a schema:Dataset}")
    # A nominator is the agent of an endorsement, counted once each: several
    # people put forward more than one dataset and would otherwise be counted
    # twice. The number of nominations is reported separately.
    nominators = one("SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE "
                     "{?a a schema:EndorseAction ; schema:agent ?p}")
    endorsements = one("SELECT (COUNT(DISTINCT ?a) AS ?n) WHERE {?a a schema:EndorseAction}")
    groups = one("SELECT (COUNT(DISTINCT ?t) AS ?n) WHERE "
                 "{?t a schema:DefinedTerm ; schema:inDefinedTermSet ?s}")

    # OPTIONAL, so a discipline group with no datasets is still listed. Saying a
    # group is empty is more useful than leaving it out of the table.
    discipline_rows = list(g.query(Q + """
        SELECT ?name (COUNT(?d) AS ?n) WHERE {
          ?t a schema:DefinedTerm ; schema:inDefinedTermSet ?set ; schema:name ?name .
          OPTIONAL { ?d a schema:Dataset ; schema:keywords ?t }
        } GROUP BY ?t ?name ORDER BY DESC(?n) ?name"""))
    disciplines = [{"group": str(r.name), "datasets": int(r.n)} for r in discipline_rows]

    classes = collections.Counter(short(o) for o in g.objects(None, RDF.type))
    class_rows = [{"class": c,
                   "namespace": c.split(":")[0] if ":" in c else "(none)",
                   "instances": n}
                  for c, n in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0]))]

    stats = {
        "source": args.jsonld.name,
        "triples": len(g),
        "datasets": datasets,
        "nominators": nominators,
        "nominations": endorsements,
        "discipline_groups": groups,
        "disciplines": disciplines,
        "classes": class_rows,
    }
    (args.outdir / "graph_statistics.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    nl = "\n"
    by_ns = collections.Counter(r["namespace"] for r in class_rows)
    md = f"""# Statistics

Measured from `{args.jsonld.name}`, the schema.org file the site serves and other
systems harvest. {len(g):,} triples.

| | |
|---|---|
| Datasets | **{datasets}** |
| Nominators | **{nominators}** |
| Nominations | **{endorsements}** |
| Discipline groups | **{groups}** |

Nominators are counted once each, so there are more nominations than nominators:
some people put forward more than one dataset.

## Datasets per discipline group

| Discipline group | Datasets |
|---|---|
{nl.join(f"| {d['group']} | {d['datasets']} |" for d in disciplines)}

A dataset nominated under two groups counts in both, so the column can total
more than the number of datasets. Groups with no datasets are listed rather than
dropped.

## Classes

Every type asserted in the file, and how many nodes carry it.

| Class | Namespace | Instances |
|---|---|---|
{nl.join(f"| `{c['class']}` | {c['namespace']} | {c['instances']} |" for c in class_rows)}

{nl.join(f"- **{ns}** — {n} class{'es' if n != 1 else ''}" for ns, n in sorted(by_ns.items()))}

A node can carry more than one type, so these do not sum to a node count.
"""
    (args.outdir / "graph_statistics.md").write_text(md, encoding="utf-8")

    # the diagram, with its box labels filled from the same measurements
    pcounts = {
        "person": one("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {?x a schema:Person}"),
        "organizations": one("SELECT (COUNT(DISTINCT ?o) AS ?n) WHERE {?p schema:affiliation ?o}"),
        "endorsements": endorsements,
        "justifications": one("SELECT (COUNT(?r) AS ?n) WHERE "
                              "{?a a schema:EndorseAction ; schema:result ?r}"),
        "impact_dimensions": one("SELECT (COUNT(?d) AS ?n) WHERE {?r schema:about ?d}"),
        "datasets": datasets,
        "repositories": one("SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE "
                            "{?d a schema:Dataset ; schema:includedInDataCatalog ?c}"),
        "themes": groups,
        "responsible": one("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {?x a agu:ResponsibleParty}"),
    }
    (args.outdir / "conceptual_model.svg").write_text(
        build_svg(pcounts, NODES_PUBLISHED, EDGE_LABELS_PUBLISHED,
                  title="Conceptual model of the published Impactful Datasets data",
                  desc="A nomination is a schema.org EndorseAction: its agent is the "
                       "nominator, its object the dataset, and its result the "
                       "justification, tagged with impact dimensions. Datasets carry "
                       "discipline terms as keywords and sit in repository catalogs.",
                  legend=LEGEND_PUBLISHED), encoding="utf-8")

    print(f"{len(g):,} triples in {args.jsonld.name}")
    print(f"  {datasets} datasets · {nominators} nominators · "
          f"{endorsements} nominations · {groups} discipline groups")
    print()
    for d in disciplines:
        print(f"  {d['datasets']:4d}  {d['group']}")
    print()
    for c in class_rows:
        print(f"  {c['instances']:5d}  {c['class']}")
    print()
    for f in ("graph_statistics.md", "graph_statistics.json", "conceptual_model.svg"):
        print(f"wrote {args.outdir / f}")


if __name__ == "__main__":
    main()
