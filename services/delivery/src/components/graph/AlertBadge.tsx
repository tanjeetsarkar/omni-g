"use client";

/**
 * AlertBadge — animated badge showing count of incoming alerts (M5.2).
 *
 * Props:
 *   count: number of active alerts
 *
 * - count > 0: pulsing red dot with count
 * - count === 0: grey "No alerts" indicator
 */

interface AlertBadgeProps {
  count: number;
}

export default function AlertBadge({ count }: AlertBadgeProps) {
  if (count === 0) {
    return (
      <div className="flex items-center gap-2 text-slate-400 text-sm">
        <span className="inline-block w-2 h-2 rounded-full bg-slate-600" />
        <span>No alerts</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-red-400 text-sm font-medium">
      <span
        className="inline-block w-3 h-3 rounded-full bg-red-500 animate-pulse"
        aria-hidden="true"
      />
      <span>
        {count} alert{count !== 1 ? "s" : ""}
      </span>
    </div>
  );
}
