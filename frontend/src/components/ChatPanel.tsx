"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { Message, WorkflowDefinition, CharacterState } from "@/types";
import * as api from "@/lib/api";

// ─── Suggestion chips ────────────────────────────────────────────────────────

const SUGGESTION_PROMPTS = [
  { icon: "📰", text: "Send me a daily news summary" },
  { icon: "📧", text: "When I get an email, forward to Slack" },
  { icon: "🌤", text: "Check weather and post to my team" },
];

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

export default function ChatPanel({
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
  const [inputText, setInputText] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [recordingError, setRecordingError] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isProcessing]);

  // Cleanup MediaRecorder and mic on unmount
  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // ─── Text send ──────────────────────────────────────────────────────────────

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
        const res = await api.chat(text.trim(), sessionId ?? undefined);

        // Persist session_id returned by backend for subsequent messages
        if (res.session_id) {
          setSessionId(res.session_id);
        }

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
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setChatError(msg);
      } finally {
        setIsProcessing(false);
      }
    },
    [isProcessing, sessionId, onNewMessage, onWorkflowReady, onCharacterUpdate, setIsProcessing]
  );

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

  // ─── Voice recording ────────────────────────────────────────────────────────

  const startRecording = useCallback(async () => {
    if (isProcessing) return; // Prevent recording while processing
    setRecordingError(null);
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
        setIsProcessing(true);
        try {
          const text = await api.transcribeAudio(blob);
          if (text) {
            await sendMessage(text);
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          setRecordingError(`Transcription failed: ${msg}`);
        } finally {
          setIsProcessing(false);
        }
      };

      recorder.start(200);
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setRecordingError(`Mic error: ${msg}`);
    }
  }, [isProcessing, sendMessage, setIsProcessing]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  }, []);

  const handleVoicePointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    startRecording();
  };

  const handleVoicePointerUp = (e: React.PointerEvent) => {
    e.preventDefault();
    stopRecording();
  };

  // ─── Workflow execution ─────────────────────────────────────────────────────

  const handleRunWorkflow = async () => {
    if (!currentWorkflow || isExecuting) return;
    setIsExecuting(true);
    onExecutionStart();

    try {
      const result = await api.executeWorkflow(currentWorkflow);
      onExecutionComplete(result);
      onCharacterUpdate(result.character_state);

      const xpMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Workflow executed! +${result.xp_result.xp_earned ?? 0} XP earned${
          result.xp_result.level_up ? ` — LEVEL UP to ${result.xp_result.new_level}!` : ""
        }`,
        timestamp: new Date(),
      };
      onNewMessage(xpMsg);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // Signal execution failure to parent so UI doesn't stay stuck in "running"
      onExecutionComplete({
        execution: {
          id: crypto.randomUUID(),
          workflow: currentWorkflow,
          status: "failed" as const,
          step_results: {},
          created_at: new Date().toISOString(),
        },
        xp_result: { xp_earned: 0, level_up: false },
        character_state: {} as CharacterState,
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

  // ─── Reset ──────────────────────────────────────────────────────────────────

  const handleReset = async () => {
    try {
      await api.resetChat(sessionId ?? undefined);
      setSessionId(null);
      const resetMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "Conversation reset. How can I help you build a new workflow?",
        timestamp: new Date(),
      };
      onNewMessage(resetMsg);
    } catch {
      // ignore
    }
  };

  // ─── Suggestion chip handler ──────────────────────────────────────────────

  const handleChipClick = useCallback(
    (text: string) => {
      if (isProcessing) return;
      sendMessage(text);
    },
    [isProcessing, sendMessage]
  );

  // ─── Render ─────────────────────────────────────────────────────────────────

  const hasOnlyWelcome = messages.length === 1 && messages[0].role === "assistant";

  return (
    <div className="panel flex flex-col h-full min-h-[400px] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
          <span className="font-semibold text-sm text-white">Chat</span>
        </div>
        <button
          onClick={handleReset}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-2 py-1 rounded-lg hover:bg-gray-800"
        >
          Start over
        </button>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {hasOnlyWelcome && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="empty-state"
          >
            {/* Illustration */}
            <div className="w-16 h-16 rounded-2xl bg-indigo-600/15 border border-indigo-500/20 flex items-center justify-center mb-1">
              <svg viewBox="0 0 40 40" className="w-9 h-9 text-indigo-400" fill="none">
                <path d="M8 28 Q6 34 12 32 L14 30" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <rect x="8" y="8" width="24" height="18" rx="5" stroke="currentColor" strokeWidth="1.5" />
                <path d="M14 16 h12 M14 20 h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </div>
            <p className="text-gray-300 font-medium text-sm">What would you like to automate?</p>
            <p className="text-gray-500 text-xs max-w-[220px]">
              Describe any task in plain English and I'll turn it into a workflow.
            </p>
          </motion.div>
        )}

        <AnimatePresence initial={false}>
          {messages.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role === "assistant" && (
                <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center text-xs mr-2 mt-1 shrink-0">
                  K
                </div>
              )}
              <div
                className={`max-w-[78%] px-3 py-2 text-sm leading-relaxed ${
                  msg.role === "user" ? "bubble-user" : "bubble-assistant"
                }`}
              >
                <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                <p className="text-xs opacity-50 mt-1 text-right">
                  {msg.timestamp.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Typing indicator */}
        {isProcessing && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex justify-start"
          >
            <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center text-xs mr-2 mt-1 shrink-0">
              K
            </div>
            <div className="bubble-assistant px-3 py-2">
              <div className="flex gap-1 items-center h-5">
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    className="w-1.5 h-1.5 bg-gray-400 rounded-full inline-block"
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
                  />
                ))}
              </div>
            </div>
          </motion.div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Error display */}
      <AnimatePresence>
        {(chatError || recordingError) && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="px-4 py-2 bg-red-950/60 border-t border-red-800 text-red-400 text-xs"
          >
            {chatError || recordingError}
            <button
              className="ml-2 underline"
              onClick={() => { setChatError(null); setRecordingError(null); }}
            >
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
                  Running…
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
        {/* Suggestion chips */}
        {!isProcessing && messages.length <= 2 && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex gap-1.5 mb-2 overflow-x-auto pb-0.5 scrollbar-none"
            style={{ scrollbarWidth: "none" }}
          >
            {SUGGESTION_PROMPTS.map((chip) => (
              <button
                key={chip.text}
                type="button"
                onClick={() => handleChipClick(chip.text)}
                className="suggestion-chip shrink-0"
              >
                <span>{chip.icon}</span>
                <span>{chip.text}</span>
              </button>
            ))}
          </motion.div>
        )}

        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          {/* Voice button — larger with label */}
          <div className="tooltip-wrapper shrink-0">
            <motion.button
              type="button"
              onPointerDown={handleVoicePointerDown}
              onPointerUp={handleVoicePointerUp}
              onPointerLeave={handleVoicePointerUp}
              whileTap={{ scale: 0.88 }}
              className={`w-12 h-12 rounded-full flex items-center justify-center select-none touch-none transition-colors ${
                isRecording
                  ? "bg-red-600 recording-pulse"
                  : "bg-gray-700 hover:bg-indigo-700"
              }`}
              title="Hold to record voice"
            >
              <svg viewBox="0 0 20 20" className="w-5 h-5 fill-white" fill="currentColor">
                <path d="M10 1a3 3 0 00-3 3v6a3 3 0 006 0V4a3 3 0 00-3-3z" />
                <path d="M5.5 10a4.5 4.5 0 009 0h-1a3.5 3.5 0 01-7 0h-1zM10 16v3m-2 0h4" stroke="white" strokeWidth="1.5" fill="none" strokeLinecap="round" />
              </svg>
            </motion.button>
            <span className="tooltip-label">{isRecording ? "Release" : "Hold to talk"}</span>
          </div>

          {/* Text area */}
          <textarea
            ref={inputRef}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isRecording
                ? "Listening… release to send"
                : "What would you like to automate? Try speaking or typing..."
            }
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
            <svg viewBox="0 0 20 20" className="w-4.5 h-4.5" fill="none">
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
            Listening… release to send your message
          </motion.p>
        )}
      </div>
    </div>
  );
}
