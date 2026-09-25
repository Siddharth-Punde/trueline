from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict


class EngineType(str, Enum):
    GOOGLE_SEARCH = "google_search"
    GOOGLE_MAPS = "google_maps"
    GOOGLE_LOCAL = "google_local"
    ADS_TRANSPARENCY = "ads_transparency"


class FindingKind(str, Enum):
    UNOFFICIAL_PHONE = "unofficial_phone"
    UNOFFICIAL_DOMAIN = "unofficial_domain"
    AD_OFF_DOMAIN = "ad_off_domain"
    ADVERTISER_MISMATCH = "advertiser_mismatch"
    MAPS_LISTING_MISMATCH = "maps_listing_mismatch"


class Brand(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    id: str
    display_name: str
    official_domains: list[str]
    official_phones: list[str]
    aliases: list[str] = Field(default_factory=list)


class PlannedQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    engine: EngineType
    query_text: str
    params: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    evidence_id: str
    engine: EngineType
    query: str
    is_ad: bool
    position: int | None
    title: str
    link: str | None
    snippet: str | None
    raw: dict[str, Any]


class Finding(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    finding_id: str
    kind: FindingKind
    value: str
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str


class ScanResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    brand_id: str
    scanned_at: datetime
    trust_score: int = Field(ge=0, le=100)
    findings: list[Finding]
    evidence: list[Evidence]