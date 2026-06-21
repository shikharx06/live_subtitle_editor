"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getHealth } from "./api";
import { wsBase } from "./config";
import type {
  ActivityEntry,
  CollabState,
  Cursor,
  FieldName,
  Instance,
  Peer,
  Segment,
  ServerMessage,
  ServerOp,
} from "./types";

const SPEAKER_FIELDS = new Set<FieldName>(["start_time_ms", "end_time_ms", "speaker_id", "text"]);

interface UnackedOp {
  message: Record<string, unknown>;
}

function orderSegments(map: Map<string, Segment>): Segment[] {
  return [...map.values()]
    .filter((s) => !s.deleted)
    .sort((a, b) => {
      if (a.position < b.position) return -1;
      if (a.position > b.position) return 1;
      return a.chunk_id < b.chunk_id ? -1 : a.chunk_id > b.chunk_id ? 1 : 0;
    });
}

export function useCollab(projectId: string, instance: Instance): CollabState {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [peers, setPeers] = useState<Peer[]>([]);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [status, setStatus] = useState<CollabState["status"]>("reconnecting");
  const [you, setYou] = useState<string | null>(null);
  const [instanceId, setInstanceId] = useState<string | null>(null);

  const segMapRef = useRef<Map<string, Segment>>(new Map());
  const peersRef = useRef<Map<string, Peer>>(new Map());
  const observedSeqRef = useRef<number>(0);
  const unackedRef = useRef<Map<string, UnackedOp>>(new Map());
  const wsRef = useRef<WebSocket | null>(null);
  const userIdRef = useRef<string>("");
  const closedRef = useRef<boolean>(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const focusedRef = useRef<Cursor | null>(null);
  const lastCursorRef = useRef<Cursor | null>(null);

  if (!userIdRef.current) {
    userIdRef.current = crypto.randomUUID();
  }

  const flushSegments = useCallback(() => {
    setSegments(orderSegments(segMapRef.current));
  }, []);

  const flushPeers = useCallback(() => {
    setPeers([...peersRef.current.values()]);
  }, []);

  const applyOp = useCallback((op: ServerOp) => {
    if (op.seq > observedSeqRef.current) {
      observedSeqRef.current = op.seq;
    }
    const map = segMapRef.current;
    const cid = op.chunk_id ?? op.payload.chunk_id ?? null;
    switch (op.op_type) {
      case "create": {
        if (!cid) break;
        map.set(cid, {
          chunk_id: cid,
          position: op.payload.position ?? "",
          start_time_ms: op.payload.start_time_ms ?? null,
          end_time_ms: op.payload.end_time_ms ?? null,
          speaker_id: op.payload.speaker_id ?? null,
          text: op.payload.text ?? "",
          deleted: false,
          updated_seq: op.seq,
          updated_by: op.actor,
        });
        break;
      }
      case "update": {
        if (!cid) break;
        const existing = map.get(cid);
        if (!existing) break;
        const fields = op.payload.fields ?? {};
        const next: Segment = { ...existing, updated_seq: op.seq, updated_by: op.actor };
        for (const key of Object.keys(fields) as FieldName[]) {
          if (!SPEAKER_FIELDS.has(key)) continue;
          const value = fields[key];
          if (key === "start_time_ms" || key === "end_time_ms") {
            next[key] = value === null || value === undefined ? null : Number(value);
          } else if (key === "speaker_id") {
            next.speaker_id = (value as string | null) ?? null;
          } else {
            next.text = (value as string | null) ?? "";
          }
        }
        map.set(cid, next);
        break;
      }
      case "delete": {
        if (!cid) break;
        const existing = map.get(cid);
        if (existing) {
          map.set(cid, { ...existing, deleted: true, updated_seq: op.seq, updated_by: op.actor });
        } else {
          map.set(cid, {
            chunk_id: cid,
            position: "",
            start_time_ms: null,
            end_time_ms: null,
            speaker_id: null,
            text: "",
            deleted: true,
            updated_seq: op.seq,
            updated_by: op.actor,
          });
        }
        break;
      }
      case "move": {
        if (!cid) break;
        const existing = map.get(cid);
        if (existing && op.payload.position !== undefined) {
          map.set(cid, { ...existing, position: op.payload.position, updated_seq: op.seq, updated_by: op.actor });
        }
        break;
      }
      default:
        break;
    }
  }, []);

  const recordActivity = useCallback((op: ServerOp) => {
    setActivity((prev) => {
      const entry: ActivityEntry = {
        id: `${op.seq}:${op.actor}`,
        seq: op.seq,
        actor: op.actor,
        op_type: op.op_type,
        chunk_id: op.chunk_id ?? op.payload.chunk_id ?? null,
        ts: op.ts,
      };
      if (prev.some((e) => e.id === entry.id)) return prev;
      return [...prev, entry].slice(-200);
    });
  }, []);

  const send = useCallback((message: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }, []);

  const connect = useCallback(() => {
    if (closedRef.current) return;
    const url = `${wsBase(instance)}/projects/${projectId}/ws`;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      const last = observedSeqRef.current > 0 ? observedSeqRef.current : null;
      ws.send(
        JSON.stringify({
          type: "hello",
          user_id: userIdRef.current,
          last_seq: last,
          cursor: lastCursorRef.current,
        }),
      );
      for (const { message } of unackedRef.current.values()) {
        ws.send(JSON.stringify(message));
      }
      setStatus("live");
    };

    ws.onmessage = (event) => {
      let msg: ServerMessage;
      try {
        msg = JSON.parse(event.data as string) as ServerMessage;
      } catch {
        return;
      }
      handleMessage(msg);
    };

    ws.onclose = () => {
      if (closedRef.current) return;
      setStatus("reconnecting");
      scheduleReconnect();
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        /* noop */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instance, projectId]);

  const scheduleReconnect = useCallback(() => {
    if (closedRef.current) return;
    if (reconnectTimerRef.current) return;
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      connect();
    }, 600);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connect]);

  const handleMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "welcome": {
          setYou(msg.you);
          if (msg.snapshot) {
            segMapRef.current = new Map();
            for (const seg of msg.snapshot.segments) {
              segMapRef.current.set(seg.chunk_id, { ...seg, deleted: false });
            }
            if (msg.snapshot.base_seq > observedSeqRef.current) {
              observedSeqRef.current = msg.snapshot.base_seq;
            }
          }
          peersRef.current = new Map();
          for (const peer of msg.peers) {
            if (peer.user_id !== userIdRef.current) {
              peersRef.current.set(peer.user_id, peer);
            }
          }
          flushSegments();
          flushPeers();
          setStatus("live");
          break;
        }
        case "sync": {
          for (const op of msg.ops) {
            applyOp(op);
            recordActivity(op);
          }
          flushSegments();
          break;
        }
        case "op": {
          if (msg.client_op_id && unackedRef.current.has(msg.client_op_id)) {
            unackedRef.current.delete(msg.client_op_id);
          }
          applyOp(msg);
          recordActivity(msg);
          flushSegments();
          break;
        }
        case "ack": {
          unackedRef.current.delete(msg.client_op_id);
          if (msg.seq > observedSeqRef.current) {
            observedSeqRef.current = msg.seq;
          }
          break;
        }
        case "presence": {
          if (msg.actor === userIdRef.current) break;
          if (msg.status === "leave") {
            peersRef.current.delete(msg.actor);
          } else {
            peersRef.current.set(msg.actor, { user_id: msg.actor, cursor: msg.cursor });
          }
          flushPeers();
          break;
        }
        case "error": {
          break;
        }
        default:
          break;
      }
    },
    [applyOp, flushPeers, flushSegments, recordActivity],
  );

  useEffect(() => {
    closedRef.current = false;
    observedSeqRef.current = 0;
    segMapRef.current = new Map();
    peersRef.current = new Map();
    unackedRef.current = new Map();
    setSegments([]);
    setPeers([]);
    setActivity([]);
    setStatus("reconnecting");
    connect();
    getHealth(instance)
      .then((h) => setInstanceId(h.instance))
      .catch(() => setInstanceId(null));

    return () => {
      closedRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        try {
          ws.close();
        } catch {
          /* noop */
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, instance]);

  const sendOp = useCallback(
    (message: Record<string, unknown>) => {
      const clientOpId = message.client_op_id as string;
      unackedRef.current.set(clientOpId, { message });
      send(message);
    },
    [send],
  );

  const addSegment = useCallback(
    (fields?: Partial<Pick<Segment, "text" | "start_time_ms" | "end_time_ms" | "speaker_id">>) => {
      const chunkId = crypto.randomUUID();
      sendOp({
        type: "op",
        client_op_id: crypto.randomUUID(),
        op_type: "create",
        chunk_id: chunkId,
        fields: {
          text: fields?.text ?? "",
          start_time_ms: fields?.start_time_ms ?? 0,
          end_time_ms: fields?.end_time_ms ?? 0,
          speaker_id: fields?.speaker_id ?? null,
        },
      });
      return chunkId;
    },
    [sendOp],
  );

  const updateField = useCallback(
    (chunkId: string, field: FieldName, value: string | number | null) => {
      const existing = segMapRef.current.get(chunkId);
      if (existing) {
        segMapRef.current.set(chunkId, { ...existing, [field]: value });
        flushSegments();
      }
      sendOp({
        type: "op",
        client_op_id: crypto.randomUUID(),
        op_type: "update",
        chunk_id: chunkId,
        fields: { [field]: value },
      });
    },
    [sendOp, flushSegments],
  );

  const remove = useCallback(
    (chunkId: string) => {
      sendOp({
        type: "op",
        client_op_id: crypto.randomUUID(),
        op_type: "delete",
        chunk_id: chunkId,
      });
    },
    [sendOp],
  );

  const move = useCallback(
    (chunkId: string, direction: "up" | "down") => {
      const ordered = orderSegments(segMapRef.current);
      const idx = ordered.findIndex((s) => s.chunk_id === chunkId);
      if (idx === -1) return;
      let before: string | null;
      let after: string | null;
      if (direction === "up") {
        if (idx === 0) return;
        const prev = ordered[idx - 1];
        const prevPrev = idx - 2 >= 0 ? ordered[idx - 2] : null;
        before = prevPrev ? prevPrev.position : null;
        after = prev.position;
      } else {
        if (idx === ordered.length - 1) return;
        const next = ordered[idx + 1];
        const nextNext = idx + 2 < ordered.length ? ordered[idx + 2] : null;
        before = next.position;
        after = nextNext ? nextNext.position : null;
      }
      sendOp({
        type: "op",
        client_op_id: crypto.randomUUID(),
        op_type: "move",
        chunk_id: chunkId,
        before,
        after,
      });
    },
    [sendOp],
  );

  const undo = useCallback(() => {
    send({ type: "undo", client_op_id: crypto.randomUUID() });
  }, [send]);

  const setCursor = useCallback(
    (cursor: Cursor | null) => {
      focusedRef.current = cursor;
      lastCursorRef.current = cursor;
      send({ type: "presence", cursor });
    },
    [send],
  );

  const actions = useMemo(
    () => ({ addSegment, updateField, remove, move, undo, setCursor }),
    [addSegment, updateField, remove, move, undo, setCursor],
  );

  return { segments, peers, activity, status, you, instanceId, actions };
}
