"use client";

import React, { useEffect, useState, useRef } from "react";
import {
  Bell,
  CheckCheck,
  ShieldCheck,
  AlertTriangle,
  Coins,
  Info,
  Copy,
  Check,
  ArrowLeftRight,
} from "lucide-react";
import { useWeb3 } from "@/context/Web3Context";
import { useLanguage } from "@/context/LanguageContext";

interface NotificationItem {
  id: number;
  category: string;
  title: string;
  message: string;
  tx_hash?: string | null;
  is_read: boolean;
  created_at?: string | null;
}

export function NotificationBell() {
  const { currentUser, isAuthenticated, apiFetch } = useWeb3();
  const { lang, t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const activeAddress = isAuthenticated && currentUser?.address ? currentUser.address : "";

  const loadNotifications = async () => {
    if (!activeAddress) {
      setOpen(false);
      setItems([]);
      setUnread(0);
      return;
    }
    try {
      const data = await apiFetch("/notifications?limit=20");
      setItems(Array.isArray(data?.items) ? data.items : []);
      setUnread(Number(data?.unread_count || 0));
    } catch {
      // Im lặng khi backend chưa sẵn sàng
    }
  };

  useEffect(() => {
    const clearNotifState = () => {
      setOpen(false);
      setItems([]);
      setUnread(0);
      setCopiedId(null);
    };

    window.addEventListener("rwa:session-cleared", clearNotifState);

    if (!activeAddress) {
      clearNotifState();
      return () => {
        window.removeEventListener("rwa:session-cleared", clearNotifState);
      };
    }

    loadNotifications();
    const timer = setInterval(loadNotifications, 5000);
    const onRefresh = () => loadNotifications();
    const onVisibility = () => {
      if (document.visibilityState === "visible") loadNotifications();
    };
    window.addEventListener("focus", onRefresh);
    window.addEventListener("rwa:notifications-updated", onRefresh);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(timer);
      window.removeEventListener("rwa:session-cleared", clearNotifState);
      window.removeEventListener("focus", onRefresh);
      window.removeEventListener("rwa:notifications-updated", onRefresh);
      document.removeEventListener("visibilitychange", onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAddress]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const markRead = async (id: number) => {
    try {
      await apiFetch(`/notifications/${id}/read`, { method: "POST" });
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, is_read: true } : it)));
      setUnread((prev) => Math.max(0, prev - 1));
    } catch {}
  };

  const markAllRead = async () => {
    try {
      await apiFetch("/notifications/read-all", { method: "POST" });
      setItems((prev) => prev.map((it) => ({ ...it, is_read: true })));
      setUnread(0);
    } catch {}
  };

  const copyTx = (id: number, tx: string) => {
    navigator.clipboard?.writeText(tx);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const renderIcon = (cat: string) => {
    if (cat === "transfer")
      return <ArrowLeftRight className="w-4 h-4 text-emerald-600 shrink-0" strokeWidth={1.75} />;
    if (cat === "kyc")
      return <ShieldCheck className="w-4 h-4 text-blue-600 shrink-0" strokeWidth={1.75} />;
    if (cat === "freeze")
      return <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" strokeWidth={1.75} />;
    if (cat === "dividend")
      return <Coins className="w-4 h-4 text-emerald-600 shrink-0" strokeWidth={1.75} />;
    return <Info className="w-4 h-4 text-slate-500 shrink-0" strokeWidth={1.75} />;
  };

  const formatNotifTime = (iso?: string | null) => {
    if (!iso) return "";
    const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
    const d = new Date(normalized);
    return isNaN(d.getTime()) ? iso : d.toLocaleString(lang === "en" ? "en-US" : "vi-VN");
  };

  if (!isAuthenticated || !currentUser || !activeAddress) {
    return null;
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          if (!open) loadNotifications();
        }}
        title={t("notif.title")}
        className="relative inline-flex items-center justify-center w-8 h-8 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 shadow-xs transition-colors"
      >
        <Bell className="w-4 h-4" strokeWidth={1.75} />
        {unread > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-600 text-white text-[10px] font-semibold tabular-nums flex items-center justify-center shadow-xs">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 sm:w-96 bg-white border border-slate-200/80 rounded-xl shadow-lg z-50 overflow-hidden">
          <div className="px-4 py-3 bg-slate-50/80 border-b border-slate-200/80 flex items-center justify-between">
            <div className="text-xs font-semibold text-slate-900 tabular-nums">
              {t("notif.header")} ({unread} {t("notif.unread")})
            </div>
            {unread > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 transition-colors"
              >
                <CheckCheck className="w-3.5 h-3.5" strokeWidth={1.75} />
                <span>{t("notif.markAll")}</span>
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto divide-y divide-slate-100">
            {items.length === 0 ? (
              <div className="px-4 py-8 text-center text-xs text-slate-500">
                {t("notif.empty")}
              </div>
            ) : (
              items.map((item) => (
                <div
                  key={item.id}
                  onClick={() => !item.is_read && markRead(item.id)}
                  className={`px-4 py-3 text-xs cursor-pointer transition-colors hover:bg-slate-50/80 ${
                    !item.is_read ? "bg-blue-50/40" : "bg-white"
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    <div className="mt-0.5">{renderIcon(item.category)}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <p className={`font-medium text-slate-900 ${!item.is_read ? "font-semibold" : ""}`}>
                          {item.title}
                        </p>
                        {!item.is_read && <span className="w-2 h-2 rounded-full bg-blue-600 shrink-0" />}
                      </div>
                      <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{item.message}</p>
                      <div className="flex items-center justify-between gap-2 mt-1.5">
                        <span className="text-[11px] text-slate-400 tabular-nums">
                          {formatNotifTime(item.created_at)}
                        </span>
                        {item.tx_hash && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              copyTx(item.id, item.tx_hash!);
                            }}
                            title={copiedId === item.id ? "Đã sao chép" : item.tx_hash}
                            className="inline-flex items-center gap-1 font-mono text-[11px] text-blue-600 hover:text-blue-700"
                          >
                            {copiedId === item.id ? (
                              <>
                                <Check className="w-3 h-3 text-emerald-600" strokeWidth={1.75} />
                                <span className="font-sans text-emerald-600 font-medium">Đã sao chép</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3 h-3" strokeWidth={1.75} />
                                <span>{item.tx_hash.slice(0, 10)}...</span>
                              </>
                            )}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
