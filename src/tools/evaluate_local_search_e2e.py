from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_paths import ENV_DIR, USER_DATA_DIR as USER_DATA
from runtime_versions import OPEN_INTERPRETER_VERSION

from launcher import config as launcher_config
from launcher.agent.backend import AgentConfig, ProcessRuntimeSpec
from launcher.agent.backend_factory import create_backend
from launcher.agent.events import AgentEvent
from launcher.agent.local_search_eval import analyze_trace, assess_case, collect_turn
from launcher.agent.profiles import default as default_profile
from launcher.agent.runtime_config import build_cmd_for_mode
from launcher.agent.service import AgentService


CASES = [
    {
        "name": "current_python_version",
        "prompt": (
            "오늘 기준 Python의 최신 안정 버전을 인터넷에서 확인해줘. "
            "검색 결과를 사용하고, 확인한 공개 출처 URL을 최소 1개 포함해서 두 문장 이내로 답해줘."
        ),
        "expect_search": True,
        "min_fetch": 0,
        "min_sources": 1,
        "require_citation": True,
    },
    {
        "name": "oi_search_architecture",
        "prompt": (
            f"Open Interpreter {OPEN_INTERPRETER_VERSION}의 MCP 기능과 web search 구현 방식을 웹에서 조사해줘. "
            "서로 다른 공개 출처 최소 2개의 본문을 실제로 읽고, 일반 검색이 Playwright 브라우저 자동화인지 "
            "HTTP/provider search 방식인지 근거 URL과 함께 짧게 결론 내줘."
        ),
        "expect_search": True,
        "min_fetch": 2,
        "min_sources": 2,
        "require_citation": True,
    },
    {
        "name": "arithmetic_control",
        "prompt": "17 * 23을 계산해서 숫자만 답해줘. 인터넷 검색은 필요하지 않아.",
        "expect_search": False,
        "min_fetch": 0,
        "min_sources": 0,
    },
]


def build_agent_config(
    *,
    workspace: Path,
    mode: str,
    model: str,
    network_mode: str,
    runtime_spec: ProcessRuntimeSpec | None = None,
) -> AgentConfig:
    profile = default_profile()
    return AgentConfig(
        workspace=Path(workspace),
        mode=mode,
        model=model,
        network_mode=network_mode,
        profile_name=profile.name,
        runtime_spec=runtime_spec,
        instructions=profile.system_message,
    )


def serialize_event(event: AgentEvent) -> dict:
    return {
        "type": event.type.value,
        "content": event.content,
        "source_level": event.source_level,
        "request_id": event.request_id,
        "data": dict(event.data) if event.data is not None else None,
    }


def _http_json(url: str, timeout: float = 3.0):
    request = urllib.request.Request(url, headers={"User-Agent": "Local_AI_Agent-E2E/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _preflight(model: str) -> dict:
    result = {"ollama": False, "model_installed": False, "searxng": False, "notes": []}
    try:
        tags = _http_json(launcher_config.OLLAMA_API_TAGS)
        result["ollama"] = True
        installed = {
            str(item.get("name") or item.get("model") or "")
            for item in (tags.get("models") or [])
            if isinstance(item, dict)
        }
        result["model_installed"] = model in installed
        if not result["model_installed"]:
            result["notes"].append(f"model not listed by Ollama: {model}")
    except Exception as exc:
        result["notes"].append(f"Ollama preflight failed: {type(exc).__name__}: {exc}")

    try:
        _http_json(launcher_config.SEARXNG_URL.rstrip("/") + "/search?q=Open+Interpreter&format=json")
        result["searxng"] = True
    except Exception as first_exc:
        try:
            from launcher import searxng_runtime

            searxng_runtime.start(ENV_DIR)
            _http_json(launcher_config.SEARXNG_URL.rstrip("/") + "/search?q=Open+Interpreter&format=json", timeout=8.0)
            result["searxng"] = True
        except Exception as exc:
            result["notes"].append(
                "SearXNG preflight failed: "
                + f"{type(first_exc).__name__}: {first_exc}; start retry: {type(exc).__name__}: {exc}"
            )
    return result


def _runtime_spec_for_case(*, mode: str, workspace: Path, model: str) -> tuple[ProcessRuntimeSpec | None, bool]:
    if mode == "host":
        return None, True

    profile = default_profile()
    container = launcher_config.SANDBOX_CONTAINER_PREFIX + "eval_" + secrets.token_hex(4)
    command, is_host = build_cmd_for_mode(
        "sandbox",
        ENV_DIR,
        profile,
        workspace,
        container,
        None,
        None,
        model_tag=model,
        tor_proxy=(launcher_config.NET_MODE == "tor"),
    )
    if command is None or is_host:
        raise RuntimeError("Could not build the sandbox runtime command")
    return ProcessRuntimeSpec(command=tuple(str(part) for part in command)), False


def _run_case(*, case: dict, mode: str, model: str, timeout_s: float, workspace_root: Path) -> dict:
    workspace = workspace_root / case["name"]
    workspace.mkdir(parents=True, exist_ok=True)
    runtime_spec, _ = _runtime_spec_for_case(mode=mode, workspace=workspace, model=model)
    config = build_agent_config(
        workspace=workspace,
        mode=mode,
        model=model,
        network_mode=launcher_config.NET_MODE,
        runtime_spec=runtime_spec,
    )
    service = AgentService(create_backend(mode, ENV_DIR))
    events: list[AgentEvent] = []
    start_error = None
    try:
        if not service.start(config):
            startup = service.poll_events(max_n=500)
            events.extend(startup)
            detail = "; ".join(event.content for event in startup if event.content) or "unknown startup failure"
            raise RuntimeError(detail)
        events = collect_turn(service, case["prompt"], timeout_s=timeout_s)
        report = analyze_trace(events)
        assessment = assess_case(
            report,
            require_citation=bool(case.get("require_citation")),
            expect_search=bool(case["expect_search"]),
            min_fetch=int(case.get("min_fetch", 0)),
            min_sources=int(case.get("min_sources", 0)),
        )
    except Exception as exc:
        start_error = f"{type(exc).__name__}: {exc}"
        report = analyze_trace(events)
        assessment = {"passed": False, "failures": ["runtime_error"]}
    finally:
        service.stop(timeout=3.0)

    return {
        "name": case["name"],
        "prompt": case["prompt"],
        "expectation": {
            "expect_search": case["expect_search"],
            "min_fetch": case.get("min_fetch", 0),
            "min_sources": case.get("min_sources", 0),
        },
        "runtime_error": start_error,
        "report": report,
        "assessment": assessment,
        "events": [serialize_event(event) for event in events],
    }


def run_suite(*, mode: str, model: str, timeout_s: float) -> dict:
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    result_dir = USER_DATA / "search_eval_results"
    workspace_root = USER_DATA / "search_eval_workspace"
    result_dir.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    preflight = _preflight(model)
    cases = [
        _run_case(
            case=case,
            mode=mode,
            model=model,
            timeout_s=timeout_s,
            workspace_root=workspace_root,
        )
        for case in CASES
    ]
    passed = sum(1 for case in cases if case["assessment"]["passed"])
    suite = {
        "timestamp": stamp,
        "model": model,
        "quantization": model.rsplit(":", 1)[-1] if ":" in model else "unknown",
        "mode": mode,
        "network_mode": launcher_config.NET_MODE,
        "preflight": preflight,
        "summary": {"passed": passed, "total": len(cases), "all_passed": passed == len(cases)},
        "cases": cases,
        "analysis_scope": (
            "Observable Open Interpreter/App Server events only: reasoning summaries when emitted, "
            "MCP tool calls/results, final text, failures and repetition. Hidden chain-of-thought is not inspected."
        ),
    }
    filename = "local_search_e2e_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    output = result_dir / filename
    output.write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")
    suite["output_file"] = str(output)
    return suite


def _print_summary(suite: dict) -> None:
    print("=" * 72)
    print("Local_AI_Agent local search E2E")
    print("model:", suite["model"])
    print("quantization:", suite["quantization"])
    print("mode:", suite["mode"], "/ network:", suite["network_mode"])
    print("preflight:", json.dumps(suite["preflight"], ensure_ascii=False))
    print("-" * 72)
    for case in suite["cases"]:
        report = case["report"]
        verdict = "PASS" if case["assessment"]["passed"] else "FAIL"
        print(
            f"[{verdict}] {case['name']}: search={report['search_calls']} "
            f"fetch={report['fetch_calls']} failures={report['failed_tool_calls']} "
            f"repeats={report['repeated_identical_calls']} sources={len(report['source_urls'])} "
            f"score={report['observable_agent_score']}"
        )
        if case["runtime_error"]:
            print("  runtime_error:", case["runtime_error"])
        if case["assessment"]["failures"]:
            print("  assessment:", ", ".join(case["assessment"]["failures"]))
        print("  tools:", " -> ".join(report["tool_sequence"]) or "(none)")
        print("  answer:", report["final_text"][:500].replace("\n", " "))
    print("-" * 72)
    print(f"result: {suite['summary']['passed']}/{suite['summary']['total']} passed")
    print("json:", suite["output_file"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run real Local_AI_Agent web-search E2E evaluation")
    parser.add_argument("--mode", choices=("sandbox", "host"), default="sandbox")
    parser.add_argument("--model", default=launcher_config.MODEL_TAG)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args(argv)

    suite = run_suite(mode=args.mode, model=args.model, timeout_s=max(10.0, args.timeout))
    _print_summary(suite)
    return 0 if suite["summary"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
