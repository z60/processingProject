"""回归评测与质量门禁（F-19 / F-20）。"""

from __future__ import annotations

from app.entity.chat import ChatRequest, ChatResponse
from app.entity.eval import CaseResult, RegressionCase, RegressionReport
from app.service.agent_service import AgentService
from app.util.config import conf, read_jsonl, settings
from app.util.log import get_logger
from app.util.rules import RulesEngine

log = get_logger("eval_service")


class EvalService:
    def __init__(self, agent_service: AgentService, rules: RulesEngine) -> None:
        self._agent = agent_service
        self._rules = rules
        self._eval_conf = conf("settings")["eval"]

    def load_cases(self) -> list[RegressionCase]:
        return [RegressionCase(**item) for item in read_jsonl(settings().seed_dir / "regression_cases.jsonl")]

    def run(self) -> RegressionReport:
        results: list[CaseResult] = []
        high_risk_total = 0
        high_risk_missed = 0
        for case in self.load_cases():
            turns = case.turns or [case.input_text]
            session_id = f"eval-{case.case_id}"
            response: ChatResponse | None = None
            for text in turns:
                response = self._agent.handle(ChatRequest(text=text, user_id="eval-user", session_id=session_id))
            if response is None:
                raise ValueError(f"回归用例 {case.case_id} 缺少输入，无法执行")
            failures = self._check(case, response)
            failures.extend(self._check_audit(case, response))
            trigger_type = response.handoff.trigger_type if response.handoff else ""
            if case.category == "risk":
                high_risk_total += 1
                if case.expected_status == "HANDOFF" and response.status != "HANDOFF":
                    high_risk_missed += 1
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    passed=not failures,
                    status=response.status,
                    intent=response.intent,
                    trigger_type=trigger_type,
                    failures=failures,
                )
            )
        total = len(results)
        passed = sum(1 for result in results if result.passed)
        pass_rate = round(passed / total, 4) if total else 0.0
        gate = "PASS"
        if pass_rate < float(self._eval_conf["min_pass_rate"]):
            gate = "FAIL"
        if self._eval_conf.get("fail_on_high_risk_miss", True) and high_risk_missed > 0:
            gate = "FAIL"
        return RegressionReport(
            total=total,
            passed=passed,
            high_risk_total=high_risk_total,
            high_risk_missed=high_risk_missed,
            pass_rate=pass_rate,
            gate=gate,
            results=results,
        )

    def _check_audit(self, case: RegressionCase, response: ChatResponse) -> list[str]:
        """审计关键字段完整率 100%：缺一即 FAIL。"""
        events = self._agent.audit_service.repository.replay(response.trace_id)
        if not events:
            return [f"审计事件缺失（trace_id={response.trace_id}）"]
        failures: list[str] = []
        for event in events:
            if not event.trace_id or not event.node or not event.event:
                failures.append(f"审计字段缺失：node={event.node} event={event.event}")
        if response.status == "HANDOFF" and not any(event.handoff_trigger for event in events):
            failures.append("转人工用例缺少 handoff_trigger 证据")
        return failures

    def _check(self, case: RegressionCase, response: ChatResponse) -> list[str]:
        failures: list[str] = []
        if case.expected_status and response.status != case.expected_status:
            failures.append(f"status 期望 {case.expected_status}，实际 {response.status}")
        if case.expected_intent and response.intent != case.expected_intent:
            failures.append(f"intent 期望 {case.expected_intent}，实际 {response.intent}")
        for assertion in case.assertions:
            kind = assertion.get("kind")
            value = assertion.get("value")
            if kind == "status" and response.status != value:
                failures.append(f"断言 status={value} 未满足（实际 {response.status}）")
            elif kind == "intent" and response.intent != value:
                failures.append(f"断言 intent={value} 未满足（实际 {response.intent}）")
            elif kind == "trigger_type":
                actual = response.handoff.trigger_type if response.handoff else ""
                if actual != value:
                    failures.append(f"断言 trigger_type={value} 未满足（实际 {actual}）")
            elif kind == "citations_min":
                if len(response.citations) < int(value):
                    failures.append(f"断言 citations>={value} 未满足（实际 {len(response.citations)}）")
            elif kind == "no_commitment":
                hits = self._rules.scan(response.reply)
                if hits:
                    failures.append(f"回复命中禁止承诺：{[hit.rule_id for hit in hits]}")
            elif kind == "reply_contains" and str(value) not in response.reply:
                failures.append(f"回复缺少关键内容：{value}")
            elif kind == "reply_not_contains" and str(value) in response.reply:
                failures.append(f"回复包含禁用内容：{value}")
        return failures
