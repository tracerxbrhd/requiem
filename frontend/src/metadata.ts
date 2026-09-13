import { createContext, useCallback, useEffect, useState } from 'react';
import { ApiError, request, type Entity } from './api';

type Metadata = {
    entities: Entity[];
    status: 'loading' | 'ready' | 'rate_limited' | 'unavailable';
    error?: string;
};
export const SelectorMetadata = createContext<{
    status: Metadata['status'];
    error?: string;
    kind: 'Role' | 'Channel';
    retry: () => void;
} | null>(null);

export function useMetadata(path: string | null) {
    const [value, setValue] = useState<Metadata>({
        entities: [],
        status: 'loading',
    });
    const [attempt, setAttempt] = useState(0);
    const retry = useCallback(() => setAttempt((x) => x + 1), []);
    useEffect(() => {
        if (!path) return;
        let active = true;
        setValue((old) => ({ ...old, status: 'loading', error: undefined }));
        void request<Entity[]>(path).then(
            (entities) => {
                if (active) setValue({ entities, status: 'ready' });
            },
            (error: Error) => {
                if (active)
                    setValue((old) => ({
                        ...old,
                        status:
                            error instanceof ApiError &&
                            error.code === 'discord_rate_limited'
                                ? 'rate_limited'
                                : 'unavailable',
                        error: error.message,
                    }));
            },
        );
        return () => {
            active = false;
        };
    }, [path, attempt]);
    return { ...value, retry };
}
