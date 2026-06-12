import React from "react";
interface Props { mode: string; }
export default function CapitalModeBanner({ mode }: Props) {
  if (mode === "capital_preservation") return (
    <div className="bg-yellow-50 border border-yellow-300 rounded-xl p-4 flex items-center gap-3">
      <span className="text-2xl">⚠️</span>
      <div>
        <p className="font-bold text-yellow-800">Capital Preservation Mode Active</p>
        <p className="text-yellow-700 text-sm">
          Account below 85% of starting capital. Only Bull Put Spreads and Bear Call Spreads allowed.
          Position size cut by 50%. Signal threshold raised to 0.80.
        </p>
      </div>
    </div>
  );
  return null;
}
