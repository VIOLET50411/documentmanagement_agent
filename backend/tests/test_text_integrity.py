from pathlib import Path


MOJIBAKE_MARKERS = (
    "\u9a9e\u6751",        # 骞村
    "\u5bb8\ue1bd\u68be",  # 宸梾
    "\u9352\u8dfa\u5bb3",  # 鍒跺害
    "\u93c2\u56e8\u3002",  # 鏂囨。
    "\u93c8\ue046\u7161",  # 鏈煡
    "\u9359\u509d\u20ac",  # 鍙傝€
    "\u7f01\u64b9\ue191",  # 缁撹
    "\u93bd\u6a3f\ue6e6",  # 鎽樿
    "\u9365\u70fd\u74df",  # 鍥炵瓟
    "\u6fc0\u7fe1\u80f6\u922b",  # 娴佺▼
)

SCAN_ROOTS = (
    Path("backend/app"),
    Path("backend/tests"),
    Path("frontend/src"),
    Path("docs"),
    Path("datasets"),
    Path("docmind-miniapp"),
)

SCAN_FILES = (
    Path("task_plan.md"),
    Path("findings.md"),
    Path("progress.md"),
)

SKIP_PARTS = {"__pycache__", "dist", "node_modules"}
SKIP_FILES = {Path("backend/tests/test_text_integrity.py")}
ALLOWED_SUFFIXES = {".py", ".ts", ".vue", ".js", ".css", ".md", ".json", ".yaml", ".yml", ".txt", ".csv"}


def _normalize_path(path: Path) -> Path:
    return Path(str(path).replace("\\", "/"))


def _should_scan(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        return False
    if any(part in SKIP_PARTS for part in path.parts):
        return False
    if _normalize_path(path) in SKIP_FILES:
        return False
    return True


def test_source_files_do_not_contain_common_mojibake_markers():
    hits: list[str] = []

    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not _should_scan(path):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in MOJIBAKE_MARKERS:
                if marker in text:
                    hits.append(f"{path}: {marker.encode('unicode_escape').decode()}")

    for path in SCAN_FILES:
        if not path.exists() or not _should_scan(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                hits.append(f"{path}: {marker.encode('unicode_escape').decode()}")

    assert not hits, "Found suspicious mojibake markers:\n" + "\n".join(hits[:50])
