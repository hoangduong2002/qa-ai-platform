from dotenv import load_dotenv
import os

load_dotenv()


class Settings:

    MODEL_PROVIDER = os.getenv(
        "MODEL_PROVIDER",
        "deepseek"
    )

    DEEPSEEK_API_KEY = os.getenv(
        "DEEPSEEK_API_KEY"
    )

    GITHUB_TOKEN = os.getenv(
        "GITHUB_TOKEN"
    )


settings = Settings()