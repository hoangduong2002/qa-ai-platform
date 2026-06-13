from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_env() -> None:
    """
    Load project environment files in a predictable order.

    .env is the non-secret/default layer.
    .env.secrets is loaded last and may override values from .env.
    """

    load_dotenv(
        dotenv_path=PROJECT_ROOT / ".env",
        override=False,
    )
    load_dotenv(
        dotenv_path=PROJECT_ROOT / ".env.secrets",
        override=True,
    )
