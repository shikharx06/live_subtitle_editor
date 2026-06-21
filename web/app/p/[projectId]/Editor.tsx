"use client";

import Link from "next/link";

import { INSTANCE_LABEL, otherInstance, peerColor, shortId } from "@/lib/config";
import { formatTimecode, initials } from "@/lib/format";
import { useCollab } from "@/lib/useCollab";
import type { Instance, Peer } from "@/lib/types";

import { SegmentRow } from "./SegmentRow";

interface Props {
  projectId: string;
  instance: Instance;
}

export function Editor({ projectId, instance }: Props) {
  const { segments, peers, activity, status, you, instanceId, actions } = useCollab(projectId, instance);
  const peer = otherInstance(instance);

  const cursorsByChunk = new Map<string, Peer[]>();
  for (const p of peers) {
    if (!p.cursor) continue;
    const list = cursorsByChunk.get(p.cursor.chunk_id) ?? [];
    list.push(p);
    cursorsByChunk.set(p.cursor.chunk_id, list);
  }

  const timelineMs = segments.reduce((max, s) => Math.max(max, s.end_time_ms ?? 0), 0);
  const live = status === "live";

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-hairline bg-paper/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-3 px-6 py-3">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-accent" />
            <span className="font-serif text-lg font-semibold tracking-tight text-ink">Sonata</span>
          </div>

          <span
            data-testid="instance-badge"
            className="rounded-full border border-hairline bg-surface px-2.5 py-1 text-xs font-medium text-subtle"
            title={INSTANCE_LABEL[instance]}
          >
            {instanceId ?? INSTANCE_LABEL[instance]}
          </span>

          <span className="hidden items-center gap-1.5 text-xs text-faint sm:flex">
            project
            <code data-testid="project-id" className="rounded bg-surface px-1.5 py-0.5 font-mono text-subtle">
              {shortId(projectId)}
            </code>
          </span>

          <span className="flex-1" />

          <span
            data-testid="conn-status"
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
              live ? "bg-accent-soft text-accent-ink" : "bg-live-soft text-live"
            }`}
          >
            <span
              aria-hidden
              className={`h-1.5 w-1.5 rounded-full ${live ? "animate-pulse bg-accent" : "bg-live"}`}
            />
            <span className="capitalize">{status}</span>
          </span>

          <div data-testid="presence" className="flex items-center">
            {peers.length === 0 ? (
              <span className="text-xs text-faint">just you</span>
            ) : (
              <div className="flex -space-x-2">
                {peers.map((p) => (
                  <span
                    key={p.user_id}
                    data-testid="presence-chip"
                    data-user-id={p.user_id}
                    data-editing={p.cursor ? p.cursor.field : undefined}
                    title={p.cursor ? `${shortId(p.user_id)} · editing ${p.cursor.field}` : shortId(p.user_id)}
                    className="grid h-7 w-7 place-items-center rounded-full text-[10px] font-bold text-white ring-2 ring-paper"
                    style={{ backgroundColor: peerColor(p.user_id) }}
                  >
                    {initials(p.user_id)}
                  </span>
                ))}
              </div>
            )}
          </div>

          <Link
            href={`/p/${projectId}?instance=${peer}`}
            data-testid="peer-link"
            className="rounded-full border border-hairline bg-surface px-3 py-1 text-xs font-medium text-subtle transition hover:border-ink/30 hover:text-ink"
          >
            Open on {peer} ↗
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-serif text-3xl tracking-tight text-ink">Subtitle timeline</h1>
            <p className="mt-1 text-sm text-subtle">
              {segments.length} {segments.length === 1 ? "line" : "lines"}
              <span className="mx-2 text-hairline">·</span>
              <span className="font-mono text-subtle">{formatTimecode(timelineMs)}</span> runtime
              {you ? (
                <>
                  <span className="mx-2 text-hairline">·</span>
                  <span className="inline-flex items-center gap-1.5">
                    you
                    <span
                      className="grid h-4 w-4 place-items-center rounded-full text-[8px] font-bold text-white"
                      style={{ backgroundColor: peerColor(you) }}
                    >
                      {initials(you)}
                    </span>
                  </span>
                </>
              ) : null}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="undo"
              onClick={() => actions.undo()}
              className="rounded-xl border border-hairline bg-surface px-4 py-2 text-sm font-medium text-ink transition hover:border-ink/30 hover:bg-paper active:translate-y-px"
            >
              ↶ Undo
            </button>
            <button
              type="button"
              data-testid="add-segment"
              onClick={() => actions.addSegment()}
              className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition hover:bg-accent-ink active:translate-y-px"
            >
              <span aria-hidden className="text-base leading-none">+</span> Add line
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_19rem]">
          <section className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-card">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-hairline text-[11px] uppercase tracking-wider text-faint">
                  <th className="w-10 px-3 py-2.5 font-semibold">#</th>
                  <th className="px-3 py-2.5 font-semibold">In</th>
                  <th className="px-3 py-2.5 font-semibold">Out</th>
                  <th className="px-3 py-2.5 font-semibold">Speaker</th>
                  <th className="px-3 py-2.5 font-semibold">Subtitle</th>
                  <th className="w-px px-3 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {segments.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-16 text-center">
                      <p className="font-serif text-lg text-subtle">No lines yet</p>
                      <p className="mt-1 text-sm text-faint">
                        Add the first subtitle to start the timeline.
                      </p>
                    </td>
                  </tr>
                ) : (
                  segments.map((seg, i) => (
                    <SegmentRow
                      key={seg.chunk_id}
                      index={i + 1}
                      segment={seg}
                      actions={actions}
                      isFirst={i === 0}
                      isLast={i === segments.length - 1}
                      peerCursors={cursorsByChunk.get(seg.chunk_id) ?? []}
                    />
                  ))
                )}
              </tbody>
            </table>
          </section>

          <aside className="h-fit overflow-hidden rounded-2xl border border-hairline bg-surface shadow-card">
            <h2 className="border-b border-hairline px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-faint">
              Activity
            </h2>
            <ul data-testid="activity-log" className="flex max-h-[30rem] flex-col gap-0.5 overflow-y-auto p-2">
              {activity.length === 0 ? (
                <li className="px-2 py-3 text-xs text-faint">Edits will appear here.</li>
              ) : (
                [...activity].reverse().map((a) => (
                  <li
                    key={a.id}
                    data-testid="activity-item"
                    className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-xs hover:bg-paper"
                  >
                    <span className="font-mono text-[10px] text-faint">#{a.seq}</span>
                    <span
                      className="grid h-5 w-5 shrink-0 place-items-center rounded-full text-[8px] font-bold text-white"
                      style={{ backgroundColor: peerColor(a.actor) }}
                      title={a.actor === you ? "you" : shortId(a.actor)}
                    >
                      {initials(a.actor)}
                    </span>
                    <span className="font-medium text-ink">{a.op_type}</span>
                    {a.chunk_id ? (
                      <span className="ml-auto font-mono text-[10px] text-faint">{a.chunk_id.slice(0, 4)}</span>
                    ) : null}
                  </li>
                ))
              )}
            </ul>
          </aside>
        </div>
      </main>
    </div>
  );
}
