#!/usr/bin/env python3
"""
Compare a generated schema.org file against the one currently published.

Answers the question a reviewer actually has before a deploy: what would change
if this went live? Resources are matched on @id and reported as added, removed
or changed, with the changed ones broken down by which property moved.

It compares meaning rather than text. Reformatting, key order and whitespace all
produce no diff; a renamed dataset or a dropped nomination produces one.

If nothing is published yet the comparison still succeeds and reports everything
as new, which is the correct answer for a first deploy rather than an error.

Requirements: none beyond the standard library.

Usage:
    python compare_to_published.py site/data/impactful_datasets.data.jsonld \\
        --published https://data.agu.org/impactful-datasets/data/impactful_datasets.data.jsonld \\
        -o reports/changes_vs_published.md
"""
import argparse
import collections
import json
import urllib.error
import urllib.request
from pathlib import Path

PUBLISHED = ("https://data.agu.org/impactful-datasets/data/"
             "impactful_datasets.data.jsonld")

# Properties that change on every build regardless of the data, and would
# otherwise drown the report in noise.
IGNORE = {"dateModified"}


def flatten(doc):
    """Every node carrying an @id, anywhere in the document, keyed by that @id.

    The graph nests: endorsements sit inside item lists, agents inside
    endorsements. Comparing only the top level would miss a changed nominator
    entirely, so this walks the whole structure.
    """
    # The @context describes the vocabulary, not the collection. Walking it
    # picks up term definitions such as {"@id": "…/dataset", "@container":
    # "@list"} and reports them as untyped resources, which is noise: a change
    # there is a change to the encoding, not to the data.
    if isinstance(doc, dict):
        doc = {k: v for k, v in doc.items() if k != "@context"}

    out = {}

    def walk(node):
        if isinstance(node, dict):
            nid = node.get("@id")
            # A bare {"@id": …} is a pointer, not a description. Counting one as
            # a present resource makes a deleted dataset look "changed" -- it
            # still has a pointer from the catalog's list -- when it has in fact
            # gone. Only nodes that say something about themselves count.
            if nid and len(node) > 1:
                prev = out.get(nid)
                if prev is None or len(node) > len(prev):
                    out[nid] = node
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return out


def canon(node):
    """A node reduced to something comparable, with volatile keys dropped."""
    def c(v):
        if isinstance(v, dict):
            return {k: c(x) for k, x in sorted(v.items()) if k not in IGNORE}
        if isinstance(v, list):
            return sorted((json.dumps(c(x), sort_keys=True, ensure_ascii=False) for x in v))
        return v
    return {k: c(v) for k, v in sorted(node.items()) if k not in IGNORE}


def label(node):
    for key in ("name", "alternateName", "text", "rdfs:label"):
        v = node.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return node.get("@id", "?")


def kind(node):
    t = node.get("@type")
    return (t[0] if isinstance(t, list) else t) or "untyped"


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "agu-impactful-datasets/1.0",
                      "Accept": "application/ld+json, application/json"})
    with urllib.request.urlopen(req, timeout=60) as fh:
        return json.loads(fh.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("local", type=Path, help="the file this build produced")
    ap.add_argument("--published", default=PUBLISHED,
                    help="the live file to compare against")
    ap.add_argument("-o", "--out", type=Path,
                    default=Path("reports/changes_vs_published.md"))
    ap.add_argument("--max-listed", type=int, default=25,
                    help="how many of each kind of change to name individually")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    new = flatten(json.loads(args.local.read_text(encoding="utf-8")))

    unpublished = None
    try:
        # A local path works too, which makes the comparison testable without a
        # network and lets you diff two builds against each other.
        if str(args.published).startswith(("http://", "https://")):
            old = flatten(fetch(args.published))
        else:
            old = flatten(json.loads(Path(args.published).read_text(encoding="utf-8")))
    except urllib.error.HTTPError as e:
        unpublished = "%s %s" % (e.code, e.reason)
        old = {}
    except Exception as e:                                   # noqa: BLE001
        unpublished = str(e)
        old = {}

    added = [i for i in new if i not in old]
    removed = [i for i in old if i not in new]
    changed, unchanged = [], []
    for i in set(new) & set(old):
        a, b = canon(old[i]), canon(new[i])
        if a == b:
            unchanged.append(i)
            continue
        props = sorted(set(a) ^ set(b)) + sorted(
            k for k in set(a) & set(b) if a[k] != b[k])
        changed.append((i, sorted(set(props))))
    changed_ids = [i for i, _ in changed]
    props_of = {i: p for i, p in changed}

    def kind_of(i):
        return kind(new.get(i) or old.get(i) or {})

    out = []
    w = out.append
    w("# What would change if this went live\n")
    if unpublished:
        w(f"Nothing is published at `{args.published}` yet ({unpublished}), so "
          "every resource below is new. This is the expected result for a first "
          "deploy.\n")
    else:
        w(f"Comparing this build against `{args.published}`.\n")

    # Broken out by @type, because "12 resources changed" says nothing about
    # whether the collection gained a dataset or a nominator changed their
    # affiliation. The type is what tells you which.
    buckets = {"added": collections.Counter(kind_of(i) for i in added),
               "removed": collections.Counter(kind_of(i) for i in removed),
               "changed": collections.Counter(kind_of(i) for i in changed_ids),
               "unchanged": collections.Counter(kind_of(i) for i in unchanged)}
    types = sorted(set().union(*(b.keys() for b in buckets.values())),
                   key=lambda k: (-(buckets["added"][k] + buckets["removed"][k]
                                    + buckets["changed"][k]),
                                  -buckets["unchanged"][k], k))

    w("## By type\n")
    w("| @type | Added | Removed | Changed | Unchanged |")
    w("|---|---|---|---|---|")
    for k in types:
        a, r, c, u = (buckets["added"][k], buckets["removed"][k],
                      buckets["changed"][k], buckets["unchanged"][k])
        # Zeros as a dash: a row of noughts is harder to read past than a row
        # that says nothing happened here.
        cell = lambda n, bold=False: ("—" if not n else
                                      (f"**{n}**" if bold else str(n)))
        w(f"| `{k}` | {cell(a, True)} | {cell(r, True)} | {cell(c, True)} | {cell(u)} |")
    w(f"| **total** | **{len(added)}** | **{len(removed)}** | "
      f"**{len(changed)}** | {len(unchanged)} |")
    w("")

    if not (added or removed or changed):
        w("The published file and this build describe the same data. Deploying "
          "would change nothing.\n")

    def section(title, ids, note=None, detail=None):
        if not ids:
            return
        w(f"## {title} ({len(ids)})\n")
        if note:
            w(note + "\n")
        # Grouped by type here too, so the list reads the same way as the table
        # above rather than mixing datasets in among their nominators.
        by_type = collections.defaultdict(list)
        for i in ids:
            by_type[kind_of(i)].append(i)
        for k in sorted(by_type, key=lambda k: (-len(by_type[k]), k)):
            rows = sorted(by_type[k],
                          key=lambda i: label(new.get(i) or old.get(i) or {}).lower())
            w(f"**`{k}`** — {len(rows)}\n")
            for i in rows[:args.max_listed]:
                node = new.get(i) or old.get(i) or {}
                w(f"- {label(node)}{detail(i) if detail else ''}")
            if len(rows) > args.max_listed:
                w(f"- …and {len(rows) - args.max_listed} more")
            w("")

    section("Added", added,
            "Present in this build and not in the published file.")
    section("Removed", removed,
            "In the published file and gone from this build. A removal is worth "
            "a second look: a dataset that disappears takes its published URL "
            "with it.")
    section("Changed", changed_ids,
            "Same @id, different content.",
            detail=lambda i: "  \n  changed: "
            + ", ".join(f"`{p}`" for p in props_of[i][:6])
            + (" …" if len(props_of[i]) > 6 else ""))

    if changed:
        hot = collections.Counter(p for _, ps in changed for p in ps)
        w("## Which properties moved\n")
        w("| Property | Resources affected |")
        w("|---|---|")
        for p_, n in hot.most_common(15):
            w(f"| `{p_}` | {n} |")
        w("")

    report = "\n".join(out)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
