"use client";

import { Suspense, use } from "react";
import { useSearchParams } from "next/navigation";

import { isInstance } from "@/lib/config";
import type { Instance } from "@/lib/types";

import { Editor } from "./Editor";

function ProjectEditor({ projectId }: { projectId: string }) {
  const searchParams = useSearchParams();
  const raw = searchParams.get("instance");
  const instance: Instance = isInstance(raw) ? raw : "lb";
  return <Editor key={`${projectId}:${instance}`} projectId={projectId} instance={instance} />;
}

export default function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  return (
    <Suspense fallback={<div className="p-8 text-sm text-slate-500">Loading…</div>}>
      <ProjectEditor projectId={projectId} />
    </Suspense>
  );
}
