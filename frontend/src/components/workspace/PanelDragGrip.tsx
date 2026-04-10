"use client";

/** Six-dot grip shown on draggable panel headers (replaces easy-to-miss braille / unicode). */
export default function PanelDragGrip() {
  return (
    <svg
      width={12}
      height={14}
      viewBox="0 0 12 14"
      className="shrink-0 text-gray-400"
      aria-hidden
    >
      <circle cx={3} cy={3.5} r={1.25} fill="currentColor" />
      <circle cx={9} cy={3.5} r={1.25} fill="currentColor" />
      <circle cx={3} cy={7} r={1.25} fill="currentColor" />
      <circle cx={9} cy={7} r={1.25} fill="currentColor" />
      <circle cx={3} cy={10.5} r={1.25} fill="currentColor" />
      <circle cx={9} cy={10.5} r={1.25} fill="currentColor" />
    </svg>
  );
}
