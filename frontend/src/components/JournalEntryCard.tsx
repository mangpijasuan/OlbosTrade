import React from "react";
interface Props { entry: any; }
export default function JournalEntryCard({ entry }: Props) {
  return (
    <div className="bg-white border rounded-xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-semibold capitalize">{entry.strategy?.replace(/_/g, " ") ?? "Unknown"} — {entry.underlying ?? ""}</p>
          <p className="text-sm text-gray-500">{entry.entry_date ?? "No date"}</p>
        </div>
        <div className="text-right">
          {entry.pnl !== null && entry.pnl !== undefined && (
            <p className={`font-bold ${entry.pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
              {entry.pnl >= 0 ? "+" : ""}${entry.pnl.toFixed(0)}
            </p>
          )}
          {entry.followed_rules !== null && entry.followed_rules !== undefined && (
            <p className={`text-xs ${entry.followed_rules ? "text-green-600" : "text-red-500"}`}>
              {entry.followed_rules ? "✓ Rules followed" : "✗ Rules breached"}
            </p>
          )}
        </div>
      </div>
      {entry.pre_trade_thesis && <p className="text-sm text-gray-700">{entry.pre_trade_thesis}</p>}
      {entry.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {entry.tags.map((t: string) => (
            <span key={t} className="bg-blue-50 text-blue-600 text-xs px-2 py-0.5 rounded">{t}</span>
          ))}
        </div>
      )}
    </div>
  );
}
