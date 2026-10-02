import numpy as np
import sounddevice as sd
import onnxruntime
import asyncio
import threading
import time
import logging

class NaturalVoiceBargeIn:
    def __init__(self, session_memory, player):
        self.session_memory = session_memory
        self.player = player
        self.logger = logging.getLogger("NaturalVoiceBargeIn")
        self.logger.setLevel(logging.INFO)

        # Configuration (can be moved to session_memory config later)
        self.model_path = 'silero_vad.onnx' # Expects model in root or configured path
        self.threshold = 0.4
        self.sampling_rate = 16000
        self.frame_size = 512 # 32ms frames for Silero
        self.interruption_buffer_ms = 100 # require sustained speech to interrupt
        self.running = False
        self.stream = None
        self.interruption_event = threading.Event()

        # Audio data state
        self.audio_buffer = []
        self.last_speech_time = 0
        self.consecutive_speech_frames = 0
        
        try:
            self.session = onnxruntime.InferenceSession(self.model_path)
            self.logger.info("Silero VAD loaded.")
        except Exception as e:
            self.logger.error(f"Failed to load VAD model: {e}")
            self.running = False

    def validate_audio(self, audio_frame):
        # Placeholder for integration with existing EchoGuard to distinguish 
        # user voice from speaker echo during playback.
        # If player.is_playing(), apply echo cancellation or higher threshold.
        # For now, return raw frame.
        return audio_frame

    def _audio_callback(self, indata, frames, time_info, status):
        if not self.running or not hasattr(self, 'session'):
            return
        
        processed_frame = self.validate_audio(indata.copy())
        
        # Convert to flat float32
        audio_float32 = processed_frame.flatten().astype(np.float32)
        
        input_name = self.session.get_inputs()[0].name
        output_name = self.session.get_outputs()[0].name
        
        try:
            # Silero VAD inference
            ort_inputs = {input_name: np.expand_dims(audio_float32, axis=0)}
            ort_outs = self.session.run([output_name], ort_inputs)
            speech_prob = ort_outs[0][0]

            if speech_prob > self.threshold:
                self.consecutive_speech_frames += 1
                # Check if threshold sustained duration is met
                required_frames = self.interruption_buffer_ms / (self.frame_size / (self.sampling_rate / 1000))
                
                if self.consecutive_speech_frames >= required_frames:
                    self.last_speech_time = time.time()
                    # Interruption condition met
                    if self.player and self.player.is_playing():
                        self.logger.info("Speech detected, interrupting playback.")
                        self.player.stop() # Existing interface: Stop playback immediately
                        # Session memory hooks to cancel ongoing Gemini generation
                        if self.session_memory:
                            self.session_memory.cancel_current_response() # Existing interface
                            self.session_memory.clear_audio_queue() # Existing interface

                    self.interruption_event.set() # Signal core to start capturing
            else:
                self.consecutive_speech_frames = 0
        except Exception as e:
            self.logger.error(f"Inference error: {e}")

    def start(self):
        self.running = True
        self.stream = sd.InputStream(
            samplerate=self.sampling_rate,
            blocksize=self.frame_size,
            dtype='float32',
            channels=1,
            callback=self._audio_callback
        )
        self.stream.start()
        self.logger.info("Continuous VAD monitoring started.")

    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.logger.info("Continuous VAD monitoring stopped.")

def run(parameters: dict, response=None, player=None, session_memory=None):
    if session_memory is None:
        return {"status": "error", "message": "session_memory not provided"}

    enabled = parameters.get("enabled", True)
    
    # Store instance in session to keep context between calls
    instance_key = "natural_voice_barge_in_instance"
    current_instance = session_memory.get_private_context(instance_key) if hasattr(session_memory, 'get_private_context') else None

    if enabled:
        if current_instance is None:
            vbi = NaturalVoiceBargeIn(session_memory, player)
            vbi.start()
            if hasattr(session_memory, 'set_private_context'):
                session_memory.set_private_context(instance_key, vbi)
            return {"status": "success", "message": "Voice barge-in enabled."}
        else:
            return {"status": "info", "message": "Voice barge-in already running."}
    else:
        if current_instance is not None:
            current_instance.stop()
            if hasattr(session_memory, 'set_private_context'):
                session_memory.set_private_context(instance_key, None)
            return {"status": "success", "message": "Voice barge-in disabled."}
        else:
            return {"status": "info", "message": "Voice barge-in not running."}

PLUGIN = {
    "name": "natural_voice_barge_in",
    "description": "Enables real-time voice conversation by interrupting playback when the user starts speaking.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "enabled": {
                "type": "BOOLEAN",
                "description": "Set to true to enable voice barge-in, false to disable."
            }
        },
        "required": ["enabled"]
    },
    "run": run
}