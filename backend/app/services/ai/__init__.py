"""Provider-agnostic LLM/SLM layer for HomeHoard.

The app talks to language models through one small interface (``base.AIProvider``)
so feature code never depends on a vendor. The active provider and its config are
resolved from the instance-global ``AppSetting`` store layered over the add-on/env
defaults (``provider_config``), and built by ``registry.get_provider``.
"""
