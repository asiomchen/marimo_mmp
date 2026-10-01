export function resolveDepiction(depictions: Record<string, string> | null, depictionId: string | null): string | null {
  if (!depictionId || !depictions || typeof depictions !== "object") return null;
  const source = depictions[depictionId];
  return typeof source === "string" && source ? source : null;
}
