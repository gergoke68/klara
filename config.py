"""
Configuration management for Voice Assistant Gateway.
Loads settings from environment variables with sensible defaults.
"""

from __future__ import annotations
import os
import logging
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")


@dataclass
class SipConfig:
    """SIP/3CX connection settings."""
    extension: str
    password: str
    server: str
    auth_id: str = ""  # Separate auth ID (3CX uses this instead of extension)
    port: int = 5060
    transport: str = "udp"
    preferred_codec: str = "PCMU"
    
    def __post_init__(self):
        # If auth_id not provided, use extension
        if not self.auth_id:
            self.auth_id = self.extension
    
    @property
    def registrar_uri(self) -> str:
        """Get the SIP registrar URI."""
        return f"sip:{self.server}:{self.port}"
    
    @property
    def account_uri(self) -> str:
        """Get the SIP account URI."""
        return f"sip:{self.extension}@{self.server}"


@dataclass
class GeminiConfig:
    """Google Gemini API settings."""
    api_key: str
    model: str = "gemini-2.0-flash-exp"
    voice_name: str = "Aoede"
    
    # Audio format settings (fixed for Gemini Live API)
    send_sample_rate: int = 16000  # Input to Gemini
    receive_sample_rate: int = 24000  # Output from Gemini
    channels: int = 1  # Mono
    sample_width: int = 2  # 16-bit
    
    # System instruction (loaded from file)
    system_instruction: str = ""

    @classmethod
    def load_instruction(cls) -> str:
        """Load system instruction from file."""
        try:
            path = Path(__file__).parent / "system_instruction.txt"
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to load system_instruction.txt: {e}")
        
        # Fallback default
        return (
            "You are a helpful Hungarian home assistant. "
            "You are concise and witty. "
            "Always respond in Hungarian."
        )


@dataclass
class Config:
    """Main configuration container."""
    sip: SipConfig
    gemini: GeminiConfig
    log_level: str = "INFO"
    
    def __post_init__(self):
        """Configure logging after initialization."""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        # Validate required fields
        required = {
            "SIP_EXTENSION": os.getenv("SIP_EXTENSION"),
            "SIP_PASSWORD": os.getenv("SIP_PASSWORD"),
            "SIP_SERVER": os.getenv("SIP_SERVER"),
            "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),
        }
        
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Please copy .env.example to .env and fill in your values."
            )
        
        sip = SipConfig(
            extension=required["SIP_EXTENSION"],
            password=required["SIP_PASSWORD"],
            server=required["SIP_SERVER"],
            auth_id=os.getenv("SIP_AUTH_ID", ""),  # Optional separate auth ID
            port=int(os.getenv("SIP_PORT", "5060")),
            transport=os.getenv("SIP_TRANSPORT", "udp").lower(),
            preferred_codec=os.getenv("PREFERRED_CODEC", "PCMU").upper(),
        )
        
        gemini = GeminiConfig(
            api_key=required["GEMINI_API_KEY"],
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp"),
            system_instruction=GeminiConfig.load_instruction(),
            voice_name=os.getenv("GEMINI_VOICE_NAME", "Aoede"),
        )
        
        return cls(
            sip=sip,
            gemini=gemini,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
    
    def __repr__(self) -> str:
        """Safe string representation (hides secrets)."""
        return (
            f"Config(\n"
            f"  sip=SipConfig(extension={self.sip.extension!r}, "
            f"server={self.sip.server!r}, port={self.sip.port}),\n"
            f"  gemini=GeminiConfig(model={self.gemini.model!r}, voice={self.gemini.voice_name!r}),\n"
            f"  log_level={self.log_level!r}\n"
            f")"
        )


# Singleton config instance
_config: Config | None = None


def get_config() -> Config:
    """Get or create the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config
