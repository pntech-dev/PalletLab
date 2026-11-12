import { useEffect, useRef, useState } from "react";
import type { AppSettings } from "./appSettings";
import type { SolidWorksOptions, UpdateStatus } from "./App";

type Section = "general" | "view" | "cad" | "about";

const SECTIONS: { id: Section; title: string; description: string }[] = [
  { id: "general", title: "Общее", description: "Параметры новых проектов и автоматического сохранения." },
  { id: "view", title: "Вид и управление", description: "Настройки отображения и начального положения камеры." },
  { id: "cad", title: "CAD и чертежи", description: "Шаблоны и параметры экспорта в CAD-системы." },
  { id: "about", title: "О программе", description: "Версия PalletLab, связь с разработчиком и обновления." },
];

export function SettingsDialog({ version, settings, solidworks, initialSection = "general", update, lastUpdateCheck, onCheckUpdates, onSave, onClose }: {
  version?: string; settings: AppSettings; solidworks: SolidWorksOptions | null; initialSection?: Section;
  update: UpdateStatus; lastUpdateCheck: string | null; onCheckUpdates: () => Promise<void>;
  onSave: (settings: AppSettings, solidworks: SolidWorksOptions | null) => Promise<boolean>; onClose: () => void;
}) {
  const [draft, setDraft] = useState(settings);
  const [checking, setChecking] = useState(false);
  const parsedCheck = lastUpdateCheck ? new Date(lastUpdateCheck) : null;
  const checkLabel = parsedCheck && !Number.isNaN(parsedCheck.getTime())
    ? `Последняя проверка ${parsedCheck.toLocaleDateString("ru-RU")} в ${parsedCheck.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`
    : "Проверка ещё не выполнялась";
  async function checkUpdates() {
    setChecking(true);
    try { await onCheckUpdates(); } finally { setChecking(false); }
  }
  const [cadDraft, setCadDraft] = useState<SolidWorksOptions>(solidworks ?? {
    partTemplate: "", assemblyTemplate: "", drawingTemplate: "", materialLibrary: "", materialName: "",
  });
  const [materials, setMaterials] = useState<string[]>([]);
  const [cadError, setCadError] = useState<string | null>(null);
  const [cadBusy, setCadBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [missingFiles, setMissingFiles] = useState({ partTemplate: false, assemblyTemplate: false, drawingTemplate: false, materialLibrary: false });
  const [searchMessage, setSearchMessage] = useState<string | null>(null);
  const initialCad = useRef(JSON.stringify(cadDraft));
  const materialLoadVersion = useRef(0);
  const loadedLibraryPath = useRef<string | null>(null);
  useEffect(() => {
    if (!solidworks?.materialLibrary) return;
    let cancelled = false;
    const version = ++materialLoadVersion.current;
    void window.pywebview?.api?.solidworks_materials(solidworks.materialLibrary).then((result) => {
      if (cancelled || version !== materialLoadVersion.current) return;
      if (result.ok && result.materials?.length) { loadedLibraryPath.current = solidworks.materialLibrary; setMaterials(result.materials); }
      else setCadError(result.error ?? "Не удалось прочитать сохранённую библиотеку материалов SolidWorks.");
    }).catch(() => { if (!cancelled && version === materialLoadVersion.current) setCadError("Не удалось прочитать сохранённую библиотеку материалов SolidWorks."); });
    return () => { cancelled = true; };
  }, []);
  async function selectTemplate(kind: "part" | "assembly" | "drawing") {
    setCadBusy(true);
    try {
      const result = await window.pywebview?.api?.select_solidworks_template(kind);
      if (result?.cancelled) return;
      if (!result?.ok || !result.path) { setCadError(result?.error ?? "Не удалось выбрать шаблон SolidWorks."); return; }
      const field = kind === "part" ? "partTemplate" : kind === "assembly" ? "assemblyTemplate" : "drawingTemplate";
      setCadDraft((current) => ({ ...current, [field]: result.path! }));
      setMissingFiles((current) => ({ ...current, [field]: false }));
      setCadError(null);
    } catch { setCadError("Не удалось выбрать шаблон SolidWorks."); }
    finally { setCadBusy(false); }
  }
  function changeLibraryPath(value: string) {
    materialLoadVersion.current += 1;
    setCadBusy(false);
    loadedLibraryPath.current = null;
    setMissingFiles((current) => ({ ...current, materialLibrary: false }));
    setMaterials([]);
    setCadError(null);
    setCadDraft((current) => ({ ...current, materialLibrary: value, materialName: "" }));
  }
  async function loadTypedLibrary(value: string) {
    const path = value.trim();
    if (!path || path === loadedLibraryPath.current) return;
    const version = ++materialLoadVersion.current;
    setCadBusy(true);
    try {
      const result = await window.pywebview?.api?.solidworks_materials(path);
      if (version !== materialLoadVersion.current) return;
      if (!result?.ok || !result.materials?.length) {
        setMissingFiles((current) => ({ ...current, materialLibrary: true }));
        setCadError(result?.error ?? "Не удалось прочитать библиотеку материалов SolidWorks."); return;
      }
      setMissingFiles((current) => ({ ...current, materialLibrary: false }));
      const names = result.materials;
      loadedLibraryPath.current = path;
      setMaterials(names);
      setCadDraft((current) => ({ ...current, materialLibrary: path,
        materialName: names.includes(current.materialName) ? current.materialName : names[0] }));
      setCadError(null);
    } catch {
      if (version === materialLoadVersion.current) setCadError("Не удалось прочитать библиотеку материалов SolidWorks.");
    } finally {
      if (version === materialLoadVersion.current) setCadBusy(false);
    }
  }
  async function selectLibrary() {
    setCadBusy(true);
    try {
      const result = await window.pywebview?.api?.select_solidworks_material_library();
      if (result?.cancelled) { await loadTypedLibrary(cadDraft.materialLibrary); return; }
      if (!result?.ok || !result.materialLibrary || !result.materials?.length) {
        setCadError(result?.error ?? "Не удалось прочитать библиотеку материалов SolidWorks."); return;
      }
      materialLoadVersion.current += 1;
      const names = result.materials;
      loadedLibraryPath.current = result.materialLibrary;
      setMissingFiles((current) => ({ ...current, materialLibrary: false }));
      setMaterials(names);
      setCadDraft((current) => ({ ...current, materialLibrary: result.materialLibrary!,
        materialName: names.includes(current.materialName) ? current.materialName : names[0] }));
      setCadError(null);
    } catch { setCadError("Не удалось прочитать библиотеку материалов SolidWorks."); }
    finally { setCadBusy(false); }
  }
  async function searchCadFiles() {
    materialLoadVersion.current += 1;
    setSearching(true);
    setCadBusy(true);
    setSearchMessage(null);
    setCadError(null);
    try {
      const result = await window.pywebview?.api?.discover_cad_templates(cadDraft);
      if (!result?.ok) { setCadError(result?.error ?? "Не удалось выполнить поиск шаблонов."); return; }
      const missing = { partTemplate: !result.partTemplate, assemblyTemplate: !result.assemblyTemplate,
        drawingTemplate: Boolean(cadDraft.drawingTemplate && !result.drawingTemplate),
        materialLibrary: !result.materialLibrary };
      setMissingFiles(missing);
      if (result.materialLibrary) {
        materialLoadVersion.current += 1;
        loadedLibraryPath.current = result.materialLibrary;
        setMaterials(result.materials);
      }
      setCadDraft((current) => ({ ...current,
        partTemplate: result.partTemplate ?? current.partTemplate,
        assemblyTemplate: result.assemblyTemplate ?? current.assemblyTemplate,
        drawingTemplate: result.drawingTemplate ?? current.drawingTemplate,
        materialLibrary: result.materialLibrary ?? current.materialLibrary,
        materialName: result.materialLibrary
          ? (result.materials.includes(current.materialName) ? current.materialName : result.materials[0] ?? "")
          : current.materialName,
      }));
      setSearchMessage(Object.values(missing).some(Boolean)
        ? "Не все файлы найдены. Укажите недостающие пути вручную."
        : "Файлы найдены. Проверьте пути и сохраните настройки.");
    } catch { setCadError("Не удалось выполнить поиск шаблонов."); }
    finally { setSearching(false); setCadBusy(false); }
  }
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
    const cadChanged = JSON.stringify(cadDraft) !== initialCad.current;
    if (cadChanged && [cadDraft.partTemplate, cadDraft.assemblyTemplate, cadDraft.materialLibrary, cadDraft.materialName].some((value) => !value.trim())) {
    setActive("cad"); setCadError("Для сохранения настроек SolidWorks выберите шаблоны детали и сборки, библиотеку и материал."); return;
    }
    setSaving(true);
    try { if (await onSave(draft, cadChanged ? cadDraft : null)) onClose(); else setError("Не удалось сохранить настройки программы."); }
    catch { setError("Не удалось сохранить настройки программы."); }
    finally { setSaving(false); }
  };
  const [active, setActive] = useState<Section>(initialSection);
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
                <p>Поиск шаблонов детали, сборки и чертежа в настройках SolidWorks, реестре Windows и стандартных папках, а также стандартной библиотеки материалов.</p>
                <button type="button" className="secondary" disabled={cadBusy || saving} onClick={() => void searchCadFiles()}>{searching ? "Поиск…" : "Найти шаблоны"}</button>
                {searchMessage ? <p role="status">{searchMessage}</p> : null}
              </section>
              <section className="settings-group settings-cad-group"><h4>SolidWorks</h4>
                <p>Выберите шаблоны детали, сборки и чертежа, библиотеку материалов и материал для экспорта.</p>
                {initialSection === "cad" && !solidworks ? <p>Для экспорта в SolidWorks сначала заполните и сохраните эти настройки.</p> : null}
                <label className="file-field">Шаблон детали (.prtdot)
                  <div className="file-field-control"><input value={cadDraft.partTemplate} placeholder="Не выбран" disabled={searching} aria-invalid={missingFiles.partTemplate} aria-describedby={missingFiles.partTemplate ? "part-template-error" : undefined} onChange={(event) => { setMissingFiles((current) => ({ ...current, partTemplate: false })); setCadDraft((current) => ({ ...current, partTemplate: event.target.value })); }} /><button type="button" className="secondary" disabled={cadBusy || saving} onClick={() => void selectTemplate("part")}>Обзор…</button></div>
                  {missingFiles.partTemplate ? <span id="part-template-error" className="field-error">Шаблон детали не найден.</span> : null}
                </label>
                <label className="file-field">Шаблон сборки (.asmdot)
                  <div className="file-field-control"><input value={cadDraft.assemblyTemplate} placeholder="Не выбран" disabled={searching} aria-invalid={missingFiles.assemblyTemplate} aria-describedby={missingFiles.assemblyTemplate ? "assembly-template-error" : undefined} onChange={(event) => { setMissingFiles((current) => ({ ...current, assemblyTemplate: false })); setCadDraft((current) => ({ ...current, assemblyTemplate: event.target.value })); }} /><button type="button" className="secondary" disabled={cadBusy || saving} onClick={() => void selectTemplate("assembly")}>Обзор…</button></div>
                  {missingFiles.assemblyTemplate ? <span id="assembly-template-error" className="field-error">Шаблон сборки не найден.</span> : null}
                </label>
                <label className="file-field">Шаблон чертежа (.drwdot)
                  <div className="file-field-control"><input value={cadDraft.drawingTemplate} placeholder="Не выбран — использовать шаблон SolidWorks по умолчанию" disabled={searching} aria-invalid={missingFiles.drawingTemplate} aria-describedby={missingFiles.drawingTemplate ? "drawing-template-error" : undefined} onChange={(event) => { setMissingFiles((current) => ({ ...current, drawingTemplate: false })); setCadDraft((current) => ({ ...current, drawingTemplate: event.target.value })); }} /><button type="button" className="secondary" disabled={cadBusy || saving} onClick={() => void selectTemplate("drawing")}>Обзор…</button></div>
                  {missingFiles.drawingTemplate ? <span id="drawing-template-error" className="field-error">Шаблон чертежа не найден.</span> : null}
                </label>
                <label className="file-field">Библиотека материалов (.sldmat)
                  <div className="file-field-control"><input value={cadDraft.materialLibrary} placeholder="Не выбрана" disabled={searching} aria-invalid={missingFiles.materialLibrary} aria-describedby={missingFiles.materialLibrary ? "material-library-error" : undefined} onChange={(event) => changeLibraryPath(event.target.value)} onBlur={(event) => { if (!(event.relatedTarget instanceof HTMLElement && event.relatedTarget.dataset.libraryBrowse)) void loadTypedLibrary(event.target.value); }} /><button type="button" className="secondary" disabled={cadBusy || saving} data-library-browse="true" onClick={() => void selectLibrary()}>Обзор…</button></div>
                  {missingFiles.materialLibrary ? <span id="material-library-error" className="field-error">Библиотека материалов не найдена.</span> : null}
                </label>
                <p className="modal-hint">Стандартный путь: <code>C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\russian\sldmaterials\solidworks materials.sldmat</code></p>
                <label className="material-field">Материал SolidWorks
                  <select value={cadDraft.materialName} disabled={materials.length === 0 || cadBusy || saving} onChange={(event) => setCadDraft({ ...cadDraft, materialName: event.target.value })}>
                    {cadDraft.materialName && !materials.includes(cadDraft.materialName) ? <option value={cadDraft.materialName}>{cadDraft.materialName}</option> : null}
                    {!cadDraft.materialName ? <option value="">Сначала выберите библиотеку</option> : null}
                    {materials.map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                </label>
                {cadError ? <p className="error" role="alert">{cadError}</p> : null}
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
                <div className="settings-update"><span>{checkLabel}</span><button type="button" className="secondary" onClick={() => void checkUpdates()} disabled={checking || ["checking", "downloading", "ready", "installing"].includes(update.state)}>Проверить обновления</button></div>
                <p role="status">{update.state === "checking" ? "Проверка обновлений…"
                  : update.state === "current" ? "Установлена последняя версия."
                  : update.state === "check_failed" ? "Не удалось проверить обновления. Проверьте подключение и повторите попытку."
                  : update.state === "available" ? `Доступна версия ${update.version}.${update.manualOnly ? " Для portable-версии скачайте её вручную." : ""}`
                  : update.state === "unavailable" ? "Автоматические обновления доступны для установленной версии."
                  : update.state === "ready" ? "Обновление готово к установке."
                  : update.state === "downloading" ? "Обновление скачивается…"
                  : update.state === "failed" ? "Не удалось скачать обновление."
                  : null}</p>
                {["available", "downloading", "ready", "failed"].includes(update.state) ? <p>Закройте настройки, чтобы перейти к обновлению.</p> : null}
              </section>
            </>}
            <p className="settings-default-hint">Все изменённые параметры «по умолчанию» будут применяться к новым проектам.</p>
          </div>
        </div>
        <footer className="modal-actions settings-footer">
          {error ? <p className="error settings-save-error" role="alert">{error}</p> : null}
          <button type="button" className="secondary" onClick={onClose} disabled={saving}>Отмена</button>
          <button type="button" onClick={() => void save()} disabled={saving || cadBusy}>Сохранить</button>
        </footer>
      </section>
    </div>
  );
}
