"use client";

import { useEffect, useRef, useCallback, useState } from "react";

export interface ContextMenuItem {
  label: string;
  icon?: string;
  onClick?: () => void | Promise<void>;
  danger?: boolean;
  disabled?: boolean;
  separator?: boolean;
  checked?: boolean;
  submenu?: ContextMenuItem[];
}

interface ContextMenuProps {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
}

function MenuItemRow({
  item,
  onClose,
}: {
  item: ContextMenuItem;
  onClose: () => void;
}) {
  const [submenuOpen, setSubmenuOpen] = useState(false);
  const itemRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const openSubmenu = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setSubmenuOpen(true);
  }, []);

  const closeSubmenu = useCallback(() => {
    timeoutRef.current = setTimeout(() => setSubmenuOpen(false), 150);
  }, []);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  if (item.separator) {
    return <div className="h-px bg-gray-700 my-1 mx-2" role="separator" />;
  }

  const hasSubmenu = item.submenu && item.submenu.length > 0;

  return (
    <div
      ref={itemRef}
      className="relative"
      onMouseEnter={hasSubmenu ? openSubmenu : undefined}
      onMouseLeave={hasSubmenu ? closeSubmenu : undefined}
    >
      <button
        role="menuitem"
        disabled={item.disabled}
        onClick={() => {
          if (item.disabled) return;
          if (hasSubmenu) return;
          void Promise.resolve(item.onClick?.()).finally(() => {
            onClose();
          });
        }}
        className={`w-full text-left px-3 py-1.5 text-[13px] flex items-center gap-2 transition-colors rounded-sm
          ${item.disabled ? "text-gray-600 cursor-not-allowed" : ""}
          ${item.danger && !item.disabled ? "text-red-400 hover:bg-red-500/10" : ""}
          ${!item.danger && !item.disabled ? "text-gray-200 hover:bg-white/10" : ""}
        `}
      >
        {/* Checkmark / icon area */}
        <span className="w-4 text-center text-xs flex-shrink-0">
          {item.checked ? "✓" : item.icon ?? ""}
        </span>
        <span className="flex-1">{item.label}</span>
        {hasSubmenu && (
          <span className="text-gray-500 text-xs ml-2">▸</span>
        )}
      </button>

      {/* Submenu */}
      {hasSubmenu && submenuOpen && (
        <div
          className="absolute left-full top-0 ml-0.5 min-w-[170px] bg-[#1e1e32] rounded-lg shadow-xl border border-gray-700 py-1 z-[101]"
          role="menu"
          onMouseEnter={openSubmenu}
          onMouseLeave={closeSubmenu}
        >
          {item.submenu!.map((sub, idx) => (
            <MenuItemRow
              key={sub.label ?? `sep-${idx}`}
              item={sub}
              onClose={onClose}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, handleKeyDown]);

  const estimatedHeight = items.reduce(
    (acc, item) => acc + (item.separator ? 9 : 32),
    16,
  );
  const clampedX = Math.min(x, window.innerWidth - 240);
  const clampedY = Math.min(y, window.innerHeight - estimatedHeight);

  return (
    <div
      ref={menuRef}
      className="fixed z-[100] min-w-[190px] bg-[#1e1e32] rounded-lg shadow-xl border border-gray-700 py-1 animate-in fade-in zoom-in-95 duration-100"
      style={{ left: clampedX, top: clampedY }}
      role="menu"
      aria-label="Context menu"
    >
      {items.map((item, idx) => (
        <MenuItemRow
          key={item.label ?? `sep-${idx}`}
          item={item}
          onClose={onClose}
        />
      ))}
    </div>
  );
}
