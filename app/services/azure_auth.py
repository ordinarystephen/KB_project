"""Shared cached Azure AD authentication primitives."""

from functools import lru_cache


@lru_cache(maxsize=1)
def get_azure_credential():
    """Build one DefaultAzureCredential chain for all Azure services."""
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


@lru_cache(maxsize=1)
def get_cognitive_services_token_provider():
    """Build one reusable Cognitive Services bearer-token provider."""
    from azure.identity import get_bearer_token_provider

    return get_bearer_token_provider(
        get_azure_credential(), "https://cognitiveservices.azure.com/.default"
    )
