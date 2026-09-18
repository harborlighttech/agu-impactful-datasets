#!/usr/bin/env python3
"""
Prepare the party cleanup worksheets from the RDF graph.

One file lands in data/cleanup/responsible_party.csv: every credited party, how
it would be typed, the evidence behind that, and a DECISION column for a human to
overrule it.

It was two files once, and they overlapped badly. Both carried a column called
`confidence` meaning different things -- confidence that a party is not a person,
versus confidence in the assertion finally made -- and they disagreed on 75 of
191 shared rows. Worse, the file a reviewer was meant to edit held only the
flagged parties, hiding the ~166 typed ResponsibleParty purely because nothing
was known about them, which is exactly where a human can help.

This runs before the schema.org data is built, which is the whole point: the
decisions recorded here are an input to that build, so they have to exist first
and have to survive being regenerated.

**Decisions are never overwritten.** A DECISION already in the worksheet is
carried across and reported. Without that, re-running this after new nominations
arrive would silently erase a reviewer's work, and nothing downstream would look
wrong -- the build would simply fall back to guessing.

Requirements:
    pip install rdflib        # not needed: the graph is read as plain JSON

Usage:
    python prepare_cleanup.py data/output/impactful_datasets.jsonld -o data/cleanup
"""
import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from party_typing import (PARTY_RULES, classify, confidence_of,  # noqa: E402
                          load_review, reason_of)

# ---------------------------------------------------------------- flagging ----
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
NAME_IN_STRING = re.compile(
    r"\b[A-Z][a-z'\u2019-]{1,}\s+(?:[A-Z]\.\s*){0,2}[A-Z][a-z'\u2019-]{1,}\b")


def evidence(name, has_orcid):
    score, why = 0, []
    m = ORG_RE.search(name)
    if m:
        score += 3; why.append("organisation word '%s'" % m.group(0).strip().lower())
    acr = ACRONYM.findall(name)
    if acr:
        score += 2; why.append("acronym %s" % ", ".join(acr[:3]))
    if re.search(r"[(),/&]|\band\b", name) and not PERSONISH.match(name):
        score += 1; why.append("punctuation or conjunction")
    if len(name.split()) > 4:
        score += 1; why.append("%d words" % len(name.split()))
    if re.search(r"\d", name):
        score += 1; why.append("contains a digit")
    if PERSONISH.match(name) or INITIALS.match(name):
        score -= 3; why.append("reads as a personal name")
    if has_orcid:
        score -= 4; why.append("has an ORCID")
    return score, "; ".join(why)


def looks_mixed(name):
    if not re.search(r"[,&/]|\band\b|et al", name):
        return False
    has_person = any(not ORG_RE.search(m.group(0)) for m in NAME_IN_STRING.finditer(name))
    return has_person and bool(ORG_RE.search(name) or ACRONYM.search(name))


def suggest(name, score):
    if len(name.split()) >= 12 or PROSE.search(name):
        return ("not an entity", "re-parse or drop",
                "free text captured as a name; typing it at all would be wrong")
    if looks_mixed(name):
        return ("mixed people and organisations", "split first",
                "one string holds several entities; retyping alone will not fix it")
    if re.search(r"help\s*desk|user\s*services|managers?\s*/|curators?:", name, re.I):
        return ("service desk or role", "Organization", "names a function rather than a person")
    if re.search(r"\bteams?\b|\bgroup\b|\bproject\b|\bconsortium\b|\bnetwork\b", name, re.I):
        return ("team, project or network", "Organization",
                "collective agent; ResearchProject may fit better in some cases")
    names = [m.group(0) for m in NAME_IN_STRING.finditer(name) if not ORG_RE.search(m.group(0))]
    if len(names) > 1 and re.search(r"[,&]|\band\b", name):
        return ("several people in one string", "split first",
                "list of names; split into separate Person nodes, do not retype")
    if ACRONYM.fullmatch(name.replace(" ", "")) or (
            ACRONYM.search(name) and not NAME_IN_STRING.search(name)):
        return ("organisation", "Organization", "acronym with no personal name")
    if ORG_RE.search(name) and not (PERSONISH.match(name) or INITIALS.match(name)):
        return ("organisation", "Organization", "institutional name")
    if score >= 4:
        return ("organisation", "Organization", "institutional name")
    if score >= 2:
        return ("uncertain", "review", "weak signals only")
    return ("person", "leave as Person", "")


# ------------------------------------------------------------------ graph ----
def gather(graph_path):
    """Every credited party in the RDF graph, with the roles it appears in."""
    doc = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    nodes = doc["@graph"]
    by_id = {n["@id"]: n for n in nodes if n.get("@id")}

    def typed(node, want):
        t = node.get("@type")
        return want in (t if isinstance(t, list) else [t])

    parties = collections.defaultdict(
        lambda: {"roles": collections.Counter(), "orcid": "", "datasets": [],
                 "nominator": False})

    datasets = [n for n in nodes if typed(n, "dcat:Dataset")]
    titles = {d["@id"]: d.get("title", "") for d in datasets}

    for d in datasets:
        for key, role in (("creator", "creator"), ("curator", "curator")):
            for item in (d.get(key) or []):
                name = item.get("name") if isinstance(item, dict) else item
                if not name:
                    continue
                e = parties[name]
                e["roles"][role] += 1
                if titles[d["@id"]] not in e["datasets"]:
                    e["datasets"].append(titles[d["@id"]])

    for n in nodes:
        if not typed(n, "agu:Nomination"):
            continue
        title = titles.get(n.get("nominates"), "")
        for ref in (n.get("nominator") or []):
            person = by_id.get(ref) if isinstance(ref, str) else ref
            if not isinstance(person, dict):
                continue
            name = person.get("name")
            if not name:
                continue
            e = parties[name]
            e["roles"]["nominator"] += 1
            e["nominator"] = True
            if str(person.get("@id", "")).startswith("https://orcid.org/"):
                e["orcid"] = person["@id"]
            if title and title not in e["datasets"]:
                e["datasets"].append(title)

    return parties


# ------------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("graph", type=Path, help="the RDF graph from step 1")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("data/cleanup"))
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    out_path = args.outdir / "responsible_party.csv"
    existing = load_review(out_path)
    held = {n: r for n, r in existing.items()
            if (r.get("DECISION") or "").strip() or (r.get("CORRECTED_NAME") or "").strip()}

    parties = gather(args.graph)

    # First pass: the evidence, which is what the typing rules read.
    review = {}
    for name, e in parties.items():
        score, why = evidence(name, bool(e["orcid"]))
        kind, action, note = suggest(name, score)
        prev = held.get(name, {})
        review[name] = {
            "name": name,
            "suggested_kind": kind,
            "suggested_action": action,
            "flag_confidence": ("high" if score >= 5 else "medium" if score >= 2 else "low")
                               if action != "leave as Person" else "",
            "score": score,
            "evidence": why,
            "note": note,
            "DECISION": prev.get("DECISION", ""),
            "CORRECTED_NAME": prev.get("CORRECTED_NAME", ""),
        }

    # Second pass: apply the rules, now that every row's evidence exists.
    rows = []
    for name, e in parties.items():
        r = review[name]
        kind, rule = classify(name, e["orcid"] or None, e["nominator"], review)
        # Two different questions, so two different column names. Calling both
        # "confidence" is what made the old pair of files misleading.
        rows.append({
            "assigned_type": kind,
            "name": name,
            "needs_review": ("yes" if r["suggested_action"] not in ("leave as Person",)
                             else "defaulted" if rule == "R11" else ""),
            "rule": rule,
            "why": reason_of(rule),
            "assertion_confidence": confidence_of(rule),
            "suggested_kind": r["suggested_kind"],
            "suggested_action": r["suggested_action"],
            "flag_confidence": r["flag_confidence"],
            "evidence_score": r["score"],
            "evidence": r["evidence"],
            "note": r["note"],
            "roles": ", ".join("%s x%d" % (k, c) for k, c in sorted(e["roles"].items())),
            "occurrences": sum(e["roles"].values()),
            "orcid": e["orcid"],
            "example_datasets": " | ".join(e["datasets"][:3]),
            "DECISION": r["DECISION"],
            "CORRECTED_NAME": r["CORRECTED_NAME"],
        })

    # Rows wanting attention first: flagged, then defaulted, then settled.
    rank = {"yes": 0, "defaulted": 1, "": 2}
    conf_rank = {"low": 0, "medium": 1, "high": 2}
    rows.sort(key=lambda r: (rank[r["needs_review"]],
                             conf_rank[r["assertion_confidence"]],
                             r["name"].lower()))
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # ---- what happened ---------------------------------------------------
    carried = sum(1 for r in rows if r["DECISION"].strip() or r["CORRECTED_NAME"].strip())
    orphaned = sorted(set(held) - set(parties))
    kinds = collections.Counter(r["assigned_type"] for r in rows)
    flags = collections.Counter(r["needs_review"] for r in rows)
    rules = collections.Counter(r["rule"] for r in rows)

    print("parties found           : %d  -> %s" % (len(rows), out_path))
    print("wanting review          : %d flagged, %d defaulted with nothing to go on"
          % (flags["yes"], flags["defaulted"]))
    print("decisions carried across: %d of %d held" % (carried, len(held)))
    if orphaned:
        print("decisions with no matching party any more: %d" % len(orphaned))
        for n in orphaned[:5]:
            print("   %s" % n)
    print()
    for k in ("Person", "Organization", "agu:ResponsibleParty"):
        print("  %-22s %4d" % (k, kinds[k]))
    print()
    print("by rule: %s" % ", ".join("%s=%d" % (r, rules[r]) for r in sorted(
        rules, key=lambda x: int(x[1:]))))

    if orphaned:
        print("::warning::%d decision(s) no longer match a party and were dropped" % len(orphaned))


if __name__ == "__main__":
    main()
