"use client";

import { useEffect, useRef, useState } from "react";

import { SPEAKERS } from "@/lib/config";
import type { CollabActions, FieldName, Segment } from "@/lib/types";

interface Props {
  segment: Segment;
  actions: CollabActions;
  isFirst: boolean;
  isLast: boolean;
}

function useFieldValue<T extends string | number>(remote: T, focused: boolean): [T, (v: T) => void] {
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

export function SegmentRow({ segment, actions, isFirst, isLast }: Props) {
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

  return (
    <tr data-testid="segment-row" data-chunk-id={segment.chunk_id} className="border-b border-slate-100">
      <td className="px-2 py-1">
        <input
          data-testid="seg-start"
          type="number"
          className="w-24 rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
          value={start}
          onChange={(e) => setStart(e.target.value)}
          onFocus={() => focus("start_time_ms")}
          onBlur={(e) => {
            commitNumber("start_time_ms", e.target.value);
            blur();
          }}
        />
      </td>
      <td className="px-2 py-1">
        <input
          data-testid="seg-end"
          type="number"
          className="w-24 rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
          value={end}
          onChange={(e) => setEnd(e.target.value)}
          onFocus={() => focus("end_time_ms")}
          onBlur={(e) => {
            commitNumber("end_time_ms", e.target.value);
            blur();
          }}
        />
      </td>
      <td className="px-2 py-1">
        <select
          data-testid="seg-speaker"
          className="rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
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
      </td>
      <td className="px-2 py-1">
        <input
          data-testid="seg-text"
          type="text"
          className="w-full min-w-[16rem] rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => focus("text")}
          onBlur={(e) => {
            actions.updateField(segment.chunk_id, "text", e.target.value);
            blur();
          }}
        />
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
