import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiClient, ApiError, type Me } from "./api";
import { SessionProvider, readStoredKey, storeKey, useSession } from "./session";
import { ApprovalsView } from "./views/Approvals";
import { AuditView } from "./views/Audit";
import { MachineView } from "./views/MachineDetail";
import { Overview } from "./views/Overview";
import { RecommendationView } from "./views/RecommendationView";

export type Route =
  | { name: "overview" }
  | { name: "machine"; id: string }
  | { name: "recommendation"; id: string }
  | { name: "approvals" }
  | { name: "audit" };

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "machines" && parts[1]) return { name: "machine", id: parts[1] };
  if (parts[0] === "recommendations" && parts[1]) return { name: "recommendation", id: parts[1] };
  if (parts[0] === "approvals") return { name: "approvals" };
  if (parts[0] === "audit") return { name: "audit" };
  return { name: "overview" };
}

function useRoute(): Route {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return useMemo(() => parseRoute(hash), [hash]);
}

function Login({ onSignIn, error }: { onSignIn: (key: string) => void; error: string | null }) {
  const [key, setKey] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (key.trim()) onSignIn(key.trim());
  };
  return (
    <main>
      <section className="card login">
        <h1>SpindleSage</h1>
        <p className="secondary">Maintenance operations dashboard. Sign in with your API key.</p>
        <form onSubmit={submit}>
          <label htmlFor="api-key">API key</label>
          <input
            id="api-key"
            type="password"
            autoComplete="off"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="ss_..."
          />
          <button className="primary" type="submit" disabled={!key.trim()}>
            Sign in
          </button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <p className="muted small">
            Keys are created by an administrator with <code>python -m apps.api.keys</code>. The key is kept only for
            this browser tab.
          </p>
        </form>
      </section>
    </main>
  );
}

function TopBar({ route }: { route: Route }) {
  const { me, can, signOut } = useSession();
  const links: [string, string, boolean][] = [
    ["#/", "Machines", route.name === "overview" || route.name === "machine"],
    ["#/approvals", "Approvals", route.name === "approvals"],
  ];
  if (can("read_audit")) links.push(["#/audit", "Audit trail", route.name === "audit"]);
  return (
    <header className="topbar">
      <span className="brand">SpindleSage</span>
      <nav aria-label="Main">
        {links.map(([href, label, current]) => (
          <a key={href} href={href} aria-current={current ? "page" : undefined}>
            {label}
          </a>
        ))}
      </nav>
      <div className="who">
        <span>
          {me.user_id} · {me.role.replace("_", " ")}
        </span>
        <button onClick={signOut}>Sign out</button>
      </div>
    </header>
  );
}

function Shell() {
  const route = useRoute();
  return (
    <>
      <TopBar route={route} />
      <main>
        {route.name === "overview" && <Overview />}
        {route.name === "machine" && <MachineView machineId={route.id} />}
        {route.name === "recommendation" && <RecommendationView recommendationId={route.id} />}
        {route.name === "approvals" && <ApprovalsView />}
        {route.name === "audit" && <AuditView />}
      </main>
    </>
  );
}

export function App({ makeClient = (key: string) => new ApiClient(key) }: { makeClient?: (key: string) => ApiClient }) {
  const [auth, setAuth] = useState<{ client: ApiClient; me: Me } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(() => readStoredKey() !== null);

  const signIn = useCallback(
    async (key: string) => {
      const client = makeClient(key);
      try {
        const me = await client.me();
        storeKey(key);
        setAuth({ client, me });
        setError(null);
      } catch (err) {
        storeKey(null);
        setError(err instanceof ApiError && err.status === 401 ? "That API key was not accepted." : String(err));
      } finally {
        setChecking(false);
      }
    },
    [makeClient],
  );

  const signOut = useCallback(() => {
    storeKey(null);
    setAuth(null);
  }, []);

  useEffect(() => {
    const stored = readStoredKey();
    if (stored) void signIn(stored);
  }, [signIn]);

  return (
    <>
      <div className="banner" role="note">
        Research build · all telemetry is <strong>simulated</strong> and models are trained on synthetic benchmarks ·
        SpindleSage only recommends; it never controls machines.
      </div>
      {checking ? (
        <main>
          <p className="muted">Signing in…</p>
        </main>
      ) : auth ? (
        <SessionProvider client={auth.client} me={auth.me} onSignOut={signOut}>
          <Shell />
        </SessionProvider>
      ) : (
        <Login onSignIn={signIn} error={error} />
      )}
    </>
  );
}
