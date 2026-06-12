import React from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

interface Props { data: number[]; }

export default function EquityCurve({ data }: Props) {
  const chartData = data.map((v, i) => ({ day: i, value: Math.round(v) }));
  if (chartData.length < 2) return <div className="flex items-center justify-center h-48 text-gray-400">No equity data yet</div>;
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="day" label={{ value: "Days", position: "insideBottom", offset: -5 }} />
        <YAxis tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
        <Tooltip formatter={(v: number) => [`$${v.toLocaleString()}`, "Portfolio"]} />
        <Line type="monotone" dataKey="value" stroke="#3b82f6" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
