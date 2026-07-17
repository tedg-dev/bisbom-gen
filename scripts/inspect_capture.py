#!/usr/bin/env python3
"""Diagnostic: summarize a Java inline capture log.

Prints, for the first .jar event: whether member entries carry a
recorded sha1, and a sample of member names. Also lists captured
.class write paths that contain 'META-INF/versions' (MRJAR classes).

Usage: inspect_capture.py <path-to-capture.jsonl>
"""
import json
import sys


def main():
    path = sys.argv[1]
    events = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
    classes = [e for e in events if e.get("kind") == "class"]
    jars = [e for e in events if e.get("kind") == "jar"]
    print(f"events={len(events)} classes={len(classes)} jars={len(jars)}")

    mr = [e for e in classes if "META-INF/versions" in (e.get("path") or "")]
    print(f"\nMRJAR .class events ({len(mr)}):")
    for e in mr[:10]:
        print(f"  path={e.get('path')}")
        print(f"    class_name={e.get('class_name')!r} sha1={e.get('sha1')}")

    if jars:
        j = jars[0]
        ents = j.get("entries", [])
        print(f"\nfirst jar: path={j.get('path')} entries={len(ents)}")
        with_sha = [m for m in ents if m.get("sha1")]
        print(f"  members with recorded sha1: {len(with_sha)}/{len(ents)}")
        print("  sample member keys:", list(ents[0].keys()) if ents else [])
        mrm = [m for m in ents
               if "META-INF/versions" in (m.get("name") or "")]
        print(f"  MRJAR member entries ({len(mrm)}):")
        for m in mrm[:10]:
            print(f"    name={m.get('name')} sha1={m.get('sha1')}")


if __name__ == "__main__":
    main()
