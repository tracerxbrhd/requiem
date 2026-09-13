import {
    createContext,
    useContext,
    useEffect,
    useState,
    type ReactNode,
} from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { request, setCsrf, type Session } from './api';
import { State } from './ui';
const AuthContext = createContext<{
    session: Session | null;
    refresh: () => Promise<void>;
}>({ session: null, refresh: async () => {} });
export function AuthProvider({ children }: { children: ReactNode }) {
    const [session, setSession] = useState<Session | null>(null);
    const [error, setError] = useState('');
    async function refresh() {
        try {
            const value = await request<Session>('/auth/session');
            setCsrf(value.csrf);
            setSession(value);
            setError('');
        } catch (e) {
            setError((e as Error).message);
        }
    }
    useEffect(() => {
        void refresh();
        const unauthorized = () => {
            setCsrf(null);
            setSession((s) => (s ? { ...s, user: null } : s));
        };
        window.addEventListener('requiem:unauthorized', unauthorized);
        return () =>
            window.removeEventListener('requiem:unauthorized', unauthorized);
    }, []);
    if (error)
        return (
            <State
                title="We couldn't connect"
                detail={error}
                retry={() => void refresh()}
            />
        );
    return (
        <AuthContext.Provider value={{ session, refresh }}>
            {children}
        </AuthContext.Provider>
    );
}
export const useAuth = () => useContext(AuthContext);
export function Protected() {
    const { session } = useAuth();
    if (!session) return <State title="Preparing your workspace" busy />;
    return session.user ? <Outlet /> : <Navigate to="/dashboard" replace />;
}
