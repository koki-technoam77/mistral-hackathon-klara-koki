"use client";

import { useEffect, useMemo, useRef, useCallback, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type ReactFlowInstance,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion } from "framer-motion";
import type { WorkflowDefinition, WorkflowStep, WorkflowExecutionStatus } from "@/types";

// ─── Action type detection ────────────────────────────────────────────────────

function getActionCategory(action: string): string {
  const a = action.toLowerCase();
  if (a.includes("composio") || a.includes("gmail") || a.includes("slack") || a.includes("notion")) return "composio";
  if (a.includes("llm") || a.includes("openai") || a.includes("claude") || a.includes("gpt") || a.includes("generate")) return "llm";
  if (a.includes("browser") || a.includes("scrape") || a.includes("web") || a.includes("crawl")) return "browser";
  if (a.includes("api") || a.includes("http") || a.includes("fetch") || a.includes("webhook")) return "api";
  return "default";
}

// ─── Human-readable label helpers ────────────────────────────────────────────

/**
 * Converts a snake_case or camelCase action identifier into a friendly,
 * Title Case label. e.g. "send_email" → "Send Email", "fetchWebhook" → "Fetch Webhook"
 */
function toHumanLabel(action: string): string {
  // Strip common prefixes like "composio_", "api_"
  const stripped = action
    .replace(/^(composio_|api_|llm_|browser_)/i, "")
    .replace(/_/g, " ")
    // camelCase to words
    .replace(/([a-z])([A-Z])/g, "$1 $2");
  return stripped
    .split(" ")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ")
    .trim() || action;
}

/** Estimated seconds per step — rough heuristic for the toolbar display */
function estimateMinutes(stepCount: number): string {
  const secs = stepCount * 8;
  if (secs < 60) return `~${secs}s`;
  return `~${Math.round(secs / 60)}m`;
}

const CATEGORY_COLORS: Record<string, string> = {
  composio: "#22c55e",
  llm: "#3b82f6",
  browser: "#a855f7",
  api: "#f97316",
  default: "#6366f1",
};

const CATEGORY_BG: Record<string, string> = {
  composio: "rgba(34,197,94,0.1)",
  llm: "rgba(59,130,246,0.1)",
  browser: "rgba(168,85,247,0.1)",
  api: "rgba(249,115,22,0.1)",
  default: "rgba(99,102,241,0.1)",
};

// ─── Custom node renderer ─────────────────────────────────────────────────────

interface WorkflowNodeData {
  step: WorkflowStep;
  category: string;
  active: boolean;
  completed: boolean;
}

function WorkflowNode({ data }: { data: WorkflowNodeData }) {
  const { step, category, active, completed } = data;
  const borderColor = CATEGORY_COLORS[category];
  const bgColor = CATEGORY_BG[category];

  const humanLabel = toHumanLabel(step.action);

  const paramsPreview = Object.entries(step.params)
    .slice(0, 2)
    .map(([k, v]) => `${toHumanLabel(k)}: ${String(v).slice(0, 22)}`)
    .join(" · ");

  const categoryIcon: Record<string, string> = {
    composio: "🔌",
    llm: "✨",
    browser: "🌐",
    api: "⚡",
    default: "⚙️",
  };

  return (
    <div
      className={`rounded-xl p-3 min-w-[160px] max-w-[220px] text-sm border-2 transition-all duration-300 ${
        active ? "node-active shadow-lg" : ""
      } ${completed ? "opacity-75" : ""}`}
      style={{
        borderColor,
        background: bgColor,
        boxShadow: active ? `0 0 18px 4px ${borderColor}55` : undefined,
      }}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-base leading-none">{categoryIcon[category]}</span>
        {completed && <span className="ml-auto text-green-400 text-sm">✓</span>}
        {active && (
          <span className="ml-auto text-yellow-400 text-xs animate-pulse">● Running</span>
        )}
      </div>
      <div className="font-semibold text-white text-xs leading-tight truncate">{humanLabel}</div>
      {paramsPreview && (
        <div className="text-gray-400 text-xs mt-1 truncate leading-tight">{paramsPreview}</div>
      )}
    </div>
  );
}

const nodeTypes = { workflowNode: WorkflowNode };

// ─── Layout helpers ───────────────────────────────────────────────────────────

const NODE_W = 220;
const NODE_H = 80;
const X_GAP = 80;
const Y_GAP = 60;

function buildNodesAndEdges(
  workflow: WorkflowDefinition,
  activeStepId: string | null,
  completedStepIds: Set<string>,
  visibleCount: number
): { nodes: Node[]; edges: Edge[] } {
  const steps = workflow.steps.slice(0, visibleCount);

  // Simple left-to-right layout; wrap every 4 nodes into next row
  const COLS = 4;
  const nodes: Node[] = steps.map((step, i) => {
    const col = i % COLS;
    const row = Math.floor(i / COLS);
    const category = getActionCategory(step.action);
    return {
      id: step.id,
      type: "workflowNode",
      position: { x: col * (NODE_W + X_GAP), y: row * (NODE_H + Y_GAP) },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: {
        step,
        category,
        active: step.id === activeStepId,
        completed: completedStepIds.has(step.id),
      } satisfies WorkflowNodeData,
    };
  });

  const edges: Edge[] = steps.flatMap((step) => {
    if (!step.depends_on?.length) return [];
    return step.depends_on.map((dep) => ({
      id: `${dep}->${step.id}`,
      source: dep,
      target: step.id,
      animated: step.id === activeStepId,
      style: { stroke: "#6366f1", strokeWidth: 1.5 },
    }));
  });

  // Fallback: sequential edges if no depends_on
  if (edges.length === 0 && steps.length > 1) {
    for (let i = 0; i < steps.length - 1; i++) {
      edges.push({
        id: `seq-${i}`,
        source: steps[i].id,
        target: steps[i + 1].id,
        animated: steps[i + 1].id === activeStepId,
        style: { stroke: "#6366f1", strokeWidth: 1.5 },
      });
    }
  }

  return { nodes, edges };
}

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  workflow: WorkflowDefinition | null;
  executionStatus?: WorkflowExecutionStatus | null;
  stepResults?: Record<string, unknown>;
}

export default function WorkflowVisualizer({ workflow, executionStatus, stepResults }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [visibleCount, setVisibleCount] = useState(0);
  const rfInstance = useRef<ReactFlowInstance | null>(null);

  const onInit = useCallback((instance: ReactFlowInstance) => {
    rfInstance.current = instance;
  }, []);

  // Determine active + completed steps from step_results
  const completedStepIds = useMemo(() => {
    if (!stepResults) return new Set<string>();
    return new Set(Object.keys(stepResults));
  }, [stepResults]);

  // Find first non-completed step during running
  const activeStepId = useMemo(() => {
    if (executionStatus !== "running" || !workflow) return null;
    const next = workflow.steps.find((s) => !completedStepIds.has(s.id));
    return next?.id ?? null;
  }, [executionStatus, workflow, completedStepIds]);

  // Animate nodes appearing sequentially on new workflow
  useEffect(() => {
    if (!workflow) {
      setVisibleCount(0);
      return;
    }
    setVisibleCount(0);
    let count = 0;
    const total = workflow.steps.length;
    const timer = setInterval(() => {
      count += 1;
      setVisibleCount(count);
      if (count >= total) clearInterval(timer);
    }, 120);
    return () => clearInterval(timer);
  }, [workflow]);

  // Rebuild flow graph whenever deps change
  useEffect(() => {
    if (!workflow) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const { nodes: n, edges: e } = buildNodesAndEdges(
      workflow,
      activeStepId,
      completedStepIds,
      visibleCount
    );
    setNodes(n);
    setEdges(e);

    // Fit view to show all nodes after the last node appears
    if (visibleCount >= workflow.steps.length && rfInstance.current) {
      // Small delay to let React Flow update layout
      requestAnimationFrame(() => {
        rfInstance.current?.fitView({ padding: 0.25, duration: 300 });
      });
    }
  }, [workflow, visibleCount, activeStepId, completedStepIds]);

  if (!workflow) {
    return (
      <div className="panel flex flex-col items-center justify-center h-full min-h-[300px] gap-4 px-6 text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4 }}
          className="w-20 h-20 rounded-2xl bg-gray-800/60 border border-gray-700 flex items-center justify-center"
        >
          <svg viewBox="0 0 64 64" className="w-12 h-12 text-gray-600" fill="none">
            <rect x="4" y="24" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="2" />
            <rect x="24" y="10" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="2" />
            <rect x="24" y="38" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="2" />
            <rect x="44" y="24" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="2" />
            <line x1="20" y1="32" x2="24" y2="18" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
            <line x1="20" y1="32" x2="24" y2="46" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
            <line x1="40" y1="18" x2="44" y2="28" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
            <line x1="40" y1="46" x2="44" y2="36" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
          </svg>
        </motion.div>
        <div>
          <p className="text-gray-300 font-medium text-sm">Your workflow will appear here</p>
          <p className="text-gray-500 text-xs mt-1 max-w-[200px] mx-auto leading-relaxed">
            Start by describing what you want to automate in the chat.
          </p>
        </div>
        <div className="flex gap-1.5 flex-wrap justify-center">
          {["Connect apps", "Schedule tasks", "Auto-reply"].map((tag) => (
            <span
              key={tag}
              className="text-xs text-gray-600 border border-gray-800 rounded-full px-2.5 py-0.5"
            >
              {tag}
            </span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="panel flex flex-col h-full min-h-[300px] overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-800 shrink-0">
        <div className="flex flex-col min-w-0">
          <span className="font-semibold text-sm truncate text-white leading-tight">{workflow.name}</span>
          {workflow.description && (
            <span className="text-gray-500 text-xs truncate hidden sm:block leading-tight mt-0.5">
              {workflow.description}
            </span>
          )}
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs shrink-0">
          {/* Step count + estimated time */}
          <span className="flex items-center gap-1 text-gray-400 bg-gray-800 rounded-full px-2.5 py-0.5 border border-gray-700">
            <svg viewBox="0 0 12 12" className="w-3 h-3" fill="none">
              <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.2"/>
              <path d="M6 3v3l2 1.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            </svg>
            {workflow.steps.length} steps · {estimateMinutes(workflow.steps.length)}
          </span>
          <span
            className="px-2 py-0.5 rounded-full border text-gray-400 capitalize"
            style={{ borderColor: "#374151" }}
          >
            {workflow.trigger.type}
          </span>
          {executionStatus && (
            <span
              className={`px-2 py-0.5 rounded-full font-medium capitalize ${
                executionStatus === "completed"
                  ? "bg-green-900/40 text-green-400 border border-green-700"
                  : executionStatus === "running"
                  ? "bg-yellow-900/40 text-yellow-400 border border-yellow-700 animate-pulse"
                  : executionStatus === "failed"
                  ? "bg-red-900/40 text-red-400 border border-red-700"
                  : "bg-gray-800 text-gray-400 border border-gray-700"
              }`}
            >
              {executionStatus === "running" ? "Running..." : executionStatus}
            </span>
          )}
        </div>
      </div>

      {/* Legend */}
      <div className="flex gap-3 px-4 py-2 border-b border-gray-700/50 text-xs shrink-0">
        {Object.entries(CATEGORY_COLORS).filter(([k]) => k !== "default").map(([cat, color]) => (
          <div key={cat} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ background: color }} />
            <span className="text-gray-400 capitalize">{cat}</span>
          </div>
        ))}
      </div>

      {/* React Flow canvas */}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onInit={onInit}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#374151" gap={20} size={1} />
          <Controls />
          <MiniMap
            nodeColor={(n) => {
              const d = n.data as unknown as WorkflowNodeData;
              return CATEGORY_COLORS[d?.category ?? "default"] ?? "#6366f1";
            }}
            style={{ background: "#1f2937" }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}
