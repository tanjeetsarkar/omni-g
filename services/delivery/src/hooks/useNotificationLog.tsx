"use client";

/**
 * useNotificationLog — React Context provider for persistent error/notification logging.
 *
 * Ring buffer (max 50 entries) of {id, type, message, timestamp, dismissed}.
 * Provides pushNotification(), dismissAll(), getUnreadCount().
 */

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
} from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type NotificationType = "error" | "warning" | "info" | "success";

export interface NotificationEntry {
  id: string;
  type: NotificationType;
  message: string;
  timestamp: number;
  dismissed: boolean;
}

interface NotificationContextValue {
  notifications: NotificationEntry[];
  pushNotification: (type: NotificationType, message: string) => void;
  dismissNotification: (id: string) => void;
  dismissAll: () => void;
  getUnreadCount: () => number;
}

const MAX_NOTIFICATIONS = 50;

// ─── Context ──────────────────────────────────────────────────────────────────

const NotificationContext = createContext<NotificationContextValue | null>(
  null,
);

// ─── Provider ─────────────────────────────────────────────────────────────────

export function NotificationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [notifications, setNotifications] = useState<NotificationEntry[]>([]);
  const counterRef = useRef(0);

  const pushNotification = useCallback(
    (type: NotificationType, message: string) => {
      counterRef.current += 1;
      const entry: NotificationEntry = {
        id: `notif-${counterRef.current}-${Date.now()}`,
        type,
        message,
        timestamp: Date.now(),
        dismissed: false,
      };
      setNotifications((prev) => {
        const updated = [entry, ...prev].slice(0, MAX_NOTIFICATIONS);
        return updated;
      });
    },
    [],
  );

  const dismissNotification = useCallback((id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, dismissed: true } : n)),
    );
  }, []);

  const dismissAll = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, dismissed: true })));
  }, []);

  const getUnreadCount = useCallback((): number => {
    return notifications.filter((n) => !n.dismissed).length;
  }, [notifications]);

  const value: NotificationContextValue = {
    notifications,
    pushNotification,
    dismissNotification,
    dismissAll,
    getUnreadCount,
  };

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useNotificationLog(): NotificationContextValue {
  const ctx = useContext(NotificationContext);
  if (!ctx) {
    throw new Error(
      "useNotificationLog must be used within a NotificationProvider",
    );
  }
  return ctx;
}
