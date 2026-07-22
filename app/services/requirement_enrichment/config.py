from __future__ import annotations

import os

from app.services.requirement_enrichment.models import EnrichmentMode


def enrichment_mode() -> EnrichmentMode:
    raw = os.getenv("KB_ANALYSIS_ENRICHMENT_MODE", EnrichmentMode.SHADOW.value).strip().lower()

    if raw == EnrichmentMode.OFF.value:
        return EnrichmentMode.OFF

    if raw == EnrichmentMode.MANUAL.value:
        return EnrichmentMode.MANUAL

    if raw == EnrichmentMode.AUTOMATIC.value:
        return EnrichmentMode.AUTOMATIC

    return EnrichmentMode.SHADOW
