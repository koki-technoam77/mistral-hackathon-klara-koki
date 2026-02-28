import asyncio
import logging

from elevenlabs import ElevenLabs

from app.models.character import VoiceConfig

logger = logging.getLogger(__name__)


# Real ElevenLabs voice IDs — evolves as character levels up
VOICE_PRESETS: dict[tuple[int, int], VoiceConfig] = {
    (1, 2): VoiceConfig(voice_id="EXAVITQu4vr4xnSDxMaL", stability=0.85, style=0.3),   # Sarah — soft, young
    (3, 4): VoiceConfig(voice_id="21m00Tcm4TlvDq8ikWAM", stability=0.7, style=0.5),     # Rachel — calm, friendly
    (5, 7): VoiceConfig(voice_id="XrExE9yKIg1WjnnlVkGX", stability=0.55, style=0.7),    # Matilda — warm, confident
    (8, 100): VoiceConfig(voice_id="Xb7hH8MSUJpSbSDYk0k2", stability=0.4, style=0.85),  # Alice — confident, British
}


def _split_text_for_tts(text: str, max_chars: int = 480) -> list[str]:
    """Split text into chunks at sentence boundaries for TTS synthesis.

    Splits at sentence-ending punctuation (.!?。！？), falling back to
    comma/clause boundaries, then whitespace, then hard cut.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # Try to find a sentence boundary within the limit
        candidate = remaining[:max_chars]
        cut = -1

        # Priority 1: sentence-ending punctuation
        for sep in ('.', '!', '?', '。', '！', '？'):
            idx = candidate.rfind(sep)
            if idx > max_chars // 3:  # Don't cut too early
                cut = idx + 1
                break

        # Priority 2: comma/semicolon/clause boundary
        if cut == -1:
            for sep in (',', ';', '、', '；', '\n'):
                idx = candidate.rfind(sep)
                if idx > max_chars // 3:
                    cut = idx + 1
                    break

        # Priority 3: whitespace
        if cut == -1:
            idx = candidate.rfind(' ')
            if idx > max_chars // 3:
                cut = idx + 1

        # Priority 4: hard cut
        if cut == -1:
            cut = max_chars

        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].strip()

    return chunks


class VoiceService:
    def __init__(self, config):
        self.config = config
        self.elevenlabs_client = ElevenLabs(api_key=config.elevenlabs_api_key)

    def _transcribe_sync(self, audio_data: bytes) -> str:
        """Synchronous ElevenLabs STT call — run via asyncio.to_thread."""
        response = self.elevenlabs_client.speech_to_text.convert(
            model_id="scribe_v1",
            file=audio_data,
        )
        return response.text.strip() if response.text else ""

    async def transcribe(self, audio_data: bytes) -> str:
        try:
            return await asyncio.to_thread(self._transcribe_sync, audio_data)
        except Exception as e:
            logger.error("STT error: %s", e, exc_info=True)
            return ""

    def _synthesize_sync(self, text: str, voice_config: VoiceConfig, output_format: str = "mp3_44100_128") -> bytes:
        """Synchronous ElevenLabs TTS call — run via asyncio.to_thread."""
        kwargs: dict = {
            "voice_id": voice_config.voice_id,
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": voice_config.stability,
                "similarity_boost": voice_config.style,
            },
        }
        if output_format != "mp3_44100_128":
            kwargs["output_format"] = output_format
        response = self.elevenlabs_client.text_to_speech.convert(**kwargs)
        return b"".join(response)

    async def synthesize(self, text: str, voice_config: VoiceConfig) -> bytes:
        try:
            return await asyncio.to_thread(self._synthesize_sync, text, voice_config)
        except Exception as e:
            logger.error("TTS error: %s", e, exc_info=True)
            return b""

    async def synthesize_pcm(self, text: str, voice_config: VoiceConfig) -> bytes:
        """Synthesize speech as PCM 16-bit 16kHz mono for Anam avatar passthrough."""
        try:
            return await asyncio.to_thread(self._synthesize_sync, text, voice_config, "pcm_16000")
        except Exception as e:
            logger.error("PCM TTS error: %s", e, exc_info=True)
            return b""

    # 160ms silence at 16kHz 16-bit mono = 5120 zero bytes
    _PCM_SILENCE_PADDING = b"\x00" * 5120
    _MAX_CHUNKS = 10
    _MAX_PCM_BYTES = 10 * 1024 * 1024  # 10 MB

    async def synthesize_pcm_chunked(self, text: str, voice_config: VoiceConfig) -> bytes:
        """Synthesize long text as PCM by splitting into chunks and concatenating.

        PCM 16-bit 16kHz mono has no headers, so raw byte concatenation works.
        Inserts 160ms silence between chunks to avoid audio artifacts.
        """
        chunks = _split_text_for_tts(text)
        if not chunks:
            return b""

        # Cap chunks to prevent API abuse
        if len(chunks) > self._MAX_CHUNKS:
            logger.warning("Text too long: %d chunks, capping to %d", len(chunks), self._MAX_CHUNKS)
            chunks = chunks[: self._MAX_CHUNKS]

        pcm_parts: list[bytes] = []
        total_bytes = 0

        for i, chunk in enumerate(chunks):
            logger.debug("PCM chunk %d/%d (%d chars)", i + 1, len(chunks), len(chunk))
            part = await self.synthesize_pcm(chunk, voice_config)
            if part:
                if total_bytes + len(part) > self._MAX_PCM_BYTES:
                    logger.warning("PCM output would exceed %d bytes, stopping", self._MAX_PCM_BYTES)
                    break
                pcm_parts.append(part)
                total_bytes += len(part)

        # Join with silence padding between chunks
        if len(pcm_parts) <= 1:
            return pcm_parts[0] if pcm_parts else b""
        return self._PCM_SILENCE_PADDING.join(pcm_parts)

    @staticmethod
    def get_voice_for_level(level: int) -> VoiceConfig:
        for (min_level, max_level), voice_config in VOICE_PRESETS.items():
            if min_level <= level <= max_level:
                return voice_config
        # Fallback to Sarah (level 1 default)
        return VoiceConfig(voice_id="EXAVITQu4vr4xnSDxMaL", stability=0.85, style=0.3)
