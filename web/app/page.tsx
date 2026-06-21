"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createProject } from "@/lib/api";
import { INSTANCE_LABEL } from "@/lib/config";
import type { Instance } from "@/lib/types";

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
    <main className="mx-auto flex max-w-xl flex-col gap-8 px-6 py-16">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Collaborative Subtitles Editor</h1>
        <p className="mt-2 text-sm text-slate-600">
          Pick a backend instance, create a project, or join an existing one.
        </p>
      </header>

      <section className="flex flex-col gap-2">
        <label className="text-sm font-medium text-slate-700" htmlFor="instance-select">
          Backend instance
        </label>
        <select
          id="instance-select"
          data-testid="instance-select"
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
          value={instance}
          onChange={(e) => setInstance(e.target.value as Instance)}
        >
          <option value="app1">{INSTANCE_LABEL.app1}</option>
          <option value="app2">{INSTANCE_LABEL.app2}</option>
          <option value="lb">{INSTANCE_LABEL.lb}</option>
        </select>
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold">Create new project</h2>
        <button
          type="button"
          data-testid="create-project"
          disabled={busy}
          onClick={handleCreate}
          className="inline-flex w-fit items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50"
        >
          {busy ? "Creating…" : "Create new project"}
        </button>
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold">Join existing</h2>
        <div className="flex gap-2">
          <input
            type="text"
            data-testid="join-id"
            placeholder="project id"
            value={joinId}
            onChange={(e) => setJoinId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleJoin();
            }}
            className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
          />
          <button
            type="button"
            data-testid="join-submit"
            onClick={handleJoin}
            className="inline-flex items-center rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-900"
          >
            Join
          </button>
        </div>
      </section>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </main>
  );
}
