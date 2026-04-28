from __future__ import annotations

from opentelemetry import metrics

meter = metrics.get_meter("fastapi_saas_template")

__all__ = ["meter"]
