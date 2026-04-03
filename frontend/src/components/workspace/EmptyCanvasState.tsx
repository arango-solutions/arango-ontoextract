"use client";

export default function EmptyCanvasState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-6 select-none">
      <svg
        className="w-20 h-20 text-gray-300 mb-6"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        strokeWidth={1}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"
        />
      </svg>

      <h2 className="text-lg font-semibold text-gray-500 mb-2">
        No ontology selected
      </h2>
      <p className="text-sm text-gray-400 max-w-xs mb-4">
        Select an ontology from the Asset Explorer to visualize its class graph.
      </p>
      <p className="text-xs text-gray-300">
        Or drop a document here to start extraction
      </p>

      <div className="mt-8 flex items-center gap-2 text-xs text-gray-300">
        <kbd className="px-1.5 py-0.5 bg-gray-100 border border-gray-200 rounded text-gray-400 font-mono">
          Right-click
        </kbd>
        <span>on canvas for more options</span>
      </div>
    </div>
  );
}
