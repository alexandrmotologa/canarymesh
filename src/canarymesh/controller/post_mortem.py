"""Automated post-mortem incident report generator for rollback events."""

import datetime
import logging
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("canarymesh.postmortem")


@dataclass
class PostMortemReport:
    """Structured report documenting an emergency rollback incident."""
    incident_id: str
    timestamp: str
    reason: str
    previous_canary_weight: float
    error_rate_percent: float
    p99_ms: float
    total_window_requests: int
    failed_requests_count: int
    markdown_summary: str


class PostMortemEngine:
    """Generates and archives post-mortem incident documentation."""

    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or Path("incidents")
        self.incidents: list[PostMortemReport] = []

    def record_incident(
        self,
        reason: str,
        previous_weight: float,
        metrics: dict[str, Any],
    ) -> PostMortemReport:
        """Create a post-mortem report and store it in memory and optionally on disk."""
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        now = datetime.datetime.now(datetime.UTC).isoformat()

        err_rate = float(metrics.get("error_rate_percent", 0.0))
        p99 = float(metrics.get("p99_ms", 0.0))
        total_reqs = int(metrics.get("total_requests", 0))
        status_5xx = int(metrics.get("status_5xx", 0))

        md_content = f"""# Incident Post-Mortem: {incident_id}

- **Date**: {now}
- **Service**: CanaryMesh Edge Proxy
- **Severity**: Critical (Automated Rollback Tripped)

## Executive Summary

At `{now}`, the CanaryMesh Rollback Guard triggered an emergency rollback, reducing Canary traffic weight from `{previous_weight:.1f}%` to `0.0%`.

## Trigger reason

> {reason}

## Telemetry at trigger point

| Metric | Recorded Value |
| :--- | :--- |
| **5xx Server Errors** | {status_5xx} requests |
| **5xx Error Rate** | {err_rate:.2f}% |
| **p99 Latency** | {p99:.1f} ms |
| **Active Window Requests** | {total_reqs} requests |

## Action taken

1. Canary traffic was immediately zeroed out to prevent client impact.
2. 100% of client traffic shifted to the Stable upstream.
3. Incident alerts were dispatched to configured notification channels.
"""

        report = PostMortemReport(
            incident_id=incident_id,
            timestamp=now,
            reason=reason,
            previous_canary_weight=previous_weight,
            error_rate_percent=err_rate,
            p99_ms=p99,
            total_window_requests=total_reqs,
            failed_requests_count=status_5xx,
            markdown_summary=md_content,
        )

        self.incidents.append(report)

        # Write to disk if directory exists or is accessible
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            report_file = self.output_dir / f"{incident_id}.md"
            report_file.write_text(md_content, encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to write report to disk: %s", exc)

        return report

    def get_incidents(self) -> list[dict[str, Any]]:
        """Return serialized list of all recorded incidents."""
        return [asdict(r) for r in self.incidents]
