"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { Message, WorkflowDefinition, CharacterState } from "@/types";
import * as api from "@/lib/api";
import { initAnamAvatar, type AnamAvatarHandle } from "@/lib/anam";
import {
  connectElevenLabs,
  stopElevenLabs,
  isElevenLabsConnected,
} from "@/lib/elevenlabs-agent";

interface Props {
  messages: Message[];
  onNewMessage: (msg: Message) => void;
  onWorkflowReady: (workflow: WorkflowDefinition) => void;
  onCharacterUpdate: (state: CharacterState) => void;
  onExecutionStart: () => void;
  onExecutionComplete: (result: Awaited<ReturnType<typeof api.executeWorkflow>>) => void;
  currentWorkflow: WorkflowDefinition | null;
  isProcessing: boolean;
  setIsProcessing: (v: boolean) => void;
}

type ConversationStatus =
  | "initializing"
  | "connecting"
  | "active"
  | "error"
  | "disconnected";

/** Play a short notification chime via Web Audio API */
function playNotificationSound(): void {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(1100, ctx.currentTime + 0.1);
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.3);
    osc.onended = () => ctx.close();
  } catch {
    // non-critical
  }
}

export default function AvatarChat({
  messages,
  onNewMessage,
  onWorkflowReady,
  onCharacterUpdate,
  onExecutionStart,
  onExecutionComplete,
  currentWorkflow,
  isProcessing,
  setIsProcessing,
}: Props) {
  const [status, setStatus] = useState<ConversationStatus>("initializing");
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [showTranscript, setShowTranscript] = useState(true);
  const [levelUpFlash, setLevelUpFlash] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [workflowReady, setWorkflowReady] = useState(false);

  const avatarRef = useRef<AnamAvatarHandle | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const mountedRef = useRef(true);
  const initStartedRef = useRef(false);
  const sessionIdRef = useRef<string | null>(null);
  const lastChatCallRef = useRef(0); // Rate limiting: min 2s between chat calls

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Auto-scroll transcript
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isProcessing]);

  // ─── Start the full pipeline: Anam avatar + ElevenLabs Agent ───────────────

  const startConversation = useCallback(async () => {
    if (initStartedRef.current) return;
    initStartedRef.current = true;
    setStatus("connecting");
    setError(null);

    try {
      // 1. Get session config from backend (Anam token + ElevenLabs agent ID)
      const config = await api.getAnamSession();
      if (!mountedRef.current) return;

      // 2. Initialize Anam avatar
      console.log("[Avatar] Initializing Anam avatar...");
      const avatar = await initAnamAvatar(
        config.session_token,
        "anam-avatar-video"
      );
      if (!mountedRef.current) {
        avatar.disconnect();
        return;
      }
      avatarRef.current = avatar;
      console.log("[Avatar] Anam avatar connected");

      // 3. Connect ElevenLabs Agent WebSocket
      console.log("[Avatar] Connecting ElevenLabs Agent...");
      await connectElevenLabs(config.elevenlabs_agent_id, {
        onReady: () => {
          console.log("[Avatar] ElevenLabs ready — conversation active");
          if (mountedRef.current) {
            setStatus("active");
          }
        },
        onAudio: (audioBase64) => {
          // Forward agent audio to Anam for lip-sync
          avatarRef.current?.sendAudioChunk(audioBase64);
          if (mountedRef.current) setIsSpeaking(true);
        },
        onUserTranscript: (text) => {
          if (!mountedRef.current) return;
          onNewMessage({
            id: crypto.randomUUID(),
            role: "user",
            content: text,
            timestamp: new Date(),
          });
          // Rate-limited: send transcript to backend for workflow detection
          const now = Date.now();
          if (now - lastChatCallRef.current < 2000) return; // Min 2s between calls
          lastChatCallRef.current = now;
          api
            .chat(text, sessionIdRef.current ?? undefined)
            .then((res) => {
              if (!mountedRef.current) return;
              if (res.session_id) sessionIdRef.current = res.session_id;
              onCharacterUpdate(res.character_state);
              if (res.ready && res.workflow) {
                onWorkflowReady(res.workflow);
                setWorkflowReady(true);
                playNotificationSound();
                // Add visible notification message to transcript
                onNewMessage({
                  id: crypto.randomUUID(),
                  role: "assistant",
                  content: `Workflow "${res.workflow.name}" generated! Tap "Run Workflow" below to execute it.`,
                  timestamp: new Date(),
                });
                // Auto-dismiss after 5s
                setTimeout(() => {
                  if (mountedRef.current) setWorkflowReady(false);
                }, 5000);
              }
            })
            .catch((err) => {
              console.warn("[Avatar] Backend chat error (non-blocking):", err);
            });
        },
        onAgentResponse: (text) => {
          // End the Anam audio sequence when agent finishes speaking
          avatarRef.current?.endSequence();
          if (!mountedRef.current) return;
          setIsSpeaking(false);
          onNewMessage({
            id: crypto.randomUUID(),
            role: "assistant",
            content: text,
            timestamp: new Date(),
          });
        },
        onInterrupt: () => {
          avatarRef.current?.interruptPersona();
          avatarRef.current?.endSequence();
          if (mountedRef.current) setIsSpeaking(false);
        },
        onDisconnect: () => {
          if (mountedRef.current) setStatus("disconnected");
        },
        onError: (err) => {
          console.error("[Avatar] ElevenLabs error:", err);
          if (mountedRef.current) {
            setStatus("error");
            setError(err.message);
          }
        },
      });
    } catch (err) {
      console.error("[Avatar] Init error:", err);
      if (mountedRef.current) {
        setStatus("error");
        setError(err instanceof Error ? err.message : String(err));
      }
    }
  }, [onNewMessage, onWorkflowReady, onCharacterUpdate]);

  // Auto-start on mount
  useEffect(() => {
    startConversation();
    return () => {
      stopElevenLabs();
      avatarRef.current?.disconnect();
      avatarRef.current = null;
    };
  }, [startConversation]);

  // ─── Retry connection ──────────────────────────────────────────────────────

  const handleRetry = useCallback(() => {
    stopElevenLabs();
    avatarRef.current?.disconnect();
    avatarRef.current = null;
    initStartedRef.current = false;
    setStatus("initializing");
    setError(null);
    startConversation();
  }, [startConversation]);

  // ─── Workflow execution ────────────────────────────────────────────────────

  const handleRunWorkflow = async () => {
    const workflow = currentWorkflow;
    if (!workflow || isExecuting) return;
    setIsExecuting(true);
    onExecutionStart();

    try {
      const result = await api.executeWorkflow(workflow);
      onExecutionComplete(result);
      onCharacterUpdate(result.character_state);

      const didLevelUp = result.xp_result.level_up;
      const xpContent = didLevelUp
        ? `LEVEL UP! Your companion evolved to level ${result.xp_result.new_level}! +${result.xp_result.xp_earned ?? 0} XP`
        : `Workflow executed! +${result.xp_result.xp_earned ?? 0} XP earned`;

      onNewMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: xpContent,
        timestamp: new Date(),
      });

      if (didLevelUp) setLevelUpFlash(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      onExecutionComplete({
        execution: {
          id: crypto.randomUUID(),
          workflow,
          status: "failed" as const,
          step_results: {},
          created_at: new Date().toISOString(),
        },
        xp_result: { xp_earned: 0, level_up: false },
        character_state: null as unknown as CharacterState,
      });
      onNewMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Execution error: ${msg}`,
        timestamp: new Date(),
      });
    } finally {
      setIsExecuting(false);
    }
  };

  // ─── Status config ────────────────────────────────────────────────────────

  const statusConfig = {
    initializing: { color: "bg-gray-500", label: "Initializing..." },
    connecting: { color: "bg-yellow-500 animate-pulse", label: "Connecting..." },
    active: { color: "bg-emerald-500", label: "Conversation Active" },
    error: { color: "bg-red-500", label: "Connection Error" },
    disconnected: { color: "bg-gray-500", label: "Disconnected" },
  };
  const statusInfo = statusConfig[status];

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full min-h-[400px] overflow-hidden rounded-2xl border border-gray-800 bg-gray-950">
      {/* Avatar video area */}
      <div className="relative flex-1 min-h-0 bg-gradient-to-b from-gray-900 to-gray-950">
        {/* Video element */}
        <video
          id="anam-avatar-video"
          autoPlay
          playsInline
          muted={false}
          className="w-full h-full object-cover absolute inset-0"
          style={{ minHeight: "300px", background: "#000" }}
        />

        {/* Level-up golden flash overlay */}
        <AnimatePresence>
          {levelUpFlash && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: [0, 0.6, 0] }}
              transition={{ duration: 2.5 }}
              className="absolute inset-0 bg-gradient-to-t from-yellow-500/30 to-transparent pointer-events-none z-10"
              onAnimationComplete={() => setLevelUpFlash(false)}
            />
          )}
        </AnimatePresence>

        {/* Connecting / Error overlay */}
        {status !== "active" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-950/80 backdrop-blur-sm z-20">
            {(status === "initializing" || status === "connecting") && (
              <motion.div
                animate={{ scale: [1, 1.1, 1], opacity: [0.5, 1, 0.5] }}
                transition={{ duration: 2, repeat: Infinity }}
                className="w-24 h-24 rounded-full bg-indigo-600/30 border-2 border-indigo-500/50 flex items-center justify-center mb-4"
              >
                <svg viewBox="0 0 40 40" className="w-12 h-12 text-indigo-400" fill="none">
                  <circle cx="20" cy="14" r="6" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M8 34c0-6.627 5.373-12 12-12s12 5.373 12 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </motion.div>
            )}
            {status === "connecting" && (
              <p className="text-indigo-300 text-sm font-medium">
                Connecting avatar and voice agent...
              </p>
            )}
            {status === "initializing" && (
              <p className="text-gray-500 text-sm">Initializing...</p>
            )}
            {(status === "error" || status === "disconnected") && (
              <div className="text-center px-6">
                <div className="w-16 h-16 rounded-full bg-red-600/20 border border-red-500/30 flex items-center justify-center mx-auto mb-3">
                  <span className="text-2xl">!</span>
                </div>
                <p className="text-red-400 text-sm font-medium">
                  {status === "error" ? "Connection failed" : "Disconnected"}
                </p>
                {error && (
                  <p className="text-gray-500 text-xs mt-1 max-w-xs break-words">
                    {error}
                  </p>
                )}
                <button
                  onClick={handleRetry}
                  className="mt-3 px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition-colors"
                >
                  Retry Connection
                </button>
              </div>
            )}
          </div>
        )}

        {/* Status badge */}
        <div className="absolute top-3 left-3 flex items-center gap-2 bg-gray-900/80 backdrop-blur rounded-full px-3 py-1.5 z-30">
          <div className={`w-2 h-2 rounded-full ${statusInfo.color}`} />
          <span className="text-xs text-gray-300">{statusInfo.label}</span>
        </div>

        {/* Speaking indicator */}
        <AnimatePresence>
          {isSpeaking && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-indigo-600/80 backdrop-blur rounded-full px-3 py-1.5 z-30"
            >
              <div className="flex gap-0.5 items-end h-3">
                {[0, 1, 2, 3, 4].map((i) => (
                  <motion.div
                    key={i}
                    className="w-0.5 bg-white rounded-full"
                    animate={{ height: ["4px", "12px", "4px"] }}
                    transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.1 }}
                  />
                ))}
              </div>
              <span className="text-xs text-white font-medium">Speaking...</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Mic active indicator (when conversation is active) */}
        <AnimatePresence>
          {status === "active" && !isSpeaking && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-gray-800/80 backdrop-blur rounded-full px-3 py-1.5 z-30"
            >
              <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              <span className="text-xs text-gray-300">Listening...</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Transcript toggle */}
        <button
          onClick={() => setShowTranscript((v) => !v)}
          className="absolute top-3 right-3 bg-gray-900/80 backdrop-blur rounded-full p-2 text-gray-400 hover:text-white transition-colors z-30"
          title={showTranscript ? "Hide transcript" : "Show transcript"}
        >
          <svg viewBox="0 0 20 20" className="w-4 h-4" fill="currentColor">
            <path d="M2 5a2 2 0 012-2h12a2 2 0 012 2v6a2 2 0 01-2 2H6l-4 4V5z" />
          </svg>
        </button>

        {/* End conversation button */}
        {status === "active" && (
          <button
            onClick={() => {
              stopElevenLabs();
              avatarRef.current?.disconnect();
              avatarRef.current = null;
              setStatus("disconnected");
            }}
            className="absolute top-3 right-14 bg-red-600/80 hover:bg-red-500 backdrop-blur rounded-full px-3 py-1.5 text-white text-xs font-semibold transition-colors z-30"
          >
            End Call
          </button>
        )}

        {/* Transcript overlay */}
        <AnimatePresence>
          {showTranscript && messages.length > 0 && (
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className="absolute top-12 right-3 bottom-14 w-72 bg-gray-950/85 backdrop-blur-md rounded-xl border border-gray-800 overflow-hidden flex flex-col z-20"
            >
              <div className="px-3 py-2 border-b border-gray-800 flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
                <span className="text-xs font-medium text-gray-300">Transcript</span>
              </div>
              <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2 scrollbar-thin">
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`text-xs leading-relaxed ${
                      msg.role === "user" ? "text-indigo-300" : "text-gray-400"
                    }`}
                  >
                    <span className="font-medium text-gray-500">
                      {msg.role === "user" ? "You" : "Flow"}:{" "}
                    </span>
                    {msg.content}
                  </div>
                ))}
                <div ref={bottomRef} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Error display */}
      <AnimatePresence>
        {error && status === "active" && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="px-4 py-2 bg-red-950/60 border-t border-red-800 text-red-400 text-xs"
          >
            {error}
            <button className="ml-2 underline" onClick={() => setError(null)}>
              dismiss
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Workflow action bar */}
      <AnimatePresence>
        {currentWorkflow && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className={`px-4 py-2.5 border-t border-gray-700 flex items-center gap-3 shrink-0 ${
              workflowReady ? "bg-emerald-950/40 border-emerald-700" : "bg-indigo-950/30"
            }`}
          >
            <div className="flex-1 min-w-0">
              <p className="text-xs text-indigo-300 font-medium truncate">
                Workflow ready: {currentWorkflow.name}
              </p>
              <p className="text-xs text-gray-500">{currentWorkflow.steps.length} steps</p>
            </div>
            <button
              onClick={handleRunWorkflow}
              disabled={isExecuting}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-semibold transition-colors flex items-center gap-1.5"
            >
              {isExecuting ? (
                <>
                  <motion.span
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                    className="inline-block"
                  >
                    ⟳
                  </motion.span>
                  Running...
                </>
              ) : (
                <>▶ Run Workflow</>
              )}
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom info bar */}
      <div className="px-4 py-3 border-t border-gray-800 shrink-0 flex items-center justify-center gap-3">
        {status === "active" ? (
          <p className="text-gray-400 text-xs text-center">
            Voice conversation active — speak naturally. The avatar will respond in real-time.
          </p>
        ) : (
          <p className="text-gray-500 text-xs text-center">
            {status === "connecting"
              ? "Setting up voice conversation..."
              : status === "error"
              ? "Connection failed. Click Retry to try again."
              : "Waiting for connection..."}
          </p>
        )}
      </div>
    </div>
  );
}
