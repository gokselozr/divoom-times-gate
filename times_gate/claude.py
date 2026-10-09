"""Claude Code transcript fallback plus official status-line telemetry."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import time

from .codex import Snapshot, Quota, repo_name, timestamp
from .runtime import DATA_ROOT

TELEMETRY_MAX_AGE=7*86400


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool)


def interrupted(message):
    content=(message or {}).get("content") if isinstance(message,dict) else None
    texts=[content] if isinstance(content,str) else [
        item.get("text","") for item in content or [] if isinstance(item,dict)]
    return any(isinstance(t,str) and t.startswith("[Request interrupted") for t in texts)


def window_quota(item,observed):
    if not isinstance(item,dict):
        return Quota()
    used = item.get("used_percentage",item.get("utilization"))
    if not number(used) or not 0 <= used <= 100:
        return Quota()
    reset = item.get("resets_at")
    reset = timestamp(reset) if isinstance(reset,str) else reset
    return Quota(100-used,reset if number(reset) else None,observed)


def status_snapshot(data: dict,observed: float) -> Snapshot:
    workspace = data.get("workspace") or {}
    cwd = workspace.get("project_dir") or workspace.get("current_dir") or data.get("cwd") or ""
    model = data.get("model") or {}
    context = data.get("context_window") or {}
    rates = data.get("rate_limits") or {}
    remaining = context.get("remaining_percentage")
    used = context.get("used_percentage")
    if not number(remaining) and number(used):
        remaining = 100-used
    remaining = max(0,min(100,remaining)) if number(remaining) else None
    size = context.get("context_window_size")
    size = int(size) if number(size) and size > 0 else None
    usage = context.get("current_usage")
    tokens = None
    if isinstance(usage,dict):
        counts = [usage.get(k,0) for k in ("input_tokens","cache_creation_input_tokens","cache_read_input_tokens")]
        if all(number(n) and n >= 0 for n in counts):
            tokens = int(sum(counts))
    if tokens is None and size and remaining is not None:
        tokens = round(size*(100-remaining)/100)
    effort = data.get("effort") or {}
    branch = (data.get("worktree") or {}).get("branch") or ""
    return Snapshot(provider="claude",repo=(workspace.get("repo") or {}).get("name") or repo_name(cwd) or "NO REPO",
                    cwd=cwd,branch=branch,model=model.get("id") or model.get("display_name") or "UNKNOWN",
                    effort=effort.get("level") or "UNKNOWN",context_tokens=tokens,context_window=size,
                    context_remaining_override=remaining,context_observed_at=observed,
                    session_id=data.get("session_id") or "",observed_at=observed,
                    five_hour=window_quota(rates.get("five_hour"),observed),
                    weekly=window_quota(rates.get("seven_day"),observed))


class ClaudeSession:
    def __init__(self,path):
        self.path=path
        self.offset=0
        self.identity=None
        self.snapshot=Snapshot(provider="claude")
        self.window_hints={}

    def read(self):
        stat=self.path.stat()
        identity=(stat.st_dev,stat.st_ino)
        if self.identity != identity or stat.st_size < self.offset:
            self.offset=0
            self.snapshot=Snapshot(provider="claude")
            self.window_hints={}
        self.identity=identity
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            while line:=stream.readline():
                if not line.endswith(b"\n"):
                    break
                self.offset=stream.tell()
                try:
                    self.apply(json.loads(line))
                except (ValueError,TypeError,AttributeError):
                    continue

    def apply(self,event):
        if event.get("isSidechain") or event.get("agentId"):
            return
        s=self.snapshot
        kind=event.get("type")
        if kind not in ("assistant","user","system","cost-state"):
            return
        if not s.cwd and event.get("cwd"):
            s.cwd=event["cwd"]
            s.repo=repo_name(s.cwd) or "NO REPO"
        s.session_id=event.get("sessionId") or s.session_id
        # Claude records "HEAD" outside a git repo; that is not a branch name.
        branch=event.get("gitBranch")
        if branch and branch != "HEAD":
            s.branch=branch
        if kind in ("assistant","user"):
            s.observed_at=max(s.observed_at,timestamp(event.get("timestamp")))
        if kind == "user" and not event.get("isMeta"):
            # Prompts and tool results mean a turn is running; an interrupt ends it unanswered.
            s.state="" if interrupted(event.get("message")) else "working"
        if kind == "assistant":
            message=event.get("message") or {}
            reason=message.get("stop_reason")
            if reason == "end_turn":
                s.state="done"
                s.finished_at=timestamp(event.get("timestamp"))
            elif reason:
                s.state="working"
            model=message.get("model")
            previous=s.model
            if model and model != "<synthetic>":
                s.model=model
            effort=event.get("perTurnEffort") or event.get("effort")
            if isinstance(effort,str):
                s.effort=effort
            usage=message.get("usage")
            if isinstance(usage,dict):
                counts=[usage.get(k,0) for k in ("input_tokens","cache_creation_input_tokens","cache_read_input_tokens")]
                if all(number(n) and n >= 0 for n in counts):
                    s.context_tokens=int(sum(counts))
                    s.context_observed_at=timestamp(event.get("timestamp"))
            explicit=message.get("context_window") or event.get("context_window")
            if isinstance(explicit,dict) and number(explicit.get("context_window_size")):
                s.context_window=int(explicit["context_window_size"])
            elif model in self.window_hints:
                s.context_window=self.window_hints[model]
            elif model and model not in ("<synthetic>",previous):
                # A different model's window must not be reused; keep it for the same model.
                s.context_window=None
        elif kind == "cost-state":
            # A recorded [1m] model variant is session evidence, not a guess from today's defaults.
            for model,usage in (event.get("modelUsage") or {}).items():
                if "[1m]" in model:
                    self.window_hints[model.replace("[1m]","")]=1000000
                elif isinstance(usage,dict) and number(usage.get("contextWindow")):
                    self.window_hints[model]=int(usage["contextWindow"])
            if s.model in self.window_hints:
                s.context_window=self.window_hints[s.model]
        elif kind == "system" and event.get("subtype") == "compact_boundary":
            # The pre-compaction input is no longer the current context.
            s.context_tokens=None
            s.context_remaining_override=None
            s.context_invalidated_at=max(s.context_invalidated_at,timestamp(event.get("timestamp"),s.observed_at))
            s.context_observed_at=s.context_invalidated_at
            s.observed_at=max(s.observed_at,s.context_invalidated_at)


class ClaudeReader:
    def __init__(self,home: Path | None=None,repo="",session_id="",telemetry: Path | None=None):
        self.home=home or Path(os.environ.get("CLAUDE_CONFIG_DIR",str(Path.home()/".claude")))
        self.repo=repo
        self.session_id=session_id
        self.telemetry=telemetry or DATA_ROOT/"output"/"claude"/"telemetry"
        self.cache={}

    def matches(self,s):
        return (not self.repo or self.repo.casefold() in (s.repo.casefold(),s.cwd.casefold())) and (
            not self.session_id or self.session_id==s.session_id)

    def poll(self):
        snapshots=[]
        # Only top-level transcripts; subagent folders must not become the main conversation.
        paths=[]
        for path in (self.home/"projects").glob("*/*.jsonl"):
            try: paths.append((path.stat().st_mtime,path))
            except OSError: pass
        paths.sort(reverse=True)
        recent=paths[:24]
        for _,path in recent:
            session=self.cache.setdefault(path,ClaudeSession(path))
            try: session.read()
            except OSError: continue
            if session.snapshot.session_id:
                snapshots.append(session.snapshot)
        self.cache={p:self.cache[p] for _,p in recent if p in self.cache}
        native={}
        now=time.time()
        for path in self.telemetry.glob("*.json"):
            try:
                # Bridge files are this app's own output; drop sessions idle for a week.
                if now-path.stat().st_mtime > TELEMETRY_MAX_AGE:
                    path.unlink(missing_ok=True)
                    continue
                data=json.loads(path.read_text(encoding="utf-8"))
                snap=status_snapshot(data,float(data.get("observed_at",path.stat().st_mtime)))
                if snap.session_id:
                    native[snap.session_id]=snap
            except (OSError,ValueError,TypeError,AttributeError):
                continue
        merged={s.session_id:merge(native.get(s.session_id),s) for s in snapshots}
        for session_id,snap in native.items():
            merged.setdefault(session_id,replace(snap))
        selected=[s for s in merged.values() if self.matches(s)]
        result=max(selected,key=lambda s:s.observed_at) if selected else Snapshot(provider="claude")
        # Limits are account-wide; take the freshest status-line report from any session.
        limits=[s for s in native.values() if s.five_hour.remaining is not None or s.weekly.remaining is not None]
        if limits:
            account=max(limits,key=lambda s:s.observed_at)
            result.five_hour,result.weekly=account.five_hour,account.weekly
        else:
            result.five_hour,result.weekly=Quota(),Quota()
        return result


def merge(native,transcript):
    """Status-line data wins for one session; the transcript fills gaps and marks activity."""
    if native is None:
        return replace(transcript)
    result=replace(native,observed_at=max(native.observed_at,transcript.observed_at),
                   state=transcript.state,finished_at=transcript.finished_at,
                   context_invalidated_at=transcript.context_invalidated_at)
    for name,missing in (("model","UNKNOWN"),("effort","UNKNOWN"),("branch",""),("cwd","")):
        if getattr(result,name)==missing:
            setattr(result,name,getattr(transcript,name))
    if result.repo=="NO REPO":
        result.repo=transcript.repo
    if transcript.context_invalidated_at and native.context_observed_at <= transcript.context_invalidated_at:
        result.context_tokens=None
        result.context_remaining_override=None
        result.context_observed_at=transcript.context_invalidated_at
    if transcript.context_left is not None and (
            result.context_left is None or transcript.context_observed_at > native.context_observed_at):
        result.context_remaining_override=None
        result.context_tokens=transcript.context_tokens
        result.context_window=transcript.context_window
        result.context_observed_at=transcript.context_observed_at
    return result


def demo_snapshot():
    now=time.time()
    return Snapshot(provider="claude",repo="creative-studio",branch="main",model="claude-opus-5",effort="high",
                    context_tokens=140000,context_window=200000,context_observed_at=now,observed_at=now,
                    session_id="DEMO",five_hour=Quota(65,now+5400,now),weekly=Quota(82,now+172800,now))
