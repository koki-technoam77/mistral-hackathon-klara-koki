/**
 * Anam AI Avatar client utilities.
 * Uses audio passthrough mode — our backend provides PCM audio,
 * Anam renders the avatar with lip-sync.
 */

export interface AnamAvatarHandle {
  sendPcmAudio: (pcmArrayBuffer: ArrayBuffer) => void;
  endSequence: () => void;
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
    sendPcmAudio: (pcmArrayBuffer: ArrayBuffer) => {
      audioInputStream.sendAudioChunk(pcmArrayBuffer);
    },
    endSequence: () => {
      audioInputStream.endSequence();
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
