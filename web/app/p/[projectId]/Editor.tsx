"use client";

import Link from "next/link";

import { INSTANCE_LABEL, otherInstance, peerColor, shortId } from "@/lib/config";
import { useCollab } from "@/lib/useCollab";
import type { Instance } from "@/lib/types";

import { SegmentRow } from "./SegmentRow";

interface Props {
  projectId: string;
  instance: Instance;
}

export function Editor({ projectId, instance }: Props) {
  const { segments, peers, activity, status, you, instanceId, actions } = useCollab(projectId, instance);
  const peer = otherInstance(instance);

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <header className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <span
            data-testid="instance-badge"
            className="rounded-full bg-slate-800 px-3 py-1 text-xs font-semibold text-white"
          >
            {instanceId ?? INSTANCE_LABEL[instance]}
          </span>
          <span className="text-xs text-slate-500">
            project <code data-testid="project-id" className="font-mono text-slate-700">{projectId}</code>
          </span>
          <span
            data-testid="conn-status"
            className={
              status === "live"
                ? "rounded-full bg-green-100 px-3 py-1 text-xs font-semibold text-green-700"
                : "rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700"
            }
          >
            {status}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div data-testid="presence" className="flex items-center gap-1">
            {peers.length === 0 ? (
              <span className="text-xs text-slate-400">no peers</span>
            ) : (
              peers.map((p) => (
                <span
                  key={p.user_id}
                  data-testid="presence-chip"
                  data-user-id={p.user_id}
                  title={p.user_id}
                  className="rounded-full px-2 py-1 text-xs font-semibold text-white"
                  style={{ backgroundColor: peerColor(p.user_id) }}
                >
                  {shortId(p.user_id)}
                  {p.cursor ? " ✎" : ""}
                </span>
              ))
            )}
          </div>
          <Link
            href={`/p/${projectId}?instance=${peer}`}
            data-testid="peer-link"
            className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            Open on {peer}
          </Link>
        </div>
      </header>

      <section className="flex items-center gap-2">
        <button
          type="button"
          data-testid="add-segment"
          onClick={() => actions.addSegment()}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700"
        >
          Add segment
        </button>
        <button
          type="button"
          data-testid="undo"
          onClick={() => actions.undo()}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
        >
          Undo my last
        </button>
        {you ? <span className="text-xs text-slate-400">you: {shortId(you)}</span> : null}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_18rem]">
        <section className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-2 py-2 font-medium">Start (ms)</th>
                <th className="px-2 py-2 font-medium">End (ms)</th>
                <th className="px-2 py-2 font-medium">Speaker</th>
                <th className="px-2 py-2 font-medium">Text</th>
                <th className="px-2 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {segments.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-400">
                    No segments yet. Click &ldquo;Add segment&rdquo;.
                  </td>
                </tr>
              ) : (
                segments.map((seg, i) => (
                  <SegmentRow
                    key={seg.chunk_id}
                    segment={seg}
                    actions={actions}
                    isFirst={i === 0}
                    isLast={i === segments.length - 1}
                  />
                ))
              )}
            </tbody>
          </table>
        </section>

        <aside className="flex flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
          <h2 className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Activity
          </h2>
          <ul data-testid="activity-log" className="flex max-h-[28rem] flex-col-reverse gap-1 overflow-y-auto p-3 text-xs">
            {activity.map((a) => (
              <li
                key={a.id}
                data-testid="activity-item"
                className="flex items-center gap-2 rounded border border-slate-100 bg-slate-50 px-2 py-1"
              >
                <span className="font-mono text-slate-400">#{a.seq}</span>
                <span
                  className="rounded px-1.5 py-0.5 font-semibold text-white"
                  style={{ backgroundColor: peerColor(a.actor) }}
                >
                  {shortId(a.actor)}
                </span>
                <span className="font-medium text-slate-700">{a.op_type}</span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </main>
  );
}
