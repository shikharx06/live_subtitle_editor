export type Instance = "app1" | "app2" | "lb";

export interface Speaker {
  id: string;
  label: string;
  color: string;
}

export interface Segment {
  chunk_id: string;
  start_time_ms: number | null;
  end_time_ms: number | null;
  speaker_id: string | null;
  text: string | null;
  position: string;
  deleted: boolean;
  updated_seq: number | null;
  updated_by: string | null;
}

export interface ProjectMeta {
  id: string;
  title: string | null;
  current_seq: number;
  snapshot_seq: number;
  created_at?: string;
}

export interface ProjectSnapshot extends ProjectMeta {
  segments: Segment[];
}

export type FieldName = "start_time_ms" | "end_time_ms" | "speaker_id" | "text";

export interface Cursor {
  chunk_id: string;
  field: string;
}

export interface Peer {
  user_id: string;
  cursor: Cursor | null;
}

export interface ActivityEntry {
  id: string;
  seq: number;
  actor: string;
  op_type: string;
  chunk_id: string | null;
  ts: string | null;
}

export type ConnStatus = "live" | "reconnecting";

export type OpType = "create" | "update" | "delete" | "move" | "undo";

export interface ServerOpPayload {
  chunk_id?: string;
  position?: string;
  start_time_ms?: number | null;
  end_time_ms?: number | null;
  speaker_id?: string | null;
  text?: string | null;
  fields?: Partial<Record<FieldName, unknown>>;
  undoes_seq?: number;
}

export interface WelcomeMessage {
  type: "welcome";
  you: string;
  current_seq: number;
  snapshot?: { segments: Segment[]; base_seq: number };
  base_seq?: number;
  peers: Peer[];
}

export interface SyncMessage {
  type: "sync";
  ops: ServerOp[];
}

export interface ServerOp {
  seq: number;
  actor: string;
  client_op_id?: string;
  op_type: OpType;
  chunk_id: string | null;
  payload: ServerOpPayload;
  ts: string | null;
}

export interface BroadcastOpMessage extends ServerOp {
  type: "op";
}

export interface AckMessage {
  type: "ack";
  client_op_id: string;
  seq: number;
}

export interface PresenceMessage {
  type: "presence";
  actor: string;
  cursor: Cursor | null;
  status: "join" | "update" | "leave";
}

export interface PongMessage {
  type: "pong";
}

export interface ErrorMessage {
  type: "error";
  code: string;
  message: string;
}

export type ServerMessage =
  | WelcomeMessage
  | SyncMessage
  | BroadcastOpMessage
  | AckMessage
  | PresenceMessage
  | PongMessage
  | ErrorMessage;

export interface CollabActions {
  addSegment: (fields?: Partial<Pick<Segment, "text" | "start_time_ms" | "end_time_ms" | "speaker_id">>) => string;
  updateField: (chunkId: string, field: FieldName, value: string | number | null) => void;
  remove: (chunkId: string) => void;
  move: (chunkId: string, direction: "up" | "down") => void;
  undo: () => void;
  setCursor: (cursor: Cursor | null) => void;
}

export interface CollabState {
  segments: Segment[];
  peers: Peer[];
  activity: ActivityEntry[];
  status: ConnStatus;
  you: string | null;
  instanceId: string | null;
  actions: CollabActions;
}
