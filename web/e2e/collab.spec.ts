import { test, expect, type BrowserContext, type Page } from "@playwright/test";

import {
  APP1_HTTP,
  SPEAKERS,
  chunkIdOrder,
  createProject,
  expectSameOrder,
  getSnapshot,
  lastChunkId,
  openEditor,
  rowByChunk,
  setSpeaker,
  setStart,
  textOrder,
  typeText,
  waitForRowCount,
} from "./helpers";

interface Pair {
  ctxA: BrowserContext;
  ctxB: BrowserContext;
  a: Page;
  b: Page;
  projectId: string;
}

// use:{video} is ignored for contexts created via browser.newContext(); set recordVideo explicitly.
const recordVideo = process.env.PW_VIDEO ? { dir: "test-results/videos" } : undefined;

async function setupPair(browser: import("@playwright/test").Browser): Promise<Pair> {
  const projectId = await createProject(APP1_HTTP);
  const ctxA = await browser.newContext({ recordVideo });
  const ctxB = await browser.newContext({ recordVideo });
  const a = await ctxA.newPage();
  const b = await ctxB.newPage();
  await openEditor(a, projectId, "app1");
  await openEditor(b, projectId, "app2");
  return { ctxA, ctxB, a, b, projectId };
}

async function teardown(pair: Pair): Promise<void> {
  const videoA = pair.a.video();
  const videoB = pair.b.video();
  await pair.ctxA.close();
  await pair.ctxB.close();
  if (videoA) console.log(`  🎬 video (A/app1): ${await videoA.path()}`);
  if (videoB) console.log(`  🎬 video (B/app2): ${await videoB.path()}`);
}

test.describe("cross-instance collaborative subtitles", () => {
  test("1. create + type text converges A(app1) -> B(app2)", async ({ browser }) => {
    const pair = await setupPair(browser);
    try {
      await pair.a.getByTestId("add-segment").click();
      await waitForRowCount(pair.a, 1);
      const chunkId = (await chunkIdOrder(pair.a))[0];
      await typeText(pair.a, chunkId, "hello from A");

      await waitForRowCount(pair.b, 1);
      await expect(rowByChunk(pair.b, chunkId).getByTestId("seg-text")).toHaveValue("hello from A");
    } finally {
      await teardown(pair);
    }
  });

  test("2. concurrent edits to same text converge to one value (LWW)", async ({ browser }) => {
    const pair = await setupPair(browser);
    try {
      await pair.a.getByTestId("add-segment").click();
      await waitForRowCount(pair.a, 1);
      const chunkId = (await chunkIdOrder(pair.a))[0];
      await waitForRowCount(pair.b, 1);

      await Promise.all([
        typeText(pair.a, chunkId, "AAA-version"),
        typeText(pair.b, chunkId, "BBB-version"),
      ]);

      await expect
        .poll(
          async () => {
            const va = await rowByChunk(pair.a, chunkId).getByTestId("seg-text").inputValue();
            const vb = await rowByChunk(pair.b, chunkId).getByTestId("seg-text").inputValue();
            return va === vb ? va : null;
          },
          { timeout: 20_000 },
        )
        .not.toBeNull();

      const snap = await getSnapshot(APP1_HTTP, pair.projectId);
      const seg = snap.segments.find((s) => s.chunk_id === chunkId);
      const converged = await rowByChunk(pair.a, chunkId).getByTestId("seg-text").inputValue();
      expect(seg?.text).toBe(converged);
    } finally {
      await teardown(pair);
    }
  });

  test("3. concurrent edits to different fields both survive", async ({ browser }) => {
    const pair = await setupPair(browser);
    try {
      await pair.a.getByTestId("add-segment").click();
      await waitForRowCount(pair.a, 1);
      const chunkId = (await chunkIdOrder(pair.a))[0];
      await waitForRowCount(pair.b, 1);

      await Promise.all([
        setStart(pair.a, chunkId, 4242),
        setSpeaker(pair.b, chunkId, SPEAKERS.C),
      ]);

      for (const page of [pair.a, pair.b]) {
        await expect(rowByChunk(page, chunkId).getByTestId("seg-start")).toHaveValue("4242");
        await expect(rowByChunk(page, chunkId).getByTestId("seg-speaker")).toHaveValue(SPEAKERS.C);
      }

      const snap = await getSnapshot(APP1_HTTP, pair.projectId);
      const seg = snap.segments.find((s) => s.chunk_id === chunkId);
      expect(seg?.start_time_ms).toBe(4242);
      expect(seg?.speaker_id).toBe(SPEAKERS.C);
    } finally {
      await teardown(pair);
    }
  });

  test("4. add 3 + reorder converges row order", async ({ browser }) => {
    const pair = await setupPair(browser);
    try {
      for (let i = 0; i < 3; i += 1) {
        await pair.a.getByTestId("add-segment").click();
        await waitForRowCount(pair.a, i + 1);
      }
      await waitForRowCount(pair.b, 3);
      const initial = await chunkIdOrder(pair.a);

      const last = initial[2];
      await rowByChunk(pair.a, last).getByTestId("seg-up").click();
      await expect
        .poll(async () => (await chunkIdOrder(pair.a))[1], { timeout: 20_000 })
        .toBe(last);

      const first = initial[0];
      await rowByChunk(pair.a, first).getByTestId("seg-down").click();

      await expectSameOrder(pair.a, pair.b);

      const snap = await getSnapshot(APP1_HTTP, pair.projectId);
      const backendOrder = snap.segments.map((s) => s.chunk_id);
      expect(await chunkIdOrder(pair.b)).toEqual(backendOrder);
    } finally {
      await teardown(pair);
    }
  });

  test("5. delete removes segment for the peer", async ({ browser }) => {
    const pair = await setupPair(browser);
    try {
      await pair.a.getByTestId("add-segment").click();
      await pair.a.getByTestId("add-segment").click();
      await waitForRowCount(pair.a, 2);
      await waitForRowCount(pair.b, 2);
      const ids = await chunkIdOrder(pair.a);
      const target = ids[0];

      await rowByChunk(pair.a, target).getByTestId("seg-delete").click();

      await expect(rowByChunk(pair.b, target)).toHaveCount(0, { timeout: 20_000 });
      await waitForRowCount(pair.b, 1);
    } finally {
      await teardown(pair);
    }
  });

  test("6. undo reverts an edit visibly to the peer", async ({ browser }) => {
    const pair = await setupPair(browser);
    try {
      await pair.a.getByTestId("add-segment").click();
      await waitForRowCount(pair.a, 1);
      const chunkId = (await chunkIdOrder(pair.a))[0];
      await waitForRowCount(pair.b, 1);

      await typeText(pair.a, chunkId, "original");
      await expect(rowByChunk(pair.b, chunkId).getByTestId("seg-text")).toHaveValue("original");

      await typeText(pair.a, chunkId, "changed");
      await expect(rowByChunk(pair.b, chunkId).getByTestId("seg-text")).toHaveValue("changed");

      await pair.a.getByTestId("undo").click();

      await expect(rowByChunk(pair.b, chunkId).getByTestId("seg-text")).toHaveValue("original", {
        timeout: 20_000,
      });
    } finally {
      await teardown(pair);
    }
  });

  test("7. presence chip appears for a focused peer", async ({ browser }) => {
    const pair = await setupPair(browser);
    try {
      await pair.a.getByTestId("add-segment").click();
      await waitForRowCount(pair.a, 1);
      const chunkId = (await chunkIdOrder(pair.a))[0];
      await waitForRowCount(pair.b, 1);

      await rowByChunk(pair.a, chunkId).getByTestId("seg-text").click();

      await expect(pair.b.getByTestId("presence-chip")).toHaveCount(1, { timeout: 20_000 });
      await expect(pair.b.getByTestId("presence-chip").first()).toBeVisible();
    } finally {
      await teardown(pair);
    }
  });

  test("8. reload B resyncs to converged state", async ({ browser }) => {
    const pair = await setupPair(browser);
    try {
      await pair.a.getByTestId("add-segment").click();
      await pair.a.getByTestId("add-segment").click();
      await waitForRowCount(pair.a, 2);
      const ids = await chunkIdOrder(pair.a);
      await typeText(pair.a, ids[0], "persisted-one");
      await typeText(pair.a, ids[1], "persisted-two");
      await waitForRowCount(pair.b, 2);

      await pair.b.reload();
      await expect(pair.b.getByTestId("conn-status")).toHaveText("live", { timeout: 20_000 });
      await waitForRowCount(pair.b, 2);

      await expectSameOrder(pair.a, pair.b);
      await expect.poll(async () => (await textOrder(pair.b)).join("|"), { timeout: 20_000 }).toBe(
        (await textOrder(pair.a)).join("|"),
      );
    } finally {
      await teardown(pair);
    }
  });

  test("9. randomized stress simulation converges and matches backend", async ({ browser }) => {
    test.setTimeout(180_000);
    const pair = await setupPair(browser);
    try {
      for (let i = 0; i < 4; i += 1) {
        await pair.a.getByTestId("add-segment").click();
        await waitForRowCount(pair.a, i + 1);
      }
      await waitForRowCount(pair.b, 4);

      const pages = [pair.a, pair.b];
      let rng = 123456789;
      const rand = () => {
        rng = (rng * 1103515245 + 12345) & 0x7fffffff;
        return rng / 0x7fffffff;
      };
      const speakerVals = [SPEAKERS.A, SPEAKERS.B, SPEAKERS.C, SPEAKERS.D];

      for (let i = 0; i < 30; i += 1) {
        const page = pages[Math.floor(rand() * pages.length)];
        const ids = await chunkIdOrder(page);
        const action = rand();
        if (action < 0.2 || ids.length === 0) {
          await page.getByTestId("add-segment").click();
        } else if (action < 0.5) {
          const id = ids[Math.floor(rand() * ids.length)];
          await typeText(page, id, `s${i}-${Math.floor(rand() * 1000)}`);
        } else if (action < 0.65) {
          const id = ids[Math.floor(rand() * ids.length)];
          await setSpeaker(page, id, speakerVals[Math.floor(rand() * speakerVals.length)]);
        } else if (action < 0.82 && ids.length > 1) {
          const idx = Math.floor(rand() * ids.length);
          const id = ids[idx];
          const dir = idx === 0 ? "down" : "up";
          await rowByChunk(page, id).getByTestId(`seg-${dir}`).click();
        } else if (action < 0.92 && ids.length > 2) {
          const id = ids[Math.floor(rand() * ids.length)];
          await rowByChunk(page, id).getByTestId("seg-delete").click();
        } else {
          const id = ids[Math.floor(rand() * ids.length)];
          await setStart(page, id, Math.floor(rand() * 100000));
        }
        await page.waitForTimeout(60);
      }

      const normalize = async (p: Page) => {
        const ids = await chunkIdOrder(p);
        const out: string[] = [];
        for (const id of ids) {
          const row = rowByChunk(p, id);
          const text = await row.getByTestId("seg-text").inputValue();
          const start = await row.getByTestId("seg-start").inputValue();
          const speaker = await row.getByTestId("seg-speaker").inputValue();
          out.push(`${id}|${text}|${start}|${speaker}`);
        }
        return out.join("\n");
      };

      await expect
        .poll(async () => (await chunkIdOrder(pair.a)).join(","), { timeout: 30_000 })
        .toBe((await chunkIdOrder(pair.b)).join(","));

      await expect
        .poll(async () => normalize(pair.a), { timeout: 30_000 })
        .toBe(await normalize(pair.b));

      const snap = await getSnapshot(APP1_HTTP, pair.projectId);
      const backendIds = snap.segments.map((s) => s.chunk_id);
      expect(await chunkIdOrder(pair.a)).toEqual(backendIds);

      const backendNorm = snap.segments
        .map((s) => `${s.chunk_id}|${s.text ?? ""}|${s.start_time_ms ?? ""}|${s.speaker_id ?? ""}`)
        .join("\n");
      expect(await normalize(pair.a)).toBe(backendNorm);
    } finally {
      await teardown(pair);
    }
  });
});
