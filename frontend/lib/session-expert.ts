// Binds an expert to a chat session for the session's lifetime.
//
// The expert is chosen once when a session is created and must not change
// afterwards. The backend session object does not (yet) carry an expert, so we
// persist the binding client-side, keyed by session id. This survives reloads
// within the same browser; clearing site data or switching devices drops it,
// in which case the session falls back to "no expert".

const STORAGE_KEY = "winwise.session-expert.v1";

export type SessionExpert = {
  id: string;
  name: string;
};

type SessionExpertMap = Record<string, SessionExpert>;

function readMap(): SessionExpertMap {
  if (typeof window === "undefined") {
    return {};
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" ? (parsed as SessionExpertMap) : {};
  } catch {
    return {};
  }
}

function writeMap(map: SessionExpertMap) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // Ignore quota / serialization errors — the binding is best-effort.
  }
}

export function getSessionExpert(sessionId: string): SessionExpert | null {
  if (!sessionId) return null;
  const entry = readMap()[sessionId];
  return entry && entry.id ? entry : null;
}

// Binds an expert to a session. The first binding wins: once a session has an
// expert, later calls are ignored so the expert can never be switched mid-session.
export function bindSessionExpert(sessionId: string, expert: SessionExpert) {
  if (!sessionId || !expert.id) return;
  const map = readMap();
  if (map[sessionId]) return;
  map[sessionId] = { id: expert.id, name: expert.name };
  writeMap(map);
}

export function updateSessionExpert(sessionId: string, expert: SessionExpert) {
  if (!sessionId || !expert.id) return;
  const map = readMap();
  map[sessionId] = { id: expert.id, name: expert.name };
  writeMap(map);
}

export function removeSessionExpert(sessionId: string) {
  if (!sessionId) return;
  const map = readMap();
  if (!(sessionId in map)) return;
  delete map[sessionId];
  writeMap(map);
}
