import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type ApiResult<T> = { ok: boolean; data: T };
type Summary = {
  app: string;
  config_path: string;
  database_path: string;
  state_dir: string;
  queue: { backend: string; ready: boolean; error: string | null };
  web: { read_only: boolean; actions_enabled: boolean };
  github_hooks: { range_count: number; checked_at: string | null };
};

const endpoints = [
  ["deliveries", "/api/deliveries"],
  ["events", "/api/events"],
  ["jobs", "/api/jobs"],
  ["runs", "/api/runs"],
  ["child PRs", "/api/child-prs"],
  ["PR stats", "/api/pr-stats"],
  ["GitHub IP ranges", "/api/github-ip-ranges"],
  ["effective config", "/api/config/effective"],
] as const;

function tokenFromUrl(): string | null {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("token");
  if (token) {
    window.localStorage.setItem("autobotToken", token);
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.toString());
    return token;
  }
  return window.localStorage.getItem("autobotToken");
}

async function getJson<T>(path: string, token: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function JsonPanel({ title, data }: { title: string; data: unknown }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </section>
  );
}

function App() {
  const [token, setToken] = useState<string | null>(() => tokenFromUrl());
  const [summary, setSummary] = useState<Summary | null>(null);
  const [active, setActive] = useState<(typeof endpoints)[number]>(endpoints[0]);
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  const authReady = useMemo(() => Boolean(token), [token]);

  useEffect(() => {
    if (!token) return;
    getJson<ApiResult<Summary>>("/api/summary", token)
      .then((result) => setSummary(result.data))
      .catch((err: Error) => setError(err.message));
  }, [token]);

  useEffect(() => {
    if (!token) return;
    setError(null);
    getJson<ApiResult<unknown>>(active[1], token)
      .then((result) => setData(result.data))
      .catch((err: Error) => setError(err.message));
  }, [active, token]);

  if (!authReady) {
    return (
      <main className="login">
        <h1>autobot dashboard</h1>
        <p>Enter the token printed by <code>autobot web</code>.</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const nextToken = String(form.get("token") || "");
            window.localStorage.setItem("autobotToken", nextToken);
            setToken(nextToken);
          }}
        >
          <input name="token" type="password" placeholder="dashboard token" />
          <button type="submit">Open dashboard</button>
        </form>
      </main>
    );
  }

  return (
    <main>
      <header>
        <div>
          <h1>autobot</h1>
          <p>local operations dashboard</p>
        </div>
        <button
          onClick={() => {
            window.localStorage.removeItem("autobotToken");
            setToken(null);
          }}
        >
          forget token
        </button>
      </header>

      {summary && (
        <section className="summary">
          <div><strong>queue</strong><span>{summary.queue.ready ? "ready" : "down"}</span></div>
          <div><strong>database</strong><span>{summary.database_path}</span></div>
          <div><strong>mode</strong><span>{summary.web.read_only ? "read-only" : "actions enabled"}</span></div>
          <div><strong>GitHub hooks</strong><span>{summary.github_hooks.range_count} ranges</span></div>
        </section>
      )}

      <nav>
        {endpoints.map((endpoint) => (
          <button
            key={endpoint[1]}
            className={active[1] === endpoint[1] ? "active" : ""}
            onClick={() => setActive(endpoint)}
          >
            {endpoint[0]}
          </button>
        ))}
      </nav>

      {error && <p className="error">{error}</p>}
      <JsonPanel title={active[0]} data={data} />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
