import type { CSSProperties, InputHTMLAttributes } from "react";

type Props = Omit<
    InputHTMLAttributes<HTMLInputElement>,
    "type" | "value" | "min" | "max"
> & {
    value: number;
    min: number;
    max: number;
};

/** Native range input with a token-based track and thumb. */
export function Slider({
    value,
    min,
    max,
    style,
    className = "",
    ...props
}: Props) {
    const fraction =
        max > min ? Math.max(0, Math.min(1, (value - min) / (max - min))) : 0;
    const sliderStyle = {
        ...style,
        "--slider-progress": `${fraction * 100}%`,
    } as CSSProperties;
    return (
        <input
            {...props}
            className={`ui-slider ${className}`}
            type="range"
            min={min}
            max={max}
            value={value}
            style={sliderStyle}
        />
    );
}
