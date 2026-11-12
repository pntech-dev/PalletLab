import { useEffect, useRef, useState } from "react";

type Section = "general" | "view" | "cad" | "about";

const SECTIONS: { id: Section; title: string; description: string }[] = [
  { id: "general", title: "Общее", description: "Параметры новых проектов и автоматического сохранения." },
  { id: "view", title: "Вид и управление", description: "Настройки отображения и начального положения камеры." },
  { id: "cad", title: "CAD и чертежи", description: "Шаблоны и параметры экспорта в CAD-системы." },
  { id: "about", title: "О программе", description: "Версия PalletLab, связь с разработчиком и обновления." },
];

export function SettingsDialog({ version, onClose }: { version?: string; onClose: () => void }) {
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
            <p className="settings-unavailable" role="status">Настройки пока недоступны для изменения.</p>
            {active === "general" && <>
              <section className="settings-group"><h4>Параметры поддона</h4>
                <label>Округление поддона по умолчанию
                  <select disabled defaultValue=""><option value="">Не задано</option><option>50 мм</option><option>5 мм</option><option>Не округлять</option></select>
                </label>
              </section>
              <section className="settings-group"><h4>Автосохранение</h4>
                <label className="settings-check"><input type="checkbox" disabled /> Включить автосохранение</label>
                <label>Период автосохранения, мин<input type="number" min="1" placeholder="Не задан" disabled /></label>
              </section>
            </>}
            {active === "view" && <>
              <section className="settings-group"><h4>Размеры и подсказки</h4>
                <label className="settings-check"><input type="checkbox" disabled /> Показывать размерные линии поддона</label>
                <label className="settings-check"><input type="checkbox" disabled /> Показывать сетку</label>
              </section>
              <section className="settings-group"><h4>Вид по умолчанию</h4>
                <label>Начальный вид<select disabled defaultValue=""><option value="">Не задан</option><option>Изометрия</option><option>Сверху</option><option>Спереди</option><option>Сбоку</option></select></label>
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
                <div className="settings-contact"><label>Репозиторий проекта<input readOnly value={import.meta.env.VITE_PROJECT_REPOSITORY_URL || ""} /></label>
                  <button type="button" className="secondary" disabled aria-label="Скопировать ссылку на репозиторий">Копировать</button>
                  <button type="button" className="secondary" disabled>Открыть репозиторий</button></div>
                <div className="settings-contact"><label>Почта разработчика<input readOnly value={import.meta.env.VITE_DEVELOPER_EMAIL || ""} placeholder="Не указана" /></label>
                  <button type="button" className="secondary" disabled aria-label="Скопировать адрес разработчика">Копировать</button>
                  <button type="button" className="secondary" disabled>Написать разработчику</button></div>
              </section>
              <section className="settings-group"><h4>Обновление PalletLab</h4>
                <label className="settings-check"><input type="checkbox" disabled /> Проверять обновления при каждом запуске программы</label>
                <div className="settings-update"><span>Последняя проверка: информация недоступна</span><button type="button" className="secondary" disabled>Проверить обновления</button></div>
              </section>
            </>}
            <p className="settings-default-hint">Все изменённые параметры «по умолчанию» будут применяться к новым проектам.</p>
          </div>
        </div>
        <footer className="modal-actions settings-footer">
          <button type="button" className="secondary" onClick={onClose}>Отмена</button>
          <button type="button" disabled>Сохранить</button>
        </footer>
      </section>
    </div>
  );
}
