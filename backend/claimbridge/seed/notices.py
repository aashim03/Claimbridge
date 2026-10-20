"""Deterministic denial-notice text, written like real (fictional) denial letters.

Styles make the Intake agent do real work:
  cited       quotes the policy section number
  paraphrase  names the clause topic but no section
  vague       generic wording with only a soft hint
  misleading  wording that points at a different reason
"""
import random
import re

from claimbridge.knowledge import Clause

_HEAD = re.compile(r"^.*?Notice of claim denial\.\s*Claim \S+\.\s*")
_DATE = re.compile(r"\s*Date of service: [\d-]+\.")
_TAIL = re.compile(r"\s*You may appeal this decision.*$")


def notice_core(text: str) -> str:
    """The part of a denial letter that carries meaning: service and stated reason.
    Letterhead, claim number, dates and the standard appeal footer are dropped so
    they do not dominate the embedding."""
    return _TAIL.sub("", _DATE.sub("", _HEAD.sub("", text))).strip()

BODIES = {
    "PREAUTH_MISSING": [
        "Prior authorization was not obtained before this service was performed.",
        "Our records show no pre-approval on file for this service.",
        "This service required precertification from the plan, which was not requested.",
    ],
    "NOT_MED_NECESSARY": [
        "The documentation submitted does not establish that this service was medically necessary.",
        "The services billed exceed what is considered medically necessary for the diagnosis provided.",
        "Clinical review determined the treatment was not medically necessary as documented.",
    ],
    "EXCLUDED_SERVICE": [
        "This service is not a covered benefit under your plan.",
        "The procedure billed is excluded from coverage.",
        "Your policy lists this service as a non-covered exclusion.",
    ],
    "WAITING_PERIOD": [
        "The waiting period for this benefit had not been met on the date of service.",
        "Benefits for this service begin only after the required period of continuous enrollment.",
    ],
    "OUT_OF_NETWORK": [
        "The provider who rendered this service is not part of the Lumen network.",
        "Services from non-participating providers are not covered under your plan.",
    ],
    "INCOMPLETE_DOCS": [
        "The claim was submitted without the documentation required for review.",
        "Required records, such as the itemized bill or discharge summary, were not included.",
    ],
    "CODING_ERROR": [
        "The procedure code billed is not valid for the service described.",
        "The diagnosis and procedure codes on the claim are inconsistent.",
    ],
    "DUPLICATE_CLAIM": [
        "This claim duplicates a claim already processed for the same date of service.",
        "A claim for the same member, provider, date and amount has already been processed.",
    ],
    "TIMELY_FILING": [
        "The claim was received after the filing deadline.",
        "This claim was not submitted within the timely filing limit.",
    ],
}

VAGUE = {
    "PREAUTH_MISSING": "The required approval was not on file before the procedure, so the claim cannot be paid as submitted.",
    "NOT_MED_NECESSARY": "Based on our review, the claim does not meet the plan's criteria for payment.",
    "EXCLUDED_SERVICE": "This type of service falls outside what your plan pays for.",
    "WAITING_PERIOD": "You were not yet eligible for this benefit on the date of service.",
    "OUT_OF_NETWORK": "The plan does not pay for care from this provider.",
    "INCOMPLETE_DOCS": "We could not complete our review because some records were not received.",
    "CODING_ERROR": "The claim could not be processed as billed.",
    "DUPLICATE_CLAIM": "We have already processed this claim.",
    "TIMELY_FILING": "The claim reached us too late to be considered.",
}

MISLEADING = {
    "CODING_ERROR": ("Authorization review: the services billed could not be matched to an approved "
                     "service. The procedure code submitted is not valid for the service described."),
}


def notice_text(rng: random.Random, claim_id: str, service_name: str, date: int,
                reason: str, clause: Clause | None, style: str) -> str:
    d = f"{date // 10000}-{date // 100 % 100:02d}-{date % 100:02d}"
    head = (f"Lumen Health Assurance - Notice of claim denial. Claim {claim_id}. "
            f"Service: {service_name}. Date of service: {d}.")
    if style == "vague":
        body = VAGUE[reason]
    elif style == "misleading" and reason in MISLEADING:
        body = MISLEADING[reason]
    else:
        body = rng.choice(BODIES[reason])
        if clause is not None and style == "cited":
            body += f" See Section {clause.section} ({clause.title}) of your LumenCare Silver policy."
        elif clause is not None and style == "paraphrase":
            body += f" This decision applies the policy terms on {clause.title.lower()}."
    tail = "You may appeal this decision within 180 days of this notice."
    return f"{head} {body} {tail}"
