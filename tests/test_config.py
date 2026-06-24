from app.services.config import Settings


def test_deployed_mode_defaults_to_azure(monkeypatch) -> None:
    monkeypatch.delenv("KB_LLM_MODE", raising=False)
    assert Settings().llm_mode == "azure"


def test_simulated_mode_requires_explicit_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("KB_LLM_MODE", "simulated")
    assert Settings().llm_mode == "simulated"


def test_azure_configuration_is_read_from_runtime_environment(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "workplace-deployment")
    monkeypatch.setenv(
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
        "https://example.cognitiveservices.azure.com/",
    )
    settings = Settings()
    assert settings.azure_openai_endpoint == "https://example.openai.azure.com/"
    assert settings.azure_openai_deployment == "workplace-deployment"
    assert settings.document_intelligence_endpoint == (
        "https://example.cognitiveservices.azure.com/"
    )


def test_similarity_threshold_reads_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("KB_SIMILARITY_THRESHOLD", "0.5")
    assert Settings().similarity_threshold == 0.5


def test_invalid_similarity_threshold_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("KB_SIMILARITY_THRESHOLD", "not-a-number")
    assert Settings().similarity_threshold == 0.86
