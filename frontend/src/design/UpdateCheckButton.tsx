import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, Info, Loader } from "lucide-react";
import { Button } from "./Button";
import {
    resolveUpdateCheckResult,
    type UpdateCheckPhase,
    type UpdateCheckState,
} from "./updateCheckState";

type UpdateCheckButtonProps = {
    updateState: UpdateCheckState;
    onCheck: () => Promise<void>;
    onUpdateFound?: () => void;
    installReady?: boolean;
    onInstallUpdate?: () => Promise<void> | void;
    delay?: number;
    disabled?: boolean;
};

const PHASE_ORDER: readonly UpdateCheckPhase[] = [
    "idle",
    "checking",
    "none",
    "found",
];

const PHASE_LABELS: Record<UpdateCheckPhase, string> = {
    idle: "Проверить обновления",
    checking: "Проверка обновлений...",
    none: "Обновлений нет",
    found: "Найдено обновление",
};

/** Update check button with CopyButton-style icon stack and timed status feedback. */
export function UpdateCheckButton({
    updateState,
    onCheck,
    onUpdateFound,
    installReady = false,
    onInstallUpdate,
    delay = 2500,
    disabled = false,
}: UpdateCheckButtonProps) {
    const [phase, setPhase] = useState<UpdateCheckPhase>("idle");
    const [inFlight, setInFlight] = useState(false);
    const awaitingResultRef = useRef(false);
    const timerRef = useRef<number | null>(null);
    const mountedRef = useRef(true);
    const labelWrapRef = useRef<HTMLSpanElement | null>(null);
    const labelRefs = useRef<Partial<Record<UpdateCheckPhase, HTMLSpanElement | null>>>({});
    const hasMeasuredRef = useRef(false);
    const onUpdateFoundRef = useRef(onUpdateFound);
    onUpdateFoundRef.current = onUpdateFound;

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            if (timerRef.current !== null) {
                window.clearTimeout(timerRef.current);
            }
        };
    }, []);

    const idleLabel = installReady
        ? "Установить обновление"
        : PHASE_LABELS.idle;

    const measureLabelWidth = (el: HTMLSpanElement) =>
        Math.max(el.scrollWidth, Math.ceil(el.getBoundingClientRect().width));

    useLayoutEffect(() => {
        const wrap = labelWrapRef.current;
        const activeLabel = labelRefs.current[phase];
        if (!wrap || !activeLabel) return;
        const width = measureLabelWidth(activeLabel);
        if (!hasMeasuredRef.current) {
            hasMeasuredRef.current = true;
            const prevTransition = wrap.style.transition;
            wrap.style.transition = "none";
            wrap.style.width = `${width}px`;
            void wrap.offsetWidth;
            wrap.style.transition = prevTransition;
            return;
        }
        wrap.style.width = `${width}px`;
    }, [idleLabel, phase]);

    useEffect(() => {
        const activeLabel = labelRefs.current[phase];
        const sync = () => {
            const wrap = labelWrapRef.current;
            const label = labelRefs.current[phase];
            if (!wrap || !label) return;
            wrap.style.width = `${measureLabelWidth(label)}px`;
        };
        const observer =
            typeof ResizeObserver !== "undefined" && activeLabel
                ? new ResizeObserver(sync)
                : null;
        if (observer && activeLabel) observer.observe(activeLabel);
        let disposed = false;
        void document.fonts?.ready.then(() => {
            if (!disposed) sync();
        });
        window.addEventListener("resize", sync);
        return () => {
            disposed = true;
            observer?.disconnect();
            window.removeEventListener("resize", sync);
        };
    }, [idleLabel, phase]);

    useEffect(() => {
        if (!awaitingResultRef.current) return;
        if (inFlight || updateState === "checking") {
            setPhase("checking");
            return;
        }
        awaitingResultRef.current = false;
        const resultPhase = resolveUpdateCheckResult(updateState);
        setPhase(resultPhase);
        if (resultPhase === "found") {
            onUpdateFoundRef.current?.();
        }
        if (resultPhase === "none" || resultPhase === "found") {
            if (timerRef.current !== null) {
                window.clearTimeout(timerRef.current);
            }
            timerRef.current = window.setTimeout(() => {
                timerRef.current = null;
                if (mountedRef.current) setPhase("idle");
            }, delay);
        }
    }, [delay, inFlight, updateState]);

    async function handleClick() {
        if (disabled || inFlight || updateState === "checking") return;
        if (timerRef.current !== null) {
            window.clearTimeout(timerRef.current);
            timerRef.current = null;
        }
        if (installReady && onInstallUpdate) {
            setInFlight(true);
            try {
                await onInstallUpdate();
            } finally {
                if (mountedRef.current) setInFlight(false);
            }
            return;
        }
        awaitingResultRef.current = true;
        setPhase("checking");
        setInFlight(true);
        try {
            await onCheck();
        } finally {
            if (mountedRef.current) setInFlight(false);
        }
    }

    const isBusy = phase === "checking" || inFlight || updateState === "checking";

    return (
        <Button
            variant={installReady ? "primary" : "secondary"}
            disabled={disabled || isBusy}
            aria-busy={isBusy || undefined}
            className={`ui-update-check-button is-${phase}`}
            onClick={() => void handleClick()}
        >
            <span className="ui-update-icon-slot" aria-hidden="true">
                <span className="ui-update-icon ui-update-icon--loader">
                    <Loader size={16} aria-hidden="true" />
                </span>
                <span className="ui-update-icon ui-update-icon--none">
                    <Check size={16} aria-hidden="true" />
                </span>
                <span className="ui-update-icon ui-update-icon--found">
                    <Info size={16} aria-hidden="true" />
                </span>
            </span>
            <span ref={labelWrapRef} className="ui-update-label-wrap">
                <span className="ui-update-label-stack">
                    {PHASE_ORDER.map((item) => {
                        const active = item === phase;
                        const labelText =
                            item === "idle" ? idleLabel : PHASE_LABELS[item];
                        return (
                            <span
                                key={item}
                                ref={(el) => {
                                    labelRefs.current[item] = el;
                                }}
                                aria-hidden={!active}
                                className={`ui-update-check-label${active ? " is-active" : ""}`}
                            >
                                {labelText}
                            </span>
                        );
                    })}
                </span>
            </span>
        </Button>
    );
}
