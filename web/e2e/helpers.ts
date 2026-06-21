import { expect, type Locator, type Page } from "@playwright/test";

export const APP1_HTTP = process.env.NEXT_PUBLIC_APP1_HTTP ?? "http://localhost:8001";
export const APP2_HTTP = process.env.NEXT_PUBLIC_APP2_HTTP ?? "http://localhost:8002";

export const SPEAKERS = {
  A: "11111111-1111-4111-8111-111111111111",
  B: "22222222-2222-4222-8222-222222222222",
  C: "33333333-3333-4333-8333-333333333333",
  D: "44444444-4444-4444-8444-444444444444",
} as const;

export async function createProject(base: string): Promise<string> {
  const res = await fetch(`${base}/projects`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ title: null }),
  });
  if (!res.ok) throw new Error(`create project failed: ${res.status}`);
  const body = (await res.json()) as { id: string };
  return body.id;
}

export interface BackendSnapshot {
  segments: { chunk_id: string; text: string | null; start_time_ms: number | null; end_time_ms: number | null; speaker_id: string | null; position: string }[];
}

export async function getSnapshot(base: string, projectId: string): Promise<BackendSnapshot> {
  const res = await fetch(`${base}/projects/${projectId}`);
  if (!res.ok) throw new Error(`get project failed: ${res.status}`);
  return (await res.json()) as BackendSnapshot;
}

export async function openEditor(page: Page, projectId: string, instance: "app1" | "app2"): Promise<void> {
  await page.goto(`/p/${projectId}?instance=${instance}`);
  await expect(page.getByTestId("conn-status")).toHaveText("live", { timeout: 20_000 });
}

export function rows(page: Page): Locator {
  return page.getByTestId("segment-row");
}

export function rowByChunk(page: Page, chunkId: string): Locator {
  return page.locator(`[data-testid="segment-row"][data-chunk-id="${chunkId}"]`);
}

export async function chunkIdOrder(page: Page): Promise<string[]> {
  return page.getByTestId("segment-row").evaluateAll((els) =>
    els.map((el) => el.getAttribute("data-chunk-id") ?? ""),
  );
}

export async function textOrder(page: Page): Promise<string[]> {
  return page
    .getByTestId("segment-row")
    .locator('[data-testid="seg-text"]')
    .evaluateAll((els) => els.map((el) => (el as HTMLInputElement).value));
}

export async function waitForRowCount(page: Page, count: number): Promise<void> {
  await expect(page.getByTestId("segment-row")).toHaveCount(count, { timeout: 20_000 });
}

export async function expectSameOrder(a: Page, b: Page): Promise<void> {
  await expect
    .poll(async () => (await chunkIdOrder(a)).join(","), { timeout: 20_000 })
    .toBe((await chunkIdOrder(b)).join(","));
}

export async function lastChunkId(page: Page): Promise<string> {
  const ids = await chunkIdOrder(page);
  return ids[ids.length - 1];
}

export async function typeText(page: Page, chunkId: string, value: string): Promise<void> {
  const input = rowByChunk(page, chunkId).getByTestId("seg-text");
  await input.click();
  await input.fill(value);
  await input.blur();
}

export async function setStart(page: Page, chunkId: string, value: number): Promise<void> {
  const input = rowByChunk(page, chunkId).getByTestId("seg-start");
  await input.click();
  await input.fill(String(value));
  await input.blur();
}

export async function setSpeaker(page: Page, chunkId: string, speakerId: string): Promise<void> {
  await rowByChunk(page, chunkId).getByTestId("seg-speaker").selectOption(speakerId);
}
