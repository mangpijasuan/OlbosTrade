import React from "react";
interface Props { metrics: any; }
export default function MetricsBar({ metrics }: Props) {
  if (!metrics) return null;
  const items = [
    { label: "Total Return", value: `${(metrics.total_return_pct * 100).toFixed(1)}%`, positive: metrics.total_return_pct >= 0 },
    { label: "Sharpe", value: metrics.sharpe_ratio?.toFixed(2) },
    { label: "Sortino", value: metrics.sortino_ratio?.toFixed(2) },
    { label: "Max DD", value: `${(metrics.max_drawdown_pct * 100).toFixed(1)}%`, positive: false },
    { label: "Win Rate", value: `${(metrics.win_rate * 100).toFixed(0)}%`, positive: metrics.win_rate >= 0.5 },
    { label: "Profit Factor", value: metrics.profit_factor?.toFixed(2), positive: metrics.profit_factor >= 1 },
    { label: "Trades", value: metrics.total_trades },
    { label: "Comm. Drag", value: `${(metrics.commission_drag_pct * 100).toFixed(2)}%` },
  ];
  return (
    <div className="grid grid-cols-4 md:grid-cols-8 gap-3">
      {items.map(item => (
        <div key={item.label} className="bg-white rounded-xl shadow p-3 text-center">
          <p className="text-xs text-gray-500">{item.label}</p>
          <p className={`text-lg font-bold ${item.positive === true ? "text-green-600" : item.positive === false ? "text-red-600" : ""}`}>
            {item.value}
          </p>
        </div>
      ))}
    </div>
  );
}
