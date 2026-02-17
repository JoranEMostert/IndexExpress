import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp-server"))

from expressindex_cli.main import _sanitize_payload  # noqa: E402
from reporting import strip_think_blocks  # noqa: E402
from server import _strip_think_tags  # noqa: E402


def test_strip_think_blocks_removes_reasoning():
    text = "<think>hidden chain</think>Report body"
    assert strip_think_blocks(text) == "Report body"


def test_strip_think_blocks_handles_unclosed_tag():
    text = "<think>hidden forever"
    assert strip_think_blocks(text) == ""


def test_strip_think_blocks_keeps_final_answer_after_think():
    text = "<think>reasoning</think>\n\nOK"
    assert strip_think_blocks(text) == "OK"


def test_server_strip_think_tags_is_case_insensitive():
    text = "intro<THINK>private</THINK>done"
    assert _strip_think_tags(text) == "introdone"


def test_cli_payload_sanitizes_top_level_and_clusters():
    payload = {
        "report": "<think>internal</think>Visible report",
        "final_report": "<think>x</think>Visible final",
        "cluster_reports": [
            {"query": "q1", "report": "<think>private</think>Cluster report"},
            {"query": "q2", "report": "Already clean"},
        ],
        "synthesis_reports": [
            {"group": 1, "report": "<think>y</think>Synthesis"},
        ],
        "merge_reports": [
            {"agent": 1, "report": "<think>z</think>Merged"},
        ],
    }

    cleaned = _sanitize_payload(payload)

    assert cleaned["report"] == "Visible report"
    assert cleaned["final_report"] == "Visible final"
    assert cleaned["cluster_reports"][0]["report"] == "Cluster report"
    assert cleaned["cluster_reports"][1]["report"] == "Already clean"
    assert cleaned["synthesis_reports"][0]["report"] == "Synthesis"
    assert cleaned["merge_reports"][0]["report"] == "Merged"
