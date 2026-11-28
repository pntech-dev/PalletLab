type Props = { label: string; value?: number; max?: number };

/** Shared progress display; an absent value represents an ongoing operation of unknown duration. */
export function ProgressIndicator({ label, value, max = 100 }: Props) {
    const validMax = Number.isFinite(max) && max > 0;
    const determinate =
        value !== undefined && Number.isFinite(value) && validMax;
    const current = determinate ? Math.max(0, Math.min(value, max)) : undefined;
    return (
        <div className="ui-progress">
            <div className="ui-progress-status">
                <span>{label}</span>
                {current !== undefined ? (
                    <span aria-hidden="true">
                        {Math.round((current / max) * 100)}%
                    </span>
                ) : null}
            </div>
            <div className="ui-progress-track">
                <progress
                    className="ui-progress-native"
                    aria-label={label}
                    max={validMax ? max : 100}
                    value={current}
                />
                <span
                    className={`ui-progress-fill${current === undefined ? " is-indeterminate" : ""}`}
                    style={
                        current === undefined
                            ? undefined
                            : { width: `${(current / max) * 100}%` }
                    }
                    aria-hidden="true"
                />
            </div>
        </div>
    );
}
