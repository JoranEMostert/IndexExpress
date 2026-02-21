import re
from typing import Any

try:
    from expressindex_core.sanitize import sanitize_payload, strip_think_tags
except Exception:
    def strip_think_tags(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"<think>[\s\S]*?(</think>|$)", "", text, flags=re.IGNORECASE)
        return cleaned.strip()

    def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(payload)
        for key in (
            "report",
            "final_report",
            "agent_a_report",
            "agent_b_report",
            "final_answer",
            "recommended_position",
            "final_synthesis",
        ):
            if key in sanitized and isinstance(sanitized[key], str):
                sanitized[key] = strip_think_tags(sanitized[key])

        for list_key in ("cluster_reports", "synthesis_reports", "merge_reports", "skim_reports"):
            report_rows = sanitized.get(list_key)
            if isinstance(report_rows, list):
                patched = []
                for item in report_rows:
                    if isinstance(item, dict):
                        row = dict(item)
                        if isinstance(row.get("report"), str):
                            row["report"] = strip_think_tags(row["report"])
                        patched.append(row)
                    else:
                        patched.append(item)
                sanitized[list_key] = patched

        claim_rows = sanitized.get("claims")
        if isinstance(claim_rows, list):
            patched_claims = []
            for item in claim_rows:
                if isinstance(item, dict):
                    row = dict(item)
                    if isinstance(row.get("statement"), str):
                        row["statement"] = strip_think_tags(row["statement"])
                    patched_claims.append(row)
                else:
                    patched_claims.append(item)
            sanitized["claims"] = patched_claims

        return sanitized


__all__ = ["strip_think_tags", "sanitize_payload"]
