from __future__ import annotations

import json
import re
from typing import Iterable

from .events import AgentEvent, AgentEventType

_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def _event_item(event: AgentEvent) -> dict:
    data = event.data if isinstance(event.data, dict) else {}
    item = data.get("item") if isinstance(data.get("item"), dict) else {}
    return item


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value or "").strip().rstrip(".,);]")
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _extract_urls(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _URL_RE.findall(value)
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return _URL_RE.findall(text)


def analyze_trace(events: Iterable[AgentEvent]) -> dict:
    """Summarize observable Open Interpreter agent behavior for local web search.

    This intentionally analyzes only externally observable App Server events.
    It does not claim access to hidden model chain-of-thought. Reasoning summary
    events are reported separately when the runtime exposes them.
    """
    search_calls = 0
    fetch_calls = 0
    failed_tool_calls = 0
    repeated_identical_calls = 0
    tool_sequence: list[str] = []
    source_urls: list[str] = []
    reasoning_summaries: list[str] = []
    text_parts: list[str] = []
    turn_completed = False
    seen_calls: set[str] = set()

    for event in events:
        if event.type == AgentEventType.REASONING and event.content:
            reasoning_summaries.append(event.content)
        elif event.type in (AgentEventType.TEXT, AgentEventType.TEXT_DELTA) and event.content:
            text_parts.append(event.content)
        elif event.type == AgentEventType.STATUS and event.content == "Turn completed":
            turn_completed = True

        if event.type != AgentEventType.TOOL_COMPLETED:
            continue
        item = _event_item(event)
        if str(item.get("type") or "") != "mcpToolCall":
            continue
        server = str(item.get("server") or "")
        tool = str(item.get("tool") or "")
        if server != "local_search" or not tool:
            continue

        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        tool_sequence.append(f"{server}.{tool}")
        if tool == "search":
            search_calls += 1
        elif tool == "fetch_page":
            fetch_calls += 1

        status = str(item.get("status") or "").lower()
        if status == "failed" or item.get("error"):
            failed_tool_calls += 1

        key = json.dumps([server, tool, arguments], ensure_ascii=False, sort_keys=True)
        if key in seen_calls:
            repeated_identical_calls += 1
        else:
            seen_calls.add(key)

        source_urls.extend(_extract_urls(arguments))
        source_urls.extend(_extract_urls(item.get("result")))

    source_urls = _dedupe(source_urls)
    final_text = "".join(text_parts).strip()

    score = 100
    score -= min(60, failed_tool_calls * 25)
    score -= min(40, repeated_identical_calls * 20)
    if search_calls == 0:
        score -= 40
    if search_calls > 0 and not source_urls:
        score -= 15
    if search_calls > 0 and not turn_completed:
        score -= 10
    score = max(0, min(100, score))

    return {
        "search_calls": search_calls,
        "fetch_calls": fetch_calls,
        "failed_tool_calls": failed_tool_calls,
        "repeated_identical_calls": repeated_identical_calls,
        "tool_sequence": tool_sequence,
        "source_urls": source_urls,
        "reasoning_summaries": reasoning_summaries,
        "final_text": final_text,
        "turn_completed": turn_completed,
        "observable_agent_score": score,
    }
