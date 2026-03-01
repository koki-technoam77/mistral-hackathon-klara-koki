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

// ─── SSE Streaming Execution ──────────────────────────────────────────────────

export interface StreamEvent {
  type: "step_start" | "step_complete" | "step_error" | "done";
  step_id?: string;
  status?: string;
  detail?: string;
  result?: WorkflowExecuteResponse;
}

export async function executeWorkflowStream(
  workflow: WorkflowDefinition,
  sessionId: string,
  onStepStart: (stepId: string) => void,
  onStepComplete: (stepId: string, status: string, detail?: string) => void,
  onDone: (result: WorkflowExecuteResponse) => void,
  onError?: (error: Error) => void
): Promise<void> {
  const url = `${BASE_URL}/api/workflow/execute-stream`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (API_KEY) {
    headers["Authorization"] = `Bearer ${API_KEY}`;
  }

  try {
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ workflow, session_id: sessionId }),
    });

    if (!res.ok) {
      throw new Error(`Stream error ${res.status}: ${res.statusText}`);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const jsonStr = line.slice(6).trim();
        if (!jsonStr) continue;

        try {
          const event: StreamEvent = JSON.parse(jsonStr);
          switch (event.type) {
            case "step_start":
              if (event.step_id) onStepStart(event.step_id);
              break;
            case "step_complete":
              if (event.step_id) onStepComplete(event.step_id, event.status ?? "success", event.detail);
              break;
            case "step_error":
              if (event.step_id) onStepComplete(event.step_id, "error", event.detail);
              break;
            case "done":
              if (event.result) onDone(event.result);
              break;
          }
        } catch {
          // skip malformed events
        }
      }
    }
  } catch (err) {
    if (onError) {
      onError(err instanceof Error ? err : new Error(String(err)));
    }
  }
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

// ─── Composio OAuth Connections ──────────────────────────────────────────────

export interface ComposioConnection {
  app: string;
  status: "active" | "not_connected" | "not_configured";
  connected_account_id: string | null;
}

export async function getComposioConnections(sessionId: string = "default"): Promise<{ connections: ComposioConnection[] }> {
  return apiFetch<{ connections: ComposioConnection[] }>(`/composio/connections?session_id=${encodeURIComponent(sessionId)}`);
}

export async function initiateComposioConnection(
  appName: string,
  redirectUrl: string,
  sessionId: string = "default"
): Promise<{ status: string; redirect_url?: string; connected_account_id?: string }> {
  return apiFetch<{ status: string; redirect_url?: string; connected_account_id?: string }>("/composio/connect", {
    method: "POST",
    body: JSON.stringify({ app_name: appName, redirect_url: redirectUrl, session_id: sessionId }),
  });
}

export async function getComposioConnectionStatus(
  appName: string,
  sessionId: string = "default"
): Promise<ComposioConnection> {
  return apiFetch<ComposioConnection>(`/composio/status/${encodeURIComponent(appName)}?session_id=${encodeURIComponent(sessionId)}`);
}

export async function getComposioApps(): Promise<{ apps: string[] }> {
  return apiFetch<{ apps: string[] }>("/composio/apps");
}

export interface ResourceItem {
  id: string;
  name: string;
  url: string;
}

export async function listComposioResources(
  appName: string,
  sessionId: string = "default"
): Promise<{ app: string; resources: ResourceItem[]; error?: string }> {
  return apiFetch<{ app: string; resources: ResourceItem[]; error?: string }>(
    `/composio/resources/${encodeURIComponent(appName)}?session_id=${encodeURIComponent(sessionId)}`
  );
}

// ─── Workflow Scheduler ──────────────────────────────────────────────────────

export interface ScheduledJob {
  job_id: string;
  workflow_name: string;
  entity_id: string;
  cron_expr: string | null;
  interval_seconds: number | null;
  created_at: string;
  last_run_at: string | null;
  last_status: string | null;
  run_count: number;
}

export async function scheduleWorkflow(
  workflow: WorkflowDefinition,
  options: { cron_expr?: string; interval_seconds?: number },
  sessionId: string = "default"
): Promise<ScheduledJob> {
  return apiFetch<ScheduledJob>("/workflow/schedule", {
    method: "POST",
    body: JSON.stringify({
      workflow,
      cron_expr: options.cron_expr ?? null,
      interval_seconds: options.interval_seconds ?? null,
      session_id: sessionId,
    }),
  });
}

export async function getScheduledJobs(sessionId?: string): Promise<{ schedules: ScheduledJob[] }> {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return apiFetch<{ schedules: ScheduledJob[] }>(`/workflow/schedules${qs}`);
}

export async function cancelScheduledJob(jobId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/workflow/schedule/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
}

// ─── Webhook Triggers ────────────────────────────────────────────────────────

export interface WebhookInfo {
  webhook_id: string;
  workflow_name: string;
  entity_id: string;
  url: string;
}

export async function registerWebhook(
  workflow: WorkflowDefinition,
  sessionId: string = "default"
): Promise<{ webhook_id: string; url: string }> {
  return apiFetch<{ webhook_id: string; url: string }>("/webhook/register", {
    method: "POST",
    body: JSON.stringify({ workflow, session_id: sessionId }),
  });
}

export async function listWebhooks(sessionId?: string): Promise<{ webhooks: WebhookInfo[] }> {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return apiFetch<{ webhooks: WebhookInfo[] }>(`/webhooks${qs}`);
}

export async function deleteWebhook(webhookId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/webhook/${encodeURIComponent(webhookId)}`, {
    method: "DELETE",
  });
}

// ─── Health ───────────────────────────────────────────────────────────────────

export async function checkHealth(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/health");
}
