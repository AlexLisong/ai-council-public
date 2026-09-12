"""Known OpenAI model providers without real credentials for hermetic tests."""


def provider_registry(*names):
    definitions = {
        "openai": {"base_url": "https://api.openai.com/v1", "api_key": "unused", "auth": "bearer"},
        "foundry-openai": {"base_url": "https://unit-test.openai.azure.com/openai/v1", "api_key": "unused", "auth": "api-key"},
        "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key": "unused", "auth": "bearer"},
    }
    return {name: dict(definitions[name]) for name in names}
