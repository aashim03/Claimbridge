"""Indexes and constants for the claimbridge graph. Safe to run repeatedly."""
from claimbridge import config

STATUSES = ["NEW", "RECEIVED", "CLASSIFIED", "RETRIEVED", "VERIFIED", "PLANNED",
            "AWAITING_REVIEW", "APPROVED", "VERIFIED_OUTCOME", "CURATED", "NEEDS_HUMAN", "CLOSED"]

RANGE_INDEXES = [
    ("Claim", "claim_id"), ("Claim", "status"), ("Claim", "tenant_id"),
    ("Clause", "clause_id"), ("Clause", "lineage_id"), ("Clause", "section"),
    ("PolicyVersion", "version_id"), ("Finding", "finding_id"), ("Finding", "status"),
    ("DenialReason", "code"), ("EvidenceType", "code"), ("ServiceCategory", "code"),
    ("Tenant", "tenant_id"), ("CaseEvent", "event_id"), ("Checkpoint", "checkpoint_id"),
    ("Resolution", "resolution_id"), ("Playbook", "playbook_id"), ("Agent", "agent_id"),
    ("WorkerHeartbeat", "agent_id"), ("DenialNotice", "notice_id"), ("Evidence", "doc_id"),
    ("Investigation", "investigation_id"), ("ToolCall", "call_id"),
]

VECTOR_INDEXES = [("DenialNotice", "embedding"), ("DenialReason", "embedding")]


def _try(g, q):
    try:
        g.query(q)
    except Exception as e:  # index already exists
        if "already" not in str(e).lower():
            raise


def ensure(g):
    for label, prop in RANGE_INDEXES:
        _try(g, f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
    for label, prop in VECTOR_INDEXES:
        _try(g, f"CREATE VECTOR INDEX FOR (n:{label}) ON (n.{prop}) "
                f"OPTIONS {{dimension: {config.EMBED_DIM}, similarityFunction: 'cosine'}}")
