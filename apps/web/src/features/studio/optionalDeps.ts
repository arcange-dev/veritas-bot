/**
 * Monaco and xterm are optional dependencies. They are loaded dynamically so
 * the studio still boots (with a plain-text fallback) when they are absent,
 * which keeps CI fast and the entry bundle small.
 *
 * A variable specifier plus `@vite-ignore` means the bundler does not fail the
 * build when the package is not installed.
 */
export interface MonacoLike {
  editor: {
    create: (el: HTMLElement, options: Record<string, unknown>) => {
      getModel: () => { setValue: (v: string) => void } | null;
      setModel: (m: unknown) => void;
      dispose: () => void;
      onDidChangeModelContent: (cb: () => void) => void;
      updateOptions: (o: Record<string, unknown>) => void;
      layout: () => void;
    };
    createModel: (value: string, language?: string) => unknown;
    defineTheme: (name: string, theme: Record<string, unknown>) => void;
    setTheme: (name: string) => void;
    setModelLanguage: (model: unknown, language: string) => void;
  };
}

export interface XtermLike {
  Terminal: new (options: Record<string, unknown>) => {
    open: (el: HTMLElement) => void;
    write: (data: string) => void;
    dispose: () => void;
    loadAddon: (addon: unknown) => void;
  };
  FitAddon: new () => { fit: () => void };
}

const load = async <T>(name: string): Promise<T | null> => {
  try {
    const specifier = name;
    return (await import(/* @vite-ignore */ specifier)) as T;
  } catch {
    return null;
  }
};

export const loadMonaco = (): Promise<MonacoLike | null> => load<MonacoLike>("monaco-editor");

export const loadXterm = async (): Promise<XtermLike | null> => {
  const core = await load<{ Terminal: XtermLike["Terminal"] }>("@xterm/xterm");
  const fit = await load<{ FitAddon: XtermLike["FitAddon"] }>("@xterm/addon-fit");
  if (!core || !fit) return null;
  return { Terminal: core.Terminal, FitAddon: fit.FitAddon };
};
