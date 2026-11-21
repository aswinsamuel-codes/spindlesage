import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiClient, type Me } from "./api";

// The API key lives in sessionStorage: it survives a reload but is cleared
// when the tab closes, and it is never written to localStorage.
const STORAGE_KEY = "spindlesage.apiKey";

interface Session {
  client: ApiClient;
  me: Me;
  can: (permission: string) => boolean;
  signOut: () => void;
}

const SessionContext = createContext<Session | null>(null);

export function readStoredKey(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeKey(key: string | null): void {
  try {
    if (key) sessionStorage.setItem(STORAGE_KEY, key);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable (private mode); the session just won't survive a reload.
  }
}

export function SessionProvider({
  client,
  me,
  onSignOut,
  children,
}: {
  client: ApiClient;
  me: Me;
  onSignOut: () => void;
  children: ReactNode;
}) {
  const can = useCallback((permission: string) => me.permissions.includes(permission), [me]);
  const value = useMemo(() => ({ client, me, can, signOut: onSignOut }), [client, me, can, onSignOut]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}

interface PollState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/**
 * Load data now and every `intervalMs` (0 disables refresh). `key` identifies
 * what is being loaded; when it changes the data is reset and loaded again.
 */
export function usePolling<T>(load: () => Promise<T>, key: string, intervalMs = 15000) {
  const [state, setState] = useState<PollState<T>>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    setState({ data: null, error: null, loading: true });
  }, [key]);

  useEffect(() => {
    let cancelled = false;
    const run = () => {
      load()
        .then((data) => {
          if (!cancelled) setState({ data, error: null, loading: false });
        })
        .catch((err: Error) => {
          if (!cancelled) setState((s) => ({ ...s, error: err.message, loading: false }));
        });
    };
    run();
    const timer = intervalMs > 0 ? window.setInterval(run, intervalMs) : undefined;
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearInterval(timer);
    };
    // `load` is recreated each render; `key` and `tick` decide when to refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick, intervalMs]);

  return { ...state, reload };
}
