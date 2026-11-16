"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { confirmPasswordReset, login, register, requestPasswordReset } from "@/lib/api/auth";
import { saveAuthTokens } from "@/lib/request";
import { LanguageSwitcher, useI18n } from "@/lib/i18n";

function getErrorCode(err: unknown): string | undefined {
  if (err && typeof err === "object" && "code" in err) {
    const code = (err as { code?: unknown }).code;
    if (typeof code === "string") return code;
  }
  return undefined;
}

function getErrorMessage(err: unknown, fallback: string) {
  if (err instanceof Error) return err.message;
  if (err && typeof err === "object" && "message" in err) {
    const message = (err as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return fallback;
}

type AuthMode = "login" | "register" | "reset";


function EyeToggle({ visible, onToggle }: { visible: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      tabIndex={-1}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onToggle}
      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#a7a29a] hover:text-[#111]"
    >
      {visible ? (
        <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-6.5 0-10-8-10-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c6.5 0 10 8 10 8a18.5 18.5 0 0 1-2.16 3.19M1 1l22 22" />
          <path d="M10.73 10.73A3 3 0 0 0 14.14 14" />
        </svg>
      )}
    </button>
  );
}

function LoginForm() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // The auth mode is derived from the URL (`?mode=register` / `?mode=reset`) so
  // that switching updates the address bar, survives refresh, and is
  // shareable/deep-linkable — this is what makes the "立即注册" / "忘记密码？"
  // clicks feel like a real navigation while still keeping the user on the same
  // card (no full page load).
  const modeParam = searchParams.get("mode");
  const mode: AuthMode =
    modeParam === "register" ? "register" : modeParam === "reset" ? "reset" : "login";
  const isRegisterMode = mode === "register";
  const isResetMode = mode === "reset";

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [registerConfirmPassword, setRegisterConfirmPassword] = useState("");
  const [showRegisterConfirmPassword, setShowRegisterConfirmPassword] = useState(false);

  // Reset-flow state, wired to the anonymous backend endpoints: request a code
  // (POST /password-reset/request), confirm it with a new password
  // (POST /password-reset/confirm), then land on the success screen. The confirm
  // step never logs the user in — it returns them to the login page.
  const [resetEmail, setResetEmail] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [codeCountdown, setCodeCountdown] = useState(0);
  const [codeSent, setCodeSent] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [resetSubmitting, setResetSubmitting] = useState(false);
  const [resetDone, setResetDone] = useState(false);

  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const resetEmailRef = useRef<HTMLInputElement>(null);
  const didMountRef = useRef(false);

  // On a mode switch (but not the very first render) move focus to the first
  // relevant field. This gives immediate, obvious feedback that the click did
  // something, complementing the URL / heading / extra-field changes.
  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }

    if (isRegisterMode) {
      nameRef.current?.focus();
    } else if (isResetMode) {
      resetEmailRef.current?.focus();
    } else {
      emailRef.current?.focus();
    }
  }, [isRegisterMode, isResetMode]);

  // Tick down the "send code" cooldown once per second.
  useEffect(() => {
    if (codeCountdown <= 0) return;
    const timer = setTimeout(() => setCodeCountdown((n) => n - 1), 1000);
    return () => clearTimeout(timer);
  }, [codeCountdown]);

  const goToMode = (next: AuthMode) => {
    setError("");
    setSuccess("");
    setShowPassword(false);
    setShowRegisterConfirmPassword(false);
    setShowNewPassword(false);
    setShowConfirmPassword(false);

    const params = new URLSearchParams(searchParams.toString());
    if (next === "login") {
      params.delete("mode");
    } else {
      params.set("mode", next);
    }

    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (isRegisterMode && !name.trim()) {
      setError(t("auth.noName"));
      return;
    }

    if (!email || !password) {
      setError(t("auth.noEmailPassword"));
      return;
    }

    if (password.length < 6) {
      setError(t("auth.shortPassword"));
      return;
    }

    if (isRegisterMode && registerConfirmPassword !== password) {
      setError(t("auth.passwordMismatch"));
      return;
    }

    setIsLoading(true);
    try {
      const result = isRegisterMode
        ? await register({ email, password, name: name.trim() })
        : await login({ email, password });
      saveAuthTokens({
        accessToken: result.accessToken,
        refreshToken: result.refreshToken,
      });
      // Persist the identity for the account/profile page (localStorage + 30-day
      // cookie). Prefer the values echoed back by the API `user` object — this is
      // the source of truth for the account page (name + email) — and fall back to
      // the values typed into the form when the response omits them.
      const displayEmail = result.user?.email ?? email;
      const displayName = result.user?.name ?? (isRegisterMode ? name.trim() : "");
      window.localStorage.setItem("user_email", displayEmail);
      document.cookie = `user_email=${encodeURIComponent(displayEmail)}; Path=/; Max-Age=2592000; SameSite=Lax`;
      if (displayName) {
        window.localStorage.setItem("user_name", displayName);
        document.cookie = `user_name=${encodeURIComponent(displayName)}; Path=/; Max-Age=2592000; SameSite=Lax`;
      }
      setSuccess(isRegisterMode ? t("auth.registerSuccess") : t("auth.loginSuccess"));
      router.replace("/");
    } catch (err) {
      setError(getErrorMessage(err, isRegisterMode ? t("auth.registerFailed") : t("auth.loginFailed")));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendCode = async () => {
    setError("");
    if (!resetEmail.trim()) {
      setError(t("auth.resetNoEmail"));
      resetEmailRef.current?.focus();
      return;
    }

    setSendingCode(true);
    try {
      // The backend always answers 202 when the address is well-formed (it will
      // not reveal whether the email is registered), so a resolved promise just
      // means "request accepted". Surface the hint and start the 60s cooldown
      // that mirrors the backend's resend window.
      await requestPasswordReset({ email: resetEmail.trim(), locale });
      setCodeSent(true);
      setCodeCountdown(60);
    } catch (err) {
      // 503 EMAIL_SEND_FAILED (or a network error) — let the user retry. Prefer
      // our localized copy for the known code; the backend message is Chinese-only.
      setCodeSent(false);
      const message =
        getErrorCode(err) === "EMAIL_SEND_FAILED"
          ? t("auth.codeSendFailed")
          : getErrorMessage(err, t("auth.codeSendFailed"));
      setError(message);
    } finally {
      setSendingCode(false);
    }
  };

  const handleResetSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");

    if (!resetEmail.trim()) {
      setError(t("auth.resetNoEmail"));
      return;
    }
    if (resetCode.length !== 6) {
      setError(t("auth.resetNoCode"));
      return;
    }
    // Backend requires at least 8 characters for the new password.
    if (newPassword.length < 8) {
      setError(t("auth.resetShortPassword"));
      return;
    }
    if (newPassword !== confirmNewPassword) {
      setError(t("auth.passwordMismatch"));
      return;
    }

    setResetSubmitting(true);
    try {
      await confirmPasswordReset({
        email: resetEmail.trim(),
        code: resetCode,
        newPassword,
      });
      // Success: the backend does not issue tokens or auto-login, so we show the
      // confirmation screen whose only action returns the user to the login page.
      setResetDone(true);
    } catch (err) {
      // Prefer our localized copy for the known invalid-code case; the backend
      // message is Chinese-only. Fall back to the backend text otherwise.
      const message =
        getErrorCode(err) === "AUTH_PASSWORD_RESET_CODE_INVALID"
          ? t("auth.resetCodeInvalid")
          : getErrorMessage(err, t("auth.resetFailed"));
      setError(message);
    } finally {
      setResetSubmitting(false);
    }
  };

  const backToLoginFromSuccess = () => {
    // Carry the address over so the login form is pre-filled and the user only
    // has to type the new password.
    setEmail(resetEmail.trim());
    setResetDone(false);
    setResetEmail("");
    setResetCode("");
    setNewPassword("");
    setConfirmNewPassword("");
    setCodeSent(false);
    setCodeCountdown(0);
    goToMode("login");
  };

  const inputBase =
    "h-12 w-full rounded-lg border border-[#d7d4cf] bg-white px-4 text-[16px] outline-none focus:border-[#111]";

  return (
    <div className="grid min-h-screen place-items-center bg-[rgba(248,248,247,0.82)] px-4">
      <section className="relative w-full max-w-[474px] rounded-2xl bg-[#f4f3f1] px-[56px] pb-7 pt-[34px] text-center text-[#141414] shadow-[0_18px_70px_rgba(30,28,26,0.16)] sm:min-h-[610px]">
        <div className="absolute left-[13px] top-[13px]">
          <LanguageSwitcher />
        </div>
        {/* Login mode has no close button. In register / reset mode the × acts
            as "back to login" (same as the in-form button), not an exit to home. */}
        {isRegisterMode || isResetMode ? (
          <button
            type="button"
            onClick={() => {
              if (isRegisterMode) {
                setName("");
                setEmail("");
                setPassword("");
                setRegisterConfirmPassword("");
              }
              goToMode("login");
            }}
            aria-label={t("auth.backToLogin")}
            className="absolute right-[13px] top-[13px] grid h-[34px] w-[34px] cursor-pointer place-items-center text-[#6b6b6b]"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        ) : null}

        <div className="mt-[46px] inline-flex items-center gap-2 text-[20px] font-bold tracking-[-0.01em] text-[#232f3e]">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-[#111] text-[14px] font-semibold text-white">
            W
          </span>
          <strong className="font-semibold">WinWise</strong>
        </div>

        {isResetMode && resetDone ? (
          <div className="pt-2">
            <span className="mx-auto mb-6 mt-[38px] grid h-[58px] w-[58px] place-items-center rounded-full bg-[#ece9e1] text-[#111]">
              <svg
                viewBox="0 0 24 24"
                className="h-7 w-7"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="m5 12 4 4 10-10" />
              </svg>
            </span>
            <h1 className="mb-3 text-[27px] font-normal [font-family:Georgia,'Times_New_Roman','SimSun',serif]">
              {t("auth.resetSuccessTitle")}
            </h1>
            <p className="mb-8 text-[14px] text-[#7d7b78]">{t("auth.resetSuccessSubtitle")}</p>
            <button
              type="button"
              onClick={backToLoginFromSuccess}
              className="h-[46px] w-full rounded-lg bg-[#111] text-[16px] font-semibold text-white"
            >
              {t("auth.resetSuccessButton")}
            </button>
          </div>
        ) : isResetMode ? (
          <>
            <h1 className="mb-3 mt-7 text-[27px] font-normal [font-family:Georgia,'Times_New_Roman','SimSun',serif]">
              {t("auth.resetTitle")}
            </h1>
            <p className="mb-8 text-[14px] text-[#7d7b78]">{t("auth.resetSubtitle")}</p>

            <form className="mt-5 grid gap-[14px]" onSubmit={handleResetSubmit}>
              <label htmlFor="reset-email" className="sr-only">{t("auth.email")}</label>
              <input
                id="reset-email"
                ref={resetEmailRef}
                type="email"
                value={resetEmail}
                onChange={(e) => setResetEmail(e.target.value)}
                placeholder={t("auth.email")}
                autoComplete="email"
                required
                className="h-12 w-full rounded-lg border-[1.5px] border-[#111] bg-white px-4 text-[16px] outline-none"
              />

              <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-[10px]">
                <label htmlFor="reset-code" className="sr-only">{t("auth.resetCodePlaceholder")}</label>
                <input
                  id="reset-code"
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={resetCode}
                  onChange={(e) => setResetCode(e.target.value.replace(/\D/g, ""))}
                  placeholder={t("auth.resetCodePlaceholder")}
                  required
                  className={inputBase}
                />
                <button
                  type="button"
                  onClick={handleSendCode}
                  disabled={codeCountdown > 0 || sendingCode}
                  className="h-12 cursor-pointer rounded-lg border border-[#111] bg-transparent px-2 text-[14px] text-[#191817] disabled:cursor-default disabled:border-[#d7d4cf] disabled:text-[#a7a29a]"
                >
                  {sendingCode
                    ? t("auth.sendingCode")
                    : codeCountdown > 0
                      ? t("auth.sendCodeCountdown", { seconds: codeCountdown })
                      : t("auth.sendCode")}
                </button>
              </div>

              <label htmlFor="reset-new-password" className="sr-only">{t("auth.newPassword")}</label>
              <div className="relative">
                <input
                  id="reset-new-password"
                  type={showNewPassword ? "text" : "password"}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder={t("auth.newPassword")}
                  autoComplete="new-password"
                  minLength={8}
                  required
                  className={`${inputBase} pr-10`}
                />
                <EyeToggle visible={showNewPassword} onToggle={() => setShowNewPassword((v) => !v)} />
              </div>
              <label htmlFor="reset-confirm-password" className="sr-only">{t("auth.confirmNewPassword")}</label>
              <div className="relative">
                <input
                  id="reset-confirm-password"
                  type={showConfirmPassword ? "text" : "password"}
                  value={confirmNewPassword}
                  onChange={(e) => setConfirmNewPassword(e.target.value)}
                  placeholder={t("auth.confirmNewPassword")}
                  autoComplete="new-password"
                  minLength={8}
                  required
                  className={`${inputBase} pr-10`}
                />
                <EyeToggle visible={showConfirmPassword} onToggle={() => setShowConfirmPassword((v) => !v)} />
              </div>

              {codeSent && !error ? (
                <p className="rounded-lg border border-[#b7e3c4] bg-[#f1fff5] px-3 py-2 text-left text-[13px] text-[#0f7a32]">
                  {t("auth.codeSent")}
                </p>
              ) : null}

              {error ? (
                <p className="rounded-lg border border-[#f2c9c9] bg-[#fff4f4] px-3 py-2 text-left text-[13px] text-[#b42318]">
                  {error}
                </p>
              ) : null}

              <button
                type="submit"
                disabled={resetSubmitting}
                className="h-[46px] w-full cursor-pointer rounded-lg bg-[#111] text-[16px] font-semibold text-white disabled:cursor-default disabled:opacity-70"
              >
                {resetSubmitting ? t("auth.resetting") : t("auth.resetButton")}
              </button>
              <button
                type="button"
                className="cursor-pointer text-[13px] font-medium text-[#5f5a52] underline-offset-4 hover:text-[#111] hover:underline"
                onClick={() => goToMode("login")}
              >
                {t("auth.backToLogin")}
              </button>
            </form>
          </>
        ) : (
          <>
            <h1 className="mb-3 mt-4 text-[27px] font-normal [font-family:Georgia,'Times_New_Roman','SimSun',serif]">
              {isRegisterMode ? t("auth.titleRegister") : t("auth.title")}
            </h1>
            <p className="mb-8 text-[14px] text-[#7d7b78]">
              {isRegisterMode ? t("auth.subtitleRegister") : t("auth.subtitleLogin")}
            </p>

            <form className="mt-5 grid gap-[14px]" onSubmit={handleSubmit}>
              {isRegisterMode ? (
                <>
                  <label htmlFor="name" className="sr-only">{t("auth.displayName")}</label>
                  <input
                    id="name"
                    ref={nameRef}
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("auth.displayName")}
                    autoComplete="name"
                    required={isRegisterMode}
                    className="h-12 w-full rounded-lg border border-[#d7d4cf] bg-white px-4 text-[16px] outline-none focus:border-[#111]"
                  />
                </>
              ) : null}

              <label htmlFor="email" className="sr-only">{t("auth.email")}</label>
              <input
                id="email"
                ref={emailRef}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("auth.email")}
                autoComplete="email"
                required
                className="h-12 w-full rounded-lg border-[1.5px] border-[#111] bg-white px-4 text-[16px] outline-none"
              />
              <label htmlFor="password" className="sr-only">{t("auth.password")}</label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t("auth.password")}
                  autoComplete={isRegisterMode ? "new-password" : "current-password"}
                  required
                  className="h-12 w-full rounded-lg border border-[#d7d4cf] bg-white px-4 pr-10 text-[16px] outline-none focus:border-[#111]"
                />
                <EyeToggle visible={showPassword} onToggle={() => setShowPassword((v) => !v)} />
              </div>

              {isRegisterMode ? (
                <>
                  <label htmlFor="register-confirm-password" className="sr-only">{t("auth.confirmPassword")}</label>
                  <div className="relative">
                    <input
                      id="register-confirm-password"
                      type={showRegisterConfirmPassword ? "text" : "password"}
                      value={registerConfirmPassword}
                      onChange={(e) => setRegisterConfirmPassword(e.target.value)}
                      placeholder={t("auth.confirmPassword")}
                      autoComplete="new-password"
                      required
                      className="h-12 w-full rounded-lg border border-[#d7d4cf] bg-white px-4 pr-10 text-[16px] outline-none focus:border-[#111]"
                    />
                    <EyeToggle visible={showRegisterConfirmPassword} onToggle={() => setShowRegisterConfirmPassword((v) => !v)} />
                  </div>
                </>
              ) : null}

              {!isRegisterMode ? (
                <button
                  type="button"
                  onClick={() => {
                    if (email.trim()) setResetEmail(email.trim());
                    goToMode("reset");
                  }}
                  className="-mt-1 mr-1 cursor-pointer justify-self-end text-[13px] font-medium text-[#8a837a] underline-offset-4 hover:text-[#111] hover:underline"
                >
                  {t("auth.forgotPassword")}
                </button>
              ) : null}

              {error ? (
                <p className="rounded-lg border border-[#f2c9c9] bg-[#fff4f4] px-3 py-2 text-left text-[13px] text-[#b42318]">
                  {error}
                </p>
              ) : null}

              {success ? (
                <p className="rounded-lg border border-[#b7e3c4] bg-[#f1fff5] px-3 py-2 text-left text-[13px] text-[#0f7a32]">
                  {success}
                </p>
              ) : null}

              <button
                type="submit"
                disabled={isLoading}
                className="h-[46px] w-full cursor-pointer rounded-lg bg-[#111] text-[16px] font-semibold text-white disabled:cursor-default disabled:opacity-70"
              >
                {isLoading ? (isRegisterMode ? t("auth.registering") : t("auth.loggingIn")) : isRegisterMode ? t("auth.registeringEnter") : t("auth.loginButton")}
              </button>
              <button
                type="button"
                className="cursor-pointer text-[13px] font-medium text-[#5f5a52] underline-offset-4 hover:text-[#111] hover:underline"
                onClick={() => {
                  setName("");
                  setEmail("");
                  setPassword("");
                  setRegisterConfirmPassword("");
                  goToMode(isRegisterMode ? "login" : "register");
                }}
              >
                {isRegisterMode ? t("auth.switchToLogin") : t("auth.switchToRegister")}
              </button>
            </form>

            <small className="mt-[22px] block text-[12px] text-[#aaa6a0]">
              {locale === "zh-CN"
                ? <>继续即表示您同意{" "}<Link href="/terms" className="underline underline-offset-2 hover:text-[#111]">用户服务协议</Link>{" "}和{" "}<Link href="/privacy" className="underline underline-offset-2 hover:text-[#111]">隐私政策</Link></>
                : <>By continuing, you agree to our{" "}<Link href="/terms" className="underline underline-offset-2 hover:text-[#111]">Terms of Service</Link>{" "}and{" "}<Link href="/privacy" className="underline underline-offset-2 hover:text-[#111]">Privacy Policy</Link></>
              }
            </small>
          </>
        )}
      </section>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
