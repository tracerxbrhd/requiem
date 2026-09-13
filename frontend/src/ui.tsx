import {
    useContext,
    useEffect,
    useId,
    useRef,
    useState,
    type ReactNode,
} from 'react';
import { AlertCircle, Check, Search, Shield, X } from 'lucide-react';
import { useBlocker } from 'react-router-dom';
import type { Entity } from './api';
import { locale } from './locale';
import { SelectorMetadata } from './metadata';
export function Brand() {
    return (
        <span className="brand">
            <img src="/requiem.jpg" alt="" />
            Requiem<span className="brand-dot">.</span>
        </span>
    );
}
export function State({
    title,
    detail,
    retry,
    busy = false,
}: {
    title: string;
    detail?: string;
    retry?: () => void;
    busy?: boolean;
}) {
    return (
        <div className="state glass" role="status">
            {busy ? <span className="spinner" /> : <Shield size={32} />}
            <h2>{title}</h2>
            {detail && <p>{detail}</p>}
            {retry && <button onClick={retry}>{locale.copy.retry}</button>}
        </div>
    );
}
export function Callout({
    children,
    tone = 'warning',
}: {
    children: ReactNode;
    tone?: 'warning' | 'success';
}) {
    return (
        <div className={`callout ${tone}`} role="status">
            {tone === 'success' ? (
                <Check size={18} />
            ) : (
                <AlertCircle size={18} />
            )}
            <div>{children}</div>
        </div>
    );
}
export function Toggle({
    label,
    description,
    value,
    onChange,
}: {
    label: string;
    description?: string;
    value: boolean;
    onChange: (value: boolean) => void;
}) {
    const id = useId();
    return (
        <div className="setting-row">
            <div>
                <label htmlFor={id}>{label}</label>
                {description && <p>{description}</p>}
            </div>
            <button
                id={id}
                type="button"
                role="switch"
                aria-checked={value}
                className={`toggle ${value ? 'on' : ''}`}
                onClick={() => onChange(!value)}
            >
                <span />
            </button>
        </div>
    );
}
export function Dialog({
    title,
    children,
    onClose,
    action,
    actionLabel,
    danger = false,
    busy = false,
}: {
    title: string;
    children: ReactNode;
    onClose: () => void;
    action: () => void;
    actionLabel: string;
    danger?: boolean;
    busy?: boolean;
}) {
    const ref = useRef<HTMLDialogElement>(null);
    const id = useId();
    useEffect(() => {
        const old = document.activeElement as HTMLElement | null;
        const dialog = ref.current;
        dialog?.showModal();
        return () => {
            dialog?.close();
            old?.focus();
        };
    }, []);
    return (
        <dialog
            ref={ref}
            aria-labelledby={id}
            onCancel={(e) => {
                e.preventDefault();
                if (!busy) onClose();
            }}
        >
            <div className="dialog-head">
                <h2 id={id}>{title}</h2>
                <button
                    className="icon-button"
                    aria-label="Close dialog"
                    disabled={busy}
                    onClick={onClose}
                >
                    <X />
                </button>
            </div>
            <div className="dialog-copy">{children}</div>
            <div className="actions">
                <button disabled={busy} onClick={onClose}>
                    {locale.copy.stay}
                </button>
                <button
                    className={danger ? 'danger' : 'primary'}
                    disabled={busy}
                    onClick={action}
                >
                    {busy ? 'Please wait…' : actionLabel}
                </button>
            </div>
        </dialog>
    );
}
export function UnsavedGuard({ dirty }: { dirty: boolean }) {
    const blocker = useBlocker(dirty);
    useEffect(() => {
        const guard = (e: BeforeUnloadEvent) => {
            if (dirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        };
        window.addEventListener('beforeunload', guard);
        return () => window.removeEventListener('beforeunload', guard);
    }, [dirty]);
    return blocker.state === 'blocked' ? (
        <Dialog
            title={locale.copy.unsaved}
            onClose={() => blocker.reset()}
            action={() => blocker.proceed()}
            actionLabel="Discard changes"
            danger
        >
            <p>
                Your edits have not been saved. Leave this page and discard
                them?
            </p>
        </Dialog>
    ) : null;
}
export function Selector({
    label,
    options,
    value,
    onChange,
    multiple = false,
}: {
    label: string;
    options: Entity[];
    value: string[];
    onChange: (ids: string[]) => void;
    multiple?: boolean;
}) {
    const [query, setQuery] = useState('');
    const metadata = useContext(SelectorMetadata);
    const unavailable = metadata && metadata.status !== 'ready';
    const id = useId();
    const shown = options.filter((x) =>
        x.name.toLowerCase().includes(query.toLowerCase()),
    );
    return (
        <fieldset className="selector">
            <legend>{label}</legend>
            {unavailable && (
                <div role="status" className="callout warning">
                    <div>
                        <p>
                            {metadata.status === 'loading'
                                ? 'Loading metadata…'
                                : metadata.error}
                        </p>
                        {metadata.status !== 'loading' && (
                            <button type="button" onClick={metadata.retry}>
                                Retry metadata
                            </button>
                        )}
                    </div>
                </div>
            )}
            <div className="search">
                <Search size={16} />
                <input
                    disabled={!!unavailable}
                    id={id}
                    aria-label={`Search ${label}`}
                    placeholder="Search by name…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                />
            </div>
            <div className="selection-chips">
                {value.map((x) => (
                    <span className="chip" key={x}>
                        {options.find((o) => o.id === x)?.name ??
                            `${metadata?.kind ?? 'ID'} ${x}`}
                        <button
                            disabled={!!unavailable}
                            aria-label={`Remove ${options.find((o) => o.id === x)?.name ?? x}`}
                            onClick={() =>
                                onChange(value.filter((v) => v !== x))
                            }
                            type="button"
                        >
                            <X size={12} />
                        </button>
                    </span>
                ))}
            </div>
            <div className="options">
                {!multiple && (
                    <label>
                        <input
                            disabled={!!unavailable}
                            type="radio"
                            name={id}
                            checked={!value.length}
                            onChange={() => onChange([])}
                        />
                        Use default / none
                    </label>
                )}
                {shown.map((option) => (
                    <label key={option.id}>
                        <input
                            disabled={!!unavailable}
                            type={multiple ? 'checkbox' : 'radio'}
                            name={id}
                            checked={value.includes(option.id)}
                            onChange={() =>
                                onChange(
                                    multiple
                                        ? value.includes(option.id)
                                            ? value.filter(
                                                  (x) => x !== option.id,
                                              )
                                            : [...value, option.id]
                                        : [option.id],
                                )
                            }
                        />
                        <span
                            className="entity-dot"
                            style={
                                option.colour
                                    ? {
                                          backgroundColor: `#${option.colour.toString(16).padStart(6, '0')}`,
                                      }
                                    : {}
                            }
                        />
                        {option.name}
                    </label>
                ))}
                {!unavailable && !shown.length && (
                    <p className="muted">No matching options.</p>
                )}
            </div>
        </fieldset>
    );
}
