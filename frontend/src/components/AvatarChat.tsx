"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { Message, WorkflowDefinition, CharacterState } from "@/types";
import * as api from "@/lib/api";
import { initAnamAvatar, type AnamAvatarHandle } from "@/lib/anam";

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

type AvatarStatus = "disconnected" | "connecting" | "connected" | "error";

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
  const [avatarStatus, setAvatarStatus] = useState<AvatarStatus>("disconnected");
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [inputText, setInputText] = useState("");
  const [chatError, setChatError] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [showTranscript, setShowTranscript] = useState(true);
  const [levelUpFlash, setLevelUpFlash] = useState(false);

  const avatarRef = useRef<AnamAvatarHandle | null>(null);
  const avatarStatusRef = useRef<AvatarStatus>("disconnected");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const speakingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const sessionIdRef = useRef<string | null>(null);
  const sendMessageRef = useRef<((text: string) => Promise<void>) | null>(null);
  const mountedRef = useRef(true);

  // Track mounted state to prevent post-unmount setState
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Keep avatarStatusRef in sync with avatarStatus state
  useEffect(() => {
    avatarStatusRef.current = avatarStatus;
  }, [avatarStatus]);

  // Auto-scroll transcript
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isProcessing]);

  // Initialize Anam avatar
  const initAvatar = useCallback(async () => {
    setAvatarStatus("connecting");
    try {
      const { session_token } = await api.getAnamSession();
      if (!mountedRef.current) return;

      const handle = await initAnamAvatar(session_token, "anam-avatar-video");
      if (!mountedRef.current) {
        handle.disconnect();
        return;
      }

      avatarRef.current = handle;
      setAvatarStatus("connected");
    } catch (err) {
      if (mountedRef.current) {
        console.error("Anam init error:", err);
        setAvatarStatus("error");
      }
    }
  }, []);

  // Auto-init on mount
  useEffect(() => {
    initAvatar();
    return () => {
      avatarRef.current?.disconnect();
      avatarRef.current = null;
    };
  }, [initAvatar]);

  // Cleanup mic on unmount
  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (speakingTimerRef.current) clearTimeout(speakingTimerRef.current);
    };
  }, []);

  // ─── Send message and get avatar response ──────────────────────────────────

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isProcessing) return;
      setChatError(null);

      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: text.trim(),
        timestamp: new Date(),
      };
      onNewMessage(userMsg);
      setIsProcessing(true);

      try {
        // 1. Send to orchestrator
        const res = await api.chat(text.trim(), sessionIdRef.current ?? undefined);
        if (res.session_id) sessionIdRef.current = res.session_id;

        const assistantMsg: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: res.message,
          timestamp: new Date(),
        };
        onNewMessage(assistantMsg);
        onCharacterUpdate(res.character_state);

        if (res.ready && res.workflow) {
          onWorkflowReady(res.workflow);
        }

        // 2. Send response to avatar for lip-sync (if connected)
        if (avatarRef.current && avatarStatusRef.current === "connected" && res.message) {
          try {
            setIsSpeaking(true);
            const pcmAudio = await api.synthesizePcmAudio(res.message);
            if (pcmAudio.byteLength > 0) {
              avatarRef.current.sendPcmAudio(pcmAudio);
              avatarRef.current.endSequence();
            }
          } catch (err) {
            console.error("Avatar audio error:", err);
          } finally {
            // Approximate speech duration: ~100ms per word
            const wordCount = res.message.split(/\s+/).length;
            const duration = Math.max(1000, wordCount * 100);
            if (speakingTimerRef.current) clearTimeout(speakingTimerRef.current);
            speakingTimerRef.current = setTimeout(() => {
              if (mountedRef.current) setIsSpeaking(false);
            }, duration);
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setChatError(msg);
      } finally {
        setIsProcessing(false);
      }
    },
    [isProcessing, onNewMessage, onWorkflowReady, onCharacterUpdate, setIsProcessing]
  );

  // Keep sendMessageRef in sync so onstop closure is never stale
  useEffect(() => {
    sendMessageRef.current = sendMessage;
  }, [sendMessage]);

  // ─── Text input handlers ───────────────────────────────────────────────────

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = inputText.trim();
    if (!text) return;
    setInputText("");
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const text = inputText.trim();
      if (!text) return;
      setInputText("");
      sendMessage(text);
    }
  };

  // ─── Voice recording ──────────────────────────────────────────────────────

  const startRecording = useCallback(async () => {
    if (isProcessing) return;
    setChatError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm",
      });
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        if (blob.size === 0) return; // Guard: instant tap produces empty blob
        try {
          const text = await api.transcribeAudio(blob);
          if (text && sendMessageRef.current) {
            await sendMessageRef.current(text);
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          setChatError(`Transcription failed: ${msg}`);
        }
      };

      recorder.start(200);
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setChatError(`Mic error: ${msg}`);
    }
  }, [isProcessing]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  }, []);

  // ─── Workflow execution ────────────────────────────────────────────────────

  const handleRunWorkflow = async () => {
    const workflow = currentWorkflow; // Snapshot to prevent null during async
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

      const xpMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: xpContent,
        timestamp: new Date(),
      };
      onNewMessage(xpMsg);

      // Level-up flash effect
      if (didLevelUp) {
        setLevelUpFlash(true);
      }

      // Have avatar speak the result
      if (avatarRef.current && avatarStatusRef.current === "connected") {
        try {
          setIsSpeaking(true);
          const pcm = await api.synthesizePcmAudio(xpContent);
          if (pcm.byteLength > 0) {
            avatarRef.current.sendPcmAudio(pcm);
            avatarRef.current.endSequence();
          }
          const wordCount = xpContent.split(/\s+/).length;
          const duration = Math.max(1500, wordCount * 120);
          if (speakingTimerRef.current) clearTimeout(speakingTimerRef.current);
          speakingTimerRef.current = setTimeout(() => {
            if (mountedRef.current) setIsSpeaking(false);
          }, duration);
        } catch {
          // non-critical
        }
      }
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
      const errMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Execution error: ${msg}`,
        timestamp: new Date(),
      };
      onNewMessage(errMsg);
    } finally {
      setIsExecuting(false);
    }
  };

  // ─── Status indicator ─────────────────────────────────────────────────────

  const statusConfig = {
    disconnected: { color: "bg-gray-500", label: "Disconnected" },
    connecting: { color: "bg-yellow-500 animate-pulse", label: "Connecting..." },
    connected: { color: "bg-emerald-500", label: "Avatar Active" },
    error: { color: "bg-red-500", label: "Connection Error" },
  };
  const status = statusConfig[avatarStatus];

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

        {/* Connecting overlay */}
        {avatarStatus !== "connected" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-950/80 backdrop-blur-sm">
            {avatarStatus === "connecting" && (
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
            {avatarStatus === "error" && (
              <div className="text-center px-6">
                <div className="w-16 h-16 rounded-full bg-red-600/20 border border-red-500/30 flex items-center justify-center mx-auto mb-3">
                  <span className="text-2xl">!</span>
                </div>
                <p className="text-red-400 text-sm font-medium">Avatar connection failed</p>
                <p className="text-gray-500 text-xs mt-1">You can still chat below. Voice and text work without the avatar.</p>
                <button
                  onClick={initAvatar}
                  className="mt-3 px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition-colors"
                >
                  Retry Connection
                </button>
              </div>
            )}
            {avatarStatus === "disconnected" && (
              <p className="text-gray-500 text-sm">Initializing avatar...</p>
            )}
          </div>
        )}

        {/* Status badge */}
        <div className="absolute top-3 left-3 flex items-center gap-2 bg-gray-900/80 backdrop-blur rounded-full px-3 py-1.5">
          <div className={`w-2 h-2 rounded-full ${status.color}`} />
          <span className="text-xs text-gray-300">{status.label}</span>
        </div>

        {/* Speaking indicator */}
        <AnimatePresence>
          {isSpeaking && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-indigo-600/80 backdrop-blur rounded-full px-3 py-1.5"
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

        {/* Transcript toggle */}
        <button
          onClick={() => setShowTranscript((v) => !v)}
          className="absolute top-3 right-3 bg-gray-900/80 backdrop-blur rounded-full p-2 text-gray-400 hover:text-white transition-colors"
          title={showTranscript ? "Hide transcript" : "Show transcript"}
        >
          <svg viewBox="0 0 20 20" className="w-4 h-4" fill="currentColor">
            <path d="M2 5a2 2 0 012-2h12a2 2 0 012 2v6a2 2 0 01-2 2H6l-4 4V5z" />
          </svg>
        </button>

        {/* Transcript overlay */}
        <AnimatePresence>
          {showTranscript && messages.length > 0 && (
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className="absolute top-12 right-3 bottom-14 w-72 bg-gray-950/85 backdrop-blur-md rounded-xl border border-gray-800 overflow-hidden flex flex-col"
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
                {isProcessing && (
                  <div className="text-xs text-gray-500 flex items-center gap-1">
                    <span className="font-medium">Flow:</span>
                    <motion.span
                      animate={{ opacity: [0.3, 1, 0.3] }}
                      transition={{ duration: 1.5, repeat: Infinity }}
                    >
                      thinking...
                    </motion.span>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Error display */}
      <AnimatePresence>
        {chatError && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="px-4 py-2 bg-red-950/60 border-t border-red-800 text-red-400 text-xs"
          >
            {chatError}
            <button className="ml-2 underline" onClick={() => setChatError(null)}>
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
            className="px-4 py-2.5 border-t border-gray-700 bg-indigo-950/30 flex items-center gap-3 shrink-0"
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

      {/* Input area */}
      <div className="px-3 pb-3 pt-2 border-t border-gray-800 shrink-0">
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          {/* Voice button */}
          <motion.button
            type="button"
            onPointerDown={(e) => { e.preventDefault(); startRecording(); }}
            onPointerUp={(e) => { e.preventDefault(); stopRecording(); }}
            onPointerLeave={(e) => { e.preventDefault(); stopRecording(); }}
            onPointerCancel={(e) => { e.preventDefault(); stopRecording(); }}
            whileTap={{ scale: 0.88 }}
            disabled={isProcessing}
            className={`w-12 h-12 rounded-full flex items-center justify-center select-none touch-none transition-colors shrink-0 ${
              isRecording
                ? "bg-red-600 recording-pulse"
                : "bg-gray-700 hover:bg-indigo-700 disabled:opacity-50"
            }`}
            title="Hold to record voice"
          >
            <svg viewBox="0 0 20 20" className="w-5 h-5 fill-white" fill="currentColor">
              <path d="M10 1a3 3 0 00-3 3v6a3 3 0 006 0V4a3 3 0 00-3-3z" />
              <path d="M5.5 10a4.5 4.5 0 009 0h-1a3.5 3.5 0 01-7 0h-1zM10 16v3m-2 0h4" stroke="white" strokeWidth="1.5" fill="none" strokeLinecap="round" />
            </svg>
          </motion.button>

          {/* Text input */}
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isRecording ? "Listening... release to send" : "Type or hold mic to speak..."}
            rows={1}
            disabled={isProcessing || isRecording}
            className="flex-1 resize-none bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50 max-h-32"
            style={{ minHeight: "2.5rem" }}
            onInput={(e) => {
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
            }}
          />

          {/* Send button */}
          <motion.button
            type="submit"
            disabled={!inputText.trim() || isProcessing}
            whileTap={{ scale: 0.92 }}
            className="shrink-0 w-12 h-12 rounded-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors"
          >
            <svg viewBox="0 0 20 20" className="w-4 h-4" fill="none">
              <path d="M3 10L17 3l-7 7 7 7-14-7z" stroke="white" strokeWidth="1.5" strokeLinejoin="round" />
            </svg>
          </motion.button>
        </form>

        {isRecording && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center text-red-400 text-xs mt-1.5 font-medium"
          >
            Listening... release to send
          </motion.p>
        )}
      </div>
    </div>
  );
}
