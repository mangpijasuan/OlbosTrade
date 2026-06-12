import React from "react";
interface Props { position: any; }
export default function PositionCard({ position }: Props) {
  return (
    <div className="bg-white border rounded-xl p-4 flex items-center justify-between">
      <div>
        <p className="font-semibold">{position.symbol ?? "—"}</p>
        <p className="text-sm text-gray-500">{position.strategy ?? position.option_type}</p>
      </div>
      <div className="text-right">
        <p className={`font-semibold ${(position.unrealized_pnl ?? 0) >= 0 ? "text-green-600" : "text-red-600"}`}>
          {(position.unrealized_pnl ?? 0) >= 0 ? "+" : ""}${(position.unrealized_pnl ?? 0).toFixed(0)}
        </p>
        <p className="text-sm text-gray-400">{position.quantity ?? 0} contracts</p>
      </div>
    </div>
  );
}
