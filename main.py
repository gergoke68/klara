#!/usr/bin/env python3
"""
Voice Assistant Gateway - Main Entry Point

Connects 3CX PBX to Google Gemini 2.0 Flash for real-time voice AI interactions.
Auto-answers incoming calls and bridges audio between SIP and Gemini Live API.

Usage:
    python main.py

Environment Variables (see .env.example):
    - SIP_EXTENSION: Your 3CX extension number
    - SIP_PASSWORD: Extension password
    - SIP_SERVER: 3CX server IP/hostname
    - GEMINI_API_KEY: Google Gemini API key
"""

import asyncio
import logging
import signal
import sys
import time
from typing import Optional

from config import get_config, Config
from audio_bridge import AudioBridge
from sip_client import SipClient, SipCall
from gemini_client import GeminiVoiceClient

logger = logging.getLogger(__name__)

# Retry configuration
MAX_REGISTRATION_RETRIES = 0  # 0 = infinite retries
RETRY_DELAY_SECONDS = 10


class VoiceAssistantGateway:
    """
    Main application class that orchestrates SIP and Gemini clients.
    """
    
    def __init__(self, config: Config):
        """
        Initialize the Voice Assistant Gateway.
        
        Args:
            config: Application configuration.
        """
        self.config = config
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Audio bridge for format conversion
        self.audio_bridge = AudioBridge(
            sip_sample_rate=8000,  # G.711 default
            gemini_input_rate=config.gemini.send_sample_rate,
            gemini_output_rate=config.gemini.receive_sample_rate,
        )
        
        # SIP client for 3CX
        self.sip_client: Optional[SipClient] = None
        
        # Gemini client
        self.gemini_client: Optional[GeminiVoiceClient] = None
        self._gemini_task: Optional[asyncio.Task] = None
        self._playback_task: Optional[asyncio.Task] = None
        self._running = False
        self._shutdown_requested = False
        
        logger.info("VoiceAssistantGateway initialized")
    
    def _create_sip_client(self) -> SipClient:
        """Create a new SIP client instance."""
        return SipClient(
            config=self.config.sip,
            audio_bridge=self.audio_bridge,
            loop=self.loop,
        )
    
    def _on_call_started(self, call: SipCall) -> None:
        """Callback when a SIP call is connected."""
        # Prevent race conditions - double check if session is already active
        if self.gemini_client or self._gemini_task:
            logger.info("Call started event received, but Gemini session already active - skipping")
            return

        logger.info("Call connected - starting Gemini session")
        
        # Reset audio bridge state for new call
        self.audio_bridge.reset_state()
        
        # Create and start Gemini client
        self.gemini_client = GeminiVoiceClient(
            config=self.config.gemini,
            audio_bridge=self.audio_bridge,
        )
        
        # Start Gemini session in background
        self._gemini_task = asyncio.run_coroutine_threadsafe(
            self.gemini_client.start_session(),
            self.loop
        )
        
        # Start playback task to feed audio from Gemini to SIP
        self._playback_task = asyncio.run_coroutine_threadsafe(
            self._playback_loop(call),
            self.loop
        )
        
        logger.info("Gemini session started for call")
    
    def _on_call_ended(self, call: SipCall) -> None:
        """Callback when a SIP call ends."""
        logger.info("Call ended - stopping Gemini session")
        
        # Stop Gemini session
        if self.gemini_client:
            asyncio.run_coroutine_threadsafe(
                self.gemini_client.stop_session(),
                self.loop
            )
            self.gemini_client = None
        
        # Cancel tasks
        if self._gemini_task:
            self._gemini_task.cancel()
            self._gemini_task = None
        
        if self._playback_task:
            self._playback_task.cancel()
            self._playback_task = None
        
        logger.info("Gemini session stopped")
    
    async def _playback_loop(self, call: SipCall) -> None:
        """
        Background task to feed audio from Gemini to the SIP call.
        """
        logger.debug("Starting playback loop")
        
        while call._connected and call.audio_port:
            try:
                # Get audio from Gemini (already resampled)
                audio_data = await asyncio.wait_for(
                    self.audio_bridge.get_for_sip(),
                    timeout=0.1
                )
                
                if audio_data and call.audio_port:
                    # logger.debug(f"Feeding {len(audio_data)} bytes to SIP playback buffer")
                    call.audio_port.add_playback_audio(audio_data)
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Playback loop error: {e}")
                await asyncio.sleep(0.1)
        
        logger.debug("Playback loop ended")
    
    def _try_register(self) -> bool:
        """
        Attempt to start SIP client and register.
        
        Returns:
            True if registration succeeded, False otherwise.
        """
        try:
            # Clean up existing client if any
            if self.sip_client:
                try:
                    self.sip_client.stop()
                except Exception as e:
                    logger.debug(f"Cleanup error: {e}")
            
            # Create new SIP client
            self.sip_client = self._create_sip_client()
            
            # Start SIP client
            self.sip_client.start(
                on_call_started=self._on_call_started,
                on_call_ended=self._on_call_ended,
            )
            
            # Wait for registration
            max_wait = 10
            for _ in range(max_wait * 10):
                if self._shutdown_requested:
                    return False
                if self.sip_client.is_registered:
                    return True
                time.sleep(0.1)
            
            return self.sip_client.is_registered
            
        except Exception as e:
            logger.error(f"Registration attempt failed: {e}")
            return False
    
    def start(self) -> None:
        """Start the Voice Assistant Gateway with retry logic."""
        if self._running:
            logger.warning("Gateway already running")
            return
        
        logger.info("Starting Voice Assistant Gateway...")
        self._running = True
        
        retry_count = 0
        
        while not self._shutdown_requested:
            retry_count += 1
            
            if MAX_REGISTRATION_RETRIES > 0 and retry_count > MAX_REGISTRATION_RETRIES:
                logger.error(f"Max registration retries ({MAX_REGISTRATION_RETRIES}) exceeded")
                break
            
            if retry_count > 1:
                logger.info(f"Registration attempt {retry_count}...")
            
            if self._try_register():
                logger.info("="*60)
                logger.info("Voice Assistant Gateway is READY")
                logger.info(f"Extension: {self.config.sip.extension}")
                logger.info(f"Server: {self.config.sip.server}:{self.config.sip.port}")
                logger.info("Waiting for incoming calls...")
                logger.info("="*60)
                return
            else:
                if self._shutdown_requested:
                    break
                    
                logger.warning(f"Registration failed. Retrying in {RETRY_DELAY_SECONDS} seconds...")
                
                # Wait with interrupt support
                for _ in range(RETRY_DELAY_SECONDS * 10):
                    if self._shutdown_requested:
                        break
                    time.sleep(0.1)
        
        self._running = False
    
    def stop(self) -> None:
        """Stop the Voice Assistant Gateway."""
        if self._shutdown_requested:
            return
        
        logger.info("Stopping Voice Assistant Gateway...")
        self._shutdown_requested = True
        self._running = False
        
        # Stop SIP client
        if self.sip_client:
            try:
                self.sip_client.stop()
            except Exception as e:
                logger.debug(f"SIP client stop error: {e}")
        
        logger.info("Voice Assistant Gateway stopped")
    
    def run_forever(self) -> None:
        """Run the gateway until interrupted."""
        self.start()
        
        if not self._running:
            logger.error("Failed to start gateway")
            return
        
        try:
            # Keep main thread alive
            while self._running and not self._shutdown_requested:
                asyncio.get_event_loop().run_until_complete(asyncio.sleep(1))
                
                # Check if still registered, reconnect if needed
                if self.sip_client and not self.sip_client.is_registered:
                    logger.warning("Lost SIP registration, attempting to reconnect...")
                    self._running = False  # Exit inner loop
                    self.start()  # Restart with retry logic
                    
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.stop()


def setup_signal_handlers(gateway: VoiceAssistantGateway) -> None:
    """Set up signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        gateway.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main() -> None:
    """Main entry point."""
    print("""
╔═══════════════════════════════════════════════════════════╗
║         Voice Assistant Gateway - Klara                   ║
║         3CX ↔ Google Gemini 2.0 Flash                     ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    try:
        # Load configuration
        config = get_config()
        logger.info(f"Configuration loaded:\n{config}")
        
        # Create and run gateway
        gateway = VoiceAssistantGateway(config)
        setup_signal_handlers(gateway)
        gateway.run_forever()
        
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.info(f"Retrying in {RETRY_DELAY_SECONDS} seconds...")
        time.sleep(RETRY_DELAY_SECONDS)
        main()  # Retry
    except ImportError as e:
        logger.error(f"Import error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        logger.info(f"Retrying in {RETRY_DELAY_SECONDS} seconds...")
        time.sleep(RETRY_DELAY_SECONDS)
        main()  # Retry


if __name__ == "__main__":
    main()
