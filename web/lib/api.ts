import { httpBase } from "./config";
import type { Instance, ProjectMeta, ProjectSnapshot } from "./types";

export async function createProject(instance: Instance, title: string | null): Promise<ProjectMeta> {
  const res = await fetch(`${httpBase(instance)}/projects`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) {
    throw new Error(`create project failed: ${res.status}`);
  }
  return (await res.json()) as ProjectMeta;
}

export async function getProject(instance: Instance, projectId: string): Promise<ProjectSnapshot> {
  const res = await fetch(`${httpBase(instance)}/projects/${projectId}`);
  if (!res.ok) {
    throw new Error(`get project failed: ${res.status}`);
  }
  return (await res.json()) as ProjectSnapshot;
}

export async function getHealth(instance: Instance): Promise<{ status: string; instance: string }> {
  const res = await fetch(`${httpBase(instance)}/health`);
  if (!res.ok) {
    throw new Error(`health failed: ${res.status}`);
  }
  return (await res.json()) as { status: string; instance: string };
}
