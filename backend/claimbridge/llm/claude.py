"""Claude via the Anthropic SDK, with structured outputs (messages.parse + Pydantic)."""
from pydantic import BaseModel

from claimbridge import config
from claimbridge.llm import LLMError


class ClaudeProvider:
    def __init__(self):
        import anthropic
        key = config.env_any("ANTHROPIC_API_KEY", "claude_key", "anthropic_key")
        # Without an explicit key the SDK falls back to its own credential chain.
        self.client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()

    def complete(self, model: str, system: str, user: str, schema: type[BaseModel], effort: str,
                 max_tokens: int | None = None):
        import anthropic
        try:
            resp = self.client.messages.parse(
                model=model,
                max_tokens=max_tokens or 16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort or "medium"},
                output_format=schema,
            )
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Claude connection error: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("Claude declined the request (refusal)")
        if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
            raise LLMError(f"no structured output (stop_reason={resp.stop_reason})")
        return resp.parsed_output, (resp.usage.input_tokens, resp.usage.output_tokens)
