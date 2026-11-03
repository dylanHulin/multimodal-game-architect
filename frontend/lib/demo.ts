/* Instant demo bundles: real generations captured once (scripts/capture-demo),
served as static files. Zero cost, offline-capable, instant jury-proof replay. */

export interface DemoManifestEntry {
  id: string;
  title: string;
  genre: string;
  docType: string;
  engine: string;
  file: string;
  thumb: string;
}

export interface DemoBundleImage {
  asset_type: string;
  prompt_used: string;
  file: string;
  status: string;
}

export interface DemoBundle {
  id: string;
  title: string;
  genre: string;
  engine: string;
  docType: string;
  gdd: Record<string, unknown>;
  code: Record<string, unknown> | null;
  images: DemoBundleImage[];
}

export async function loadManifest(): Promise<DemoManifestEntry[]> {
  const res = await fetch('/demo/manifest.json');
  if (!res.ok) throw new Error('manifest');
  const data: unknown = await res.json();
  if (!Array.isArray(data)) throw new Error('manifest');
  return data as DemoManifestEntry[];
}

export async function loadBundle(entry: DemoManifestEntry): Promise<DemoBundle> {
  const res = await fetch(`/demo/${entry.file}`);
  if (!res.ok) throw new Error('bundle');
  return (await res.json()) as DemoBundle;
}
