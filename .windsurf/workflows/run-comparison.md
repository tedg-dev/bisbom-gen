---
description: Compare OmniBOR SPDX SBOM against proprietary binary scan SBOM
---

# Run Comparison

Compare an OmniBOR-generated SPDX SBOM against a proprietary binary scanner SPDX SBOM.

## Prerequisites

- bisbom-gen analysis must have been run first (run `/run-analysis` workflow)
- Binary scan SPDX file must be placed in `output/binary-scan/<repo>/`

## 1. Place the binary scan SBOM

Copy the SPDX JSON file from your binary scanner (e.g., BDBA export) into:

```
output/binary-scan/curl/<filename>.spdx.json
```

## 2. Run comparison

Auto-detect latest files:
```bash
docker-compose -f docker/docker-compose.yml run --rm bisbom-env python3 /workspace/app/compare.py --repo curl
```

Or specify files explicitly:
```bash
docker-compose -f docker/docker-compose.yml run --rm bisbom-env python3 /workspace/app/compare.py \
  --repo curl \
  --bisbom-file /workspace/output/spdx/curl/curl_omnibor_2026-02-10_1430.spdx.json \
  --binary-file /workspace/output/binary-scan/curl/bdba_export.spdx.json
```

## 3. Review the comparison report

The report is written to `output/build-logs/{lang}/<repo>/{ts}/` and includes:

- **Summary table** — package counts, overlap percentage, version agreement
- **Common packages** — detected by both methods, with version match/mismatch
- **Build-interception only** — build-time dependencies not found by binary scanner
- **Binary scan only** — pre-compiled/commercial components not seen during build
- **Version mismatches** — same package, different version detected
- **Analysis notes** — strengths of each method

## Interpreting Results

| Finding | Meaning |
|---------|---------|
| High build-interception-only count | Build interception sees transitive/header-only deps binary scanner misses |
| High binary-only count | Pre-compiled SDKs, static libs, or vendor binaries not compiled from source |
| Version mismatches | Different detection methods resolve versions differently |
| High overlap + version agreement | Both methods are consistent — high confidence in SBOM accuracy |
