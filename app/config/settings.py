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

    # Incremental regeneration safety threshold.
    # Description text length ratio above this value triggers a
    # FULL_REGENERATE_RECOMMENDED safety decision.
    INCREMENTAL_MAJOR_CHANGE_THRESHOLD = float(
        os.getenv("INCREMENTAL_MAJOR_CHANGE_THRESHOLD", "0.35")
    )


settings = Settings()