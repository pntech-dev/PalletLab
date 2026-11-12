import { useEffect, useRef, useState } from "react";
import type { AppSettings } from "./appSettings";

type Section = "general" | "view" | "cad" | "about";

const SECTIONS: { id: Section; title: string; description: string }[] = [
  { id: "general", title: "Общее", description: "Параметры новых проектов и автоматического сохранения." },
  { id: "view", title: "Вид и управление", description: "Настройки отображения и начального положения камеры." },
  { id: "cad", title: "CAD и чертежи", description: "Шаблоны и параметры экспорта в CAD-системы." },
  { id: "about", title: "О программе", description: "Версия PalletLab, связь с разработчиком и обновления." },
];

export function SettingsDialog({ version, settings, onSave, onClose }: {
  version?: string; settings: AppSettings; onSave: (settings: AppSettings) => Promise<boolean>; onClose: () => void;
}) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contactMessage, setContactMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const repository = (import.meta.env.VITE_PROJECT_REPOSITORY_URL ?? "").trim();
  const email = (import.meta.env.VITE_DEVELOPER_EMAIL ?? "").trim();
  async function contactAction(action: "copy" | "repository" | "email", value: string) {
    try {
      const api = window.pywebview?.api;
      const result = action === "copy" ? await api?.copy_text(value) : await api?.open_contact(action, value);
      setContactMessage(result?.ok
        ? { ok: true, text: action === "copy" ? "Скопировано в буфер обмена." : "Открывается приложение по умолчанию." }
        : { ok: false, text: result?.error ?? "Не удалось выполнить действие." });
    } catch {
      setContactMessage({ ok: false, text: "Не удалось выполнить действие." });
    }
  }
  const save = async () => {
    if (!Number.isInteger(draft.autosaveMinutes) || draft.autosaveMinutes < 1 || draft.autosaveMinutes > 1440) {
      setError("Период автосохранения должен быть от 1 до 1440 минут."); return;
    }
    setSaving(true);
    try { if (await onSave(draft)) onClose(); else setError("Не удалось сохранить настройки программы."); }
    catch { setError("Не удалось сохранить настройки программы."); }
    finally { setSaving(false); }
  };
  const [active, setActive] = useState<Section>("general");
  const dialog = useRef<HTMLElement>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onClose();
      }
      if (event.key === "Tab" && dialog.current) {
        const elements = Array.from(dialog.current.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex='0']"));
        if (!elements.length) return;
        const first = elements[0];
        const last = elements[elements.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first.focus();
        }
      }
    };
    window.addEventListener("keydown", handleKey, true);
    return () => { window.removeEventListener("keydown", handleKey, true); previouslyFocused?.focus(); };
  }, [onClose]);

  const section = SECTIONS.find((item) => item.id === active)!;
  return (
    <div className="modal-backdrop" role="presentation">
      <section ref={dialog} tabIndex={-1} className="modal settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header className="settings-header"><h2 id="settings-title">Настройки программы</h2></header>
        <div className="settings-layout">
          <nav className="settings-nav" aria-label="Разделы настроек">
            {SECTIONS.map((item) => <button key={item.id} type="button" aria-current={active === item.id ? "page" : undefined}
              onClick={() => setActive(item.id)}>{item.title}</button>)}
          </nav>
          <div className="settings-content">
            <h3>{section.title}</h3>
            <p className="settings-description">{section.description}</p>

            {active === "general" && <>
              <section className="settings-group"><h4>Параметры поддона</h4>
                <label>Округление поддона по умолчанию
                  <select value={draft.rounding} onChange={(event) => setDraft({ ...draft, rounding: event.target.value as AppSettings["rounding"] })}><option value="50">50 мм</option><option value="5">5 мм</option><option value="none">Не округлять</option></select>
                </label>
              </section>
              <section className="settings-group"><h4>Автосохранение</h4>
                <label className="settings-check"><input type="checkbox" checked={draft.autosaveEnabled} onChange={(event) => setDraft({ ...draft, autosaveEnabled: event.target.checked })} /> Включить автосохранение</label>
                <label>Период автосохранения, мин<input type="number" min="1" max="1440" value={draft.autosaveMinutes} disabled={!draft.autosaveEnabled} onChange={(event) => setDraft({ ...draft, autosaveMinutes: Number(event.target.value) })} /></label>
              </section>
            </>}
            {active === "view" && <>
              <section className="settings-group"><h4>Размеры и подсказки</h4>
                <label className="settings-check"><input type="checkbox" checked={draft.showDimensions} onChange={(event) => setDraft({ ...draft, showDimensions: event.target.checked })} /> Показывать размерные линии поддона</label>
                <label className="settings-check"><input type="checkbox" checked={draft.showGrid} onChange={(event) => setDraft({ ...draft, showGrid: event.target.checked })} /> Показывать сетку</label>
              </section>
              <section className="settings-group"><h4>Вид по умолчанию</h4>
                <label>Начальный вид<select value={draft.camera} onChange={(event) => setDraft({ ...draft, camera: event.target.value as AppSettings["camera"] })}><option value="isometric">Изометрия</option><option value="top">Сверху</option><option value="front">Спереди</option><option value="side">Сбоку</option></select></label>
              </section>
            </>}
            {active === "cad" && <>
              <section className="settings-group"><h4>Автопоиск шаблонов</h4>
                <p>Поиск файлов шаблонов установленных CAD-систем.</p>
                <button type="button" className="secondary" disabled>Найти шаблоны</button>
              </section>
              <section className="settings-group"><h4>SolidWorks</h4>
                <p>Настройки экспорта будут перенесены в этот раздел.</p>
              </section>
            </>}
            {active === "about" && <>
              <section className="settings-group"><h4>Версия ПО</h4><p>{version ?? "Версия недоступна"}</p></section>
              <section className="settings-group"><h4>Ссылки и связь с разработчиком</h4>
                <div className="settings-contact"><label>Репозиторий проекта<input readOnly value={repository} placeholder="Не указан" /></label>
                  <button type="button" className="secondary" disabled={!repository} onClick={() => void contactAction("copy", repository)} aria-label="Скопировать ссылку на репозиторий">Копировать</button>
                  <button type="button" className="secondary" disabled={!repository} onClick={() => void contactAction("repository", repository)}>Открыть репозиторий</button></div>
                <div className="settings-contact"><label>Почта разработчика<input readOnly value={email} placeholder="Не указана" /></label>
                  <button type="button" className="secondary" disabled={!email} onClick={() => void contactAction("copy", email)} aria-label="Скопировать адрес разработчика">Копировать</button>
                  <button type="button" className="secondary" disabled={!email} onClick={() => void contactAction("email", email)}>Написать разработчику</button></div>
                {contactMessage ? <p className={contactMessage.ok ? "success-message" : "error"} role="status">{contactMessage.text}</p> : null}
              </section>
              <section className="settings-group"><h4>Обновление PalletLab</h4>
                <label className="settings-check"><input type="checkbox" checked={draft.checkUpdates} onChange={(event) => setDraft({ ...draft, checkUpdates: event.target.checked })} /> Проверять обновления при каждом запуске программы</label>
                <div className="settings-update"><span>Последняя проверка: информация недоступна</span><button type="button" className="secondary" disabled>Проверить обновления</button></div>
              </section>
            </>}
            <p className="settings-default-hint">Все изменённые параметры «по умолчанию» будут применяться к новым проектам.</p>
          </div>
        </div>
        <footer className="modal-actions settings-footer">
          {error ? <p className="error settings-save-error" role="alert">{error}</p> : null}
          <button type="button" className="secondary" onClick={onClose} disabled={saving}>Отмена</button>
          <button type="button" onClick={() => void save()} disabled={saving}>Сохранить</button>
        </footer>
      </section>
    </div>
  );
}
