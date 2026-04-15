"""Configuration for isolated image plagiarism subsystem."""

import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(_env_path)

IMAGE_PLAGIARISM_DEBUG_ROOT = Path("debug_plagiarism/image")
IMAGE_PLAGIARISM_DATA_ROOT = Path("data/plagiarism_image")
IMAGE_PLAGIARISM_INDEX_PATH = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "image_index.json"
IMAGE_PLAGIARISM_CHECKPOINT_PATH = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "image_checkpoint.json"
IMAGE_PLAGIARISM_MANIFEST_PATH = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "image_manifest.json"
IMAGE_PLAGIARISM_FEATURE_DB_PATH = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "image_features.sqlite3"
IMAGE_PLAGIARISM_BUILD_LOCK_PATH = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "image_build.lock"
IMAGE_PLAGIARISM_SHADOW_DIR = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "shadow"

# Keep paths independent from existing text plagiarism corpus files.
IMAGE_PLAGIARISM_LOCAL_ROOT = Path("/home/tdkx/workspace/tech/data/corpus_local")
IMAGE_PLAGIARISM_REMOTE_ROOT = Path("/mnt/remote_corpus")
IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH = IMAGE_PLAGIARISM_LOCAL_ROOT / "sbs_5000"

# Default thresholds.
DEFAULT_HASH_HAMMING_MAX = 18
DEFAULT_HIGH_SCORE = 0.82
DEFAULT_MEDIUM_SCORE = 0.62
DEFAULT_MIN_INLIERS = 10
DEFAULT_FEATURE_DESCRIPTOR_ROWS = 192

# Build safety guardrails (to avoid excessive disk IO from tiny batch loops on large corpora).
IMAGE_BUILD_LARGE_CORPUS_DOC_THRESHOLD = 3000
IMAGE_BUILD_MIN_LIMIT_LARGE_CORPUS = 1000
IMAGE_BUILD_NICE_LEVEL = 19
IMAGE_BUILD_IOWAIT_CHECK_EVERY_DOCS = 25
IMAGE_BUILD_IOWAIT_SAMPLE_SECONDS = 0.2
IMAGE_BUILD_IOWAIT_SLEEP_SECONDS = 2.0
IMAGE_BUILD_IOWAIT_RATIO_THRESHOLD = 0.35
IMAGE_BUILD_FEATURE_WORKERS = 2

# Best-effort cgroup limits for build workers when `systemd-run --user` is available.
IMAGE_BUILD_CPU_QUOTA = "50%"
IMAGE_BUILD_MEMORY_MAX = "2G"
IMAGE_BUILD_IO_WEIGHT = "50"

# Bailian multimodal embedding rerank. Keep it bounded: source embeddings are
# generated lazily only for coarse candidates and cached in SQLite.
IMAGE_EMBEDDING_API_KEY = (
    os.getenv("PLAGIARISM_IMAGE_EMBEDDING_API_KEY")
    or os.getenv("DASHSCOPE_API_KEY")
    or os.getenv("EMBEDDING_API_KEY")
    or ""
)
IMAGE_EMBEDDING_BASE_URL = os.getenv(
    "PLAGIARISM_IMAGE_EMBEDDING_BASE_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
)
IMAGE_EMBEDDING_MODEL = os.getenv(
    "PLAGIARISM_IMAGE_EMBEDDING_MODEL",
    "tongyi-embedding-vision-plus-2026-03-06",
)
IMAGE_EMBEDDING_DIMENSION = int(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_DIMENSION", "512"))
IMAGE_EMBEDDING_RES_LEVEL = int(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_RES_LEVEL", "1"))
IMAGE_EMBEDDING_BATCH_SIZE = int(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_BATCH_SIZE", "8"))
IMAGE_EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_TIMEOUT_SECONDS", "60"))
IMAGE_EMBEDDING_MAX_SIDE = int(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_MAX_SIDE", "768"))
IMAGE_EMBEDDING_JPEG_QUALITY = int(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_JPEG_QUALITY", "85"))
IMAGE_EMBEDDING_RERANK_ENABLED = os.getenv("PLAGIARISM_IMAGE_EMBEDDING_ENABLED", "1").lower() not in {"0", "false", "no"}
IMAGE_EMBEDDING_TOP_K = int(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_TOP_K", "24"))
IMAGE_EMBEDDING_VERIFY_TOP_K = int(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_VERIFY_TOP_K", "4"))
IMAGE_EMBEDDING_MIN_SCORE = float(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_MIN_SCORE", "0.72"))
IMAGE_EMBEDDING_HIGH_SCORE = float(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_HIGH_SCORE", "0.90"))
IMAGE_EMBEDDING_MEDIUM_SCORE = float(os.getenv("PLAGIARISM_IMAGE_EMBEDDING_MEDIUM_SCORE", "0.82"))
