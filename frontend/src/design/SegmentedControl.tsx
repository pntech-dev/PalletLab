import { useId } from "react";

type Option<T extends string> = { value: T; label: string; disabled?: boolean };

type Props<T extends string> = {
  label: string;
  value: T;
  options: readonly Option<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
};

/** A native radio group styled as the UI Kit segment control. */
export function SegmentedControl<T extends string>({ label, value, options, onChange, disabled }: Props<T>) {
  const name = useId();
  return <div className="ui-segmented" role="radiogroup" aria-label={label}>
    {options.map((option) => <label className="ui-segmented-option" key={option.value}>
      <input type="radio" name={name} value={option.value} checked={value === option.value}
        disabled={disabled || option.disabled} onChange={() => onChange(option.value)} />
      <span>{option.label}</span>
    </label>)}
  </div>;
}
