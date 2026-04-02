"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

interface Props {
  winLoss: {
    graph_wins: number;
    vector_wins: number;
    ties: number;
  };
}

const COLORS = {
  graph: "#6366f1",
  vector: "#f97316",
  tie: "#d1d5db",
};

export default function RagWinLoss({ winLoss }: Props) {
  const total = winLoss.graph_wins + winLoss.vector_wins + winLoss.ties;
  const data = [
    { name: "GraphRAG Wins", value: winLoss.graph_wins, color: COLORS.graph },
    { name: "VectorRAG Wins", value: winLoss.vector_wins, color: COLORS.vector },
    { name: "Ties", value: winLoss.ties, color: COLORS.tie },
  ];

  const graphPct = ((winLoss.graph_wins / total) * 100).toFixed(0);
  const vectorPct = ((winLoss.vector_wins / total) * 100).toFixed(0);
  const tiePct = ((winLoss.ties / total) * 100).toFixed(0);

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">
        Win / Loss / Tie
      </h3>
      <div className="flex items-center gap-4">
        <div className="w-[160px] h-[160px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={40}
                outerRadius={70}
                paddingAngle={3}
                dataKey="value"
                strokeWidth={0}
              >
                {data.map((entry, i) => (
                  <Cell key={i} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
                formatter={(value, name) => [
                  `${value} queries (${((Number(value) / total) * 100).toFixed(0)}%)`,
                  name,
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="flex-1 space-y-3">
          <div className="flex items-center gap-2">
            <span
              className="w-3 h-3 rounded-full"
              style={{ background: COLORS.graph }}
            />
            <span className="text-sm text-gray-700 flex-1">GraphRAG Wins</span>
            <span className="text-sm font-bold text-indigo-700">
              {winLoss.graph_wins}{" "}
              <span className="text-xs font-normal text-gray-400">
                ({graphPct}%)
              </span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span
              className="w-3 h-3 rounded-full"
              style={{ background: COLORS.vector }}
            />
            <span className="text-sm text-gray-700 flex-1">VectorRAG Wins</span>
            <span className="text-sm font-bold text-orange-600">
              {winLoss.vector_wins}{" "}
              <span className="text-xs font-normal text-gray-400">
                ({vectorPct}%)
              </span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span
              className="w-3 h-3 rounded-full"
              style={{ background: COLORS.tie }}
            />
            <span className="text-sm text-gray-700 flex-1">Ties</span>
            <span className="text-sm font-bold text-gray-500">
              {winLoss.ties}{" "}
              <span className="text-xs font-normal text-gray-400">
                ({tiePct}%)
              </span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
