"use client";

/**
 * NotificationBell — bell icon in the header showing unread notification count.
 * Dropdown shows recent errors/warnings with timestamps.
 *
 * V4 Phase 7: Listens to ALL Socket.io alerts. When an alert arrives
 * with a search_id that doesn't match the active search, it increments
 * the notification counter and queues it in the dropdown.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Bell,
  X,
  AlertCircle,
  AlertTriangle,
  Info,
  CheckCircle,
  Search,
} from "lucide-react";
import {
  useNotificationLog,
  type NotificationType,
} from "@/hooks/useNotificationLog";
import { useGraphExplorerStore } from "@/store/useGraphExplorerStore";
import { getSocket } from "@/lib/socket";

interface QueuedAlert {
  id: string;
  summary: string;
  query?: string;
  searchId?: string;
  timestamp: number;
  entityIds: string[];
}

function NotificationIcon({ type }: { type: NotificationType }) {
  switch (type) {
    case "error":
      return <AlertCircle size={14} className="text-red-400" />;
    case "warning":
      return <AlertTriangle size={14} className="text-amber-400" />;
    case "info":
      return <Info size={14} className="text-blue-400" />;
    case "success":
      return <CheckCircle size={14} className="text-emerald-400" />;
  }
}

function timeAgo(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function NotificationBell() {
  const { notifications, dismissNotification, dismissAll, getUnreadCount } =
    useNotificationLog();
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // V4 Phase 7: listen to ALL alerts, queue ones from other searches
  const activeSearchId = useGraphExplorerStore((s) => s.searchId);
  const [alerts, setAlerts] = useState<QueuedAlert[]>([]);
  const alertCounterRef = useRef(0);

  const clearAlerts = useCallback(() => {
    setAlerts([]);
  }, []);

  // Subscribe to all alerts on the shared socket
  useEffect(() => {
    const socket = getSocket();

    const handleAlert = (payload: Record<string, unknown>) => {
      const payloadSearchId =
        typeof payload.search_id === "string" ? payload.search_id : undefined;

      // If activeSearchId matches (or there's no search_id on the alert),
      // the useRealtimeNodes hook handles it — don't queue here.
      if (
        !payloadSearchId ||
        (activeSearchId && payloadSearchId === activeSearchId)
      ) {
        return;
      }

      // Queue alert from a different search
      alertCounterRef.current += 1;
      const entry: QueuedAlert = {
        id: `alert-${alertCounterRef.current}-${Date.now()}`,
        summary:
          typeof payload.summary === "string" && payload.summary
            ? payload.summary
            : "New results available",
        query: typeof payload.query === "string" ? payload.query : undefined,
        searchId: payloadSearchId,
        timestamp: Date.now(),
        entityIds: Array.isArray(payload.entity_ids)
          ? (payload.entity_ids as string[])
          : [],
      };
      setAlerts((prev) => [entry, ...prev].slice(0, 20));
    };

    socket.on("alert", handleAlert);
    return () => {
      socket.off("alert", handleAlert);
    };
  }, [activeSearchId]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  // Show only undismissed notifications in the dropdown
  const activeNotifications = notifications.filter((n) => !n.dismissed);

  // Total unread = regular notifications + alerts from other searches
  const totalUnread = getUnreadCount() + alerts.length;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => {
          setOpen(!open);
          if (!open) {
            // Clear alerts when opening the dropdown
            clearAlerts();
          }
        }}
        className="relative p-1.5 text-slate-400 hover:text-slate-200 transition-colors"
        aria-label={`Notifications (${totalUnread} unread)`}
      >
        <Bell size={16} />
        {totalUnread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex items-center justify-center w-4 h-4 text-[9px] font-bold text-white bg-red-500 rounded-full">
            {totalUnread > 9 ? "9+" : totalUnread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-80 max-h-96 overflow-y-auto bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700">
            <span className="text-xs font-semibold text-slate-300">
              Notifications
            </span>
            {activeNotifications.length > 0 && (
              <button
                onClick={dismissAll}
                className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
              >
                Dismiss all
              </button>
            )}
          </div>

          {/* List */}
          {activeNotifications.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-slate-500">
              No notifications
            </div>
          ) : (
            <div className="divide-y divide-slate-800">
              {activeNotifications.map((n) => (
                <div
                  key={n.id}
                  className="flex items-start gap-2 px-3 py-2 hover:bg-slate-800/50 transition-colors"
                >
                  <div className="mt-0.5 flex-shrink-0">
                    <NotificationIcon type={n.type} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-slate-300 leading-relaxed">
                      {n.message}
                    </p>
                    <span className="text-[10px] text-slate-500">
                      {timeAgo(n.timestamp)}
                    </span>
                  </div>
                  <button
                    onClick={() => dismissNotification(n.id)}
                    className="flex-shrink-0 text-slate-600 hover:text-slate-300 transition-colors"
                    aria-label="Dismiss"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
