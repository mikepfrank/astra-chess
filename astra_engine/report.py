"""Self-contained visual evidence reports; no chess logic or external assets."""
import html
import json
from pathlib import Path


def render_report(result, output_path):
    template = Path(__file__).with_name("report.template.html").read_text(encoding="utf-8")
    payload = json.dumps(result, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    output = template.replace("__QUESTION__", html.escape(result.get("label", "Search evidence"), quote=True))
    output = output.replace("__EVIDENCE__", payload)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8")
    return path
