import React from "react";

export type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral" | "purple";

interface StatusBadgeProps {
  variant?: BadgeVariant;
  dot?: boolean;
  children: React.ReactNode;
  className?: string;
  title?: string;
}

const VARIANT_CLASSES: Record<BadgeVariant, { pill: string; dot: string }> = {
  success: {
    pill: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    dot: "bg-emerald-500",
  },
  warning: {
    pill: "bg-amber-50 text-amber-700 ring-amber-600/20",
    dot: "bg-amber-500",
  },
  danger: {
    pill: "bg-rose-50 text-rose-700 ring-rose-600/20",
    dot: "bg-rose-500",
  },
  info: {
    pill: "bg-blue-50 text-blue-700 ring-blue-600/20",
    dot: "bg-blue-500",
  },
  neutral: {
    pill: "bg-slate-100 text-slate-700 ring-slate-500/20",
    dot: "bg-slate-400",
  },
  purple: {
    pill: "bg-violet-50 text-violet-700 ring-violet-600/20",
    dot: "bg-violet-500",
  },
};

export function StatusBadge({
  variant = "neutral",
  dot = false,
  children,
  className = "",
  title,
}: StatusBadgeProps) {
  const styles = VARIANT_CLASSES[variant] || VARIANT_CLASSES.neutral;
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${styles.pill} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${styles.dot}`} />}
      {children}
    </span>
  );
}
