export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not found";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") {
    const pair = value as Record<string, unknown>;
    if ("systolic" in pair && "diastolic" in pair) {
      return `${String(pair.systolic)}/${String(pair.diastolic)}`;
    }
    return Object.entries(pair)
      .map(([key, item]) => `${key}: ${String(item)}`)
      .join(", ");
  }
  return String(value);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

export function confidenceLabel(confidence: number | null): string {
  if (confidence === null) return "No confidence";
  return `${Math.round(confidence * 100)}% confidence`;
}
