export function formatTimecode(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "––:––";
  const total = Math.max(0, Math.floor(ms));
  const m = Math.floor(total / 60000);
  const s = Math.floor((total % 60000) / 1000);
  const cs = Math.floor((total % 1000) / 10);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
}

export function initials(id: string): string {
  return id.slice(0, 2).toUpperCase();
}
