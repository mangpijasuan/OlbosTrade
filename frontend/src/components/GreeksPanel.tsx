import React from "react";
interface Props { greeks: any; }
export default function GreeksPanel({ greeks }: Props) {
  const items = [
    { label: "Net Δ Delta", value: greeks?.net_delta?.toFixed(4) ?? "—", limit: "±0.30" },
    { label: "Net Θ Theta", value: greeks?.net_theta?.toFixed(4) ?? "—", note: "daily" },
    { label: "Net ν Vega", value: greeks?.net_vega?.toFixed(4) ?? "—", limit: "±0.15" },
    { label: "Net Γ Gamma", value: greeks?.net_gamma?.toFixed(4) ?? "—" },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {items.map(item => (
        <div key={item.label} className="bg-gray-50 rounded-lg p-3">
          <p className="text-xs text-gray-500">{item.label}</p>
          <p className="text-lg font-semibold">{item.value}</p>
          {item.limit && <p className="text-xs text-gray-400">Limit: {item.limit}</p>}
        </div>
      ))}
    </div>
  );
}
