#!/usr/bin/env python3
"""
Check that the party typing rules still do what they claim.

Both regressions this guards against were silent. A rule stopped firing, the
build succeeded, the data validated, and the only symptom was a number quietly
moving: six named researchers demoted from Person, and forty-two organisations
collapsing into ResponsibleParty. Nothing failed, so nothing was noticed.

The checks below assert invariants rather than counts. Counts change whenever the
nominations change and would have to be updated constantly, at which point nobody
reads them. An invariant holds whatever the data says, so it can fail loudly:

    every nominator is a Person
    every party with an ORCID is a Person
    every high-confidence organisation is an Organization
    every recorded DECISION is honoured
    no rule that has work to do fires zero times

The last one is the general form of both bugs. A rule matching no rows when rows
exist for it to match is the signature of a rule that has broken rather than a
dataset that has changed.

Requirements: none beyond the standard library.

Usage:
    python check_party_typing.py data/cleanup/responsible_party.csv
"""
import argparse
import collections
import csv
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("worksheet", type=Path, nargs="?",
                    default=Path("data/cleanup/responsible_party.csv"))
    args = ap.parse_args()

    if not args.worksheet.exists():
        raise SystemExit("no worksheet at %s" % args.worksheet)
    rows = list(csv.DictReader(open(args.worksheet, encoding="utf-8-sig")))
    if not rows:
        raise SystemExit("%s is empty" % args.worksheet)

    failures, notes = [], []

    def check(label, bad, detail=lambda r: r["name"]):
        if bad:
            failures.append((label, [detail(r) for r in bad]))
        else:
            notes.append(label)

    decided = {r["name"] for r in rows if (r.get("DECISION") or "").strip()}

    # R1. An ORCID is issued to an individual, so it is the one piece of direct
    # evidence of personhood in the data. Nothing should override it but a human.
    check("every party with an ORCID is a Person",
          [r for r in rows if r["orcid"] and r["assigned_type"] != "Person"
           and r["name"] not in decided])

    # R2. The agent of a nomination is a person by construction: the form asks
    # for one individual's name, email, ORCID and affiliation. This is the rule
    # that silently broke, demoting six researchers who left the ORCID blank.
    nominators = [r for r in rows if "nominator" in (r["roles"] or "")]
    check("every nominator is a Person",
          [r for r in nominators if r["assigned_type"] != "Person"
           and r["name"] not in decided
           and r["suggested_action"] not in ("", "leave as Person")] and [] or
          [r for r in nominators if r["assigned_type"] != "Person"
           and r["name"] not in decided
           and r["suggested_action"] in ("", "leave as Person")])

    # R5. A name that reads strongly as institutional becomes an Organization.
    # This is the rule that broke when a column was renamed, taking all
    # forty-two organisations with it.
    check("every high-confidence organisation is an Organization",
          [r for r in rows
           if r["suggested_action"] == "Organization"
           and r["flag_confidence"] == "high"
           and r["assigned_type"] != "Organization"
           and r["name"] not in decided])

    # R3. A recorded decision is the whole point of the worksheet. If one stops
    # being honoured, a reviewer's work is being discarded in silence.
    want = {"person": "Person", "organization": "Organization",
            "organisation": "Organization",
            "responsibleparty": "agu:ResponsibleParty"}
    check("every DECISION is honoured",
          [r for r in rows
           if (r.get("DECISION") or "").strip()
           and r["assigned_type"] != want.get(
               r["DECISION"].strip().lower().replace(" ", "").replace("_", ""))],
          lambda r: "%s (asked for %s, got %s)" % (r["name"], r["DECISION"],
                                                   r["assigned_type"]))

    # The general case. A rule with rows to match that matches none has broken.
    fired = collections.Counter(r["rule"] for r in rows)
    expected = {
        "R1": [r for r in rows if r["orcid"]],
        "R2": nominators,
        "R5": [r for r in rows if r["suggested_action"] == "Organization"
               and r["flag_confidence"] == "high"],
        "R9": [r for r in rows if r["suggested_action"] == "re-parse or drop"],
        "R10": [r for r in rows if r["suggested_action"] == "split first"],
    }
    silent = [rule for rule, candidates in expected.items()
              if candidates and not fired[rule]]
    if silent:
        failures.append(
            ("no rule with work to do fires zero times",
             ["%s matched nothing, but %d row(s) qualify"
              % (rule, len(expected[rule])) for rule in silent]))
    else:
        notes.append("no rule with work to do fires zero times")

    # ------------------------------------------------------------- report ----
    kinds = collections.Counter(r["assigned_type"] for r in rows)
    print("%d parties in %s" % (len(rows), args.worksheet))
    for k in ("Person", "Organization", "agu:ResponsibleParty"):
        print("  %-22s %4d" % (k, kinds[k]))
    print("  rules fired          : %s"
          % ", ".join("%s=%d" % (r, fired[r])
                      for r in sorted(fired, key=lambda x: int(x[1:]))))
    print()
    for label in notes:
        print("  ok    %s" % label)
    for label, examples in failures:
        print("  FAIL  %s" % label)
        for e in examples[:8]:
            print("          %s" % e)
        if len(examples) > 8:
            print("          …and %d more" % (len(examples) - 8))

    if failures:
        print()
        print("::error::%d party typing invariant(s) failed. A rule has stopped "
              "doing what it claims, which does not show up as a broken build."
              % len(failures))
        sys.exit(1)
    print()
    print("all invariants hold")


if __name__ == "__main__":
    main()
