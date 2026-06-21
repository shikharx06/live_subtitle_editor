import type { Instance, Speaker } from "./types";

const APP1 = process.env.NEXT_PUBLIC_APP1_HTTP ?? "http://localhost:8001";
const APP2 = process.env.NEXT_PUBLIC_APP2_HTTP ?? "http://localhost:8002";
const LB = process.env.NEXT_PUBLIC_LB_HTTP ?? "http://localhost:8080";

export const INSTANCE_HTTP: Record<Instance, string> = {
  app1: APP1,
  app2: APP2,
  lb: LB,
};

export const INSTANCE_LABEL: Record<Instance, string> = {
  app1: "app1 (instance 1)",
  app2: "app2 (instance 2)",
  lb: "load balancer",
};

export function isInstance(value: string | null | undefined): value is Instance {
  return value === "app1" || value === "app2" || value === "lb";
}

export function httpBase(instance: Instance): string {
  return INSTANCE_HTTP[instance];
}

export function wsBase(instance: Instance): string {
  return INSTANCE_HTTP[instance].replace(/^http/, "ws");
}

export function otherInstance(instance: Instance): Instance {
  if (instance === "app1") return "app2";
  if (instance === "app2") return "app1";
  return "app1";
}

export const SPEAKERS: Speaker[] = [
  { id: "11111111-1111-4111-8111-111111111111", label: "Speaker A", color: "#0F7A66" },
  { id: "22222222-2222-4222-8222-222222222222", label: "Speaker B", color: "#B26A09" },
  { id: "33333333-3333-4333-8333-333333333333", label: "Speaker C", color: "#3B5BA5" },
  { id: "44444444-4444-4444-8444-444444444444", label: "Speaker D", color: "#A23E63" },
];

export function speakerById(id: string | null): Speaker | undefined {
  return id ? SPEAKERS.find((s) => s.id === id) : undefined;
}

const PEER_COLORS = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#9333ea",
  "#ea580c",
  "#0891b2",
  "#db2777",
  "#65a30d",
];

export function peerColor(userId: string): string {
  let hash = 0;
  for (let i = 0; i < userId.length; i += 1) {
    hash = (hash * 31 + userId.charCodeAt(i)) >>> 0;
  }
  return PEER_COLORS[hash % PEER_COLORS.length];
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}
