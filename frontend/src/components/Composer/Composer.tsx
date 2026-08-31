import { useRef, useEffect } from 'react';

interface Props {
  placeholder?: string;
  onSubmit: (text: string) => void;
  disabled?: boolean;
  initialValue?: string;
  allowEmpty?: boolean;
}

export function Composer({ placeholder = 'Ask anything about AI, ML, or coding…', onSubmit, disabled, initialValue, allowEmpty }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!disabled) ref.current?.focus();
  }, [disabled]);

  useEffect(() => {
    if (initialValue !== undefined && ref.current) {
      ref.current.value = initialValue;
      ref.current.style.height = 'auto';
      ref.current.style.height = `${Math.min(ref.current.scrollHeight, 160)}px`;
    }
  }, [initialValue]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const val = ref.current?.value.trim() ?? '';
      if (val || allowEmpty) onSubmit(val);
    }
  };

  const handleSend = () => {
    const val = ref.current?.value.trim() ?? '';
    if (val || allowEmpty) {
      onSubmit(val);
      if (ref.current) ref.current.value = '';
    }
  };

  const handleInput = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <div className="relative flex w-full items-end rounded-2xl border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-4 py-3 transition-colors focus-within:border-[var(--color-border-focus)]">
      <textarea
        ref={ref}
        rows={1}
        placeholder={placeholder}
        disabled={disabled}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        className="max-h-40 min-h-[24px] w-full resize-none bg-transparent text-sm leading-6 text-[var(--color-text-primary)] outline-none placeholder:text-[var(--color-text-muted)]"
      />
      <button
        type="button"
        onClick={handleSend}
        disabled={disabled}
        className="ml-3 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--color-text-primary)] text-[var(--color-bg-primary)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14M12 5l7 7-7 7" />
        </svg>
      </button>
    </div>
  );
}
