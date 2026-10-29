"""跑回归集并执行质量门禁（F-19 / F-20）。

用法：
    python -m app.script.regression          # 门禁 PASS 退出码 0，FAIL 退出码 1
"""

from __future__ import annotations

import json
import sys

from app.service.agent_service import AgentService
from app.service.eval_service import EvalService


def main() -> int:
    service = AgentService()
    report = EvalService(service, service.rules).run()
    for result in report.results:
        flag = "PASS" if result.passed else "FAIL"
        trigger = f" trigger={result.trigger_type}" if result.trigger_type else ""
        print(f"[{flag}] {result.case_id:<6} {result.category:<9} status={result.status}{trigger}")
        for failure in result.failures:
            print(f"        - {failure}")
    print(
        f"\n通过 {report.passed}/{report.total}（{report.pass_rate:.1%}），"
        f"高风险漏转 {report.high_risk_missed}/{report.high_risk_total}，门禁 {report.gate}"
    )
    print(json.dumps(report.model_dump(), ensure_ascii=False)[:0])
    return 0 if report.gate == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
