from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _file_sha256(path: Optional[str]) -> str:
    if not path:
        return ""
    file_path = Path(str(path))
    if not file_path.exists() or not file_path.is_file():
        return ""
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_hash(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


class ToolResultCache:
    """Cache deterministic tool results for evaluation runs."""

    CACHEABLE_TOOLS = {
        "calculate_macro_emission",
        "calculate_micro_emission",
        "calculate_dispersion",
        "analyze_hotspots",
        "query_emission_factors",
        "query_knowledge",
    }

    def __init__(
        self,
        cache_dir: str | Path = "evaluation/tool_cache",
        *,
        enabled: bool = True,
        project_root: Optional[str | Path] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.cache_dir = Path(cache_dir)
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
        self._meta_path = self.cache_dir / "_metadata.json"
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._refresh_commit_guard()

    def should_cache(self, tool_name: str) -> bool:
        return self.enabled and str(tool_name or "") in self.CACHEABLE_TOOLS

    def get(self, tool_name: str, file_path: Optional[str], args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.should_cache(tool_name):
            return None
        key = self._cache_key(tool_name, file_path, args)
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            with self._lock:
                self._misses += 1
            return None
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        with self._lock:
            self._hits += 1
        return payload.get("result") if isinstance(payload, dict) else None

    def put(self, tool_name: str, file_path: Optional[str], args: Dict[str, Any], result: Dict[str, Any]) -> None:
        if not self.should_cache(tool_name):
            return
        key = self._cache_key(tool_name, file_path, args)
        payload = {
            "tool_name": tool_name,
            "file_path": str(file_path) if file_path else None,
            "result": result,
            "commit_hash": self._current_commit_hash(),
        }
        path = self.cache_dir / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def invalidate_all(self) -> None:
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0
        self._write_metadata({"commit_hash": self._current_commit_hash()})

    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }

    def _cache_key(self, tool_name: str, file_path: Optional[str], args: Dict[str, Any]) -> str:
        payload = {
            "tool_name": str(tool_name or ""),
            "file_sha256": _file_sha256(file_path),
            "args": args,
        }
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()

    def _current_commit_hash(self) -> str:
        return _git_commit_hash(self.project_root)

    def _refresh_commit_guard(self) -> None:
        metadata = self._read_metadata()
        current = self._current_commit_hash()
        if metadata.get("commit_hash") != current:
            self.invalidate_all()
        elif not self._meta_path.exists():
            self._write_metadata({"commit_hash": current})

    def _read_metadata(self) -> Dict[str, Any]:
        if not self._meta_path.exists():
            return {}
        try:
            with self._meta_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _write_metadata(self, payload: Dict[str, Any]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._meta_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
