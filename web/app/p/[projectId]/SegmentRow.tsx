"use client";

import { useEffect, useRef, useState } from "react";

import { SPEAKERS, peerColor, shortId } from "@/lib/config";
import type { CollabActions, FieldName, Peer, Segment } from "@/lib/types";

interface Props {
  segment: Segment;
  actions: CollabActions;
  isFirst: boolean;
  isLast: boolean;
  peerCursors: Peer[];
}

function useFieldValue<T extends string>(remote: T, focused: boolean): [T, (v: T) => void] {
  const [local, setLocal] = useState<T>(remote);
  const focusedRef = useRef(focused);
  focusedRef.current = focused;
  useEffect(() => {
    if (!focusedRef.current) {
      setLocal(remote);
    }
  }, [remote]);
  return [local, setLocal];
}

function PeerCursors({ peers, field }: { peers: Peer[]; field: FieldName }) {
  const here = peers.filter((p) => p.cursor?.field === field);
  if (here.length === 0) return null;
  return (
    <span className="pointer-events-none absolute -top-2 right-1 z-10 flex gap-0.5">
      {here.map((p) => (
        <span
          key={p.user_id}
          data-testid="peer-cursor"
          data-user-id={p.user_id}
          data-field={field}
          title={`${shortId(p.user_id)} is editing`}
          className="animate-pulse rounded px-1 text-[10px] font-semibold leading-tight text-white shadow"
          style={{ backgroundColor: peerColor(p.user_id) }}
        >
          {shortId(p.user_id)}
        </span>
      ))}
    </span>
  );
}

function ringStyle(peers: Peer[], field: FieldName) {
  const here = peers.find((p) => p.cursor?.field === field);
  return here ? { boxShadow: `0 0 0 2px ${peerColor(here.user_id)}` } : undefined;
}

export function SegmentRow({ segment, actions, isFirst, isLast, peerCursors }: Props) {
  const [focusedField, setFocusedField] = useState<FieldName | null>(null);

  const [start, setStart] = useFieldValue<string>(
    segment.start_time_ms === null ? "" : String(segment.start_time_ms),
    focusedField === "start_time_ms",
  );
  const [end, setEnd] = useFieldValue<string>(
    segment.end_time_ms === null ? "" : String(segment.end_time_ms),
    focusedField === "end_time_ms",
  );
  const [text, setText] = useFieldValue<string>(segment.text ?? "", focusedField === "text");

  function focus(field: FieldName) {
    setFocusedField(field);
    actions.setCursor({ chunk_id: segment.chunk_id, field });
  }

  function blur() {
    setFocusedField(null);
    actions.setCursor(null);
  }

  function commitNumber(field: "start_time_ms" | "end_time_ms", raw: string) {
    const value = raw === "" ? null : Number(raw);
    if (value !== null && Number.isNaN(value)) return;
    actions.updateField(segment.chunk_id, field, value);
  }

  const rowAccent = peerCursors[0] ? peerColor(peerCursors[0].user_id) : undefined;

  return (
    <tr
      data-testid="segment-row"
      data-chunk-id={segment.chunk_id}
      data-peer-editing={peerCursors.length > 0 ? "true" : undefined}
      className={`border-b border-slate-100 ${peerCursors.length ? "bg-amber-50" : ""}`}
      style={rowAccent ? { boxShadow: `inset 3px 0 0 0 ${rowAccent}` } : undefined}
    >
      <td className="px-2 py-1">
        <div className="relative">
          <input
            data-testid="seg-start"
            type="number"
            className="w-24 rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
            style={ringStyle(peerCursors, "start_time_ms")}
            value={start}
            onChange={(e) => setStart(e.target.value)}
            onFocus={() => focus("start_time_ms")}
            onBlur={(e) => {
              commitNumber("start_time_ms", e.target.value);
              blur();
            }}
          />
          <PeerCursors peers={peerCursors} field="start_time_ms" />
        </div>
      </td>
      <td className="px-2 py-1">
        <div className="relative">
          <input
            data-testid="seg-end"
            type="number"
            className="w-24 rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
            style={ringStyle(peerCursors, "end_time_ms")}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            onFocus={() => focus("end_time_ms")}
            onBlur={(e) => {
              commitNumber("end_time_ms", e.target.value);
              blur();
            }}
          />
          <PeerCursors peers={peerCursors} field="end_time_ms" />
        </div>
      </td>
      <td className="px-2 py-1">
        <div className="relative">
          <select
            data-testid="seg-speaker"
            className="rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
            style={ringStyle(peerCursors, "speaker_id")}
            value={segment.speaker_id ?? ""}
            onFocus={() => actions.setCursor({ chunk_id: segment.chunk_id, field: "speaker_id" })}
            onBlur={() => actions.setCursor(null)}
            onChange={(e) =>
              actions.updateField(segment.chunk_id, "speaker_id", e.target.value === "" ? null : e.target.value)
            }
          >
            <option value="">—</option>
            {SPEAKERS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <PeerCursors peers={peerCursors} field="speaker_id" />
        </div>
      </td>
      <td className="px-2 py-1">
        <div className="relative">
          <input
            data-testid="seg-text"
            type="text"
            className="w-full min-w-[16rem] rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
            style={ringStyle(peerCursors, "text")}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onFocus={() => focus("text")}
            onBlur={(e) => {
              actions.updateField(segment.chunk_id, "text", e.target.value);
              blur();
            }}
          />
          <PeerCursors peers={peerCursors} field="text" />
        </div>
      </td>
      <td className="whitespace-nowrap px-2 py-1">
        <div className="flex gap-1">
          <button
            type="button"
            data-testid="seg-up"
            disabled={isFirst}
            onClick={() => actions.move(segment.chunk_id, "up")}
            className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-30"
          >
            ↑
          </button>
          <button
            type="button"
            data-testid="seg-down"
            disabled={isLast}
            onClick={() => actions.move(segment.chunk_id, "down")}
            className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-30"
          >
            ↓
          </button>
          <button
            type="button"
            data-testid="seg-delete"
            onClick={() => actions.remove(segment.chunk_id)}
            className="rounded border border-red-300 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}
