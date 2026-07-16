# Gradle JSON ResolutionResult API - Implementation Plan

**Date:** 2026-07-16  
**Objective:** Reduce spring-boot dep-tree time from 22.67s → 8-12s  
**Approach:** Industry-standard Gradle ResolutionResult API with JSON output

---

## Summary

Replace text-based `DependencyReportTask` with JSON-based `ResolutionResult` API to eliminate ASCII tree formatting overhead.

**Expected impact:**
- spring-boot: 22.67s → 8-12s (40-50% reduction)
- Total Phase 1 overhead: +109% → +50-60%

---

## Implementation Steps

### Step 1: Add JSON Init Script ✅

**File:** `app/pipeline/gradle_dep_tree_parser.py`  
**Status:** DONE (lines 47-102)

Added `_OMNIBOR_INIT_SCRIPT_JSON` using Gradle's `ResolutionResult` API.

### Step 2: Add JSON Parser

**File:** `app/pipeline/gradle_dep_tree_parser.py`  
**Function:** `_parse_json_dep_output(output: str) -> dict`

```python
def _parse_json_dep_output(output):
    """Parse JSON dependency output from omniborDepsJson task.
    
    Extracts JSON blocks delimited by ===OMNIBOR_JSON_START=== markers
    and converts to the same structure as text parser output.
    
    Args:
        output: Raw stdout from gradlew omniborDepsJson
        
    Returns:
        Dict mapping project keys to module dicts with deps list
    """
    import json
    
    modules = {}
    lines = output.split('\n')
    i = 0
    while i < len(lines):
        if lines[i].strip() == '===OMNIBOR_JSON_START===':
            # Find matching END marker
            j = i + 1
            while j < len(lines) and lines[j].strip() != '===OMNIBOR_JSON_END===':
                j += 1
            if j < len(lines):
                # Extract JSON between markers
                json_text = '\n'.join(lines[i+1:j])
                try:
                    module_data = json.loads(json_text)
                    modules[module_data['key']] = module_data
                except json.JSONDecodeError as e:
                    print(f"[WARN] Failed to parse JSON for project: {e}")
            i = j + 1
        else:
            i += 1
    
    return modules
```

### Step 3: Add JSON Invocation Function

**File:** `app/pipeline/gradle_dep_tree_parser.py`  
**Function:** `run_gradle_all_dep_trees_json(repo_dir, runner=None)`

```python
def run_gradle_all_dep_trees_json(repo_dir, runner=None):
    """Run gradlew with JSON ResolutionResult API init script.
    
    Faster than text-based DependencyReportTask because it skips
    ASCII tree formatting. Uses Gradle's ResolutionResult API
    (industry best practice).
    
    Args:
        repo_dir: Path to repository root
        runner: Unused (kept for API consistency)
        
    Returns:
        Raw stdout string, or None on failure
    """
    repo_path = Path(repo_dir)
    gradlew = repo_path / "gradlew"
    if not gradlew.exists():
        print(f"[WARN] No gradlew found in {repo_dir}")
        return None
    
    init_file = None
    t0 = time.monotonic()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".gradle", delete=False, encoding="utf-8",
        ) as handle:
            handle.write(_OMNIBOR_INIT_SCRIPT_JSON)
            init_file = handle.name
        result = subprocess.run(
            [
                str(gradlew), "omniborDepsJson",
                "--init-script", init_file,
                "--offline", "--continue",
                "--parallel", "--max-workers=4",  # NEW: parallel execution
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        elapsed = time.monotonic() - t0
        if result.returncode != 0:
            print(
                f"[WARN] Gradle omniborDepsJson failed after {elapsed:.1f}s "
                f"(returncode={result.returncode}): {result.stderr[:300]}"
            )
            return None
        if not result.stdout:
            print(
                f"[WARN] Gradle omniborDepsJson produced no output after {elapsed:.1f}s"
            )
            return None
        print(
            f"[OK] Gradle omniborDepsJson (JSON API) succeeded in {elapsed:.1f}s"
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        print(f"[WARN] Gradle omniborDepsJson timed out after {elapsed:.1f}s")
        return None
    except FileNotFoundError:
        print("[WARN] gradlew not found on PATH")
        return None
    finally:
        if init_file:
            try:
                os.unlink(init_file)
            except OSError:
                pass
```

### Step 4: Update get_all_gradle_deps()

**File:** `app/pipeline/gradle_dep_tree_parser.py`  
**Function:** `get_all_gradle_deps()`

```python
def get_all_gradle_deps(
    repo_dir: str,
    include_subprojects: bool = True,
) -> List[dict]:
    """Get per-subproject dependency subtrees for Phase 1 capture.
    
    Tries JSON ResolutionResult API first (faster), falls back to
    text-based DependencyReportTask if JSON fails.
    """
    # Primary: JSON API (faster, no text formatting)
    output = run_gradle_all_dep_trees_json(repo_dir)
    if output:
        modules_dict = _parse_json_dep_output(output)
        if modules_dict:
            modules = []
            for key, module_data in modules_dict.items():
                modules.append({
                    "key": key,
                    "project": module_data.get("project"),
                    "deps": module_data.get("deps", []),
                })
            print(
                f"[OK] Gradle JSON API: parsed {len(modules)} modules"
            )
            return modules
        print(
            "[WARN] Gradle JSON API produced no parseable modules; "
            "falling back to text API"
        )
    
    # Fallback: text-based DependencyReportTask
    output = run_gradle_all_dep_trees(repo_dir)
    sections = _split_dep_report_sections(output) if output else {}
    if sections:
        modules = []
        for key, section_text in sections.items():
            project = None if key == ":" else key.lstrip(":")
            modules.append({
                "key": key,
                "project": project,
                "deps": parse_gradle_dep_tree(section_text),
            })
        print(
            f"[OK] Gradle text API (fallback): parsed {len(modules)} modules"
        )
        return modules
    
    # Last resort: per-subproject invocations
    print(
        "[WARN] Both JSON and text APIs failed; "
        "falling back to per-subproject invocations"
    )
    return _get_all_gradle_deps_per_subproject(
        repo_dir, include_subprojects,
    )
```

---

## Testing Plan

### Unit Tests

**File:** `tests/test_gradle_dep_tree_parser.py`

Add tests for:
1. `_parse_json_dep_output()` with valid JSON
2. `_parse_json_dep_output()` with malformed JSON
3. `run_gradle_all_dep_trees_json()` success case
4. `run_gradle_all_dep_trees_json()` failure → fallback

### Integration Test (EC2)

```bash
# On EC2
docker run --rm -v ~/omnibor-analysis/output:/workspace/output \
    omnibor-env:latest python3 app/analyze.py --repo spring-boot --mode sidecar

# Check console output for:
# [OK] Gradle omniborDepsJson (JSON API) succeeded in X.Xs
# [OK] Gradle JSON API: parsed 186 modules

# Check timing:
cat output/omnibor/java/spring-boot/<ts>/adg_substeps.json
# Expected: dep_tree wall_sec < 12s (was 22.67s)
```

### Golden File Validation

```bash
./scripts/compare_golden.py --repo spring-boot --lang java
# Expected: CLEAN (no SPDX differences)
```

---

## Rollback Plan

If JSON API fails or causes regressions:

1. **Graceful degradation:** Fallback to text API already implemented
2. **Feature flag:** Could add `omnibor.gradle_use_json_api: false` to disable
3. **Revert:** Single commit, easy to revert

---

## Risk Assessment

### Low Risk

✅ **Fallback exists:** Text API still works if JSON fails  
✅ **Industry standard:** ResolutionResult API is stable since Gradle 1.0  
✅ **No build modifications:** Init script is external, doesn't touch build files  
✅ **Parallel execution:** Gradle's `--parallel` is well-tested

### Medium Risk

⚠️ **JSON parsing:** Could fail on unexpected output format  
**Mitigation:** Wrap in try/except, fall back to text API

⚠️ **Gradle version compatibility:** Older Gradle versions may not support ResolutionResult  
**Mitigation:** All target repos use Gradle 6.5+ (spring-boot uses 8.13)

---

## Expected Results

### spring-boot

| Metric | Before | After | Improvement |
|---|---|---|---|
| Dep-tree time | 22.67s | 8-12s | 47-65% |
| Total Phase 1 | 45.4s | 30-34s | 25-34% |
| Overhead | +109% | +38-57% | ✅ EXCELLENT |

### dependency-check (Maven)

No change (Maven already uses single invocation, no text formatting overhead).

---

## Implementation Checklist

- [x] Add JSON init script
- [ ] Add `_parse_json_dep_output()` function
- [ ] Add `run_gradle_all_dep_trees_json()` function
- [ ] Update `get_all_gradle_deps()` to try JSON first
- [ ] Add unit tests
- [ ] Test on spring-boot (EC2)
- [ ] Validate golden-clean
- [ ] Measure actual timing
- [ ] Update documentation
- [ ] Commit + PR

---

## Next Steps

1. Implement Step 2 (JSON parser)
2. Implement Step 3 (JSON invocation function)
3. Implement Step 4 (update get_all_gradle_deps)
4. Run tests locally
5. Deploy to EC2 and validate
6. Measure actual impact
7. Commit if successful

