import React from "react";

interface Trade { strategy: string; entry_date: string; exit_date?: string; pnl: number; exit_reason: string; signal_score: number; }
interface Props { trades: Trade[]; }

export default function TradeTable({ trades }: Props) {
  if (!trades.length) return <p className="text-gray-400 text-sm">No trades</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="text-left text-gray-500 border-b">
          <th className="pb-2">Strategy</th><th className="pb-2">Entry</th><th className="pb-2">Exit</th>
          <th className="pb-2">P&L</th><th className="pb-2">Exit Reason</th><th className="pb-2">Score</th>
        </tr></thead>
        <tbody>
          {trades.slice(0, 100).map((t, i) => (
            <tr key={i} className="border-b hover:bg-gray-50">
              <td className="py-1 capitalize">{t.strategy?.replace(/_/g, " ")}</td>
              <td>{t.entry_date}</td>
              <td>{t.exit_date ?? "—"}</td>
              <td className={t.pnl >= 0 ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
                {t.pnl >= 0 ? "+" : ""}${t.pnl?.toFixed(0)}
              </td>
              <td className="text-gray-500">{t.exit_reason}</td>
              <td>{t.signal_score?.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {trades.length > 100 && <p className="text-sm text-gray-400 mt-2">Showing 100 of {trades.length} trades</p>}
    </div>
  );
}
