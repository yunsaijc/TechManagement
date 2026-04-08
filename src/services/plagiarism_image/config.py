"""Configuration for isolated image plagiarism subsystem."""

from pathlib import Path

IMAGE_PLAGIARISM_DEBUG_ROOT = Path("debug_plagiarism/image")
IMAGE_PLAGIARISM_DATA_ROOT = Path("data/plagiarism_image")
IMAGE_PLAGIARISM_INDEX_PATH = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "image_index.json"
IMAGE_PLAGIARISM_CHECKPOINT_PATH = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "image_checkpoint.json"
IMAGE_PLAGIARISM_MANIFEST_PATH = IMAGE_PLAGIARISM_DATA_ROOT / "index" / "image_manifest.json"

# Keep paths independent from existing text plagiarism corpus files.
IMAGE_PLAGIARISM_LOCAL_ROOT = Path("/home/tdkx/workspace/tech/data/corpus_local")
IMAGE_PLAGIARISM_REMOTE_ROOT = Path("/mnt/remote_corpus")
IMAGE_PLAGIARISM_DEFAULT_CORPUS_PATH = IMAGE_PLAGIARISM_LOCAL_ROOT / "sbs_5000"

# Default thresholds.
DEFAULT_HASH_HAMMING_MAX = 18
DEFAULT_HIGH_SCORE = 0.82
DEFAULT_MEDIUM_SCORE = 0.62
DEFAULT_MIN_INLIERS = 10
