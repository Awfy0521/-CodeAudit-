from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Mimo
    mimo_api_key: str = ""
    mimo_model: str = "mimo-v2-pro"
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # Provider
    primary_provider: str = "mimo"

    # Database
    db_path: str = "code_review.db"

    # API call
    max_retries: int = 3
    timeout: int = 120

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
