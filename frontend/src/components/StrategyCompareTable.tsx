import React from "react";
interface Props { comparison: any; }
export default function StrategyCompareTable({ comparison }: Props) {
  const rankings = comparison?.rankings ?? [];
  return (
    <div className="bg-white rounded-xl shadow p-4">
      <h2 className="font-semibold mb-3">Strategy Rankings (by Sharpe Ratio)</h2>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-gray-500 border-b">
          <th className="pb-2">Rank</th><th className="pb-2">Strategy</th>
          <th className="pb-2">Sharpe</th><th className="pb-2">Return</th>
          <th className="pb-2">Win%</th><th className="pb-2">Max DD</th><th className="pb-2">Trades</th>
        </tr></thead>
        <tbody>
          {rankings.map((r: any) => (
            <tr key={r.strategy} className={`border-b ${r.rank === 1 ? "bg-yellow-50" : ""}`}>
              <td className="py-2">{r.rank === 1 ? "🥇" : r.rank === 2 ? "🥈" : r.rank === 3 ? "🥉" : r.rank}</td>
              <td className="capitalize">{r.strategy.replace(/_/g, " ")}</td>
              <td className="font-semibold">{r.sharpe_ratio.toFixed(2)}</td>
              <td className={r.total_return_pct >= 0 ? "text-green-600" : "text-red-600"}>
                {(r.total_return_pct * 100).toFixed(1)}%
              </td>
              <td>{(r.win_rate * 100).toFixed(0)}%</td>
              <td className="text-red-600">{(r.max_drawdown_pct * 100).toFixed(1)}%</td>
              <td>{r.total_trades}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
