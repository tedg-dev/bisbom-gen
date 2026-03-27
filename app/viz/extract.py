"""Extract graph data from SPDX 2.3 JSON documents.

Reads package and relationship data, classifies nodes by type
(static, dynamic, build, Go module kind, etc.), and computes
BFS depth from the root package.
"""


def extract_graph(doc):
    """Extract nodes and edges from SPDX document.

    Returns:
        nodes: list of {id, name, version, purpose, group, fileCount}
        edges: list of {source, target, type}
        file_counts: dict of SPDXID -> count of CONTAINS relationships
    """
    pkg_map = {}
    for p in doc.get("packages", []):
        comment = p.get("comment", "")
        pkg_map[p["SPDXID"]] = {
            "id": p["SPDXID"],
            "name": p.get("name", "unknown"),
            "version": p.get("versionInfo", ""),
            "purpose": p.get(
                "primaryPackagePurpose", ""
            ),
            "comment": comment,
            "vendored": "vendored" in comment.lower(),
            "sibling": "sibling module" in comment.lower(),
        }

    # Count CONTAINS / CONTAINED_BY relationships
    # per package (Java uses CONTAINED_BY)
    file_counts = {}
    for r in doc.get("relationships", []):
        rt = r["relationshipType"]
        if rt == "CONTAINS":
            src = r["spdxElementId"]
            file_counts[src] = (
                file_counts.get(src, 0) + 1
            )
        elif rt == "CONTAINED_BY":
            tgt = r["relatedSpdxElement"]
            file_counts[tgt] = (
                file_counts.get(tgt, 0) + 1
            )

    # Classify packages into groups
    # Relationship directions vary by type:
    #   STATIC_LINK:  root → dep (root links dep)
    #   DYNAMIC_LINK: root → lib (target = lib)
    #   BUILD_TOOL_OF: tool → root (source = tool)
    #   DEPENDS_ON:   parent → child (parent needs child)
    rels = doc.get("relationships", [])
    dynamic_nodes = set()
    build_nodes = set()
    static_nodes = set()
    depends_nodes = set()

    # Find root package (target of DESCRIBES)
    root_ids = set()
    for r in rels:
        if r["relationshipType"] == "DESCRIBES":
            root_ids.add(r["relatedSpdxElement"])
    # Fallback: APPLICATION-purpose packages
    if not root_ids:
        for p in doc.get("packages", []):
            if p.get("primaryPackagePurpose") == (
                "APPLICATION"
            ):
                root_ids.add(p["SPDXID"])

    # Build adjacency for BFS depth computation
    # parent -> [children] for dependency edges
    children_of = {}  # target -> [sources]
    for r in rels:
        rt = r["relationshipType"]
        src = r["spdxElementId"]
        tgt = r["relatedSpdxElement"]
        if rt == "DYNAMIC_LINK":
            dynamic_nodes.add(src)
            dynamic_nodes.add(tgt)
        elif rt == "BUILD_TOOL_OF":
            build_nodes.add(src)
            # Reverse for BFS: target -> tool
            children_of.setdefault(
                tgt, []
            ).append(src)
        elif rt == "DEPENDS_ON":
            depends_nodes.add(src)
            depends_nodes.add(tgt)
            # src DEPENDS_ON tgt: src -> tgt
            children_of.setdefault(
                src, []
            ).append(tgt)
        elif rt == "STATIC_LINK":
            static_nodes.add(src)
            static_nodes.add(tgt)
            # Direction varies: either
            # dep→root or root→dep.
            # Add both so BFS finds them.
            children_of.setdefault(
                tgt, []
            ).append(src)
            children_of.setdefault(
                src, []
            ).append(tgt)

    # BFS from root to compute depth
    node_depth = {}  # spdx_id -> depth
    queue = list(root_ids)
    for rid in root_ids:
        node_depth[rid] = 0
    while queue:
        current = queue.pop(0)
        cur_depth = node_depth[current]
        for child in children_of.get(
            current, []
        ):
            if child not in node_depth:
                node_depth[child] = (
                    cur_depth + 1
                )
                queue.append(child)

    # Detect Go modules by parsing comment field
    go_node_kind = {}  # spdx_id -> 'stdlib'|'direct'|'indirect'
    for spdx_id, info in pkg_map.items():
        cmt = info.get("comment", "").lower()
        if "go standard library" in cmt:
            go_node_kind[spdx_id] = "stdlib"
        elif "go module (direct)" in cmt:
            go_node_kind[spdx_id] = "direct"
        elif "go module (indirect)" in cmt:
            go_node_kind[spdx_id] = "indirect"

    # When only DEPENDS_ON exists (Go, Java), use
    # BFS depth to distinguish direct vs transitive.
    # Rust uses STATIC_LINK for all crates.
    # C/C++ uses STATIC_LINK for vendored/compiled.
    has_static = bool(static_nodes - root_ids)

    nodes = []
    for spdx_id, info in pkg_map.items():
        depth = node_depth.get(spdx_id)
        if spdx_id in root_ids:
            group = "root"
            node_type = "root"
        elif spdx_id in dynamic_nodes:
            group = "dynamic"
            node_type = "dynamic"
        elif spdx_id in build_nodes:
            if depth is not None and depth >= 2:
                group = "build_deep"
                node_type = "build_deep"
            else:
                group = "build"
                node_type = "build"
        elif spdx_id in static_nodes:
            # Color by depth but type is static
            node_type = "static"
            if info.get("vendored"):
                group = "vendored"
            elif depth is not None and depth >= 1:
                group = f"depth-{min(depth, 5)}"
            else:
                group = "depth-1"
        elif spdx_id in depends_nodes:
            # Go module type grouping
            gk = go_node_kind.get(spdx_id)
            if gk == "stdlib":
                node_type = "go_stdlib"
                group = "go_stdlib"
            elif gk == "direct":
                node_type = "go_direct"
                group = "go_direct"
            elif gk == "indirect":
                node_type = "go_indirect"
                group = "go_indirect"
            elif has_static:
                # C/C++: DEPENDS_ON = transitive
                node_type = "transitive_dep"
                if depth is not None and depth >= 1:
                    group = f"depth-{min(depth, 5)}"
                else:
                    group = "depth-1"
            elif depth is not None and depth > 1:
                # Java/other: depth > 1 = transitive
                node_type = "transitive_dep"
                if depth is not None and depth >= 1:
                    group = f"depth-{min(depth, 5)}"
                else:
                    group = "depth-1"
            else:
                # Java/other: depth 1 = direct
                node_type = "direct_dep"
                group = "depth-1"
        else:
            group = "other"
            node_type = "other"

        # Override group for sibling modules
        is_sibling = info.get("sibling", False)
        if is_sibling:
            group = "sibling"
            node_type = "sibling"

        nodes.append({
            "id": spdx_id,
            "name": info["name"],
            "version": info["version"],
            "purpose": info["purpose"],
            "group": group,
            "node_type": node_type,
            "depth": depth if depth is not None else 0,
            "comment": info["comment"],
            "vendored": info.get("vendored", False),
            "sibling": is_sibling,
            "fileCount": file_counts.get(
                spdx_id, 0
            ),
        })

    # Edges: only package-to-package (skip CONTAINS, DESCRIBES)
    edges = []
    for r in rels:
        rt = r["relationshipType"]
        src = r["spdxElementId"]
        tgt = r["relatedSpdxElement"]
        if rt in (
            "STATIC_LINK", "DYNAMIC_LINK",
            "BUILD_TOOL_OF", "DEPENDS_ON",
        ):
            if src in pkg_map and tgt in pkg_map:
                edges.append({
                    "source": src,
                    "target": tgt,
                    "type": rt,
                })

    return nodes, edges
