import React from "react";
interface Props { status: any; }
export default function GuardrailStatus({ status }: Props) {
  if (!status) return <p className="text-gray-400">Loading guardrail status...</p>;
  const modeColors: Record<string, string> = {
    normal: "text-green-700 bg-green-50", capital_preservation: "text-yellow-700 bg-yellow-50",
    suspended: "text-red-700 bg-red-50",
  };
  return (
    <div className="space-y-3">
      <div className={`rounded-lg px-4 py-2 font-semibold ${modeColors[status.trading_mode] ?? ""}`}>
        Mode: {status.trading_mode?.replace(/_/g, " ").toUpperCase()}
        {!status.trading_allowed && status.reason && <p className="font-normal text-sm mt-1">{status.reason}</p>}
      </div>
      {status.flags?.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {status.flags.map((f: string) => (
            <span key={f} className="bg-orange-100 text-orange-700 text-xs px-2 py-1 rounded">{f.replace(/_/g, " ")}</span>
          ))}
        </div>
      )}
    </div>
  );
}
