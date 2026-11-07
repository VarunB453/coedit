import type { FormEvent } from "react";
import type { AuthMode } from "../types";

interface AuthScreenProps {
  mode: AuthMode;
  name: string;
  password: string;
  error: string;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onNameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onToggleMode: () => void;
}

const AuthScreen = ({
  mode,
  name,
  password,
  error,
  onSubmit,
  onNameChange,
  onPasswordChange,
  onToggleMode,
}: AuthScreenProps) => (
  <main className="auth-screen">
    <div className="auth-panel">
      <div className="auth-hero">
        <div className="auth-brand">
          <span className="brand-mark">W</span>
          <span>CoEdit</span>
        </div>
        <p className="eyebrow">Collaborative workspace</p>
        <h1>Write together in real time.</h1>
        <p className="auth-copy">
          Create polished product notes, launch plans, and strategy docs with a calm, focused workspace built for teams.
        </p>
        <ul className="feature-list">
          <li>Live collaborative editing</li>
          <li>Structured folder workspaces</li>
          <li>Clean notes and design thinking</li>
        </ul>
      </div>

      <form onSubmit={onSubmit} className="auth-form">
        <p className="eyebrow auth-eyebrow">{mode === "login" ? "Welcome back" : "Get started"}</p>
        <h2>{mode === "login" ? "Sign in to your workspace" : "Create your account"}</h2>

        <label htmlFor="username" className="field-label">Username</label>
        <input
          id="username"
          autoComplete="username"
          required
          maxLength={150}
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
          className="text-input"
        />

        <label htmlFor="password" className="field-label">Password</label>
        <input
          id="password"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          value={password}
          onChange={(event) => onPasswordChange(event.target.value)}
          className="text-input"
        />

        {error && <p role="alert" className="auth-error">{error}</p>}

        <button className="primary-btn auth-submit">
          {mode === "login" ? "Sign in" : "Create account"}
        </button>

        <button type="button" onClick={onToggleMode} className="secondary-link">
          {mode === "login" ? "Create an account" : "Already have an account? Sign in"}
        </button>
      </form>
    </div>
  </main>
);

export default AuthScreen;