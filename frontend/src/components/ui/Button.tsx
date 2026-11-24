import React from "react";

export type ButtonVariant = "primary" | "approve" | "secondary" | "danger" | "ghost";
export type ButtonSize = "xs" | "sm" | "md";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: React.ReactNode;
}

const VARIANT_MAP: Record<ButtonVariant, string> = {
  primary: "bg-blue-600 hover:bg-blue-700 text-white shadow-xs",
  approve: "bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs",
  secondary: "bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 shadow-xs",
  danger: "bg-rose-50 text-rose-600 border border-rose-200/70 hover:bg-rose-100",
  ghost: "bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900",
};

const SIZE_MAP: Record<ButtonSize, string> = {
  xs: "px-2.5 py-1 text-xs rounded-lg",
  sm: "px-3 py-1.5 text-xs rounded-lg",
  md: "px-4 py-2 text-sm rounded-lg",
};

export function Button({
  variant = "primary",
  size = "sm",
  className = "",
  type = "button",
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none ${VARIANT_MAP[variant]} ${SIZE_MAP[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
