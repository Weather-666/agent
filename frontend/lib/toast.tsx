"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type ToastVariant = "success" | "error" | "info";

type ToastItem = {
  id: number;
  variant: ToastVariant;
  message: string;
};

type ToastApi = {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

const AUTO_DISMISS_MS = 3200;

// 模块级全局入口：供非组件代码（如 axios 拦截器、api 层、工具函数）直接调用。
// ToastProvider 挂载时会把真正的实现注册进来；未挂载时的调用会被安全忽略。
let activeToastApi: ToastApi | null = null;

export const toast: ToastApi = {
  success: (message) => activeToastApi?.success(message),
  error: (message) => activeToastApi?.error(message),
  info: (message) => activeToastApi?.info(message),
};

const variantStyles: Record<ToastVariant, string> = {
  success: "border-[#bfe6c9] bg-[#eaf7ee] text-[#237a38]",
  error: "border-[#f2c9c9] bg-[#fff4f4] text-[#b42318]",
  info: "border-[#d6dbe6] bg-white text-[#1f2937]",
};

function ToastIcon({ variant }: { variant: ToastVariant }) {
  const common = {
    viewBox: "0 0 24 24",
    className: "mt-0.5 h-4 w-4 shrink-0",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.9,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  if (variant === "success") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="m8.5 12.5 2.5 2.5 4.5-5" />
      </svg>
    );
  }

  if (variant === "error") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v5" />
        <path d="M12 16h.01" />
      </svg>
    );
  }

  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <path d="M12 8h.01" />
    </svg>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const idRef = useRef(0);
  const timersRef = useRef<Record<number, ReturnType<typeof setTimeout>>>({});

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
    const timer = timersRef.current[id];
    if (timer) {
      clearTimeout(timer);
      delete timersRef.current[id];
    }
  }, []);

  const push = useCallback(
    (variant: ToastVariant, message: string) => {
      if (!message) return;
      idRef.current += 1;
      const id = idRef.current;
      setToasts((prev) => [...prev, { id, variant, message }]);
      timersRef.current[id] = setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss]
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (message) => push("success", message),
      error: (message) => push("error", message),
      info: (message) => push("info", message),
    }),
    [push]
  );

  useEffect(() => {
    activeToastApi = api;
    return () => {
      if (activeToastApi === api) activeToastApi = null;
    };
  }, [api]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[9999] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((item) => (
          <div
            key={item.id}
            role="status"
            aria-live="polite"
            className={`ww-toast-enter pointer-events-auto flex items-start gap-2.5 rounded-[10px] border px-3.5 py-3 text-sm shadow-[0_12px_28px_rgba(17,24,39,0.16)] ${variantStyles[item.variant]}`}
          >
            <ToastIcon variant={item.variant} />
            <span className="min-w-0 flex-1 break-words leading-5">{item.message}</span>
            <button
              type="button"
              onClick={() => dismiss(item.id)}
              className="shrink-0 opacity-50 transition hover:opacity-90"
              aria-label="关闭"
            >
              <svg
                viewBox="0 0 24 24"
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.9"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          </div>
        ))}
      </div>
      <style>{`
        @keyframes wwToastEnter {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .ww-toast-enter { animation: wwToastEnter 180ms ease-out; }
      `}</style>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
