import request, { adminRequest, getRefreshToken, requestData } from "../request";

export type RegisterParams = {
  email: string;
  password: string;
  name: string;
};

export type LoginParams = {
  email: string;
  password: string;
  admin?: boolean;
};

export type LoginUser = {
  id?: string | number;
  email?: string;
  username?: string;
  nickname?: string;
  avatar?: string;
  role?: string;
  planName?: string;
};

export type LoginResultUser = {
  id?: string;
  email?: string;
  name?: string;
};

export type LoginResult = {
  accessToken: string;
  refreshToken: string;
  expiresInSeconds: number;
  user?: LoginResultUser;
};

export type PreferredLocale = "zh-CN" | "en-US";

export type UserProfile = {
  id: string;
  email: string;
  name: string;
  preferredLocale: PreferredLocale | null;
  avatarUrl: string | null;
  avatarUrlExpiresAt: string | null;
  updatedAt: string;
};

export type UpdateProfileParams = {
  name?: string;
  preferredLocale?: PreferredLocale | null;
};

export type RefreshTokenParams = {
  refreshToken: string;
};

export type RefreshTokenResult = LoginResult;

export type PasswordResetRequestParams = {
  email: string;
  /** Decides the verification-code email language; defaults to zh-CN on the backend. */
  locale?: "zh-CN" | "en-US";
};

export type PasswordResetConfirmParams = {
  email: string;
  /** 6-digit ASCII code from the email. */
  code: string;
  /** New password, at least 8 characters (backend rule). */
  newPassword: string;
};

export type PasswordResetMessageResult = {
  message?: string;
};

export function register(data: RegisterParams) {
  return requestData(
    request.post<LoginResult>("/api/v1/users/register", data)
  );
}

export function login(data: LoginParams) {
  return requestData(
    request.post<LoginResult>("/api/v1/auth/login", data)
  );
}

export function logout() {
  return requestData(
    request.post("/api/v1/auth/logout", {
      refreshToken: getRefreshToken(),
    })
  );
}

export function refreshToken(data: RefreshTokenParams) {
  return requestData(
    request.post<RefreshTokenResult>("/api/v1/auth/refresh", data)
  );
}

export function getCurrentUser() {
  return requestData(request.get<LoginUser>("/api/v1/auth/me"));
}

export function getAdminCurrentUser() {
  return requestData(adminRequest.get<LoginUser>("/api/v1/auth/me"));
}

// Current-user profile endpoints. These return the full profile object
// (id/email/name/preferredLocale/avatarUrl/...) rather than the basic
// id/email/name `user` shape used by login/register/refresh.
export function getProfile() {
  return requestData(request.get<UserProfile>("/api/v1/auth/me"));
}

export function updateProfile(data: UpdateProfileParams) {
  return requestData(request.patch<UserProfile>("/api/v1/auth/me", data));
}

export function uploadAvatar(file: File) {
  const form = new FormData();
  form.append("file", file);

  return requestData(
    request.put<UserProfile>("/api/v1/auth/me/avatar", form)
  );
}

// Anonymous endpoints — no access token, tenant header, or auto-login involved.
// The backend always answers the request step with 202 (regardless of whether
// the email exists) to avoid leaking which addresses are registered.
export function requestPasswordReset(data: PasswordResetRequestParams) {
  return requestData(
    request.post<PasswordResetMessageResult>("/api/v1/auth/password-reset/request", data)
  );
}

export function confirmPasswordReset(data: PasswordResetConfirmParams) {
  return requestData(
    request.post<PasswordResetMessageResult>("/api/v1/auth/password-reset/confirm", data)
  );
}
