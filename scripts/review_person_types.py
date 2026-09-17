#!/usr/bin/env python3
"""
Flag entities typed as schema:Person in the published data that are probably not
people, and write a reviewable CSV.

Read-only: this does not modify the data. It produces a worksheet with one row per
distinct name, a suggested classification, the evidence behind it, and an empty
decision column for a human to fill in.

Usage:
    python review_person_types.py impactful_datasets.data.jsonld -o person_review.csv
"""
import argparse, collections, csv, json, re
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("jsonld", type=Path)
ap.add_argument("-o", "--out", type=Path, default=Path("person_review.csv"))
args = ap.parse_args()

G = json.loads(args.jsonld.read_text(encoding="utf-8"))["@graph"]

ORG_WORDS = r"""universit|institut|college|school|academy|laborator|observator|
center|centre|agency|administration|bureau|department|division|office|program|programme|
project|mission|team|group|consortium|network|committee|council|society|association|
foundation|federation|survey|service|facility|archive|data\s*cent|daac|repositor|
company|corporation|corp\b|\binc\b|\bllc\b|\bltd\b|gmbh|\bplc\b|partnership|
ministry|commission|authority|board|panel|working\s*group|initiative|alliance|
museum|library|press|publisher|node|portal|infrastructure|
nasa|noaa|usgs|nsf|nsidc|esa|jaxa|ncar|ucar|epa|cnes|dlr|csiro|bodc|pangaea|
science\s*team|user\s*services|help\s*desk|support|staff|personnel|community|
et\s*al|and\s+colleagues|various|multiple|many|unknown|n/?a$"""
ORG_RE = re.compile(ORG_WORDS, re.I | re.X)
ACRONYM = re.compile(r"\b[A-Z]{3,}\b")
PERSONISH = re.compile(r"^[A-Z][a-z'\u2019-]+(?:\s+[A-Z]\.?){0,3}\s+[A-Z][a-zA-Z'\u2019-]+$")
INITIALS = re.compile(r"^[A-Z]\.\s*[A-Z]?\.?\s*[A-Z][a-z]")
PROSE = re.compile(r"\b(is|are|was|were|have|has|there|curated in|we are|working on)\b", re.I)

# ---------------------------------------------------------------- gather ----
entries = collections.defaultdict(
    lambda: {"roles": collections.Counter(), "orcid": "", "datasets": []})

for n in G:
    if n.get("@type") != "Dataset":
        continue
    title = n.get("name", "")
    for key, role in (("creator", "creator"), ("agu:curator", "curator")):
        for p in (n.get(key) or []):
            e = entries[p.get("name") or "(unnamed)"]
            e["roles"][role] += 1
            if title not in e["datasets"]:
                e["datasets"].append(title)

for n in G:
    if n.get("@type") != "ItemList":
        continue
    for a in n["itemListElement"]:
        ag = a.get("agent") or {}
        e = entries[ag.get("name") or "(unnamed)"]
        e["roles"]["nominator"] += 1
        if str(ag.get("@id", "")).startswith("https://orcid.org/"):
            e["orcid"] = ag["@id"]
        obj = a.get("object", {}).get("@id", "")
        for d in G:
            if d.get("@id") == obj and d.get("name") not in e["datasets"]:
                e["datasets"].append(d.get("name"))
                break


def evidence(name, has_orcid):
    s, why = 0, []
    m = ORG_RE.search(name)
    if m:
        s += 3; why.append("organisation word '%s'" % m.group(0).strip().lower())
    acr = ACRONYM.findall(name)
    if acr:
        s += 2; why.append("acronym %s" % ", ".join(acr[:3]))
    if re.search(r"[(),/&]|\band\b", name) and not PERSONISH.match(name):
        s += 1; why.append("punctuation or conjunction")
    if len(name.split()) > 4:
        s += 1; why.append("%d words" % len(name.split()))
    if re.search(r"\d", name):
        s += 1; why.append("contains a digit")
    if PERSONISH.match(name) or INITIALS.match(name):
        s -= 3; why.append("reads as a personal name")
    if has_orcid:
        s -= 4; why.append("has an ORCID")
    return s, "; ".join(why)


NAME_IN_STRING = re.compile(r"\b[A-Z][a-z'\u2019-]{1,}\s+(?:[A-Z]\.\s*){0,2}[A-Z][a-z'\u2019-]{1,}\b")


def looks_mixed(name):
    """A person's name and an organisation in the same string.

    The person test ignores capitalised pairs that are themselves institutional
    wording -- "Science Team", "Data Center", "Royal Observatory" all match a
    First-Last shape without naming anybody.
    """
    if not re.search(r"[,&/]|\band\b|et al", name):
        return False
    has_person = any(not ORG_RE.search(m.group(0))
                     for m in NAME_IN_STRING.finditer(name))
    has_org = bool(ORG_RE.search(name) or ACRONYM.search(name))
    return has_person and has_org


def suggest(name, score):
    """What this row probably is, and therefore what should happen to it."""
    if len(name.split()) >= 12 or PROSE.search(name):
        return ("not an entity", "re-parse or drop",
                "free text captured as a name; typing it at all would be wrong")
    # checked before the collective tests: "A. Smith, B. Jones, EarthChem team"
    # is not a team, it is three entities in one cell
    if looks_mixed(name):
        return ("mixed people and organisations", "split first",
                "one string holds several entities; retyping alone will not fix it")
    if re.search(r"help\s*desk|user\s*services|managers?\s*/|curators?:", name, re.I):
        return ("service desk or role", "Organization",
                "names a function rather than a person")
    if re.search(r"\bteams?\b|\bgroup\b|\bproject\b|\bconsortium\b|\bnetwork\b", name, re.I):
        return ("team, project or network", "Organization",
                "collective agent; ResearchProject may fit better in some cases")
    # A short, clean institutional name ("University of Miami", "Taiwan Space
    # Agency") scores low simply because it is short. The organisation word is
    # the signal that matters when nothing suggests a person.
    if ORG_RE.search(name) and not (PERSONISH.match(name) or INITIALS.match(name)):
        return ("organisation", "Organization", "institutional name")
    # Several people in one cell, with nothing institutional in sight. Still a
    # data problem, but the fix is to split into Person nodes, not to retype.
    names = [m.group(0) for m in NAME_IN_STRING.finditer(name)
             if not ORG_RE.search(m.group(0))]
    if len(names) > 1 and re.search(r"[,&]|\band\b", name):
        return ("several people in one string", "split first",
                "list of names; split into separate Person nodes, do not retype")
    # A bare acronym with no personal-name shape is almost always a body.
    if ACRONYM.fullmatch(name.replace(" ", "")) or (
            ACRONYM.search(name) and not NAME_IN_STRING.search(name)):
        return ("organisation", "Organization", "acronym with no personal name")
    if score >= 4:
        return ("organisation", "Organization", "institutional name")
    if score >= 2:
        return ("uncertain", "review", "weak signals only")
    return ("person", "leave as Person", "")


rows = []
for name, e in entries.items():
    score, why = evidence(name, bool(e["orcid"]))
    kind, action, note = suggest(name, score)
    confidence = "high" if score >= 5 else "medium" if score >= 2 else "low"
    rows.append({
        "name": name,
        "current_type": "Person",
        "suggested_kind": kind,
        "suggested_action": action,
        "confidence": confidence if action != "leave as Person" else "",
        "score": score,
        "evidence": why,
        "note": note,
        "roles": ", ".join("%s x%d" % (r, c) for r, c in sorted(e["roles"].items())),
        "orcid": e["orcid"],
        "occurrences": sum(e["roles"].values()),
        "example_datasets": " | ".join(e["datasets"][:3]),
        "DECISION": "",
        "CORRECTED_NAME": "",
    })

flagged = [r for r in rows if r["suggested_action"] != "leave as Person"]
flagged.sort(key=lambda r: (r["suggested_action"], -r["score"], r["name"].lower()))

with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(flagged)

print("distinct Person-typed names : %d" % len(rows))
print("flagged for review          : %d" % len(flagged))
print()
for k, n in collections.Counter(r["suggested_action"] for r in flagged).most_common():
    print("  %-16s %3d" % (k, n))
print()
for k, n in collections.Counter(r["confidence"] for r in flagged).most_common():
    print("  confidence %-8s %3d" % (k, n))
print()
print("wrote %s" % args.out)
