"""actions._sandbox_options — 샌드박스 옵션 정의.

별도 모듈로 분리된 이유: agent_sandbox, settings 등 여러 액션에서 참조.
이전: handlers._build_sandbox_options 안에 인라인.
"""
from __future__ import annotations

from typing import List

from ..presenter.base import Option, RISK_SAFE, RISK_MEDIUM, RISK_HIGH


def build_sandbox_options(
    cpu_label: str = "CPU 제한 (2코어)",
    memory_label: str = "메모리 제한 (4G)",
) -> List[Option]:
    """샌드박스 옵션 목록 생성.

    cpu/memory 라벨은 시스템 사양 기반으로 호출자가 동적으로 결정.
    """
    return [
        Option(
            id="isolation",
            label="컨테이너 격리 (필수)",
            default=True, locked=True, risk=RISK_SAFE,
            description="호스트 시스템은 컨테이너의 변경에서 보호됩니다",
        ),
        Option(
            id="block_internet",
            label="인터넷 차단 (DNS 비활성화)",
            default=True, risk=RISK_SAFE,
            description=(
                "외부 도메인 해석 차단. 호스트 Ollama 만 접근 가능.\n"
                "데이터 유출 방지에 효과적."
            ),
            excludes=["allow_internet"],
        ),
        Option(
            id="cpu_limit",
            label=cpu_label,
            default=True, risk=RISK_SAFE,
            description="컨테이너의 CPU 사용량을 제한 (시스템 응답성 보호)",
            excludes=["no_resource_limit"],
        ),
        Option(
            id="memory_limit",
            label=memory_label,
            default=True, risk=RISK_SAFE,
            description="컨테이너 메모리를 제한 (스왑 폭주 방지)",
            excludes=["no_resource_limit"],
        ),
        Option(
            id="auto_run",
            label="자동 실행 (--auto_run)",
            default=True, risk=RISK_SAFE,
            description=(
                "매 명령마다 y/n 확인 없이 자동 실행.\n"
                "샌드박스 안이라 호스트는 안전합니다."
            ),
        ),
        Option(
            id="allow_internet",
            label="인터넷 허용",
            default=False, risk=RISK_MEDIUM,
            description=(
                "pip install / API 호출 가능해집니다.\n"
                "에이전트가 외부와 자유롭게 통신.\n"
                "데이터 유출 / 악성 다운로드 위험 증가."
            ),
            excludes=["block_internet"],
        ),
        Option(
            id="no_resource_limit",
            label="CPU/메모리 제한 해제",
            default=False, risk=RISK_MEDIUM,
            description=(
                "자원 제한 없이 실행.\n"
                "폭주 시 PC 가 일시적으로 마비될 수 있습니다."
            ),
            excludes=["cpu_limit", "memory_limit"],
        ),
        Option(
            id="privileged",
            label="privileged 모드 (호스트 디바이스 노출)",
            default=False, risk=RISK_HIGH,
            description=(
                "컨테이너에 거의 호스트 수준 권한 부여.\n"
                "이 옵션은 격리의 의미를 크게 약화시킵니다.\n"
                "특수한 디버깅 용도가 아니면 사용하지 마세요."
            ),
        ),
    ]
