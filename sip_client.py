"""
SIP client implementation using PJSUA2.
Handles SIP registration, call management, and audio bridging to Gemini.
"""

import asyncio
import logging
import random
import threading
from typing import Optional, Callable
from queue import Queue, Empty

# PJSUA2 import - requires compiled PJSIP with Python bindings
try:
    import pjsua2 as pj
except ImportError:
    raise ImportError(
        "pjsua2 module not found. Please install PJSIP with Python bindings.\n"
        "See docs/INSTALL_PJSIP.md for installation instructions."
    )

from config import SipConfig
from audio_bridge import AudioBridge, g711_ulaw_to_pcm16, pcm16_to_g711_ulaw

logger = logging.getLogger(__name__)


class AudioMediaPort(pj.AudioMediaPort):
    """
    Custom audio media port for capturing and injecting audio frames.
    Bridges the RTP audio stream with the Gemini audio pipeline.
    """
    
    def __init__(
        self,
        audio_bridge: AudioBridge,
        loop: asyncio.AbstractEventLoop,
        frame_time_ms: int = 20,
        sample_rate: int = 8000,
    ):
        """
        Initialize the audio media port.
        
        Args:
            audio_bridge: Audio bridge for routing audio to/from Gemini.
            loop: Asyncio event loop for scheduling coroutines.
            frame_time_ms: Frame time in milliseconds (typically 20ms).
            sample_rate: Sample rate of the SIP audio.
        """
        super().__init__()
        self.audio_bridge = audio_bridge
        self.loop = loop
        self.frame_time_ms = frame_time_ms
        self.sample_rate = sample_rate
        
        # Calculate samples per frame
        self.samples_per_frame = (sample_rate * frame_time_ms) // 1000
        # 16-bit = 2 bytes per sample
        self.bytes_per_frame = self.samples_per_frame * 2
        
        # Buffer for outgoing audio
        self._playback_buffer = bytearray()
        self._buffer_lock = threading.Lock()
        
        logger.debug(
            f"AudioMediaPort initialized: {sample_rate}Hz, "
            f"{frame_time_ms}ms frames, {self.samples_per_frame} samples/frame"
        )
    
    def onFrameReceived(self, frame: pj.MediaFrame) -> None:
        """
        Called when an audio frame is received from the remote party.
        This is the incoming audio that we need to send to Gemini.
        """
        try:
            # Get raw audio data from frame
            audio_data = bytes(frame.buf)
            
            if audio_data:
                # Schedule async enqueue in the event loop
                asyncio.run_coroutine_threadsafe(
                    self.audio_bridge.enqueue_from_sip(audio_data),
                    self.loop
                )
                
        except Exception as e:
            logger.error(f"Error in onFrameReceived: {e}")
    
    def onFrameRequested(self, frame: pj.MediaFrame) -> None:
        """
        Called when the media system needs an audio frame to send to the remote party.
        This is where we provide audio from Gemini.
        """
        try:
            with self._buffer_lock:
                # Check if we have enough data
                if len(self._playback_buffer) >= self.bytes_per_frame:
                    if len(self._playback_buffer) > 0:
                        logger.debug(f"onFrameRequested: Buffer has {len(self._playback_buffer)} bytes, taking {self.bytes_per_frame}")
                    
                    # Get exactly one frame worth of data
                    frame_data = bytes(self._playback_buffer[:self.bytes_per_frame])
                    del self._playback_buffer[:self.bytes_per_frame]
                    
                    # Log amplitude stats occasionally to verify we have signal
                    if len(frame_data) > 0 and (random.randint(0, 50) == 0):
                        # Simple check for signal presence (byte values)
                        max_val = max(frame_data)
                        min_val = min(frame_data)
                        logger.info(f"Audio Output: {len(frame_data)} bytes. Range: [{min_val}, {max_val}]")

                    # Use ByteVector constructor
                    bv = pj.ByteVector()
                    for b in frame_data:
                        bv.append(b)
                    
                    frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
                    frame.buf = bv
                    frame.size = len(frame_data)
                else:
                    # Not enough data, send silence (zeros)
                    # Only log silence if we had data recently or periodically to avoid spam
                    if len(self._playback_buffer) > 0:
                        logger.debug(f"onFrameRequested: Not enough data ({len(self._playback_buffer)}/{self.bytes_per_frame}), sending silence")
                    
                    bv = pj.ByteVector()
                    for _ in range(self.bytes_per_frame):
                        bv.append(0)
                        
                    frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
                    frame.buf = bv
                    frame.size = self.bytes_per_frame
                    
        except Exception as e:
            logger.error(f"Error in onFrameRequested: {e}")
            # Send silence on error - just set size, don't modify buf
            frame.size = self.bytes_per_frame
    
    def add_playback_audio(self, audio_data: bytes) -> None:
        """
        Add audio data to the playback buffer.
        Called from the Gemini client to queue audio for playback.
        """
        with self._buffer_lock:
            self._playback_buffer.extend(audio_data)
    
    def clear_playback_buffer(self) -> None:
        """Clear the playback buffer (e.g., when user interrupts)."""
        with self._buffer_lock:
            self._playback_buffer.clear()


class SipCall(pj.Call):
    """
    Represents an active SIP call.
    Handles call lifecycle and audio media management.
    """
    
    def __init__(
        self,
        account: "SipAccount",
        call_id: int = pj.PJSUA_INVALID_ID,
    ):
        super().__init__(account, call_id)
        self.account = account
        self.audio_port: Optional[AudioMediaPort] = None
        self._connected = False
        
    def onCallState(self, prm: pj.OnCallStateParam) -> None:
        """Called when call state changes."""
        ci = self.getInfo()
        state = ci.state
        state_text = ci.stateText
        
        logger.info(f"Call state: {state_text} ({state})")
        
        if state == pj.PJSIP_INV_STATE_DISCONNECTED:
            self._connected = False
            self._cleanup_media()
            logger.info("Call disconnected")
            
            # Notify account of call end
            if self.account.on_call_ended:
                self.account.on_call_ended(self)
    
    def onCallMediaState(self, prm: pj.OnCallMediaStateParam) -> None:
        """Called when call media state changes."""
        ci = self.getInfo()
        
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and \
               mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                
                # Get the audio media
                audio_media = self.getAudioMedia(mi.index)
                
                if audio_media and self.account.audio_port:
                    try:
                        # Get the audio port from the account
                        self.audio_port = self.account.audio_port
                        
                        # Ensure port is created (idempotent-ish)
                        try:
                            # Create the port with audio format if not already active
                            # We can't easily check if it's created, so we try and catch
                            fmt = pj.MediaFormatAudio()
                            fmt.type = pj.PJMEDIA_TYPE_AUDIO
                            fmt.clockRate = self.audio_port.sample_rate
                            fmt.channelCount = 1
                            fmt.bitsPerSample = 16
                            fmt.frameTimeUsec = self.audio_port.frame_time_ms * 1000
                            
                            self.audio_port.createPort("gemini_bridge", fmt)
                            logger.info("Created audio port 'gemini_bridge'")
                        except pj.Error as e:
                            # 70015 = PJ_EEXISTS (Object already exists)
                            if e.status != 70015:
                                raise e
                            logger.debug("Audio port already exists, reusing")
                        
                        # Connect audio: remote → our port → gemini
                        audio_media.startTransmit(self.audio_port)
                        # Connect audio: gemini → our port → remote
                        self.audio_port.startTransmit(audio_media)
                        
                        self._connected = True
                        logger.info("Audio media connected and transmitting")
                        
                        # Notify account of call start (idempotent)
                        if self.account.on_call_started:
                            self.account.on_call_started(self)
                            
                    except Exception as e:
                        logger.error(f"Error connecting audio media: {e}")
    
    def _cleanup_media(self) -> None:
        """Clean up media resources."""
        if self.audio_port:
            try:
                self.audio_port.clear_playback_buffer()
            except Exception as e:
                logger.debug(f"Error cleaning up media: {e}")
        self.audio_port = None


class SipAccount(pj.Account):
    """
    Represents a SIP account registered to the 3CX server.
    Handles registration and incoming call management.
    """
    
    def __init__(
        self,
        audio_bridge: AudioBridge,
        loop: asyncio.AbstractEventLoop,
    ):
        super().__init__()
        self.audio_bridge = audio_bridge
        self.loop = loop
        self.audio_port: Optional[AudioMediaPort] = None
        self.current_call: Optional[SipCall] = None
        
        # Callbacks
        self.on_call_started: Optional[Callable[[SipCall], None]] = None
        self.on_call_ended: Optional[Callable[[SipCall], None]] = None
        
        self._registered = False
    
    def onRegState(self, prm: pj.OnRegStateParam) -> None:
        """Called when registration state changes."""
        info = self.getInfo()
        
        if info.regStatus == 200:
            self._registered = True
            try:
                logger.info(f"SIP registration successful (expires: {info.regExpiresSec}s)")
            except AttributeError:
                logger.info("SIP registration successful")
        else:
            self._registered = False
            logger.warning(f"SIP registration failed: {info.regStatus} - {prm.reason}")
    
    def onIncomingCall(self, prm: pj.OnIncomingCallParam) -> None:
        """Called when an incoming call is received."""
        # Create the call object first
        call = SipCall(self, prm.callId)
        self.current_call = call
        
        # Get caller info from the call
        try:
            call_info = call.getInfo()
            caller = call_info.remoteUri
            logger.info(f"Incoming call from: {caller}")
        except Exception as e:
            logger.info(f"Incoming call (call_id: {prm.callId})")
        
        # Create audio port for this call
        self.audio_port = AudioMediaPort(
            audio_bridge=self.audio_bridge,
            loop=self.loop,
            frame_time_ms=20,
            sample_rate=8000,  # G.711 default
        )
        
        # Auto-answer the call after a short delay
        call_prm = pj.CallOpParam()
        call_prm.statusCode = 200  # OK
        
        try:
            # Small delay before answering (more natural)
            import time
            time.sleep(0.2)
            
            call.answer(call_prm)
            logger.info("Call auto-answered")
            
        except Exception as e:
            logger.error(f"Error answering call: {e}")
    
    @property
    def is_registered(self) -> bool:
        """Check if the account is registered."""
        return self._registered


class SipClient:
    """
    Main SIP client class that manages the PJSUA2 endpoint and accounts.
    """
    
    def __init__(
        self,
        config: SipConfig,
        audio_bridge: AudioBridge,
        loop: asyncio.AbstractEventLoop,
    ):
        """
        Initialize the SIP client.
        
        Args:
            config: SIP configuration.
            audio_bridge: Audio bridge for routing audio.
            loop: Asyncio event loop.
        """
        self.config = config
        self.audio_bridge = audio_bridge
        self.loop = loop
        
        self._endpoint: Optional[pj.Endpoint] = None
        self._account: Optional[SipAccount] = None
        self._transport_id: Optional[int] = None
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        
        logger.info(f"SipClient initialized for {config.extension}@{config.server}")
    
    def start(
        self,
        on_call_started: Optional[Callable[[SipCall], None]] = None,
        on_call_ended: Optional[Callable[[SipCall], None]] = None,
    ) -> None:
        """
        Start the SIP client and register to the server.
        
        Args:
            on_call_started: Callback when a call is connected.
            on_call_ended: Callback when a call ends.
        """
        if self._running:
            logger.warning("SIP client already running")
            return
        
        logger.info("Starting SIP client...")
        
        # Create and initialize PJSUA2 endpoint
        self._endpoint = pj.Endpoint()
        self._endpoint.libCreate()
        
        # Configure endpoint
        ep_cfg = pj.EpConfig()
        ep_cfg.logConfig.level = 4  # Info level
        ep_cfg.logConfig.consoleLevel = 4
        ep_cfg.uaConfig.maxCalls = 4
        
        # Configure STUN servers for NAT traversal
        ep_cfg.uaConfig.stunServer.append("stun.l.google.com:19302")
        ep_cfg.uaConfig.stunServer.append("stun1.l.google.com:19302")
        
        self._endpoint.libInit(ep_cfg)
        
        # Register the current thread with PJSIP
        try:
            self._endpoint.libRegisterThread("main")
            logger.debug("Main thread registered with PJSIP")
        except Exception as e:
            logger.debug(f"Main thread registration note: {e}")
        
        # Create transport
        tp_cfg = pj.TransportConfig()
        tp_cfg.port = 0  # Auto-select port
        
        transport_type = {
            "udp": pj.PJSIP_TRANSPORT_UDP,
            "tcp": pj.PJSIP_TRANSPORT_TCP,
            "tls": pj.PJSIP_TRANSPORT_TLS,
        }.get(self.config.transport, pj.PJSIP_TRANSPORT_UDP)
        
        self._transport_id = self._endpoint.transportCreate(transport_type, tp_cfg)
        
        # Start the library
        self._endpoint.libStart()
        logger.info("PJSUA2 library started")
        
        # Set null audio device (no physical sound card needed)
        # This is essential for running in Docker without audio devices
        pj.Endpoint.instance().audDevManager().setNullDev()
        
        # Create and register account
        self._account = SipAccount(self.audio_bridge, self.loop)
        self._account.on_call_started = on_call_started
        self._account.on_call_ended = on_call_ended
        
        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = self.config.account_uri
        acc_cfg.regConfig.registrarUri = self.config.registrar_uri
        acc_cfg.regConfig.timeoutSec = 300
        
        # Set transport for registration
        acc_cfg.sipConfig.transportId = self._transport_id
        
        # Add authentication credentials
        cred = pj.AuthCredInfo()
        cred.scheme = "digest"
        cred.realm = "*"
        cred.username = self.config.auth_id  # Use auth_id (may differ from extension)
        cred.dataType = 0  # Plain text password
        cred.data = self.config.password
        acc_cfg.sipConfig.authCreds.append(cred)
        
        self._account.create(acc_cfg)
        logger.info(f"SIP account created: {self.config.extension}")
        
        self._running = True
        
        # Start worker thread for PJSUA2 event processing
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        
        logger.info("SIP client started")
    
    def stop(self) -> None:
        """Stop the SIP client and clean up resources."""
        if not self._running:
            return
        
        logger.info("Stopping SIP client...")
        self._running = False
        
        # Wait for worker thread
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
        
        # Clean up PJSUA2
        if self._account:
            try:
                self._account.shutdown()
            except Exception as e:
                logger.debug(f"Account shutdown error: {e}")
        
        if self._endpoint:
            try:
                self._endpoint.libDestroy()
            except Exception as e:
                logger.debug(f"Endpoint destroy error: {e}")
        
        self._account = None
        self._endpoint = None
        logger.info("SIP client stopped")
    
    def _worker_loop(self) -> None:
        """Background worker loop for PJSUA2 event processing."""
        logger.debug("SIP worker thread started")
        
        # Register this thread with PJSIP - CRITICAL for threading
        try:
            self._endpoint.libRegisterThread("sip_worker")
            logger.debug("SIP worker thread registered with PJSIP")
        except Exception as e:
            logger.warning(f"Thread registration note: {e}")
        
        while self._running:
            try:
                # Handle PJSUA2 events (100ms timeout)
                self._endpoint.libHandleEvents(100)
            except Exception as e:
                if self._running:  # Only log if still supposed to be running
                    logger.error(f"Error in SIP worker loop: {e}")
        
        logger.debug("SIP worker thread ended")
    
    @property
    def is_registered(self) -> bool:
        """Check if the account is registered."""
        return self._account.is_registered if self._account else False
    
    @property
    def current_call(self) -> Optional[SipCall]:
        """Get the current active call, if any."""
        return self._account.current_call if self._account else None
