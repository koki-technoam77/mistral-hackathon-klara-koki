/**
 * Anam AI Avatar client utilities.
 * Uses audio passthrough mode — ElevenLabs Agent provides PCM audio,
 * Anam renders the avatar with lip-sync.
 */

export interface AnamAvatarHandle {
  /** Send a PCM audio chunk for lip-sync (base64 string, ArrayBuffer, or Uint8Array) */
  sendAudioChunk: (audioData: ArrayBuffer | Uint8Array | string) => void;
  /** Signal end of the current audio sequence */
  endSequence: () => void;
  /** Interrupt the current persona animation */
  interruptPersona: () => void;
  /** Disconnect and clean up */
  disconnect: () => void;
}

let anamModule: typeof import("@anam-ai/js-sdk") | null = null;

async function loadAnamSdk() {
  if (!anamModule) {
    anamModule = await import("@anam-ai/js-sdk");
  }
  return anamModule;
}

export async function initAnamAvatar(
  sessionToken: string,
  videoElementId: string
): Promise<AnamAvatarHandle> {
  const sdk = await loadAnamSdk();

  const client = sdk.createClient(sessionToken, {
    disableInputAudio: true,
  });

  // Start streaming to establish WebRTC connection first
  await client.streamToVideoElement(videoElementId);

  // Create audio input stream after connection is established
  const audioInputStream = client.createAgentAudioInputStream({
    encoding: "pcm_s16le",
    sampleRate: 16000,
    channels: 1,
  });

  return {
    sendAudioChunk: (audioData: ArrayBuffer | Uint8Array | string) => {
      audioInputStream.sendAudioChunk(audioData);
    },
    endSequence: () => {
      audioInputStream.endSequence();
    },
    interruptPersona: () => {
      try {
        client.interruptPersona();
      } catch {
        // ignore if not supported
      }
    },
    disconnect: () => {
      try {
        client.stopStreaming();
      } catch {
        // ignore cleanup errors
      }
    },
  };
}
