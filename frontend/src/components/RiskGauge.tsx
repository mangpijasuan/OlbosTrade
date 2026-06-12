import React from "react";
interface Props { label: string; value: number; max: number; unit: string; }
export default function RiskGauge({ label, value, max, unit }: Props) {
  const pct = Math.min((value / max) * 100, 100);
  const color = pct < 60 ? "bg-green-500" : pct < 85 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-600">{label}</span>
        <span className="font-semibold">{value.toFixed(2)}{unit}</span>
      </div>
      <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-gray-400 mt-1">Limit: {max}{unit}</p>
    </div>
  );
}
