/**
 * ElevenLabs Conversational AI Agent — WebSocket client with mic capture.
 *
 * Flow:
 *  1. Open WebSocket to ElevenLabs Conversational AI
 *  2. Capture mic audio at 16kHz PCM via Web Audio API
 *  3. Send base64-encoded PCM chunks as `user_audio_chunk`
 *  4. Receive agent audio, transcripts, interruptions
 *  5. Forward agent audio to Anam avatar for lip-sync
 */

export interface ElevenLabsCallbacks {
  onReady?: () => void;
  /** Base64-encoded PCM16 audio chunk from the agent */
  onAudio?: (audioBase64: string) => void;
  onUserTranscript?: (text: string) => void;
  onAgentResponse?: (text: string) => void;
  onInterrupt?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Error) => void;
}

let ws: WebSocket | null = null;
let audioContext: AudioContext | null = null;
let mediaStream: MediaStream | null = null;
let scriptProcessor: ScriptProcessorNode | null = null;
let sourceNode: MediaStreamAudioSourceNode | null = null;

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function float32ToPcm16(float32: Float32Array): ArrayBuffer {
  const pcm16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm16.buffer;
}

async function setupMicrophone(onPcmChunk: (base64: string) => void): Promise<void> {
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      sampleRate: 16000,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    },
  });

  audioContext = new AudioContext({ sampleRate: 16000 });
  sourceNode = audioContext.createMediaStreamSource(mediaStream);

  // ScriptProcessorNode is deprecated but widely supported and simpler.
  // Buffer size 4096 at 16kHz = 256ms chunks.
  scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
  scriptProcessor.onaudioprocess = (event) => {
    const inputData = event.inputBuffer.getChannelData(0);
    const pcm16 = float32ToPcm16(inputData);
    const base64 = arrayBufferToBase64(pcm16);
    onPcmChunk(base64);
  };

  sourceNode.connect(scriptProcessor);
  scriptProcessor.connect(audioContext.destination);
}

function stopMicrophone(): void {
  if (scriptProcessor) {
    scriptProcessor.disconnect();
    scriptProcessor = null;
  }
  if (sourceNode) {
    sourceNode.disconnect();
    sourceNode = null;
  }
  if (audioContext) {
    audioContext.close().catch(() => {});
    audioContext = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
}

const CONNECTION_TIMEOUT_MS = 30_000;
const MAX_TRANSCRIPT_LENGTH = 4000;
const VALID_MESSAGE_TYPES = new Set([
  "audio", "agent_response", "user_transcript",
  "interruption", "ping", "conversation_initiation_metadata",
]);

function sanitizeTranscript(text: string): string {
  if (!text || typeof text !== "string") return "";
  // Strip control characters, limit length
  return text.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "").slice(0, MAX_TRANSCRIPT_LENGTH);
}

export async function connectElevenLabs(
  agentId: string,
  callbacks: ElevenLabsCallbacks
): Promise<void> {
  const url = `wss://api.elevenlabs.io/v1/convai/conversation?agent_id=${agentId}`;

  return new Promise((resolve, reject) => {
    // Connection timeout
    const timeout = setTimeout(() => {
      ws?.close();
      reject(new Error("WebSocket connection timeout (30s)"));
    }, CONNECTION_TIMEOUT_MS);

    ws = new WebSocket(url);

    ws.onopen = async () => {
      clearTimeout(timeout);
      console.log("[ElevenLabs] WebSocket connected");
      try {
        await setupMicrophone((base64) => {
          if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ user_audio_chunk: base64 }));
          }
        });
        callbacks.onReady?.();
        resolve();
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        callbacks.onError?.(error);
        reject(error);
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string);
        if (!data.type || !VALID_MESSAGE_TYPES.has(data.type)) return;

        switch (data.type) {
          case "audio":
            if (data.audio_event?.audio_base_64) {
              callbacks.onAudio?.(data.audio_event.audio_base_64);
            }
            break;

          case "agent_response":
            if (data.agent_response_event?.agent_response) {
              const text = sanitizeTranscript(data.agent_response_event.agent_response);
              if (text) callbacks.onAgentResponse?.(text);
            }
            break;

          case "user_transcript":
            if (data.user_transcription_event?.user_transcript) {
              const text = sanitizeTranscript(data.user_transcription_event.user_transcript);
              if (text) callbacks.onUserTranscript?.(text);
            }
            break;

          case "interruption":
            callbacks.onInterrupt?.();
            break;

          case "ping":
            if (data.ping_event?.event_id) {
              ws?.send(
                JSON.stringify({ type: "pong", event_id: data.ping_event.event_id })
              );
            }
            break;

          case "conversation_initiation_metadata":
            console.log("[ElevenLabs] Conversation initiated");
            break;
        }
      } catch {
        // Ignore non-JSON messages
      }
    };

    ws.onerror = () => {
      clearTimeout(timeout);
      callbacks.onError?.(new Error("WebSocket connection error"));
    };

    ws.onclose = (event) => {
      clearTimeout(timeout);
      console.log("[ElevenLabs] WebSocket closed:", event.code);
      stopMicrophone();
      callbacks.onDisconnect?.();
    };
  });
}

export function stopElevenLabs(): void {
  stopMicrophone();
  if (ws) {
    ws.close();
    ws = null;
  }
}

export function isElevenLabsConnected(): boolean {
  return ws?.readyState === WebSocket.OPEN;
}
