"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ChatPanel from "@/components/ChatPanel";
import WorkflowVisualizer from "@/components/WorkflowVisualizer";
import CharacterPanel from "@/components/CharacterPanel";
import * as api from "@/lib/api";
import type {
  Message,
  WorkflowDefinition,
  CharacterState,
  WorkflowExecutionStatus,
} from "@/types";

// ─── Onboarding overlay ────────────────────────────────────────────────────────

const ONBOARDING_KEY = "kotoflow_onboarded_v1";

const ONBOARDING_STEPS = [
  {
    icon: "💬",
    title: "Tell me what to automate",
    description: "Describe it in plain English or just talk to me!",
  },
  {
    icon: "✨",
    title: "I'll build the workflow",
    description: "I'll ask a few questions, then design the steps for you.",
  },
  {
    icon: "🚀",
    title: "Say 'Run it' and you're done",
    description: "I'll execute everything and tell you what happened.",
  },
];

function OnboardingOverlay({ onDismiss }: { onDismiss: () => void }) {
  return (
    <motion.div
      className="onboarding-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
    >
      <motion.div
        className="onboarding-card"
        initial={{ opacity: 0, y: 24, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 12, scale: 0.98 }}
        transition={{ duration: 0.35, delay: 0.05 }}
      >
        {/* Logo */}
        <div className="flex justify-center mb-4">
          <div className="w-14 h-14 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center">
            <svg viewBox="0 0 32 32" className="w-8 h-8" fill="none">
              <circle cx="16" cy="16" r="14" fill="#6366f1" opacity="0.2" />
              <circle cx="16" cy="16" r="14" stroke="#6366f1" strokeWidth="1.5" />
              <path d="M10 20V12l6 4-6 4z" fill="#818cf8" />
              <path d="M18 12h4M18 16h3M18 20h4" stroke="#818cf8" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </div>
        </div>

        <h1 className="text-2xl font-bold text-white mb-1">Welcome to KotoFlow!</h1>
        <p className="text-gray-400 text-sm mb-6">
          Automate anything — no coding, no fuss. Just describe what you want.
        </p>

        {/* Steps */}
        <div className="flex flex-col gap-3 mb-7">
          {ONBOARDING_STEPS.map((step, i) => (
            <motion.div
              key={i}
              className="onboarding-step"
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.15 + i * 0.1 }}
            >
              <div className="onboarding-step-number">{i + 1}</div>
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-white text-sm">{step.title}</p>
                <p className="text-gray-400 text-xs mt-0.5">{step.description}</p>
              </div>
              <span className="text-xl shrink-0">{step.icon}</span>
            </motion.div>
          ))}
        </div>

        {/* CTA button */}
        <motion.button
          onClick={onDismiss}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-base transition-colors shadow-lg shadow-indigo-900/40"
        >
          Get Started
        </motion.button>

        <p className="text-gray-600 text-xs mt-4">
          Your automations are private and run on your own account.
        </p>
      </motion.div>
    </motion.div>
  );
}

// ─── Header ───────────────────────────────────────────────────────────────────

function Header({ character }: { character: CharacterState | null }) {
  return (
    <header className="flex items-center justify-between px-5 py-3 border-b border-gray-800 bg-gray-950/80 backdrop-blur shrink-0">
      <div className="flex items-center gap-3">
        {/* Logo mark */}
        <svg viewBox="0 0 32 32" className="w-7 h-7" fill="none">
          <circle cx="16" cy="16" r="14" fill="#6366f1" opacity="0.15" />
          <circle cx="16" cy="16" r="14" stroke="#6366f1" strokeWidth="1.5" />
          <path d="M10 20V12l6 4-6 4z" fill="#818cf8" />
          <path d="M18 12h4M18 16h3M18 20h4" stroke="#818cf8" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <span className="font-bold text-lg tracking-tight">
          Koto<span className="text-indigo-400">Flow</span>
        </span>
        <span className="hidden sm:inline text-xs text-gray-500 border border-gray-700 rounded px-1.5 py-0.5">
          VoiceFlow AI
        </span>
      </div>

      {/* Mini character badge */}
      {character && (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-full px-3 py-1"
        >
          <span className="text-indigo-400 font-bold text-xs">Lv.{character.level}</span>
          <span className="text-gray-300 text-xs">{character.name}</span>
          <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="xp-bar-fill h-full rounded-full"
              style={{
                width: `${Math.min(100, Math.round((character.xp / character.xp_to_next) * 100))}%`,
              }}
            />
          </div>
        </motion.div>
      )}
    </header>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentWorkflow, setCurrentWorkflow] = useState<WorkflowDefinition | null>(null);
  const [characterState, setCharacterState] = useState<CharacterState | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [executionStatus, setExecutionStatus] = useState<WorkflowExecutionStatus | null>(null);
  const [stepResults, setStepResults] = useState<Record<string, unknown>>({});
  const [xpToast, setXpToast] = useState<{ xp: number; levelUp: boolean; newLevel?: number } | null>(null);
  const [apiHealth, setApiHealth] = useState<"unknown" | "ok" | "error">("unknown");
  const [showOnboarding, setShowOnboarding] = useState(false);
  const xpToastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ─── Initial load ──────────────────────────────────────────────────────────

  useEffect(() => {
    // Show onboarding for first-time visitors
    const seen = typeof window !== "undefined" && localStorage.getItem(ONBOARDING_KEY);
    if (!seen) setShowOnboarding(true);

    // Load character state
    api.getCharacter().then(setCharacterState).catch(() => null);

    // Health check
    api
      .checkHealth()
      .then(() => setApiHealth("ok"))
      .catch(() => setApiHealth("error"));

    // Welcome message
    setMessages([
      {
        id: crypto.randomUUID(),
        role: "assistant",
        content:
          "Hi! I'm Flow-chan, your automation buddy! Just tell me what you'd like to automate and I'll take care of everything. You can type or hold the mic button and talk to me!",
        timestamp: new Date(),
      },
    ]);
  }, []);

  const handleDismissOnboarding = useCallback(() => {
    localStorage.setItem(ONBOARDING_KEY, "1");
    setShowOnboarding(false);
  }, []);

  // ─── Handlers ─────────────────────────────────────────────────────────────

  const handleNewMessage = useCallback((msg: Message) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const handleWorkflowReady = useCallback((workflow: WorkflowDefinition) => {
    setCurrentWorkflow(workflow);
    setExecutionStatus(null);
    setStepResults({});
  }, []);

  const handleCharacterUpdate = useCallback((state: CharacterState) => {
    setCharacterState(state);
  }, []);

  const handleExecutionStart = useCallback(() => {
    setExecutionStatus("running");
    setStepResults({});
  }, []);

  const handleExecutionComplete = useCallback(
    (result: Awaited<ReturnType<typeof api.executeWorkflow>>) => {
      setExecutionStatus(result.execution.status);
      setStepResults(result.execution.step_results ?? {});
      if (result.character_state) setCharacterState(result.character_state);

      if (result.xp_result?.xp_earned) {
        if (xpToastTimerRef.current) clearTimeout(xpToastTimerRef.current);
        setXpToast({
          xp: result.xp_result.xp_earned,
          levelUp: result.xp_result.level_up ?? false,
          newLevel: result.xp_result.new_level,
        });
        xpToastTimerRef.current = setTimeout(() => setXpToast(null), 3500);
      }
    },
    []
  );

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Onboarding overlay */}
      <AnimatePresence>
        {showOnboarding && (
          <OnboardingOverlay onDismiss={handleDismissOnboarding} />
        )}
      </AnimatePresence>

      <Header character={characterState} />

      {/* API health banner */}
      <AnimatePresence>
        {apiHealth === "error" && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="bg-red-950/60 border-b border-red-800 text-red-300 text-xs px-5 py-2 text-center"
          >
            Backend API is unavailable. Please ensure the server is running.
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main content area */}
      <main className="flex-1 overflow-hidden grid grid-rows-[1fr_auto] gap-3 p-3">
        {/* Top row: Chat + Workflow side by side */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 min-h-0 overflow-hidden">
          <ChatPanel
            messages={messages}
            onNewMessage={handleNewMessage}
            onWorkflowReady={handleWorkflowReady}
            onCharacterUpdate={handleCharacterUpdate}
            onExecutionStart={handleExecutionStart}
            onExecutionComplete={handleExecutionComplete}
            currentWorkflow={currentWorkflow}
            isProcessing={isProcessing}
            setIsProcessing={setIsProcessing}
          />

          <WorkflowVisualizer
            workflow={currentWorkflow}
            executionStatus={executionStatus}
            stepResults={stepResults}
          />
        </div>

        {/* Bottom row: Character panel */}
        <CharacterPanel character={characterState} />
      </main>

      {/* XP toast notification */}
      <AnimatePresence>
        {xpToast && (
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 40, scale: 0.9 }}
            className="fixed bottom-6 right-6 z-50 bg-indigo-700 border border-indigo-500 rounded-2xl px-5 py-3 shadow-2xl text-white"
          >
            <div className="flex items-center gap-3">
              <span className="text-2xl">{xpToast.levelUp ? "🌟" : "⚡"}</span>
              <div>
                {xpToast.levelUp ? (
                  <>
                    <p className="font-bold text-yellow-300">LEVEL UP!</p>
                    <p className="text-sm">Now level {xpToast.newLevel} +{xpToast.xp} XP</p>
                  </>
                ) : (
                  <>
                    <p className="font-semibold">+{xpToast.xp} XP earned</p>
                    <p className="text-xs text-indigo-300">Workflow completed</p>
                  </>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
