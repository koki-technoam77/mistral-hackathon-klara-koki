"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import * as api from "@/lib/api";

interface ConnectionInfo {
  app: string;
  status: "active" | "not_connected" | "not_configured";
  connected_account_id: string | null;
}

const APP_DISPLAY: Record<string, { name: string; icon: string; color: string }> = {
  gmail: { name: "Gmail", icon: "✉️", color: "text-red-400" },
  googlecalendar: { name: "Google Calendar", icon: "📅", color: "text-blue-400" },
  slack: { name: "Slack", icon: "💬", color: "text-purple-400" },
  todoist: { name: "Todoist", icon: "✅", color: "text-orange-400" },
};

interface Props {
  sessionId: string;
}

export default function ConnectionsPanel({ sessionId }: Props) {
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadConnections = useCallback(async () => {
    try {
      const data = await api.getComposioConnections(sessionId);
      setConnections(data.connections);
    } catch {
      setError("Failed to load connections");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    loadConnections();
  }, [loadConnections]);

  const handleConnect = async (appName: string) => {
    setConnecting(appName);
    setError(null);
    try {
      const callbackUrl = `${window.location.origin}`;
      const result = await api.initiateComposioConnection(appName, callbackUrl, sessionId);
      if (result.redirect_url) {
        // Open OAuth in new tab
        window.open(result.redirect_url, "_blank", "noopener,noreferrer");
        // Poll for connection status
        pollConnectionStatus(appName);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
      setConnecting(null);
    }
  };

  const pollConnectionStatus = (appName: string) => {
    let attempts = 0;
    const maxAttempts = 30; // 30 * 2s = 60s timeout
    const interval = setInterval(async () => {
      attempts++;
      try {
        const status = await api.getComposioConnectionStatus(appName, sessionId);
        if (status.status === "active") {
          clearInterval(interval);
          setConnecting(null);
          loadConnections(); // Refresh all
        }
      } catch {
        // ignore polling errors
      }
      if (attempts >= maxAttempts) {
        clearInterval(interval);
        setConnecting(null);
        setError(`Connection timeout for ${appName}. Please try again.`);
      }
    }, 2000);
  };

  if (loading) {
    return (
      <div className="p-4 text-center text-gray-500 text-sm">
        Loading connections...
      </div>
    );
  }

  return (
    <div className="p-3">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-300">Connected Services</h3>
        <button
          onClick={loadConnections}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          Refresh
        </button>
      </div>

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-3 px-3 py-2 bg-red-950/60 border border-red-800 rounded-lg text-red-400 text-xs"
          >
            {error}
            <button className="ml-2 underline" onClick={() => setError(null)}>dismiss</button>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="grid grid-cols-2 gap-2">
        {connections.map((conn) => {
          const display = APP_DISPLAY[conn.app] || { name: conn.app, icon: "🔗", color: "text-gray-400" };
          const isConnecting = connecting === conn.app;
          const isConnected = conn.status === "active";

          return (
            <motion.div
              key={conn.app}
              layout
              className={`relative p-3 rounded-xl border transition-colors ${
                isConnected
                  ? "bg-green-950/20 border-green-800/50"
                  : "bg-gray-900/50 border-gray-800 hover:border-gray-700"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="text-lg">{display.icon}</span>
                <span className={`text-sm font-medium ${display.color}`}>{display.name}</span>
              </div>

              {isConnected ? (
                <div className="flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  <span className="text-xs text-emerald-400">Connected</span>
                </div>
              ) : conn.status === "not_configured" ? (
                <span className="text-xs text-gray-600">Not configured</span>
              ) : (
                <button
                  onClick={() => handleConnect(conn.app)}
                  disabled={isConnecting}
                  className="text-xs px-2.5 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors"
                >
                  {isConnecting ? (
                    <span className="flex items-center gap-1">
                      <motion.span
                        animate={{ rotate: 360 }}
                        transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                        className="inline-block"
                      >
                        ⟳
                      </motion.span>
                      Waiting...
                    </span>
                  ) : (
                    "Connect"
                  )}
                </button>
              )}
            </motion.div>
          );
        })}
      </div>

      {connections.every(c => c.status === "not_configured") && (
        <p className="text-xs text-gray-600 mt-3 text-center">
          Set COMPOSIO_API_KEY in backend to enable service connections.
        </p>
      )}
    </div>
  );
}
