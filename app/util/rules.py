"""确定性规则引擎：强制转人工触发与禁止承诺检测。

规则全部来自 conf/risk_rules.json，改规则不改代码（F-05 / F-10 / 6.4）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.util.config import conf

_NEGATIONS = ("不得", "不能", "不会", "禁止", "无法", "不可", "不予", "不承诺", "不支持", "不含")


@dataclass(frozen=True)
class ForbiddenHit:
    rule_id: str
    desc: str
    action: str  # rewrite | handoff
    matched: str
    replacement: str = ""


class RulesEngine:
    def __init__(self, config: dict | None = None) -> None:
        cfg = config if config is not None else conf("risk_rules")
        self._cfg = cfg
        self._handoff_rules: list[dict] = cfg.get("handoff_rules", [])
        self._patterns = [(item, re.compile(item["pattern"])) for item in cfg.get("forbidden_patterns", [])]
        self._escalations = [(item, re.compile(item["pattern"])) for item in cfg.get("escalation_patterns", [])]

    @property
    def no_evidence_reply(self) -> str:
        return self._cfg.get("no_evidence_reply", "未找到相关制度条款")

    def handoff_reply(self, ticket_id: str) -> str:
        template = self._cfg.get("handoff_reply", "该诉求已转人工处理，工单号 {ticket_id}。")
        return template.format(ticket_id=ticket_id)

    def scan(self, text: str) -> list[ForbiddenHit]:
        """扫描回复草稿；带否定前缀（不得/禁止/不可）的引用条款不算违规。"""
        hits: list[ForbiddenHit] = []
        for item, pattern in self._patterns:
            for match in pattern.finditer(text or ""):
                start = max(0, match.start() - 8)
                if any(neg in text[start : match.end()] for neg in _NEGATIONS):
                    continue
                hits.append(
                    ForbiddenHit(
                        rule_id=item["id"],
                        desc=item.get("desc", ""),
                        action=item.get("action", "rewrite"),
                        matched=match.group(0),
                        replacement=item.get("replacement", ""),
                    )
                )
        return hits

    def scan_escalation(self, text: str) -> list[dict]:
        """扫描用户输入中的升级信号（法律/监管/投诉升级）。"""
        hits: list[dict] = []
        for item, pattern in self._escalations:
            for match in pattern.finditer(text or ""):
                hits.append({"rule_id": item["id"], "desc": item.get("desc", ""), "matched": match.group(0)})
        return hits

    def rewrite(self, text: str) -> tuple[str, list[ForbiddenHit], bool]:
        """命中 rewrite 的记录重写；命中 handoff 的记录要求转人工。"""
        hits = self.scan(text)
        rewritten = text or ""
        needs_handoff = False
        for hit in hits:
            if hit.action == "handoff":
                needs_handoff = True
                continue
            rewritten = rewritten.replace(hit.matched, hit.replacement)
        return rewritten, hits, needs_handoff

    def evaluate(
        self,
        *,
        intent: str,
        confidence: float,
        clarify_rounds: int,
        text: str,
    ) -> dict | None:
        """按配置顺序返回首个命中的转人工触发；未命中返回 None。"""
        for rule in self._handoff_rules:
            when = rule.get("when", {})
            if "forbidden_hit" in when:
                continue  # 由 guard 根据禁止承诺检测结果单独判定
            if "intents" in when and intent not in when["intents"]:
                continue
            if "confidence_between" in when:
                low, high = when["confidence_between"]
                if not (low <= confidence < high):
                    continue
            if "clarify_rounds_gte" in when and clarify_rounds < when["clarify_rounds_gte"]:
                continue
            if "text_patterns" in when:
                matched = next((p for p in when["text_patterns"] if p in (text or "")), None)
                if matched is None:
                    continue
            else:
                matched = None
            detail: dict = {"rule": rule["id"]}
            if "confidence_between" in when:
                detail["confidence"] = confidence
                detail["range"] = when["confidence_between"]
            if "intent" not in detail:
                detail["intent"] = intent
            if matched:
                detail["matched_pattern"] = matched
            if "clarify_rounds_gte" in when:
                detail["clarify_rounds"] = clarify_rounds
            return {"type": rule["id"], "desc": rule.get("desc", ""), "detail": detail}
        return None
