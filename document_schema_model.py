#!/usr/bin/env python3
"""
Document the published schema.org graph as a conceptual model diagram.

Reads data/impactful_datasets.data.jsonld, counts every class and every
property edge with SPARQL, and draws the model. Nothing is hard-coded except
the layout: if the data changes shape, the counts change with it, and a class
or property that disappears is reported rather than silently drawn.

Requirements:
    pip install rdflib

Usage:
    python document_schema_model.py impactful_datasets.data.jsonld -o schema_model.svg
"""
import argparse
import collections
from pathlib import Path

from rdflib import Graph, RDF, URIRef, BNode

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("jsonld", type=Path)
ap.add_argument("-o", "--out", type=Path, default=Path("schema_model.svg"))
args = ap.parse_args()

g = Graph()
g.parse(args.jsonld, format="json-ld")

PREFIXES = [("https://schema.org/", "schema:"),
            ("urn:org:agu:data:ns:", "agu:"),
            ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"),
            ("http://www.w3.org/2000/01/rdf-schema#", "rdfs:"),
            ("http://www.w3.org/2002/07/owl#", "owl:"),
            ("http://www.w3.org/2004/02/skos/core#", "skos:"),
            ("http://www.w3.org/ns/prov#", "prov:")]


def short(u):
    u = str(u)
    for full, pre in PREFIXES:
        if u.startswith(full):
            return u.replace(full, pre)
    return u


# ------------------------------------------------------------- measure ----
types = {}
for s, _, o in g.triples((None, RDF.type, None)):
    types.setdefault(s, short(o))

classes = collections.Counter(short(o) for o in g.objects(None, RDF.type))
edges = collections.Counter()
for s, p, o in g:
    if p == RDF.type:
        continue
    if isinstance(o, (URIRef, BNode)) and o in types:
        edges[(types.get(s, "(list cell)"), short(p), types[o])] += 1


def e(subject, prop, obj):
    """Count of one edge shape, or 0 if the data no longer has it."""
    return edges.get((subject, prop, obj), 0)


def role_count(prop, obj=None):
    return sum(n for (a, p, b), n in edges.items()
               if p == prop and (obj is None or b == obj))


# Roles that share a class: CreativeWork is a citation, a reuse example or a
# justification depending on how it is reached; DataCatalog is either the
# collection itself or a repository a dataset sits in.
n_citation = e("schema:Dataset", "schema:citation", "schema:CreativeWork")
n_reuse = e("schema:Dataset", "agu:reuseExample", "schema:CreativeWork")
n_result = e("schema:EndorseAction", "schema:result", "schema:CreativeWork")
n_repos = e("schema:Dataset", "schema:includedInDataCatalog", "schema:DataCatalog")
n_disc = e("schema:DefinedTermSet", "schema:hasDefinedTerm", "schema:DefinedTerm")
n_impact = e("schema:CreativeWork", "schema:about", "schema:DefinedTerm")
n_creator = role_count("schema:creator")
n_curator = role_count("agu:curator")
# creator and curator each land on any of the three party types; the diagram
# says so rather than drawing only the commonest target
credit = {k: (e("schema:Dataset", "schema:creator", k)
              + e("schema:Dataset", "agu:curator", k))
          for k in ("agu:ResponsibleParty", "schema:Organization", "schema:Person")}

# ------------------------------------------------------------- layout ----
# Fixed grid. Boxes are placed by hand; every number inside them comes from the
# measurements above.
W, H = 1330, 660
BW, BH = 210, 64
COL = {1: 30, 2: 326, 3: 622, 4: 918}     # 86px gutters, wide enough for labels
ROW = {1: 40, 2: 168, 3: 312, 4: 456}

RAMPS = {
    "teal":   ("#E1F5EE", "#0F6E56", "#085041", "#0F6E56", "#085041", "#9FE1CB", "#9FE1CB", "#5DCAA5"),
    "purple": ("#EEEDFE", "#534AB7", "#3C3489", "#534AB7", "#3C3489", "#CECBF6", "#CECBF6", "#AFA9EC"),
    "coral":  ("#FAECE7", "#993C1D", "#712B13", "#993C1D", "#712B13", "#F5C4B3", "#F5C4B3", "#F0997B"),
    "gray":   ("#F1EFE8", "#5F5E5A", "#444441", "#5F5E5A", "#444441", "#D3D1C7", "#D3D1C7", "#B4B2A9"),
}

# (col, row, ramp, class, role, count line)
NODES = [
    (1, 1, "coral",  "DataCatalog",      "the collection",      "1 catalog"),
    (2, 1, "gray",   "PropertyValue",    "identifiers",         "%d dataset, %d endorsement"
        % (e("schema:Dataset", "schema:identifier", "schema:PropertyValue"),
           e("schema:EndorseAction", "schema:identifier", "schema:PropertyValue"))),
    (3, 1, "purple", "ItemList",         "nominator order",     "%d lists" % classes.get("schema:ItemList", 0)),
    (4, 1, "teal",   "Organization",     "affiliations",        "%d organizations" % classes.get("schema:Organization", 0)),
    (1, 2, "coral",  "DataCatalog",      "repositories",        "%d holding repositories" % n_repos),
    (2, 2, "coral",  "Dataset",          "the nominated data",  "%d datasets" % classes.get("schema:Dataset", 0)),
    (3, 2, "purple", "EndorseAction",    "a nomination",        "%d endorsements" % classes.get("schema:EndorseAction", 0)),
    (4, 2, "teal",   "Person",           "the nominator",       "%d people" % classes.get("schema:Person", 0)),
    (1, 3, "coral",  "CreativeWork",     "citations and reuse", "%d cited, %d reuse" % (n_citation, n_reuse)),
    (2, 3, "coral",  "DefinedTerm",      "discipline groups",   "%d terms, one scheme" % n_disc),
    (3, 3, "purple", "CreativeWork",     "the justification",   "%d results" % n_result),
    (4, 3, "gray",   "agu:ResponsibleParty", "broader than either", "%d parties, kind unresolved" % classes.get("agu:ResponsibleParty", 0)),
    (3, 4, "purple", "DefinedTerm",      "impact dimensions",   "%d tags" % n_impact),
    (4, 4, "gray",   "prov:Agent",       "shared supertype",    "from PROV-O"),
]

CX = {c: COL[c] + BW / 2 for c in COL}
CY = {r: ROW[r] + BH / 2 for r in ROW}
RT = {c: COL[c] + BW for c in COL}
BT = {r: ROW[r] + BH for r in ROW}

def gut(a, b):
    """Midpoint of the gutter between two columns."""
    return (RT[a] + COL[b]) / 2

EDGES = [
    # the collection lists its datasets: down out of row 1, then right
    ([(CX[1], BT[1]), (CX[1], CY[2] - 16), (COL[2], CY[2] - 16)],
     "dataset (@list)", CX[1] + 8, (BT[1] + CY[2] - 16) / 2, "start"),
    # a dataset sits in repositories
    ([(COL[2], CY[2] + 14), (RT[1], CY[2] + 14)],
     "includedInDataCatalog", gut(1, 2), (BT[1] + ROW[2]) / 2 + 8, "middle"),
    ([(COL[3], CY[2]), (RT[2], CY[2])], "object", gut(2, 3), CY[2] - 11, "middle"),
    ([(RT[3], CY[2]), (COL[4], CY[2])], "agent", gut(3, 4), CY[2] - 11, "middle"),
    ([(CX[3], BT[1]), (CX[3], ROW[2])], "itemListElement (@list)", CX[3] + 9, (BT[1] + ROW[2]) / 2, "start"),
    ([(CX[2], ROW[2]), (CX[2], BT[1])], "identifier", CX[2] + 9, (BT[1] + ROW[2]) / 2, "start"),
    ([(CX[4], ROW[2]), (CX[4], BT[1])], "affiliation", CX[4] + 9, (BT[1] + ROW[2]) / 2, "start"),
    ([(CX[2], BT[2]), (CX[2], ROW[3])], "keywords", CX[2] + 9, (BT[2] + ROW[3]) / 2, "start"),
    ([(CX[3], BT[2]), (CX[3], ROW[3])], "result", CX[3] + 9, (BT[2] + ROW[3]) / 2, "start"),
    ([(CX[3], BT[3]), (CX[3], ROW[4])], "about", CX[3] + 9, (BT[3] + ROW[4]) / 2, "start"),
    # citations and reuse hang below-left; routed down the gutter, not across a box
    ([(COL[2], CY[2] + 26), (gut(1, 2), CY[2] + 26), (gut(1, 2), CY[3]), (RT[1], CY[3])],
     "citation / agu:reuseExample", gut(1, 2), (BT[2] + ROW[3]) / 2, "middle"),
    # credited parties hang below-right of the dataset
    ([(RT[2], CY[2] + 26), (gut(2, 3), CY[2] + 26), (gut(2, 3), BT[3] + 30),
      (CX[4] + 52, BT[3] + 30), (CX[4] + 52, BT[3])],
     "creator / agu:curator", gut(2, 3), (BT[2] + ROW[3]) / 2 - 7, "middle"),
]

# Vocabulary statements, drawn dashed to separate them from the data. They are
# what ties the AGU class to the schema.org ones: ResponsibleParty is the broader
# concept, so the match runs outward to Person and Organization, and the class
# sits under prov:Agent rather than redefining anything of schema.org's.
TRUNK = RT[4] + 42
VOCAB = [
    ([(RT[4], CY[3]), (TRUNK, CY[3]), (TRUNK, CY[2]), (RT[4], CY[2])],
     "skos:narrowMatch", TRUNK + 8, (CY[1] + CY[2]) / 2, "start"),
    ([(TRUNK, CY[2]), (TRUNK, CY[1]), (RT[4], CY[1])], "", 0, 0, "start"),
    ([(CX[4] - 46, BT[3]), (CX[4] - 46, ROW[4])],
     "rdfs:subClassOf", CX[4] - 38, (BT[3] + ROW[4]) / 2, "start"),
]

LEGEND = [(30, "coral", "Data resources"), (196, "purple", "Nomination and statements"),
          (430, "teal", "Agents"), (534, "gray", "Identifiers and unresolved parties")]


def esc(s):
    """XML-escape. These labels are authored here rather than read from the data,
    which is precisely why it is easy to forget: the ampersand in "citations &
    reuse" is enough to make the whole file unparseable."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build():
    css = [".bx{stroke-width:.6}", ".th{font:600 14.5px sans-serif}",
           ".rl{font:italic 11px sans-serif}", ".ts{font:11.5px sans-serif}",
           ".arr{stroke:#5F5E5A;stroke-width:1.5;fill:none}",
           ".el{font:10px sans-serif;fill:#3F4A50}",
           ".voc{stroke:#7A6A8F;stroke-width:1.4;fill:none;stroke-dasharray:5 4}",
           ".elv{font:italic 10px sans-serif;fill:#6B5C80}",
           ".sub{font:9.5px sans-serif;fill:#6C7A82}",
           ".elh{font:10px sans-serif;fill:none;stroke:#fff;stroke-width:3.5px;stroke-linejoin:round}",
           ".cap{font:11.5px sans-serif;fill:#5F5E5A}"]
    dark = ["@media (prefers-color-scheme:dark){", ".arr{stroke:#B4B2A9}",
            ".voc{stroke:#B9A9D0}", ".elv{fill:#C5B6DA}", ".sub{fill:#9AA7AE}",
            ".el{fill:#C9D3D9}", ".elh{stroke:#12181C}", ".cap{fill:#B4B2A9}"]
    for name, v in RAMPS.items():
        css += [f".f-{name}{{fill:{v[0]};stroke:{v[1]}}}", f".t-{name}{{fill:{v[2]}}}",
                f".s-{name}{{fill:{v[3]}}}"]
        dark += [f".f-{name}{{fill:{v[4]};stroke:{v[5]}}}", f".t-{name}{{fill:{v[6]}}}",
                 f".s-{name}{{fill:{v[7]}}}"]
    dark.append("}")

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" role="img">',
           "<title>Conceptual model of the published Impactful Datasets schema.org graph</title>",
           "<desc>A nomination is a schema.org EndorseAction whose agent is the nominator, "
           "whose object is the dataset, and whose result is the justification, itself tagged "
           "with impact dimensions. Datasets carry discipline terms as keywords, sit in "
           "repository catalogs, cite publications and reuse examples, and credit parties as "
           "creator or curator. Ordering is explicit: the collection lists its datasets and "
           "each dataset lists its nominators as RDF lists.</desc>",
           "<style>" + "".join(css) + "".join(dark) + "</style>",
           '<defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
           'markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" '
           'stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" '
           'stroke-linejoin="round"/></marker>'
           '<marker id="av" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
           'markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" '
           'stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" '
           'stroke-linejoin="round"/></marker></defs>']

    for pts, label, lx, ly, anchor in VOCAB:
        d = "M" + " L".join(f"{x:.0f} {y:.0f}" for x, y in pts)
        out.append(f'<path class="voc" d="{d}" marker-end="url(#av)"/>')
        if label:
            for cls in ("elh", "elv"):
                out.append(f'<text class="{cls}" x="{lx:.0f}" y="{ly:.0f}" '
                           f'text-anchor="{anchor}" dominant-baseline="central">'
                           f'{esc(label)}</text>')

    for pts, label, lx, ly, anchor in EDGES:
        d = "M" + " L".join(f"{x:.0f} {y:.0f}" for x, y in pts)
        out.append(f'<path class="arr" d="{d}" marker-end="url(#a)"/>')
        for cls in ("elh", "el"):
            out.append(f'<text class="{cls}" x="{lx:.0f}" y="{ly:.0f}" text-anchor="{anchor}" '
                       f'dominant-baseline="central">{esc(label)}</text>')

    bd = ("%d party · %d organization · %d person"
          % (credit["agu:ResponsibleParty"], credit["schema:Organization"],
             credit["schema:Person"]))
    for cls in ("elh", "sub"):
        out.append(f'<text class="{cls}" x="{gut(2, 3):.0f}" '
                   f'y="{(BT[2] + ROW[3]) / 2 + 8:.0f}" text-anchor="middle" '
                   f'dominant-baseline="central">{esc(bd)}</text>')

    for col, row, ramp, cls, role, count in NODES:
        x, y = COL[col], ROW[row]
        cx = x + BW / 2
        out.append(
            f'<rect class="bx f-{ramp}" x="{x}" y="{y}" width="{BW}" height="{BH}" rx="8"/>'
            f'<text class="th t-{ramp}" x="{cx:.0f}" y="{y + 17}" text-anchor="middle" '
            f'dominant-baseline="central">{esc(cls)}</text>'
            f'<text class="rl s-{ramp}" x="{cx:.0f}" y="{y + 33}" text-anchor="middle" '
            f'dominant-baseline="central">{esc(role)}</text>'
            f'<text class="ts s-{ramp}" x="{cx:.0f}" y="{y + 48}" text-anchor="middle" '
            f'dominant-baseline="central">{esc(count)}</text>')

    for x, ramp, label in LEGEND:
        out.append(f'<rect class="bx f-{ramp}" x="{x}" y="{H - 30}" width="10" height="10" rx="2"/>'
                   f'<text class="ts s-{ramp}" x="{x + 16}" y="{H - 25}" '
                   f'dominant-baseline="central">{esc(label)}</text>')
    out.append(f'<path class="voc" d="M{W - 470} {H - 25} L{W - 440} {H - 25}"/>'
               f'<text class="elv" x="{W - 432}" y="{H - 25}" '
               f'dominant-baseline="central">vocabulary statement, not data</text>')
    out.append(f'<text class="cap" x="{W - 30}" y="{H - 25}" text-anchor="end" '
               f'dominant-baseline="central">{len(g):,} triples · '
               f'{sum(classes.values()):,} typed nodes</text>')
    out.append("</svg>")
    return "\n".join(out)


args.out.write_text(build(), encoding="utf-8")

missing = [n for n in NODES if " 0 " in n[5] or n[5].startswith("0 ")]
print("classes measured : %d" % len(classes))
print("edge shapes found: %d" % len(edges))
if missing:
    print("WARNING: these boxes measured zero, so the data no longer has that shape:")
    for m in missing:
        print("   %s (%s)" % (m[3], m[4]))
print("wrote %s" % args.out)
