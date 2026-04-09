"""Configuration for isolated image plagiarism subsystem."""

from pathlib import Path

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
