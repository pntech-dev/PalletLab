import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { TriangleAlert, X } from "lucide-react";
import { Button } from "./Button";

type Props = { onClose: () => void; onConfirm: () => Promise<void> };

export function ResetDialog({ onClose, onConfirm }: Props) {
  const dialog = useRef<HTMLElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) { event.preventDefault(); event.stopImmediatePropagation(); onClose(); return; }
      if (event.key !== "Tab" || !dialog.current) return;
      const controls = Array.from(dialog.current.querySelectorAll<HTMLElement>("button:not(:disabled)"));
      const first = controls[0], last = controls[controls.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("keydown", onKey, true); previous?.focus(); };
  }, [busy, onClose]);

  async function confirm() {
    setBusy(true); setError(null);
    try { await onConfirm(); onClose(); }
    catch { setError("Не удалось сбросить проект. Попробуйте ещё раз."); }
    finally { setBusy(false); }
  }

  return createPortal(<div className="modal-backdrop" role="presentation">
    <section ref={dialog} tabIndex={-1} className="modal reset-modal" role="dialog" aria-modal="true" aria-labelledby="reset-title">
      <header className="reset-header"><h2 id="reset-title">Сбросить конфигуратор?</h2><Button variant="ghost" aria-label="Закрыть" disabled={busy} onClick={onClose}><X size={16} /></Button></header>
      <p>Параметры поддона вернутся к исходным значениям. Добавленные брусья и внесённые изменения будут удалены.</p>
      <div className="ui-message ui-message--warning"><TriangleAlert size={24} aria-hidden="true" /><div><strong>Текущий проект будет изменён</strong><p>Сохранённые файлы останутся без изменений.</p></div></div>
      <p className="modal-hint">Чтобы сохранить текущий результат, нажмите «Отмена» и сохраните проект перед сбросом.</p>
      {error ? <p className="error" role="alert">{error}</p> : null}
      <footer className="modal-actions"><Button variant="secondary" disabled={busy} onClick={onClose}>Отмена</Button><Button variant="danger" disabled={busy} onClick={() => void confirm()}>Да, сбросить</Button></footer>
    </section>
  </div>, document.body);
}
