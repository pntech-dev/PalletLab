import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown } from "lucide-react";

export type ComboboxOption<T extends string = string> = {
  value: T;
  label: string;
};

type ComboboxProps<T extends string = string> = {
  id?: string;
  value: T;
  options: readonly ComboboxOption<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  variant?: "surface" | "field";
  ariaLabel?: string;
  ariaLabelledBy?: string;
  onOpenChange?: (open: boolean) => void;
};

type MenuPosition = {
  top: number;
  left: number;
  minWidth: number;
  maxHeight: number;
};

/** Custom accessible select control styled after the Figma Combobox and Menu specs. */
export function Combobox<T extends string = string>({
  id,
  value,
  options,
  onChange,
  placeholder = "",
  disabled = false,
  className = "",
  variant = "field",
  ariaLabel,
  ariaLabelledBy,
  onOpenChange,
}: ComboboxProps<T>) {
  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [menuPos, setMenuPos] = useState<MenuPosition | null>(null);
  const onOpenChangeRef = useRef(onOpenChange);
  onOpenChangeRef.current = onOpenChange;

  useEffect(() => {
    onOpenChangeRef.current?.(open);
  }, [open]);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const listboxId = useId();

  const selectedIndex = options.findIndex((option) => option.value === value);
  const selectedOption = selectedIndex >= 0 ? options[selectedIndex] : undefined;
  const displayLabel = selectedOption?.label ?? placeholder;
  const isPlaceholder = !selectedOption && Boolean(placeholder);

  function closeMenu(restoreFocus = false) {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }

  function commitSelection(option: ComboboxOption<T>) {
    closeMenu(true);
    if (option.value !== value) {
      onChange(option.value);
    }
  }

  function updatePosition() {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const gap = 4;
    const viewportMargin = 8;
    const minWidth = Math.max(rect.width, 96);
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - gap - viewportMargin);
    const spaceAbove = Math.max(0, rect.top - gap - viewportMargin);
    const preferredHeight = Math.min(options.length * 36, 288);
    const openUpward = spaceBelow < Math.min(preferredHeight, 144) && spaceAbove > spaceBelow;
    const availableSpace = openUpward ? spaceAbove : spaceBelow;
    const maxHeight = Math.max(72, Math.min(288, availableSpace));
    const renderedHeight = Math.min(preferredHeight, maxHeight);
    const top = openUpward
      ? Math.max(viewportMargin, rect.top - gap - renderedHeight)
      : rect.bottom + gap;
    const measuredWidth = menuRef.current?.offsetWidth ?? minWidth;
    const maxLeft = Math.max(viewportMargin, window.innerWidth - measuredWidth - viewportMargin);
    const left = Math.max(viewportMargin, Math.min(rect.left, maxLeft));
    setMenuPos({ top, left, minWidth, maxHeight });
  }

  useLayoutEffect(() => {
    if (!open) {
      setMenuPos(null);
      return;
    }
    updatePosition();
    const onViewportChange = () => updatePosition();
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [open, options.length]);

  useEffect(() => {
    if (!open) return;
    setHighlightedIndex(selectedIndex >= 0 ? selectedIndex : 0);
  }, [open, selectedIndex]);

  useEffect(() => {
    if (!open) return;
    if (disabled || options.length === 0) {
      setOpen(false);
    }
  }, [disabled, open, options.length]);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => document.removeEventListener("pointerdown", handlePointerDown, true);
  }, [open]);

  useEffect(() => {
    if (!open || highlightedIndex < 0) return;
    optionRefs.current[highlightedIndex]?.scrollIntoView({ block: "nearest" });
  }, [open, highlightedIndex]);

  function handleTriggerKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (disabled || options.length === 0) return;
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setOpen(true);
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeMenu(true);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((current) => (current + 1) % options.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((current) => (current <= 0 ? options.length - 1 : current - 1));
    } else if (event.key === "Home") {
      event.preventDefault();
      setHighlightedIndex(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setHighlightedIndex(options.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const target = options[highlightedIndex] ?? selectedOption ?? options[0];
      if (target) commitSelection(target);
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-activedescendant={open && highlightedIndex >= 0 ? `${listboxId}-opt-${highlightedIndex}` : undefined}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        disabled={disabled}
        className={[
          "ui-combobox-trigger",
          `ui-combobox-trigger--${variant}`,
          isPlaceholder ? "is-placeholder" : "",
          className,
        ].filter(Boolean).join(" ")}
        onClick={(event) => {
          event.stopPropagation();
          if (disabled || options.length === 0) return;
          setOpen((current) => !current);
        }}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="ui-combobox-value">{displayLabel}</span>
        <ChevronDown className="ui-combobox-arrow" size={16} aria-hidden="true" />
      </button>
      {open && menuPos ? createPortal(
        <div
          ref={menuRef}
          id={listboxId}
          role="listbox"
          className="ui-combobox-menu"
          data-in-viewport={triggerRef.current?.closest(".viewport") ? "true" : undefined}
          style={{
            top: `${menuPos.top}px`,
            left: `${menuPos.left}px`,
            minWidth: `${menuPos.minWidth}px`,
            maxHeight: `${menuPos.maxHeight}px`,
          }}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
        >
          {options.map((option, index) => {
            const selected = option.value === value;
            const highlighted = index === highlightedIndex;
            return (
              <button
                key={option.value}
                ref={(el) => {
                  optionRefs.current[index] = el;
                }}
                id={`${listboxId}-opt-${index}`}
                type="button"
                role="option"
                aria-selected={selected}
                tabIndex={-1}
                className={[
                  "ui-combobox-option",
                  selected ? "is-selected" : "",
                  highlighted ? "is-highlighted" : "",
                ].filter(Boolean).join(" ")}
                onMouseEnter={() => setHighlightedIndex(index)}
                onClick={() => commitSelection(option)}
              >
                {option.label}
              </button>
            );
          })}
        </div>,
        document.body,
      ) : null}
    </>
  );
}
