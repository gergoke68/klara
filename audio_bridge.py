"""
Audio bridge for converting between SIP and Gemini audio formats.
Handles sample rate conversion and bidirectional audio routing.
"""

import asyncio
import logging
import struct
from typing import Optional

# Try to import audioop (removed in Python 3.13)
try:
    import audioop
except ImportError:
    import audioop_lts as audioop

logger = logging.getLogger(__name__)


class AudioBridge:
    """
    Bridges audio between SIP (typically 8kHz G.711) and Gemini (16kHz/24kHz PCM).
    
    Audio flow:
    - SIP → Gemini: 8kHz (or native rate) → 16kHz resampling
    - Gemini → SIP: 24kHz → 8kHz (or native rate) resampling
    """
    
    def __init__(
        self,
        sip_sample_rate: int = 8000,
        gemini_input_rate: int = 16000,
        gemini_output_rate: int = 24000,
        sample_width: int = 2,  # 16-bit = 2 bytes
        channels: int = 1,
    ):
        """
        Initialize the audio bridge.
        
        Args:
            sip_sample_rate: Sample rate of SIP audio (typically 8000 for G.711).
            gemini_input_rate: Sample rate expected by Gemini (16000 Hz).
            gemini_output_rate: Sample rate from Gemini output (24000 Hz).
            sample_width: Bytes per sample (2 for 16-bit PCM).
            channels: Number of audio channels (1 for mono).
        """
        self.sip_sample_rate = sip_sample_rate
        self.gemini_input_rate = gemini_input_rate
        self.gemini_output_rate = gemini_output_rate
        self.sample_width = sample_width
        self.channels = channels
        
        # Resampling state (for audioop.ratecv)
        self._sip_to_gemini_state: Optional[tuple] = None
        self._gemini_to_sip_state: Optional[tuple] = None
        
        # Async queues for audio flow
        self.sip_to_gemini_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self.gemini_to_sip_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        
        logger.info(
            f"AudioBridge initialized: SIP@{sip_sample_rate}Hz ↔ "
            f"Gemini@{gemini_input_rate}Hz/{gemini_output_rate}Hz"
        )
    
    def reset_state(self) -> None:
        """Reset resampling state (call when starting a new call)."""
        self._sip_to_gemini_state = None
        self._gemini_to_sip_state = None
        
        # Clear queues
        while not self.sip_to_gemini_queue.empty():
            try:
                self.sip_to_gemini_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        while not self.gemini_to_sip_queue.empty():
            try:
                self.gemini_to_sip_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        logger.debug("AudioBridge state reset")
    
    def sip_to_gemini(self, audio_data: bytes) -> bytes:
        """
        Convert audio from SIP format to Gemini input format.
        
        Args:
            audio_data: Raw PCM audio from SIP (16-bit, sip_sample_rate Hz).
            
        Returns:
            Resampled PCM audio for Gemini (16-bit, 16kHz).
        """
        if not audio_data:
            return b""
        
        # If rates match, no conversion needed
        if self.sip_sample_rate == self.gemini_input_rate:
            return audio_data
        
        try:
            # Resample using audioop
            converted, self._sip_to_gemini_state = audioop.ratecv(
                audio_data,
                self.sample_width,
                self.channels,
                self.sip_sample_rate,
                self.gemini_input_rate,
                self._sip_to_gemini_state,
            )
            return converted
        except Exception as e:
            logger.error(f"SIP→Gemini resampling error: {e}")
            return audio_data
    
    def gemini_to_sip(self, audio_data: bytes) -> bytes:
        """
        Convert audio from Gemini output format to SIP format.
        
        Args:
            audio_data: Raw PCM audio from Gemini (16-bit, 24kHz).
            
        Returns:
            Resampled PCM audio for SIP (16-bit, sip_sample_rate Hz).
        """
        if not audio_data:
            return b""
        
        # If rates match, no conversion needed
        if self.gemini_output_rate == self.sip_sample_rate:
            return audio_data
        
        try:
            # Resample using audioop
            converted, self._gemini_to_sip_state = audioop.ratecv(
                audio_data,
                self.sample_width,
                self.channels,
                self.gemini_output_rate,
                self.sip_sample_rate,
                self._gemini_to_sip_state,
            )
            return converted
        except Exception as e:
            logger.error(f"Gemini→SIP resampling error: {e}")
            return audio_data
    
    async def enqueue_from_sip(self, audio_data: bytes) -> None:
        """
        Enqueue audio received from SIP for sending to Gemini.
        Audio is resampled before queueing.
        """
        if not audio_data:
            return
        
        resampled = self.sip_to_gemini(audio_data)
        try:
            self.sip_to_gemini_queue.put_nowait(resampled)
        except asyncio.QueueFull:
            logger.warning("SIP→Gemini queue full, dropping audio frame")
    
    async def enqueue_from_gemini(self, audio_data: bytes) -> None:
        """
        Enqueue audio received from Gemini for sending to SIP.
        Audio is resampled before queueing.
        """
        if not audio_data:
            return
        
        resampled = self.gemini_to_sip(audio_data)
        try:
            self.gemini_to_sip_queue.put_nowait(resampled)
        except asyncio.QueueFull:
            logger.warning("Gemini→SIP queue full, dropping audio frame")
    
    async def get_for_gemini(self) -> bytes:
        """Get the next audio chunk to send to Gemini."""
        return await self.sip_to_gemini_queue.get()
    
    async def get_for_sip(self) -> bytes:
        """Get the next audio chunk to send to SIP."""
        return await self.gemini_to_sip_queue.get()
    
    def get_for_sip_nowait(self) -> Optional[bytes]:
        """Get the next audio chunk for SIP without blocking (returns None if empty)."""
        try:
            return self.gemini_to_sip_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None


def g711_ulaw_to_pcm16(ulaw_data: bytes) -> bytes:
    """
    Convert G.711 μ-law encoded audio to 16-bit PCM.
    
    Args:
        ulaw_data: G.711 μ-law encoded audio bytes.
        
    Returns:
        16-bit linear PCM audio bytes.
    """
    return audioop.ulaw2lin(ulaw_data, 2)


def pcm16_to_g711_ulaw(pcm_data: bytes) -> bytes:
    """
    Convert 16-bit PCM audio to G.711 μ-law encoding.
    
    Args:
        pcm_data: 16-bit linear PCM audio bytes.
        
    Returns:
        G.711 μ-law encoded audio bytes.
    """
    return audioop.lin2ulaw(pcm_data, 2)


def g711_alaw_to_pcm16(alaw_data: bytes) -> bytes:
    """
    Convert G.711 A-law encoded audio to 16-bit PCM.
    
    Args:
        alaw_data: G.711 A-law encoded audio bytes.
        
    Returns:
        16-bit linear PCM audio bytes.
    """
    return audioop.alaw2lin(alaw_data, 2)


def pcm16_to_g711_alaw(pcm_data: bytes) -> bytes:
    """
    Convert 16-bit PCM audio to G.711 A-law encoding.
    
    Args:
        pcm_data: 16-bit linear PCM audio bytes.
        
    Returns:
        G.711 A-law encoded audio bytes.
    """
    return audioop.lin2alaw(pcm_data, 2)
