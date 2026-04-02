#!/usr/bin/env bash
set -euo pipefail

# 安全入口：不走危险 API refresh，只走离线短任务
# 依赖: uv

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export PLAGIARISM_CORPUS_PATH="${PLAGIARISM_CORPUS_PATH:-/home/tdkx/workspace/tech/data/corpus_local/sbs_5000}"
SRC_CORPUS_PATH="${SRC_CORPUS_PATH:-/mnt/remote_corpus/2025/sbs}"
LOCAL_INGEST_DIR="${LOCAL_INGEST_DIR:-data/plagiarism/local_ingest}"

export PLAGIARISM_CORPUS_INDEX_PATH="${PLAGIARISM_CORPUS_INDEX_PATH:-${LOCAL_INGEST_DIR}/corpus_index.json}"
export PLAGIARISM_CORPUS_SQLITE_PATH="${PLAGIARISM_CORPUS_SQLITE_PATH:-${LOCAL_INGEST_DIR}/corpus_index.db}"
export PLAGIARISM_CORPUS_MANIFEST_PATH="${PLAGIARISM_CORPUS_MANIFEST_PATH:-${LOCAL_INGEST_DIR}/corpus_manifest.json}"
export PLAGIARISM_CORPUS_CHECKPOINT_PATH="${PLAGIARISM_CORPUS_CHECKPOINT_PATH:-${LOCAL_INGEST_DIR}/corpus_refresh_checkpoint.json}"

CHECKPOINT_FILE="${PLAGIARISM_CORPUS_CHECKPOINT_PATH}"
MANIFEST_FILE="${PLAGIARISM_CORPUS_MANIFEST_PATH}"
INDEX_FILE="${PLAGIARISM_CORPUS_INDEX_PATH}"
SQLITE_FILE="${PLAGIARISM_CORPUS_SQLITE_PATH}"
SQLITE_WAL_FILE="${SQLITE_FILE}-wal"
SQLITE_SHM_FILE="${SQLITE_FILE}-shm"

usage() {
  cat <<'USAGE'
用法:
  scripts/corpus_safe.sh scan [max_scan]
  scripts/corpus_safe.sh build [limit] [max_concurrency]
  scripts/corpus_safe.sh step [max_scan] [limit] [max_concurrency]
  scripts/corpus_safe.sh loop [rounds] [max_scan] [limit] [max_concurrency]
  scripts/corpus_safe.sh run-all [max_scan] [limit] [max_concurrency]
  scripts/corpus_safe.sh mirror5000 [count]
  scripts/corpus_safe.sh status
  scripts/corpus_safe.sh reset

说明:
  scan   : 只扫描目录并更新 manifest，不解析文档
  build  : 从 manifest 取一小批文档建索引，默认并发=4
  step   : 执行一次 scan + build
  loop   : 执行多轮 step，默认 rounds=10、max_scan=2000、limit=5、并发=4
  run-all: 单进程 ingest，自动循环直到 manifest 没有 pending
  mirror5000: 从远端目录复制前 N 个 docx 到本地目录（默认 5000）
  status : 查看 checkpoint / manifest / corpus 状态
  reset  : 清空 checkpoint 和 manifest
USAGE
}

cmd_scan() {
  local max_scan="${1:-2000}"
  uv run python -m src.services.plagiarism.corpus_maintenance scan-manifest \
    --max-scan "${max_scan}" --verbose
}

cmd_build() {
  local limit="${1:-5}"
  local max_concurrency="${2:-4}"
  uv run python -m src.services.plagiarism.corpus_maintenance build-batch \
    --limit "${limit}" \
    --max-concurrency "${max_concurrency}" \
    --verbose
}

cmd_ingest() {
  local max_scan="${1:-2000}"
  local limit="${2:-5}"
  local max_concurrency="${3:-4}"
  uv run python -m src.services.plagiarism.corpus_maintenance ingest \
    --max-scan "${max_scan}" \
    --limit "${limit}" \
    --max-concurrency "${max_concurrency}" \
    --verbose
}

cmd_status() {
  echo "[status] corpus_path: ${PLAGIARISM_CORPUS_PATH}"
  echo "[status] source_path: ${SRC_CORPUS_PATH}"
  echo "[status] local_ingest_dir: ${LOCAL_INGEST_DIR}"
  echo "[status] index: ${INDEX_FILE}"
  echo "[status] sqlite: ${SQLITE_FILE}"
  echo "[status] manifest: ${MANIFEST_FILE}"
  echo "[status] checkpoint: ${CHECKPOINT_FILE}"
  if [[ -f "${CHECKPOINT_FILE}" ]]; then
    cat "${CHECKPOINT_FILE}"
  else
    echo "{}"
  fi
  echo
  echo "[status] manifest pending count"
  uv run python - <<'PY'
import json
import os
from pathlib import Path
manifest_path = Path(os.environ["PLAGIARISM_CORPUS_MANIFEST_PATH"])
if not manifest_path.exists():
    print("0")
    raise SystemExit(0)
try:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
except Exception:
    print("manifest parse error")
    raise SystemExit(0)
pending = sum(
    1 for item in data.values()
    if isinstance(item, dict) and item.get("action") in {"new", "update", "fix_path"}
)
print(pending)
PY
}

cmd_reset() {
  rm -f "${CHECKPOINT_FILE}" "${MANIFEST_FILE}" "${INDEX_FILE}" "${SQLITE_FILE}" "${SQLITE_WAL_FILE}" "${SQLITE_SHM_FILE}"
  rm -rf "${LOCAL_INGEST_DIR}/corpus_index_shards" "${LOCAL_INGEST_DIR}/corpus_char4_inverted"
  echo "[reset] removed local ingest artifacts under ${LOCAL_INGEST_DIR}"
}

cmd_mirror5000() {
  local count="${1:-5000}"
  local src="${SRC_CORPUS_PATH%/}"
  local dst="${PLAGIARISM_CORPUS_PATH%/}"
  local tmp_list
  tmp_list="$(mktemp)"

  if [[ ! -d "${src}" ]]; then
    echo "[mirror5000] source not found: ${src}" >&2
    rm -f "${tmp_list}"
    return 1
  fi

  mkdir -p "${dst}"
  echo "[mirror5000] source=${src}"
  echo "[mirror5000] target=${dst}"
  echo "[mirror5000] selecting first ${count} docx files..."

  # 在 pipefail 下 head 会触发上游 Broken pipe，导致脚本提前退出
  set +o pipefail
  (
    cd "${src}" && find . -type f -name '*.docx' | LC_ALL=C sort | sed -n "1,${count}p"
  ) > "${tmp_list}"
  set -o pipefail

  local selected
  selected="$(wc -l < "${tmp_list}" | tr -d ' ')"
  echo "[mirror5000] selected=${selected}"
  if [[ "${selected}" -eq 0 ]]; then
    rm -f "${tmp_list}"
    return 0
  fi

  rsync -a --files-from="${tmp_list}" "${src}/" "${dst}/"
  rm -f "${tmp_list}"
  echo "[mirror5000] done"
}

pending_count() {
  uv run python - <<'PY'
import json
import os
from pathlib import Path
manifest_path = Path(os.environ["PLAGIARISM_CORPUS_MANIFEST_PATH"])
if not manifest_path.exists():
    print(0)
    raise SystemExit(0)
try:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
except Exception:
    print(0)
    raise SystemExit(0)
pending = sum(
    1 for item in data.values()
    if isinstance(item, dict) and item.get("action") in {"new", "update", "fix_path"}
)
print(pending)
PY
}

main() {
  local action="${1:-}"
  case "${action}" in
    scan)
      shift
      cmd_scan "${1:-2000}"
      ;;
    build)
      shift
      cmd_build "${1:-5}" "${2:-4}"
      ;;
    step)
      shift
      local max_scan="${1:-2000}"
      local limit="${2:-5}"
      local max_concurrency="${3:-4}"
      cmd_scan "${max_scan}"
      cmd_build "${limit}" "${max_concurrency}"
      ;;
    loop)
      shift
      local rounds="${1:-10}"
      local max_scan="${2:-2000}"
      local limit="${3:-5}"
      local max_concurrency="${4:-4}"
      local i=1
      while [[ "${i}" -le "${rounds}" ]]; do
        echo "[loop] round ${i}/${rounds}"
        cmd_scan "${max_scan}"
        cmd_build "${limit}" "${max_concurrency}"
        i=$((i + 1))
      done
      ;;
    run-all)
      shift
      cmd_ingest "${1:-2000}" "${2:-5}" "${3:-4}"
      ;;
    mirror5000)
      shift
      cmd_mirror5000 "${1:-5000}"
      ;;
    status)
      cmd_status
      ;;
    reset)
      cmd_reset
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "unknown action: ${action}" >&2
      usage
      return 1
      ;;
  esac
}

main "$@"
