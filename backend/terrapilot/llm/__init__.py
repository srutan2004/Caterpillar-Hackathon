"""LLM gateway: the only code path to any LLM (§12.3). Features call `get_gateway().run(task=..., inputs=...)`."""

from terrapilot.llm.gateway import LLMGateway, get_gateway
from terrapilot.llm.types import LLMResult

__all__ = ["LLMGateway", "LLMResult", "get_gateway"]
