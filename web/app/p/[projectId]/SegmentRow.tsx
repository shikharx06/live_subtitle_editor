"use client";

import { useEffect, useRef, useState } from "react";

import { SPEAKERS, peerColor, shortId, speakerById } from "@/lib/config";
import { formatTimecode } from "@/lib/format";
import type { CollabActions, FieldName, Peer, Segment } from "@/lib/types";

interface Props {
  index: number;
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

function PeerTags({ peers, field }: { peers: Peer[]; field: FieldName }) {
  const here = peers.filter((p) => p.cursor?.field === field);
  if (here.length === 0) return null;
  return (
    <span className="pointer-events-none absolute -top-2.5 left-2 z-10 flex gap-1">
      {here.map((p) => (
        <span
          key={p.user_id}
          data-testid="peer-cursor"
          data-user-id={p.user_id}
          data-field={field}
          title={`${shortId(p.user_id)} is editing`}
          className="animate-pulse rounded-full px-1.5 py-px text-[9px] font-bold leading-tight text-white shadow-soft"
          style={{ backgroundColor: peerColor(p.user_id) }}
        >
          {shortId(p.user_id)}
        </span>
      ))}
    </span>
  );
}

function peerBorder(peers: Peer[], field: FieldName) {
  const here = peers.find((p) => p.cursor?.field === field);
  return here ? { borderColor: peerColor(here.user_id), boxShadow: `0 0 0 3px ${peerColor(here.user_id)}22` } : undefined;
}

const inputBase =
  "w-full rounded-lg border border-hairline bg-paper/60 px-2.5 py-1.5 text-sm text-ink outline-none transition focus:border-accent focus:bg-surface focus:ring-4 focus:ring-accent/10";

export function SegmentRow({ index, segment, actions, isFirst, isLast, peerCursors }: Props) {
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

  const speaker = speakerById(segment.speaker_id);
  const accent = peerCursors[0] ? peerColor(peerCursors[0].user_id) : undefined;

  return (
    <tr
      data-testid="segment-row"
      data-chunk-id={segment.chunk_id}
      data-peer-editing={peerCursors.length > 0 ? "true" : undefined}
      className={`group border-b border-hairline/70 align-top transition-colors last:border-0 ${
        peerCursors.length ? "bg-live-soft/40" : "hover:bg-paper/70"
      }`}
      style={accent ? { boxShadow: `inset 3px 0 0 0 ${accent}` } : undefined}
    >
      <td className="px-3 py-3 font-mono text-xs text-faint">{String(index).padStart(2, "0")}</td>

      <td className="px-3 py-2.5">
        <div className="relative w-24">
          <input
            data-testid="seg-start"
            type="number"
            className={`${inputBase} font-mono`}
            style={peerBorder(peerCursors, "start_time_ms")}
            value={start}
            onChange={(e) => setStart(e.target.value)}
            onFocus={() => focus("start_time_ms")}
            onBlur={(e) => {
              commitNumber("start_time_ms", e.target.value);
              blur();
            }}
          />
          <PeerTags peers={peerCursors} field="start_time_ms" />
          <span className="mt-1 block font-mono text-[10px] text-faint">
            {formatTimecode(start === "" ? null : Number(start))}
          </span>
        </div>
      </td>

      <td className="px-3 py-2.5">
        <div className="relative w-24">
          <input
            data-testid="seg-end"
            type="number"
            className={`${inputBase} font-mono`}
            style={peerBorder(peerCursors, "end_time_ms")}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            onFocus={() => focus("end_time_ms")}
            onBlur={(e) => {
              commitNumber("end_time_ms", e.target.value);
              blur();
            }}
          />
          <PeerTags peers={peerCursors} field="end_time_ms" />
          <span className="mt-1 block font-mono text-[10px] text-faint">
            {formatTimecode(end === "" ? null : Number(end))}
          </span>
        </div>
      </td>

      <td className="px-3 py-2.5">
        <div className="relative flex items-center gap-2">
          <span
            aria-hidden
            className="h-2.5 w-2.5 shrink-0 rounded-full border border-black/5"
            style={{ backgroundColor: speaker?.color ?? "#D9D5CC" }}
          />
          <select
            data-testid="seg-speaker"
            className={`${inputBase} cursor-pointer appearance-none pr-7`}
            style={peerBorder(peerCursors, "speaker_id")}
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
          <PeerTags peers={peerCursors} field="speaker_id" />
        </div>
      </td>

      <td className="px-3 py-2.5">
        <div className="relative">
          <input
            data-testid="seg-text"
            type="text"
            placeholder="Subtitle text…"
            className={`${inputBase} min-w-[14rem]`}
            style={peerBorder(peerCursors, "text")}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onFocus={() => focus("text")}
            onBlur={(e) => {
              actions.updateField(segment.chunk_id, "text", e.target.value);
              blur();
            }}
          />
          <PeerTags peers={peerCursors} field="text" />
        </div>
      </td>

      <td className="px-3 py-2.5">
        <div className="flex items-center gap-0.5 text-subtle opacity-50 transition group-hover:opacity-100 group-focus-within:opacity-100">
          <button
            type="button"
            data-testid="seg-up"
            aria-label="Move up"
            disabled={isFirst}
            onClick={() => actions.move(segment.chunk_id, "up")}
            className="grid h-7 w-7 place-items-center rounded-md transition hover:bg-paper hover:text-ink disabled:opacity-25 disabled:hover:bg-transparent"
          >
            ↑
          </button>
          <button
            type="button"
            data-testid="seg-down"
            aria-label="Move down"
            disabled={isLast}
            onClick={() => actions.move(segment.chunk_id, "down")}
            className="grid h-7 w-7 place-items-center rounded-md transition hover:bg-paper hover:text-ink disabled:opacity-25 disabled:hover:bg-transparent"
          >
            ↓
          </button>
          <button
            type="button"
            data-testid="seg-delete"
            aria-label="Delete line"
            onClick={() => actions.remove(segment.chunk_id)}
            className="grid h-7 w-7 place-items-center rounded-md text-danger/80 transition hover:bg-danger-soft hover:text-danger"
          >
            ✕
          </button>
        </div>
      </td>
    </tr>
  );
}
