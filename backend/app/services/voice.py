import io
import logging

from elevenlabs import ElevenLabs
from mistralai import Mistral

from app.models.character import VoiceConfig

logger = logging.getLogger(__name__)


VOICE_PRESETS: dict[tuple[int, float], VoiceConfig] = {
    (1, 2): VoiceConfig(voice_id="voice_shy_001", stability=0.9, style=0.2),
    (3, 4): VoiceConfig(voice_id="voice_friendly_001", stability=0.7, style=0.5),
    (5, 7): VoiceConfig(voice_id="voice_confident_001", stability=0.5, style=0.7),
    (8, 100): VoiceConfig(voice_id="voice_professional_001", stability=0.4, style=0.9),
}


class VoiceService:
    def __init__(self, config):
        self.config = config
        self.mistral_client = Mistral(api_key=config.mistral_api_key)
        self.elevenlabs_client = ElevenLabs(api_key=config.elevenlabs_api_key)

    async def transcribe(self, audio_data: bytes) -> str:
        try:
            response = await self.mistral_client.audio.transcriptions.complete_async(
                model="voxtral-mini-latest",
                file={"content": io.BytesIO(audio_data), "file_name": "recording.webm"},
            )
            return response.text.strip()
        except Exception as e:
            logger.error("Transcription error: %s", e, exc_info=True)
            return ""

    async def synthesize(self, text: str, voice_config: VoiceConfig) -> bytes:
        try:
            response = self.elevenlabs_client.text_to_speech.convert(
                voice_id=voice_config.voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                voice_settings={
                    "stability": voice_config.stability,
                    "similarity_boost": voice_config.style,
                },
            )
            return b"".join(response)
        except Exception as e:
            logger.error("TTS error: %s", e, exc_info=True)
            return b""

    async def synthesize_pcm(self, text: str, voice_config: VoiceConfig) -> bytes:
        """Synthesize speech as PCM 16-bit 16kHz mono for Anam avatar passthrough."""
        try:
            response = self.elevenlabs_client.text_to_speech.convert(
                voice_id=voice_config.voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="pcm_16000",
                voice_settings={
                    "stability": voice_config.stability,
                    "similarity_boost": voice_config.style,
                },
            )
            return b"".join(response)
        except Exception as e:
            logger.error("PCM TTS error: %s", e, exc_info=True)
            return b""

    @staticmethod
    def get_voice_for_level(level: int) -> VoiceConfig:
        for (min_level, max_level), voice_config in VOICE_PRESETS.items():
            if min_level <= level <= max_level:
                return voice_config
        return VoiceConfig(voice_id="voice_professional_001", stability=0.4, style=0.9)
