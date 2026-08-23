from meal_organizer.config import LLMConfig, UserConfig


def test_user_configs_do_not_share_lists():
    first = UserConfig()
    second = UserConfig()
    first.dislikes.append("tomato")
    assert second.dislikes == []


def test_llm_defaults():
    config = LLMConfig()
    assert config.provider == "ollama"
    assert config.ollama_host.startswith("http://")
