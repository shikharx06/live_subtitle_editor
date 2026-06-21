"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createProject } from "@/lib/api";
import { INSTANCE_LABEL } from "@/lib/config";
import type { Instance } from "@/lib/types";

const FEATURES = ["Live presence", "Conflict-free edits", "Reconnect-safe"];

export default function LandingPage() {
  const router = useRouter();
  const [instance, setInstance] = useState<Instance>("lb");
  const [joinId, setJoinId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    setBusy(true);
    setError(null);
    try {
      const project = await createProject(instance, null);
      router.push(`/p/${project.id}?instance=${instance}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to create project");
      setBusy(false);
    }
  }

  function handleJoin() {
    const id = joinId.trim();
    if (!id) return;
    router.push(`/p/${id}?instance=${instance}`);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-10 px-6 py-16">
      <header className="animate-fade-up">
        <div className="flex items-center gap-2 text-sm font-medium text-accent">
          <span className="inline-block h-2 w-2 rounded-full bg-accent" />
          Sonata <span className="text-faint">·</span>{" "}
          <span className="text-subtle">Subtitle Studio</span>
        </div>
        <h1 className="mt-5 font-serif text-5xl leading-[1.05] tracking-tight text-ink">
          Write subtitles
          <br />
          together, line by line.
        </h1>
        <p className="mt-4 max-w-md text-[15px] leading-relaxed text-subtle">
          A real-time, multi-editor timeline for dubbing studios. Pick a backend instance,
          start a project, and watch every edit converge instantly.
        </p>
      </header>

      <section
        className="animate-fade-up rounded-2xl border border-hairline bg-surface p-6 shadow-card sm:p-8"
        style={{ animationDelay: "80ms" }}
      >
        <label htmlFor="instance-select" className="text-xs font-semibold uppercase tracking-wider text-faint">
          Backend instance
        </label>
        <div className="relative mt-2">
          <select
            id="instance-select"
            data-testid="instance-select"
            value={instance}
            onChange={(e) => setInstance(e.target.value as Instance)}
            className="w-full appearance-none rounded-xl border border-hairline bg-paper px-4 py-3 text-sm font-medium text-ink outline-none transition focus:border-accent focus:bg-surface focus:ring-4 focus:ring-accent/10"
          >
            <option value="app1">{INSTANCE_LABEL.app1}</option>
            <option value="app2">{INSTANCE_LABEL.app2}</option>
            <option value="lb">{INSTANCE_LABEL.lb}</option>
          </select>
          <svg
            aria-hidden
            viewBox="0 0 20 20"
            className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-faint"
          >
            <path d="M6 8l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </div>

        <button
          type="button"
          data-testid="create-project"
          disabled={busy}
          onClick={handleCreate}
          className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-white shadow-soft transition hover:bg-accent-ink active:translate-y-px disabled:opacity-50"
        >
          {busy ? "Creating…" : "Create a project"}
          <span aria-hidden>→</span>
        </button>

        <div className="my-6 flex items-center gap-3 text-xs font-medium uppercase tracking-wider text-faint">
          <span className="h-px flex-1 bg-hairline" />
          or join existing
          <span className="h-px flex-1 bg-hairline" />
        </div>

        <div className="flex gap-2">
          <input
            type="text"
            data-testid="join-id"
            placeholder="paste a project id"
            value={joinId}
            onChange={(e) => setJoinId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleJoin();
            }}
            className="flex-1 rounded-xl border border-hairline bg-paper px-4 py-3 font-mono text-sm text-ink outline-none transition placeholder:font-sans placeholder:text-faint focus:border-accent focus:bg-surface focus:ring-4 focus:ring-accent/10"
          />
          <button
            type="button"
            data-testid="join-submit"
            onClick={handleJoin}
            className="rounded-xl border border-hairline bg-surface px-5 py-3 text-sm font-semibold text-ink transition hover:border-ink/30 hover:bg-paper active:translate-y-px"
          >
            Join
          </button>
        </div>

        {error ? <p className="mt-3 text-sm font-medium text-danger">{error}</p> : null}
      </section>

      <ul className="animate-fade-up flex flex-wrap gap-2" style={{ animationDelay: "160ms" }}>
        {FEATURES.map((f) => (
          <li
            key={f}
            className="rounded-full border border-hairline bg-surface/70 px-3 py-1 text-xs font-medium text-subtle"
          >
            {f}
          </li>
        ))}
      </ul>
    </main>
  );
}
