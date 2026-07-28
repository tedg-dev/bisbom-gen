#!/bin/bash
set -euo pipefail

# ECS Phase 2 entrypoint: download from S3, run analysis, upload results.
# Required env vars (set by ECS RunTask container overrides):
#   S3_INPUT_PATH  — s3://bucket/prefix/phase1/
#   S3_OUTPUT_PATH — s3://bucket/prefix/spdx/
#   REPO_NAME      — repository name (e.g., "WebGoat")
#   S3_BUCKET      — bucket name (for awscli)

WORK_DIR="/workspace/output"
SPDX_DIR="/workspace/spdx"

echo "[SIDECAR] Starting Phase 2 for ${REPO_NAME}"
echo "[SIDECAR] S3 input:  ${S3_INPUT_PATH}"
echo "[SIDECAR] S3 output: ${S3_OUTPUT_PATH}"

# Download and extract Phase 1 archive from S3
echo "[SIDECAR] Downloading Phase 1 archive..."
mkdir -p "${WORK_DIR}" "${SPDX_DIR}"
aws s3 cp "${S3_INPUT_PATH}" /tmp/phase1.tar.gz
echo "[SIDECAR] Extracting archive..."
tar xzf /tmp/phase1.tar.gz -C "${WORK_DIR}"
rm -f /tmp/phase1.tar.gz

# Find the manifest file
MANIFEST=$(find "${WORK_DIR}" -name "phase1_manifest.json" -type f | head -n 1)
if [ -z "${MANIFEST}" ]; then
    echo "[SIDECAR] ERROR: phase1_manifest.json not found"
    exit 1
fi
# Read the original repo name from the manifest so Phase 2
# directory paths match what Phase 1 produced.
MANIFEST_REPO=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['repo_name'])" "${MANIFEST}")
echo "[SIDECAR] Manifest: ${MANIFEST}"
echo "[SIDECAR] Manifest repo_name: ${MANIFEST_REPO} (S3 repo: ${REPO_NAME})"

# Run SPDX generation
python3 /workspace/app/analyze.py \
    --repo "${MANIFEST_REPO}" \
    --mode sidecar \
    --phase spdx \
    --manifest "${MANIFEST}" \
    --skip-clone

# Upload SPDX output back to S3
echo "[SIDECAR] Uploading SPDX results..."
SPDX_COUNT=0
for f in $(find "${WORK_DIR}" -name "*.spdx.json" -o -name "*.spdx.html"); do
    BASENAME=$(basename "$f")
    aws s3 cp "$f" "${S3_OUTPUT_PATH}${BASENAME}"
    SPDX_COUNT=$((SPDX_COUNT + 1))
done

echo "[SIDECAR] Uploaded ${SPDX_COUNT} SPDX files to ${S3_OUTPUT_PATH}"
echo "[SIDECAR] Phase 2 complete"
