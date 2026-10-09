"""Read only Codex telemetry; never collect message contents or credentials."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

FULL_SCAN_SECONDS = 60


def repo_name(cwd: str) -> str:
    return PureWindowsPath(cwd).name if "\\" in cwd else Path(cwd).name


@dataclass
class Quota:
    remaining: float | None = None
    resets_at: float | None = None
    observed_at: float = 0

    def available(self, now: float) -> bool:
        return self.remaining is not None and (not self.resets_at or now < self.resets_at)

    def stale(self, now: float) -> bool:
        return now - self.observed_at > 900


@dataclass
class Snapshot:
    provider: str = "codex"
    repo: str = "NO SESSION"
    branch: str = ""
    model: str = "UNKNOWN"
    effort: str = "UNKNOWN"
    context_tokens: int | None = None
    context_window: int | None = None
    context_observed_at: float = 0
    context_invalidated_at: float = 0
    context_remaining_override: float | None = None
    session_id: str = ""
    cwd: str = ""
    observed_at: float = 0
    five_hour: Quota = field(default_factory=Quota)
    weekly: Quota = field(default_factory=Quota)
    state: str = ""  # "working" while a turn runs, "done" once the agent has answered
    finished_at: float = 0

    @property
    def context_percent(self) -> float | None:
        if self.context_tokens is None or not self.context_window:
            return None
        return max(0, min(100, 100 * self.context_tokens / self.context_window))

    @property
    def context_left(self) -> float | None:
        if self.context_remaining_override is not None:
            return max(0, min(100, self.context_remaining_override))
        used = self.context_percent
        return None if used is None else 100 - used

    @property
    def context_tokens_left(self) -> int | None:
        left = self.context_left
        return round(self.context_window * left / 100) if self.context_window and left is not None else None


def timestamp(value: str | None, fallback: float = 0) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else fallback
    except (ValueError, AttributeError):
        return fallback


def parse_limits(value: dict | None, observed: float) -> tuple[Quota, Quota]:
    windows = {}
    if isinstance(value, dict) and value.get("limit_id", "codex") == "codex":
        for key in ("primary", "secondary"):
            item = value.get(key)
            if not isinstance(item, dict):
                continue
            used = item.get("used_percent")
            if not isinstance(used, (int, float)) or not 0 <= used <= 100:
                continue
            windows[item.get("window_minutes")] = Quota(100 - used, item.get("resets_at"), observed)
    return windows.get(300, Quota()), windows.get(10080, Quota())


class Session:
    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.identity = None
        self.root = True
        self.snapshot = Snapshot()
        self.rate_limits = None
        self.rate_observed_at = 0.0

    def read(self) -> None:
        stat = self.path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if self.identity != identity or stat.st_size < self.offset:
            self.offset = 0
            self.root = True
            self.snapshot = Snapshot()
            self.rate_limits = None
            self.rate_observed_at = 0
        self.identity = identity
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            while line := stream.readline():
                # The writer may have only flushed half a JSON line. Retry next poll.
                if not line.endswith(b"\n"):
                    break
                self.offset = stream.tell()
                try:
                    self.apply(json.loads(line))
                except (ValueError, TypeError, AttributeError):
                    continue
                if not self.root:
                    break

    def apply(self, event: dict) -> None:
        payload = event.get("payload") or {}
        observed = timestamp(event.get("timestamp"))
        kind = event.get("type")
        s = self.snapshot
        if kind == "session_meta":
            source = payload.get("source")
            self.root = not payload.get("parent_thread_id") and not (
                isinstance(source, dict) and "subagent" in source
            )
            s.session_id = payload.get("id", "")
            s.cwd = payload.get("cwd", "")
            s.repo = repo_name(s.cwd) or "NO REPO"
            s.branch = (payload.get("git") or {}).get("branch", "")
            s.observed_at = observed
        elif kind == "turn_context":
            s.model = payload.get("model") or "UNKNOWN"
            s.effort = payload.get("effort") or "UNKNOWN"
            s.cwd = payload.get("cwd") or s.cwd
            s.repo = repo_name(s.cwd) or "NO REPO"
            s.observed_at = max(s.observed_at, observed)
        elif kind == "event_msg" and payload.get("type") in ("task_started", "task_complete", "turn_aborted"):
            done = payload["type"] == "task_complete"
            s.state = "done" if done else "working" if payload["type"] == "task_started" else ""
            s.finished_at = observed if done else s.finished_at
            s.observed_at = max(s.observed_at, observed)
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info")
            if isinstance(info, dict):
                # Cumulative total_token_usage is NOT the current context size.
                last = info.get("last_token_usage") or {}
                tokens = last.get("total_tokens")
                window = info.get("model_context_window")
                if isinstance(tokens, int) and tokens >= 0:
                    s.context_tokens = tokens
                    s.context_observed_at = observed
                if isinstance(window, int) and window > 0:
                    s.context_window = window
            if isinstance(payload.get("rate_limits"), dict) and payload["rate_limits"].get("limit_id", "codex") == "codex":
                self.rate_limits = payload["rate_limits"]
                self.rate_observed_at = observed
            s.observed_at = max(s.observed_at, observed)
        elif kind == "token_usage_record":
            tokens = (payload.get("usage") or {}).get("total_tokens")
            if isinstance(tokens, int) and tokens >= 0:
                s.context_tokens = tokens
                s.context_observed_at = observed
                s.observed_at = max(s.observed_at, observed)


class CodexReader:
    def __init__(self, home: Path | None = None, repo: str = "", session_id: str = ""):
        self.home = home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        self.repo = repo
        self.session_id = session_id
        self.cache: dict[Path, Session] = {}
        self.known: set[Path] = set()
        self.scanned_at = 0.0

    def files(self) -> set[Path]:
        folder = self.home / "sessions"
        now = time.time()
        # The full tree grows for months; walk it rarely and check the newest leaf folder each poll.
        if now - self.scanned_at >= FULL_SCAN_SECONDS:
            self.known = set(folder.rglob("*.jsonl"))
            self.scanned_at = now
            return self.known
        leaf = folder
        while True:
            try:
                children = sorted((p for p in leaf.iterdir() if p.is_dir()), reverse=True)
            except OSError:
                break
            if not children:
                break
            leaf = children[0]
        self.known.update(leaf.glob("*.jsonl"))
        return self.known

    def poll(self) -> Snapshot:
        candidates = []
        for path in self.files():
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
        candidates.sort(reverse=True)
        roots = []
        # Read recent metadata first; guardian/review sessions must never replace the user session.
        for _, path in candidates[:128]:
            session = self.cache.setdefault(path, Session(path))
            try:
                session.read()
            except OSError:
                continue
            if session.root and session.snapshot.session_id:
                roots.append(session)
            if len(roots) >= 12:
                break
        keep = {p for _, p in candidates[:128]}
        self.cache = {p: v for p, v in self.cache.items() if p in keep}
        matched = [r for r in roots if (
            not self.repo or self.repo.casefold() in (r.snapshot.repo.casefold(), r.snapshot.cwd.casefold())
        ) and (not self.session_id or r.snapshot.session_id == self.session_id)]
        snapshot = max(matched, key=lambda r: r.snapshot.observed_at).snapshot if matched else Snapshot()
        # Limits are account-wide; use the freshest root snapshot, independent of repo pinning.
        limits = [r for r in roots if r.rate_limits is not None]
        if limits:
            latest = max(limits, key=lambda r: r.rate_observed_at)
            snapshot.five_hour, snapshot.weekly = parse_limits(latest.rate_limits, latest.rate_observed_at)
        else:
            snapshot.five_hour, snapshot.weekly = Quota(), Quota()
        return snapshot


def demo_snapshot() -> Snapshot:
    now = time.time()
    return Snapshot(repo="divoom-times-gate", branch="main", model="gpt-6.1-sol", effort="high",
                    context_tokens=74000, context_window=258400, context_observed_at=now,
                    observed_at=now, session_id="DEMO", five_hour=Quota(73, now + 7200, now),
                    weekly=Quota(91, now + 172800, now))
