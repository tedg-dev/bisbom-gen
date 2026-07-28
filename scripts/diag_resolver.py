#!/usr/bin/env python3
"""Diagnostic: show how make_source_resolver scores each candidate .java
for a given class file, to explain a source-attribution decision.

Usage: diag_resolver.py <repo_dir> <source_file> <class_path>
"""
import os
import sys

from app.pipeline.interception import (
    _path_similarity_score,
    make_source_resolver,
)


def main():
    repo_dir, source_file, class_path = sys.argv[1], sys.argv[2], sys.argv[3]

    # Rebuild the same basename index the resolver uses, but print scores.
    candidates = []
    for root, _dirs, files in os.walk(repo_dir):
        for name in files:
            if name == source_file:
                candidates.append(os.path.join(root, name))

    cpath = os.path.abspath(class_path).replace(os.sep, "/")
    print(f"class_path (abs): {cpath}")
    print(f"source_file     : {source_file}")
    print(f"candidates ({len(candidates)}):")
    for c in candidates:
        ac = os.path.abspath(c).replace(os.sep, "/")
        score = _path_similarity_score(cpath, ac)
        print(f"  score={score:3d}  {ac}")

    resolve = make_source_resolver(repo_dir)
    result = resolve(source_file, class_path)
    print(f"\nRESOLVED -> {result[0] if result else None}")


if __name__ == "__main__":
    main()
