"""
Gemini Live API client for real-time voice interaction.
Uses WebSocket-based bidirectional streaming for low-latency audio.
"""

import asyncio
import logging
from typing import Optional, Callable, Any

from google import genai
from google.genai import types

from config import GeminiConfig
from tools import TOOL_DEFINITIONS, execute_tool
from audio_bridge import AudioBridge

logger = logging.getLogger(__name__)


class GeminiVoiceClient:
    """
    Client for Gemini Live API with real-time audio streaming and function calling.
    """
    
    def __init__(self, config: GeminiConfig, audio_bridge: AudioBridge):
        """
        Initialize the Gemini voice client.
        
        Args:
            config: Gemini configuration.
            audio_bridge: Audio bridge for format conversion.
        """
        self.config = config
        self.audio_bridge = audio_bridge
        self._client: Optional[genai.Client] = None
        self._session = None
        self._running = False
        self._tasks: list[asyncio.Task] = []
        
        logger.info(f"GeminiVoiceClient initialized with model: {config.model}")
    
    def _create_client(self) -> genai.Client:
        """Create and return a Gemini client configured for Live API."""
        return genai.Client(
            api_key=self.config.api_key,
            http_options={"api_version": "v1alpha"}
        )
    
    def _create_live_config(self) -> dict:
        """Create the Live API configuration."""
        return {
            "response_modalities": ["AUDIO"],
            "system_instruction": self.config.system_instruction,
            "tools": [{"function_declarations": TOOL_DEFINITIONS}],
            "generation_config": {
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": self.config.voice_name
                        }
                    }
                }
            }
        }
    
    async def start_session(self) -> None:
        """Start a new Gemini Live API session."""
        if self._running:
            logger.warning("Session already running")
            return
        
        self._client = self._create_client()
        self._running = True
        
        logger.info("Starting Gemini Live API session...")
        
        try:
            async with self._client.aio.live.connect(
                model=self.config.model,
                config=self._create_live_config(),
            ) as session:
                self._session = session
                logger.info("Connected to Gemini Live API")
                
                # Send initial prompt to trigger greeting
                await session.send_client_content(
                    turns=[{"role": "user", "parts": [{"text": "A hívás most kapcsolódott. Köszöntsd a hívót!"}]}],
                    turn_complete=True
                )
                logger.info("Sent initial greeting prompt")
                
                # Start send and receive tasks
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._send_audio_loop())
                    tg.create_task(self._receive_response_loop())
                    
        except asyncio.CancelledError:
            logger.info("Gemini session cancelled")
        except Exception as e:
            logger.error(f"Gemini session error: {e}")
            raise
        finally:
            self._running = False
            self._session = None
            logger.info("Gemini session ended")
    
    async def stop_session(self) -> None:
        """Stop the current session."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("Gemini session stop requested")
    
    async def _send_audio_loop(self) -> None:
        """Continuously send audio from the bridge to Gemini."""
        logger.debug("Starting audio send loop")
        
        while self._running and self._session:
            try:
                # Get audio from the bridge (resampled from SIP)
                audio_data = await asyncio.wait_for(
                    self.audio_bridge.get_for_gemini(),
                    timeout=0.1
                )
                
                if audio_data and self._session:
                    # Send as realtime audio input
                    await self._session.send_realtime_input(
                        audio={
                            "data": audio_data,
                            "mime_type": "audio/pcm"
                        }
                    )
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error sending audio to Gemini: {e}")
                await asyncio.sleep(0.1)
        
        logger.debug("Audio send loop ended")
    
    async def _receive_response_loop(self) -> None:
        """Receive and process responses from Gemini."""
        logger.debug("Starting response receive loop")
        
        while self._running and self._session:
            try:
                turn = self._session.receive()
                
                async for response in turn:
                    await self._handle_response(response)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error receiving from Gemini: {e}")
                await asyncio.sleep(0.1)
        
        logger.debug("Response receive loop ended")
    
    async def _handle_response(self, response: Any) -> None:
        """Handle a single response from Gemini."""
        # Check for audio content
        if response.server_content and response.server_content.model_turn:
            for part in response.server_content.model_turn.parts:
                # Handle audio output
                if hasattr(part, 'inline_data') and part.inline_data:
                    if hasattr(part.inline_data, 'data') and part.inline_data.data:
                        audio_data = part.inline_data.data
                        if isinstance(audio_data, bytes) and len(audio_data) > 0:
                            logger.info(f"Received {len(audio_data)} bytes of audio from Gemini")
                            await self.audio_bridge.enqueue_from_gemini(audio_data)
                        else:
                            logger.warning(f"Received non-bytes or empty audio: {type(audio_data)}")
                
                # Handle text (for logging/debugging - this is "thinking" output)
                if hasattr(part, 'text') and part.text:
                    logger.info(f"Gemini text: {part.text}")
        
        # Check for tool calls
        if response.tool_call:
            await self._handle_tool_call(response.tool_call)
    
    async def _handle_tool_call(self, tool_call: Any) -> None:
        """Handle a function call request from Gemini."""
        for function_call in tool_call.function_calls:
            name = function_call.name
            args = dict(function_call.args) if function_call.args else {}
            
            logger.info(f"Gemini requested tool call: {name}({args})")
            
            try:
                # Execute the tool
                result = execute_tool(name, args)
                
                # Send the result back to Gemini
                if self._session:
                    await self._session.send_tool_response(
                        function_responses=[
                            types.FunctionResponse(
                                name=name,
                                response={"result": result}
                            )
                        ]
                    )
                    logger.info(f"Tool {name} result sent to Gemini: {result}")
                    
            except Exception as e:
                logger.error(f"Tool execution error: {e}")
                # Send error response
                if self._session:
                    await self._session.send_tool_response(
                        function_responses=[
                            types.FunctionResponse(
                                name=name,
                                response={"error": str(e)}
                            )
                        ]
                    )


async def run_gemini_session(config: GeminiConfig, audio_bridge: AudioBridge) -> None:
    """
    Convenience function to run a Gemini voice session.
    
    Args:
        config: Gemini configuration.
        audio_bridge: Audio bridge for format conversion.
    """
    client = GeminiVoiceClient(config, audio_bridge)
    await client.start_session()
