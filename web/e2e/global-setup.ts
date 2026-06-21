import { APP1_HTTP, APP2_HTTP } from "./helpers";

async function checkHealth(base: string): Promise<void> {
  const res = await fetch(`${base}/health`);
  if (!res.ok) {
    throw new Error(`backend ${base} unhealthy: ${res.status}`);
  }
  const body = (await res.json()) as { status: string; instance: string };
  if (body.status !== "ok") {
    throw new Error(`backend ${base} returned status=${body.status}`);
  }
}

export default async function globalSetup(): Promise<void> {
  try {
    await Promise.all([checkHealth(APP1_HTTP), checkHealth(APP2_HTTP)]);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Backend not reachable (${msg}). Start it with 'docker compose up -d --build' from the repo root.`,
    );
  }
}
