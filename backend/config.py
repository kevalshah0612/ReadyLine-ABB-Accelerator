from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Only the backend can access provider credentials; never serialize this object."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    nvidia_api_key: SecretStr = SecretStr("")
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_enable_thinking: bool = True
    nvidia_max_tokens: int = Field(default=16384, ge=1024, le=32768)
    nvidia_timeout_seconds: int = Field(default=180, ge=10, le=600)
    readyline_db: str = str(ROOT / "data" / "readyline.sqlite3")
    cookie_secure: bool = False
