#!/usr/bin/env python3
"""
How a credited party gets its type. Shared, so the rules exist in one place.

Two steps need this: preparing the cleanup worksheets, which reports how every
party would be typed, and building the data, which applies it. If each carried
its own copy they would drift, and the worksheet would stop describing the
build it is meant to explain.

The guiding principle is to assert only what the evidence supports. Where it is
thin, agu:ResponsibleParty is the honest answer: it says the party is
responsible for the dataset without claiming to know whether it is a person or
an institution. Guessing Person would be a stronger claim than the data carries.
"""
import csv
from pathlib import Path

# Each rule is a branch in classify(). The id travels into the reports, so a row
# can be traced back to the line that produced it. `confidence` is confidence in
# the assertion actually made, not in how specific it is: calling an unparsed
# sentence a ResponsibleParty is low confidence, while calling it *something*
# responsible is trivially true.
PARTY_RULES = {
    "R1":  ("ORCID supplied", "high"),
    "R2":  ("agent of an EndorseAction; the form collects one person", "medium"),
    "R3":  ("DECISION cell filled in by a reviewer", "high"),
    "R4":  ("named exception, reviewed by hand", "high"),
    "R5":  ("worksheet: organisation, high confidence", "high"),
    "R6":  ("worksheet: organisation, medium confidence -- not enough to claim Organization", "medium"),
    "R7":  ("worksheet: organisation, low confidence -- left as Person", "low"),
    "R8":  ("worksheet: uncertain", "low"),
    "R9":  ("worksheet: not an entity; needs re-parsing upstream", "low"),
    "R10": ("worksheet: several entities in one string; needs splitting", "medium"),
    "R11": ("no ORCID, not reviewed; nothing supports a narrower type", "low"),
}

# Ruled on by hand, and not derivable from anything in the row.
KEEP_AS_PERSON = {"Jing Gao ( jinggao@udel.edu )"}

PARTY_KIND = {"Person": "person",
              "Organization": "organization",
              "agu:ResponsibleParty": "party"}

DECISION_WORDS = {"person": "Person",
                  "organization": "Organization",
                  "organisation": "Organization",
                  "responsibleparty": "agu:ResponsibleParty"}


def load_review(path):
    """The review worksheet, keyed by party name. Missing file is not an error."""
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return {row["name"]: row for row in csv.DictReader(fh)}


def classify(name, orcid=None, is_nominator=False, review=None):
    """Return (type, rule id). `review` is the worksheet from load_review()."""
    row = (review or {}).get(name)
    decided = (row or {}).get("DECISION", "").strip()

    # A recorded decision comes first, ahead of every inference including the
    # ORCID. Someone looked at this party and said what it is; nothing the
    # heuristics notice should outrank that. Ordering it first also means a
    # decision keeps working when a rule below it breaks -- which is the point
    # of writing one down.
    if decided:                                                      # RULE R3
        key = decided.lower().replace(" ", "").replace("_", "")
        return DECISION_WORDS.get(key, "agu:ResponsibleParty"), "R3"
    if orcid:                                                        # RULE R1
        return "Person", "R1"
    # R2 asks whether anything was flagged about this party, not merely whether a
    # row exists. The worksheet carries every party, so testing for a row would
    # silence this rule entirely and demote every nominator without an ORCID.
    if is_nominator and (row or {}).get("suggested_action", "") in (
            "", "leave as Person"):                                  # RULE R2
        return "Person", "R2"
    if name in KEEP_AS_PERSON:                                       # RULE R4
        return "Person", "R4"

    action = (row or {}).get("suggested_action")
    if action == "Organization":                                     # RULES R5-R7
        # flag_confidence: how strongly the name looks institutional. Distinct
        # from assertion_confidence, which describes the claim finally made --
        # the two disagree often, and sharing one column name was what made the
        # earlier pair of worksheets misleading.
        return {"high":   ("Organization", "R5"),
                "medium": ("agu:ResponsibleParty", "R6"),
                "low":    ("Person", "R7")}.get(
                    (row or {}).get("flag_confidence", ""),
                    ("agu:ResponsibleParty", "R6"))
    if action == "review":                                           # RULE R8
        return "agu:ResponsibleParty", "R8"
    if action == "re-parse or drop":                                 # RULE R9
        return "agu:ResponsibleParty", "R9"
    if action == "split first":                                      # RULE R10
        return "agu:ResponsibleParty", "R10"
    return "agu:ResponsibleParty", "R11"                             # RULE R11


def confidence_of(rule):
    return PARTY_RULES[rule][1]


def reason_of(rule):
    return PARTY_RULES[rule][0]
