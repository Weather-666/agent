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
import { useI18n } from "@/lib/i18n";

type ConfirmOptions = {
  message: string;
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
};

type PromptOptions = {
  message?: string;
  title?: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  cancelLabel?: string;
};

type DialogApi = {
  confirm: (options: ConfirmOptions | string) => Promise<boolean>;
  prompt: (options: PromptOptions | string) => Promise<string | null>;
};

const DialogContext = createContext<DialogApi | null>(null);

type ConfirmState = ConfirmOptions & {
  kind: "confirm";
  resolve: (value: boolean) => void;
};

type PromptState = PromptOptions & {
  kind: "prompt";
  resolve: (value: string | null) => void;
};

type DialogState = ConfirmState | PromptState;

export function DialogProvider({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [promptValue, setPromptValue] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const confirm = useCallback<DialogApi["confirm"]>((options) => {
    const opts = typeof options === "string" ? { message: options } : options;
    return new Promise<boolean>((resolve) => {
      setDialog({ kind: "confirm", ...opts, resolve });
    });
  }, []);

  const prompt = useCallback<DialogApi["prompt"]>((options) => {
    const opts = typeof options === "string" ? { message: options } : options;
    setPromptValue(opts.defaultValue ?? "");
    return new Promise<string | null>((resolve) => {
      setDialog({ kind: "prompt", ...opts, resolve });
    });
  }, []);

  const close = useCallback(
    (result: boolean | string | null) => {
      setDialog((current) => {
        if (!current) return null;
        if (current.kind === "confirm") current.resolve(Boolean(result));
        else current.resolve(typeof result === "string" ? result : null);
        return null;
      });
    },
    []
  );

  useEffect(() => {
    if (!dialog) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close(dialog.kind === "prompt" ? null : false);
    };

    document.addEventListener("keydown", onKeyDown);
    if (dialog.kind === "prompt") {
      queueMicrotask(() => inputRef.current?.focus());
    }

    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [dialog, close]);

  const api = useMemo<DialogApi>(() => ({ confirm, prompt }), [confirm, prompt]);

  const isDanger = dialog?.kind === "confirm" && dialog.tone === "danger";
  const confirmClass = isDanger
    ? "rounded-[8px] border border-[#d94848] bg-[#d94848] px-4 py-2 text-sm text-white hover:bg-[#c53d3d]"
    : "rounded-[8px] border border-[#1d4ed8] bg-[#1d4ed8] px-4 py-2 text-sm text-white hover:bg-[#1a43b8]";

  return (
    <DialogContext.Provider value={api}>
      {children}
      {dialog ? (
        <div
          className="fixed inset-0 z-[9998] grid place-items-center bg-[rgba(17,24,39,0.36)] p-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="wwDialogTitle"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              close(dialog.kind === "prompt" ? null : false);
            }
          }}
        >
          <section className="relative w-full max-w-[440px] rounded-[8px] border border-[#e6e6e3] bg-white p-5 shadow-[0_20px_60px_rgba(15,23,42,0.22)]">
            <button
              type="button"
              aria-label={t("common.dialogClose")}
              className="absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-full border border-[#d6d6d1] bg-white text-xl leading-none text-[#626872] hover:bg-[#f6f6f4]"
              onClick={() => close(dialog.kind === "prompt" ? null : false)}
            >
              ×
            </button>

            <h2 id="wwDialogTitle" className="pr-8 text-[18px] font-medium text-[#1f2933]">
              {dialog.title ??
                (dialog.kind === "prompt" ? t("common.dialogPromptTitle") : t("common.dialogConfirmTitle"))}
            </h2>

            {dialog.message ? (
              <p className="mt-3 text-sm leading-relaxed text-[#5c626b]">{dialog.message}</p>
            ) : null}

            {dialog.kind === "prompt" ? (
              <input
                ref={inputRef}
                type="text"
                value={promptValue}
                placeholder={dialog.placeholder}
                onChange={(event) => setPromptValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    close(promptValue.trim());
                  }
                }}
                className="mt-3 w-full rounded-[8px] border border-[#d6dbe6] px-3 py-2 text-sm text-[#1f2937] outline-none focus:border-[#1d4ed8]"
              />
            ) : null}

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-[8px] border border-[#d6d6d1] bg-white px-4 py-2 text-sm text-[#111827] hover:bg-[#f6f6f4]"
                onClick={() => close(dialog.kind === "prompt" ? null : false)}
              >
                {dialog.cancelLabel ?? t("common.dialogCancel")}
              </button>
              <button
                type="button"
                className={confirmClass}
                onClick={() => close(dialog.kind === "prompt" ? promptValue.trim() : true)}
              >
                {dialog.confirmLabel ?? t("common.dialogConfirm")}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </DialogContext.Provider>
  );
}

export function useDialog() {
  const context = useContext(DialogContext);
  if (!context) throw new Error("useDialog must be used within DialogProvider");
  return context;
}
