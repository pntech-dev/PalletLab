import { Component, type ErrorInfo, type ReactNode } from "react";
type Props = {
    children: ReactNode;
    resetKey: number;
    onError: (error: Error, info: ErrorInfo) => void;
};

/** Keep the editor usable if rendering a model fails. */
export class ViewportErrorBoundary extends Component<
    Props,
    { failed: boolean }
> {
    state = { failed: false };

    static getDerivedStateFromError() {
        return { failed: true };
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        console.error(
            "[PalletLab] Ошибка отображения 3D-вида:",
            error,
            info.componentStack,
        );
        this.props.onError(error, info);
    }

    componentDidUpdate(previous: Props) {
        if (this.state.failed && previous.resetKey !== this.props.resetKey)
            this.setState({ failed: false });
    }

    render() {
        if (!this.state.failed) return this.props.children;
        return null;
    }
}
