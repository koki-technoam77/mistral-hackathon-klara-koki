import type {
  ChatResponse,
  CharacterState,
  WorkflowDefinition,
  WorkflowExecuteResponse,
  AnamSessionResponse,
} from "@/types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

// ─── Generic fetch helper ─────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}/api${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (API_KEY) {
    headers["Authorization"] = `Bearer ${API_KEY}`;
  }
  if (options.headers) {
    Object.assign(headers, options.headers);
  }
  const res = await fetch(url, {
    headers,
    ...options,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new Error(`API error ${res.status}: ${detail}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

export async function chat(message: string, sessionId?: string): Promise<ChatResponse> {
  const payload: Record<string, string> = { message };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  return apiFetch<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function resetChat(sessionId?: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/chat/reset", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId ?? "" }),
  });
}

// ─── Workflow ─────────────────────────────────────────────────────────────────

export async function executeWorkflow(
  workflow: WorkflowDefinition
): Promise<WorkflowExecuteResponse> {
  return apiFetch<WorkflowExecuteResponse>("/workflow/execute", {
    method: "POST",
    body: JSON.stringify({ workflow }),
  });
}

export interface FeedbackPayload {
  user_request: string;
  workflow: WorkflowDefinition;
  feedback_type: "accept" | "reject" | "edit";
  edited?: boolean;
}

export async function submitFeedback(
  data: FeedbackPayload
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/workflow/feedback", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ─── Character ────────────────────────────────────────────────────────────────

export async function getCharacter(): Promise<CharacterState> {
  return apiFetch<CharacterState>("/character");
}

// ─── Voice ───────────────────────────────────────────────────────────────────

export async function transcribeAudio(audioBlob: Blob): Promise<string> {
  const form = new FormData();
  form.append("file", audioBlob, "recording.webm");

  const url = `${BASE_URL}/api/voice/transcribe`;
  const headers: Record<string, string> = {};
  if (API_KEY) {
    headers["Authorization"] = `Bearer ${API_KEY}`;
  }
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: form,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new Error(`Transcription error ${res.status}: ${detail}`);
  }

  const data = await res.json();
  return data.text as string;
}

export async function synthesizeVoice(text: string): Promise<Blob> {
  const url = `${BASE_URL}/api/voice/synthesize`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (API_KEY) {
    headers["Authorization"] = `Bearer ${API_KEY}`;
  }
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ text }),
  });

  if (!res.ok) {
    throw new Error(`Synthesis error ${res.status}: ${res.statusText}`);
  }

  return res.blob();
}

// ─── Anam Avatar ─────────────────────────────────────────────────────────────

export async function getAnamSession(): Promise<AnamSessionResponse> {
  return apiFetch<AnamSessionResponse>("/anam/session", {
    method: "POST",
  });
}

export async function synthesizePcmAudio(text: string): Promise<ArrayBuffer> {
  const url = `${BASE_URL}/api/voice/synthesize-pcm`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (API_KEY) {
    headers["Authorization"] = `Bearer ${API_KEY}`;
  }
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ text }),
  });

  if (!res.ok) {
    throw new Error(`PCM synthesis error ${res.status}: ${res.statusText}`);
  }

  return res.arrayBuffer();
}

// ─── Health ───────────────────────────────────────────────────────────────────

export async function checkHealth(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/health");
}
