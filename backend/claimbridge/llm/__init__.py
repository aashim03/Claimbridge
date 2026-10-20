"""Provider-agnostic structured LLM calls.

    result = complete(task="intake", system=..., user=..., schema=MyPydanticModel)

The platform comes from LLM_PLATFORM (groq | openai | claude | fake). Every call is
recorded under data/llm_cache, keyed by platform, model, prompt and schema, so the
evaluation and the demo can replay exactly (LLM_MODE=cached or offline).

The LLM only ever extracts structure from text or phrases wording. Callers validate
its output against the graph before anything is written.
"""
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass

from pydantic import BaseModel

from claimbridge import config

log = logging.getLogger("claimbridge.llm")


class LLMError(Exception):
    pass


@dataclass
class Meta:
    platform: str
    model: str
    cached: bool
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


def _provider(platform: str):
    if platform == "groq":
        from claimbridge.llm import openai_compat
        return openai_compat.GroqProvider()
    if platform == "openai":
        from claimbridge.llm import openai_compat
        return openai_compat.OpenAIProvider()
    if platform == "claude":
        from claimbridge.llm import claude
        return claude.ClaudeProvider()
    if platform == "fake":
        from claimbridge.llm import fake
        return fake.FakeProvider()
    raise LLMError(f"unknown LLM_PLATFORM {platform!r}")


def model_name(platform: str | None = None) -> str:
    platform = platform or config.LLM_PLATFORM
    return config.LLM_MODEL or config.DEFAULT_MODELS[platform]


def _key(platform, model, task, system, user, schema) -> str:
    blob = json.dumps([platform, model, task, system, user, schema.model_json_schema()],
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def complete(task: str, system: str, user: str, schema: type[BaseModel],
             effort: str | None = None, model: str | None = None,
             max_tokens: int | None = None) -> tuple[BaseModel, Meta]:
    """`model` overrides LLM_MODEL for this call (used for rate-limit fallbacks); `max_tokens` caps the
    completion (reasoning included) where the provider supports it."""
    platform = config.LLM_PLATFORM
    model = model or model_name(platform)
    key = _key(platform, model, task, system, user, schema)
    path = config.LLM_CACHE_DIR / platform / f"{task}-{key}.json"

    if config.LLM_MODE in ("cached", "offline") and path.exists():
        rec = json.loads(path.read_text(encoding="utf-8"))
        meta = Meta(platform, model, True, 0, rec.get("input_tokens"), rec.get("output_tokens"))
        _ledger(task, key, meta, user)
        return schema.model_validate(rec["output"]), meta
    if config.LLM_MODE == "offline" and platform != "fake":
        raise LLMError(f"LLM_MODE=offline and no recorded response for {task} ({key})")

    t0 = time.time()
    out, usage = _provider(platform).complete(model, system, user, schema,
                                              effort or config.LLM_REASONING_EFFORT, max_tokens=max_tokens)
    meta = Meta(platform, model, False, int((time.time() - t0) * 1000), *usage)
    if platform != "fake":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "task": task, "platform": platform, "model": model,
            "system": system, "user": user, "output": out.model_dump(mode="json"),
            "input_tokens": meta.input_tokens, "output_tokens": meta.output_tokens,
        }, indent=1), encoding="utf-8")
    log.info("llm %s via %s/%s in %d ms", task, platform, model, meta.latency_ms)
    _ledger(task, key, meta, user)
    return out, meta


_CLAIM = re.compile(r"\bEV-[A-Z0-9]+-[A-Z0-9]+\b")


def _ledger(task: str, key: str, meta: Meta, user: str):
    """During an evaluation run, record every call (fresh, replayed or fake) with the system and claim
    it served and the exact cache entry used, so tokens and costs are attributed, never inferred."""
    path = os.environ.get("EVAL_LEDGER")
    if not path:
        return
    m = _CLAIM.search(user)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "run_id": os.environ.get("EVAL_RUN_ID"),
           "system": os.environ.get("EVAL_SYSTEM"), "task": task, "key": key, "platform": meta.platform,
           "model": meta.model, "cached": meta.cached, "input_tokens": meta.input_tokens,
           "output_tokens": meta.output_tokens, "claim_id": m.group(0) if m else None}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def strict_schema(schema: type[BaseModel]) -> dict:
    """JSON schema in the strict form constrained decoders require: every object closed
    (additionalProperties false) and every property listed in `required`."""
    s = schema.model_json_schema()

    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}).keys())
            node.pop("default", None)
            node.pop("title", None)
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)
    fix(s)
    return s
