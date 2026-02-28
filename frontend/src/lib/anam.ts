/**
 * Anam AI Avatar client utilities.
 * Uses audio passthrough mode — ElevenLabs Agent provides PCM audio,
 * Anam renders the avatar with lip-sync.
 */

export interface AnamAvatarHandle {
  /** Send a base64-encoded PCM audio chunk for lip-sync */
  sendAudioChunk: (audioBase64: string) => void;
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
    sendAudioChunk: (audioBase64: string) => {
      audioInputStream.sendAudioChunk(audioBase64);
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
