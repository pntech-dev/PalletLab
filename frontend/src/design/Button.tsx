import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "secondary" | "tertiary" | "ghost" | "danger";
};

/** Shared button behavior and design-system variants. */
export function Button({
    variant,
    className = "",
    type = "button",
    ...props
}: ButtonProps) {
    return (
        <button
            type={type}
            className={[
                "ui-button",
                variant && `ui-button--${variant}`,
                className,
            ]
                .filter(Boolean)
                .join(" ")}
            {...props}
        />
    );
}
