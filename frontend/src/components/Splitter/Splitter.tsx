import { useState, useCallback, useEffect, useRef } from 'react';

interface Props {
  onResize?: (width: number) => void;
  initialWidth?: number;
  minWidth?: number;
  maxWidth?: number;
}

export function Splitter({ onResize, initialWidth: _initialWidth = 384, minWidth = 280, maxWidth = 600 }: Props) {
  const [dragging, setDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  useEffect(() => {
    if (!dragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const container = containerRef.current?.parentElement;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const clamped = Math.min(maxWidth, Math.max(minWidth, rect.width - x));
      onResize?.(clamped);
    };

    const handleMouseUp = () => setDragging(false);

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [dragging, minWidth, maxWidth, onResize]);

  return (
    <div
      ref={containerRef}
      onMouseDown={handleMouseDown}
      className={`group relative z-10 flex w-1.5 shrink-0 cursor-col-resize items-center justify-center transition-colors ${
        dragging
          ? 'bg-[var(--color-accent)]/20'
          : 'hover:bg-[var(--color-accent)]/10'
      }`}
    >
      <div
        className={`h-8 w-0.5 rounded-full transition-colors ${
          dragging
            ? 'bg-[var(--color-accent)]'
            : 'bg-[var(--color-border-default)] group-hover:bg-[var(--color-accent)]'
        }`}
      />
    </div>
  );
}
