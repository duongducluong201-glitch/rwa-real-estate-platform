"use client";

import React from "react";
import { Globe } from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";

export function LanguageSwitcher() {
  const { lang, setLang } = useLanguage();

  return (
    <div
      data-no-i18n="true"
      className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-100/80 p-0.5 text-xs font-medium"
      title={
        lang === "vi"
          ? "Chuyển ngôn ngữ Tiếng Việt / English"
          : "Switch Language Vietnamese / English"
      }
    >
      <Globe className="w-3.5 h-3.5 text-slate-500 ml-1.5 mr-1 hidden sm:block" strokeWidth={1.75} />
      <button
        type="button"
        onClick={() => setLang("vi")}
        className={`px-2 py-1 rounded-md text-[11px] font-semibold transition-colors ${
          lang === "vi"
            ? "bg-white text-slate-900 shadow-xs"
            : "text-slate-500 hover:text-slate-900"
        }`}
      >
        VI
      </button>
      <button
        type="button"
        onClick={() => setLang("en")}
        className={`px-2 py-1 rounded-md text-[11px] font-semibold transition-colors ${
          lang === "en"
            ? "bg-white text-slate-900 shadow-xs"
            : "text-slate-500 hover:text-slate-900"
        }`}
      >
        EN
      </button>
    </div>
  );
}
