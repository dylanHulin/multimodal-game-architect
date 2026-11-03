/* Visible fallback notice for mock/placeholder/error generation output.
 * Renders nothing on success so call sites need no status check. */

const TONE: Record<string, string> = {
  mock: 'bg-amber-900/40 text-amber-300 border-amber-500/30',
  placeholder: 'bg-amber-900/40 text-amber-300 border-amber-500/30',
};

export default function FallbackBadge({
  status,
  message,
}: {
  status?: string;
  message: string;
}) {
  if (!status || status === 'success') return null;
  const tone = TONE[status] ?? 'bg-red-900/40 text-red-300 border-red-500/30';
  return (
    <p role="status" className={`text-xs border rounded-lg px-2 py-1 mb-2 ${tone}`}>
      <span className="font-bold uppercase">{status}</span>
      <span className="opacity-80"> — {message}</span>
    </p>
  );
}
