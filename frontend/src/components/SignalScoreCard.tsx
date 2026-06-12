import React from "react";
interface Props { signal: any; }
export default function SignalScoreCard({ signal }: Props) {
  const score = signal.score ?? 0;
  const approved = signal.approved ?? false;
  return (
    <div className={`border rounded-xl p-4 ${approved ? "border-green-300 bg-green-50" : "border-gray-200 bg-white"}`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="font-semibold">{signal.strategy?.replace(/_/g, " ")} — {signal.underlying}</p>
          <p className="text-sm text-gray-500">Score: {score.toFixed(3)}</p>
        </div>
        <span className={`px-3 py-1 rounded-full text-sm font-medium ${approved ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
          {approved ? "APPROVE" : "REJECT"}
        </span>
      </div>
    </div>
  );
}
