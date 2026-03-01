// ─── Workflow types ──────────────────────────────────────────────────────────

export type TriggerType = "schedule" | "webhook" | "manual";

export interface WorkflowTrigger {
  type: TriggerType;
  cron?: string;
  webhook_url?: string;
}

export interface WorkflowStep {
  id: string;
  action: string;
  params: Record<string, unknown>;
  output?: string;
  depends_on?: string[];
}

export interface WorkflowDefinition {
  name: string;
  description?: string;
  trigger: WorkflowTrigger;
  steps: WorkflowStep[];
}

export type WorkflowExecutionStatus = "pending" | "running" | "completed" | "failed";

export interface WorkflowExecution {
  id: string;
  workflow: WorkflowDefinition;
  status: WorkflowExecutionStatus;
  step_results: Record<string, unknown>;
  created_at: string;
  completed_at?: string;
}

// ─── Character types ─────────────────────────────────────────────────────────

export type SkillBranch = "communication" | "data" | "creative" | "scheduling" | "devops";

export type AppearanceStage = "egg" | "hatchling" | "creature" | "evolved" | "master";

export interface SkillState {
  level: number;
  workflows_completed: number;
  xp: number;
}

export interface Achievement {
  id: string;
  name: string;
  icon: string;
  description: string;
  earned: boolean;
  earned_at?: string;
}

export interface VoiceConfig {
  voice_id: string;
  stability: number;
  style: number;
}

export interface CharacterState {
  name: string;
  level: number;
  xp: number;
  xp_to_next: number;
  appearance_stage: AppearanceStage;
  voice_config: VoiceConfig;
  skills: Record<SkillBranch, SkillState>;
  achievements: Achievement[];
}

// ─── API response types ───────────────────────────────────────────────────────

export interface ChatResponse {
  message: string;
  ready: boolean;
  workflow?: WorkflowDefinition;
  character_state: CharacterState;
  session_id: string;
  needs_connection?: string[];
}

export interface WorkflowExecuteResponse {
  execution: WorkflowExecution;
  xp_result: {
    xp_earned: number;
    level_up: boolean;
    new_level?: number;
    skill_updates?: Record<string, unknown>;
  };
  character_state: CharacterState;
}

// ─── UI types ────────────────────────────────────────────────────────────────

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

// ─── Anam Avatar types ──────────────────────────────────────────────────────

export interface AnamSessionResponse {
  session_token: string;
  elevenlabs_agent_id: string;
}

// ─── Composio Connection types ──────────────────────────────────────────────

export interface ComposioConnection {
  app: string;
  status: "active" | "not_connected" | "not_configured";
  connected_account_id: string | null;
}
