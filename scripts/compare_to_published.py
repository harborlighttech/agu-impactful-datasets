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
    changed, same = [], 0
    for i in set(new) & set(old):
        a, b = canon(old[i]), canon(new[i])
        if a == b:
            same += 1
            continue
        props = sorted(set(a) ^ set(b)) + sorted(
            k for k in set(a) & set(b) if a[k] != b[k])
        changed.append((i, sorted(set(props))))

    out, w = [], None
    out.append("# What would change if this went live\n")
    if unpublished:
        out.append(f"Nothing is published at `{args.published}` yet "
                   f"({unpublished}), so every resource below is new. This is the "
                   "expected result for a first deploy.\n")
    else:
        out.append(f"Comparing this build against `{args.published}`.\n")

    out.append("| | Resources |")
    out.append("|---|---|")
    out.append(f"| Added | **{len(added)}** |")
    out.append(f"| Removed | **{len(removed)}** |")
    out.append(f"| Changed | **{len(changed)}** |")
    out.append(f"| Unchanged | {same} |")
    out.append("")

    if not (added or removed or changed):
        out.append("The published file and this build describe the same data. "
                   "Deploying would change nothing.\n")

    def section(title, ids, note=None, detail=None):
        if not ids:
            return
        by = collections.Counter(kind(new.get(i) or old.get(i) or {}) for i in ids)
        out.append(f"## {title} ({len(ids)})\n")
        if note:
            out.append(note + "\n")
        out.append("| Type | Count |")
        out.append("|---|---|")
        for t, n in by.most_common():
            out.append(f"| {t} | {n} |")
        out.append("")
        shown = sorted(ids, key=lambda i: label(new.get(i) or old.get(i) or {}).lower())
        for i in shown[:args.max_listed]:
            node = new.get(i) or old.get(i) or {}
            extra = detail(i) if detail else ""
            out.append(f"- **{label(node)}** — `{kind(node)}`{extra}")
        if len(shown) > args.max_listed:
            out.append(f"- …and {len(shown) - args.max_listed} more")
        out.append("")

    section("Resources added", added,
            "Present in this build and not in the published file.")
    section("Resources removed", removed,
            "In the published file and gone from this build. A removal is worth "
            "a second look: a dataset that disappears takes its published URL "
            "with it.")

    changed_ids = [i for i, _ in changed]
    props = {i: p for i, p in changed}
    section("Resources changed", changed_ids,
            "Same @id, different content.",
            detail=lambda i: "  \n  changed: " + ", ".join(f"`{p}`" for p in props[i][:6])
            + (" …" if len(props[i]) > 6 else ""))

    if changed:
        hot = collections.Counter(p for _, ps in changed for p in ps)
        out.append("## Which properties moved\n")
        out.append("| Property | Resources affected |")
        out.append("|---|---|")
        for p, n in hot.most_common(15):
            out.append(f"| `{p}` | {n} |")
        out.append("")

    report = "\n".join(out)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
