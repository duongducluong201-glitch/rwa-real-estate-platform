"use client";

import React, { useState } from "react";
import { Copy, Check } from "lucide-react";

interface CopyAddressProps {
  value?: string | null;
  address?: string | null;
  chars?: number;
  prefixLen?: number;
  suffixLen?: number;
  className?: string;
  textClassName?: string;
}

export function CopyAddress({
  value,
  address,
  chars,
  prefixLen,
  suffixLen,
  className = "",
  textClassName = "text-xs text-slate-500",
}: CopyAddressProps) {
  const [copied, setCopied] = useState(false);
  const resolvedValue = value ?? address;
  const pLen = prefixLen ?? (chars ? chars + 2 : 6);
  const sLen = suffixLen ?? (chars ?? 4);

  if (!resolvedValue) {
    return <span className="font-mono text-xs text-slate-400">—</span>;
  }

  const clean = String(resolvedValue).trim();
  const display =
    clean.length > pLen + sLen + 3
      ? `${clean.slice(0, pLen)}...${clean.slice(-sLen)}`
      : clean;

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    navigator.clipboard?.writeText(clean);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <span className={`relative inline-flex items-center gap-1 whitespace-nowrap font-mono ${className}`}>
      <span title={clean} className={`tabular-nums ${textClassName}`}>
        {display}
      </span>
      <button
        type="button"
        onClick={handleCopy}
        title={copied ? "Đã sao chép" : "Sao chép"}
        className="p-0.5 rounded text-slate-400 hover:text-blue-600 hover:bg-slate-100 transition-colors"
      >
        {copied ? (
          <Check className="w-3.5 h-3.5 text-emerald-600" strokeWidth={1.75} />
        ) : (
          <Copy className="w-3.5 h-3.5" strokeWidth={1.75} />
        )}
      </button>
      {copied && (
        <span className="pointer-events-none absolute -top-7 left-1/2 -translate-x-1/2 z-50 rounded-md bg-slate-900 px-2 py-0.5 font-sans text-[10px] font-medium text-white shadow-md whitespace-nowrap">
          Đã sao chép
        </span>
      )}
    </span>
  );
}
