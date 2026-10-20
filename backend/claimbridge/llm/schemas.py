"""Structured outputs the agents ask LLMs for. Everything is validated again downstream."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

ReasonCode = Literal["PREAUTH_MISSING", "NOT_MED_NECESSARY", "EXCLUDED_SERVICE", "WAITING_PERIOD",
                     "OUT_OF_NETWORK", "INCOMPLETE_DOCS", "CODING_ERROR", "DUPLICATE_CLAIM",
                     "TIMELY_FILING"]


class IntakeExtraction(BaseModel):
    denial_reason: Literal["PREAUTH_MISSING", "NOT_MED_NECESSARY", "EXCLUDED_SERVICE", "WAITING_PERIOD",
                           "OUT_OF_NETWORK", "INCOMPLETE_DOCS", "CODING_ERROR", "DUPLICATE_CLAIM",
                           "TIMELY_FILING", "UNKNOWN"] = Field(
        description="The actual denial reason; UNKNOWN if not a denial or unsupported")
    cited_section: Optional[str] = Field(description="Policy section number quoted in the notice, e.g. '4.2', or null")
    mentions_emergency: bool = Field(description="Whether the notice says the service was an emergency")
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(description="One sentence: which words in the notice decided the reason")


class PlanItem(BaseModel):
    kind: Literal["EVIDENCE_NEEDED", "ACTION", "WARNING", "REJECTED_PRECEDENT"]
    text: str = Field(description="One plain-language sentence for the policyholder or caseworker")
    cite_ids: list[str] = Field(description="IDs from ALLOWED_IDS that support this item")


class PlanDraft(BaseModel):
    summary: str = Field(description="Two sentences at most. No promise of approval.")
    items: list[PlanItem]


EvidenceCode = Literal["PREAUTH_APPROVAL", "RETRO_AUTH_REQUEST", "SPECIALIST_REFERRAL",
                       "PHYSICIAN_NECESSITY_LETTER", "PROGRESS_NOTES", "ITEMIZED_BILL",
                       "CORRECTED_CODING_SUBMISSION", "DISCHARGE_SUMMARY", "EMERGENCY_ATTESTATION",
                       "BMI_RECORD", "SUPERVISED_PROGRAM_RECORD", "GENETIC_COUNSELOR_REFERRAL",
                       "LAB_REPORT", "ENROLLMENT_RECORD", "PROOF_OF_TIMELY_FILING"]
Disposition = Literal["APPEAL_VIABLE", "APPEAL_NEEDS_EVIDENCE", "NO_BASIS_ESCALATE"]


class BaselineItem(BaseModel):
    kind: Literal["EVIDENCE_NEEDED", "ACTION", "WARNING", "REJECTED_PRECEDENT"]
    text: str
    cite_ids: list[str] = Field(description="IDs of retrieved passages (CL-... or CS-...) that support this item")


class BaselineFindingsAnswer(BaseModel):
    """The information-parity baseline: it sees the same abstract findings ClaimBridge stores, and names
    the findings (F-...) it relies on instead of past cases."""
    denial_reason: ReasonCode
    policy_version: Literal["V2024", "V2025", "V2026"] = Field(
        description="The policy version in force on the service date")
    cited_section: Optional[str] = Field(description="Policy section the denial rests on, e.g. '4.2'")
    required_evidence: list[EvidenceCode] = Field(description="Evidence an appeal needs under the governing terms")
    missing_evidence: list[EvidenceCode] = Field(description="Required evidence the claim does not have yet")
    precedent_finding_ids: list[str] = Field(
        description="IDs of findings (F-...) that apply to this claim; empty if none apply")
    disposition: Disposition
    summary: str
    items: list[BaselineItem]


class BaselineAnswer(BaseModel):
    """What the plain-RAG baseline must decide: the same decisions ClaimBridge makes."""
    denial_reason: ReasonCode
    policy_version: Literal["V2024", "V2025", "V2026"] = Field(
        description="The policy version in force on the service date")
    cited_section: Optional[str] = Field(description="Policy section the denial rests on, e.g. '4.2'")
    required_evidence: list[EvidenceCode] = Field(description="Evidence an appeal needs under the governing terms")
    missing_evidence: list[EvidenceCode] = Field(description="Required evidence the claim does not have yet")
    precedent_case_ids: list[str] = Field(
        description="IDs of past cases (HC-...) whose resolution applies to this claim; empty if none apply")
    disposition: Disposition
    summary: str
    items: list[BaselineItem]
