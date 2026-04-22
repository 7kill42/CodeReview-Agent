from config import LLMConfig, Settings


def test_component_llm_config_falls_back_to_global_defaults():
    settings = Settings(
        LLM_PROVIDER="anthropic",
        LLM_MODEL="claude-opus-4-6",
        LLM_BASE_URL="",
        ANTHROPIC_API_KEY="ant-key",
    )

    cfg = settings.get_llm_config("STYLE_AGENT")

    assert cfg == LLMConfig(
        provider="anthropic",
        model="claude-opus-4-6",
        base_url="",
        api_key="ant-key",
    )


def test_component_llm_config_uses_component_specific_overrides():
    settings = Settings(
        LLM_PROVIDER="anthropic",
        LLM_MODEL="claude-opus-4-6",
        ANTHROPIC_API_KEY="ant-key",
        SECURITY_AGENT_LLM_PROVIDER="openrouter",
        SECURITY_AGENT_LLM_MODEL="openai/gpt-4.1-mini",
        SECURITY_AGENT_LLM_BASE_URL="https://openrouter.ai/api/v1",
        SECURITY_AGENT_LLM_API_KEY="router-key",
    )

    cfg = settings.get_llm_config("SECURITY_AGENT")

    assert cfg == LLMConfig(
        provider="openrouter",
        model="openai/gpt-4.1-mini",
        base_url="https://openrouter.ai/api/v1",
        api_key="router-key",
    )


def test_component_llm_config_uses_provider_specific_default_key_when_not_overridden():
    settings = Settings(
        LLM_PROVIDER="anthropic",
        LLM_MODEL="claude-opus-4-6",
        OPENAI_API_KEY="openai-key",
        AGGREGATOR_LLM_PROVIDER="deepseek",
        AGGREGATOR_LLM_MODEL="deepseek-chat",
        AGGREGATOR_LLM_BASE_URL="https://api.deepseek.com/v1",
    )

    cfg = settings.get_llm_config("AGGREGATOR")

    assert cfg == LLMConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key="openai-key",
    )


def test_component_llm_config_uses_openai_key_for_qwenapi_alias():
    settings = Settings(
        LLM_PROVIDER="qwenapi",
        LLM_MODEL="qwen3.6-flash",
        OPENAI_API_KEY="dashscope-key",
        LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    cfg = settings.get_llm_config("SECURITY_AGENT")

    assert cfg == LLMConfig(
        provider="qwenapi",
        model="qwen3.6-flash",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="dashscope-key",
    )
