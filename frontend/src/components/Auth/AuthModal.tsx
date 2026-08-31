import { useAuthStore } from '../../stores/authStore';

interface Props {
  open: boolean;
  onClose: () => void;
  initialTab?: 'login' | 'signup';
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

export function AuthModal({ open, onClose, initialTab = 'login' }: Props) {
  const { authLoading, authError, googleLogin, clearAuthError } = useAuthStore();

  if (!open) return null;

  const isSignup = initialTab === 'signup';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm space-y-5 rounded-xl border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-center">
          <h2 className="text-lg font-bold text-[var(--color-text-primary)]">AI Research Coach</h2>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
            {isSignup
              ? 'Create an account to run scored assessments and keep your history.'
              : 'Log in to run scored assessments and keep your history.'}
          </p>
        </div>

        <button
          onClick={() => {
            clearAuthError();
            googleLogin();
          }}
          disabled={authLoading}
          className="flex w-full items-center justify-center gap-3 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] py-3 text-sm font-semibold text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-border-focus)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <GoogleIcon />
          {authLoading ? 'Redirecting to Google...' : 'Continue with Google'}
        </button>

        <p className="text-center text-xs text-[var(--color-text-muted)]">
          First-time sign-in creates your account automatically.
        </p>

        {authError && (
          <p className="text-center text-xs text-[var(--color-error)]">{authError}</p>
        )}

        {authError && authError.includes('GOOGLE_CLIENT_ID') && (
          <div className="rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 p-3 text-xs leading-relaxed text-[var(--color-text-secondary)]">
            Google login isn&rsquo;t configured on this server yet. An admin needs to create an
            OAuth 2.0 Web client in the Google Cloud Console (redirect URI{' '}
            <code className="rounded bg-[var(--color-bg-tertiary)] px-1 py-0.5">http://localhost:8001/api/auth/google/callback</code>)
            and add <code className="rounded bg-[var(--color-bg-tertiary)] px-1 py-0.5">GOOGLE_CLIENT_ID</code> and{' '}
            <code className="rounded bg-[var(--color-bg-tertiary)] px-1 py-0.5">GOOGLE_CLIENT_SECRET</code> to{' '}
            <code className="rounded bg-[var(--color-bg-tertiary)] px-1 py-0.5">.env</code>.
            You can keep using the app in guest practice mode meanwhile.
          </div>
        )}

        <button
          onClick={onClose}
          className="w-full rounded-lg border border-[var(--color-border-default)] py-2.5 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text-primary)]"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}