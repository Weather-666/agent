"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { activatePlatformUser } from "@/lib/api/users";
import { useI18n, type Translate } from "@/lib/i18n";


function getErrorMessage(error: unknown, t: Translate) {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }

  return t("platformActivate.activateFailed");
}

export default function PlatformActivatePage() {
  const router = useRouter();
  const { t } = useI18n();
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  useEffect(() => {
    queueMicrotask(() => {
      const searchParams = new URLSearchParams(window.location.search);
      setToken(searchParams.get("token") ?? "");
    });
  }, []);

  async function handleActivate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccessMessage("");

    if (!token) {
      setError(t("platformActivate.missingToken"));
      return;
    }

    if (password.length < 8) {
      setError(t("platformActivate.passwordTooShort"));
      return;
    }

    if (password !== confirmPassword) {
      setError(t("platformActivate.passwordMismatch"));
      return;
    }

    setIsSubmitting(true);

    try {
      const result = await activatePlatformUser({
        token,
        newPassword: password,
        name: name.trim() || undefined,
      });

      setSuccessMessage(t("platformActivate.activated", { email: result.email }));
      window.setTimeout(() => {
        router.push("/admin/login");
      }, 1000);
    } catch (err) {
      setError(getErrorMessage(err, t));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f3f4f8] px-4 py-10 text-[#111827]">
      <section className="mx-auto grid max-w-[480px] gap-5 rounded-[14px] border border-[#dde2ea] bg-white p-6 shadow-[0_20px_60px_rgba(15,23,42,0.12)]">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">WinWise Platform</p>
          <h1 className="mt-2 text-2xl font-semibold">{t("platformActivate.title")}</h1>
          <p className="mt-2 text-sm leading-6 text-[#6b7280]">{t("platformActivate.subtitle")}</p>
        </div>

        {!token ? (
          <p className="rounded-[8px] border border-[#f2c9c9] bg-[#fff4f4] px-3 py-2 text-sm text-[#b42318]">
            {t("platformActivate.missingTokenNotice")}
          </p>
        ) : null}

        {error ? (
          <p className="rounded-[8px] border border-[#f2c9c9] bg-[#fff4f4] px-3 py-2 text-sm text-[#b42318]">
            {error}
          </p>
        ) : null}

        {successMessage ? (
          <p className="rounded-[8px] border border-[#b7e3c4] bg-[#f1fff5] px-3 py-2 text-sm text-[#0f7a32]">
            {successMessage}
          </p>
        ) : null}

        <form className="grid gap-3" onSubmit={handleActivate}>
          <label className="grid gap-2 text-sm text-[#5c626b]">
            <span>{t("platformActivate.tokenLabel")}</span>
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={t("platformActivate.tokenPlaceholder")}
              required
              className="h-[42px] rounded-[8px] border border-[#d6d6d1] px-3 text-sm text-[#111827] outline-none focus:border-[#111827]"
            />
          </label>

          <label className="grid gap-2 text-sm text-[#5c626b]">
            <span>{t("platformActivate.nameLabel")}</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Expert User"
              className="h-[42px] rounded-[8px] border border-[#d6d6d1] px-3 text-sm text-[#111827] outline-none focus:border-[#111827]"
            />
          </label>

          <label className="grid gap-2 text-sm text-[#5c626b]">
            <span>{t("platformActivate.passwordLabel")}</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={t("platformActivate.passwordPlaceholder")}
              required
              className="h-[42px] rounded-[8px] border border-[#d6d6d1] px-3 text-sm text-[#111827] outline-none focus:border-[#111827]"
            />
          </label>

          <label className="grid gap-2 text-sm text-[#5c626b]">
            <span>{t("platformActivate.confirmPasswordLabel")}</span>
            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              className="h-[42px] rounded-[8px] border border-[#d6d6d1] px-3 text-sm text-[#111827] outline-none focus:border-[#111827]"
            />
          </label>

          <button
            type="submit"
            disabled={isSubmitting || !token}
            className="mt-1 inline-flex min-h-[42px] items-center justify-center rounded-[8px] bg-[#111827] px-4 text-sm font-normal text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting ? t("platformActivate.submitting") : t("platformActivate.submit")}
          </button>
        </form>
      </section>
    </main>
  );
}
