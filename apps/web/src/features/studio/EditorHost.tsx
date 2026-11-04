/**
 * Hosts one Monaco instance and swaps models per file. Falls back to a styled
 * textarea when Monaco is not installed, so the studio is never a dead panel.
 *
 * While an agent holds the write scope for this file the editor is read-only:
 * a human and an agent writing the same file simultaneously loses work.
 */
import { useEffect, useRef, useState } from "react";
import { loadMonaco, type MonacoLike } from "./optionalDeps";

interface EditorHostProps {
  path: string;
  value: string;
  language: string;
  readOnly: boolean;
  onChange: (next: string) => void;
}

interface EditorHandle {
  dispose: () => void;
  setModel: (value: string, language: string) => void;
  updateOptions: (o: Record<string, unknown>) => void;
  layout: () => void;
}

export function EditorHost({ path, value, language, readOnly, onChange }: EditorHostProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<EditorHandle | null>(null);
  const onChangeRef = useRef(onChange);
  const [monaco, setMonaco] = useState<MonacoLike | null>(null);
  const [failed, setFailed] = useState(false);

  onChangeRef.current = onChange;

  useEffect(() => {
    let disposed = false;
    void loadMonaco().then((mod) => {
      if (disposed) return;
      if (!mod) {
        setFailed(true);
        return;
      }
      setMonaco(mod);
    });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (!monaco || !hostRef.current) return;
    monaco.editor.defineTheme("superagent-graphite", {
      base: "vs-dark",
      inherit: true,
      rules: [{ token: "comment", foreground: "5f6a7a", fontStyle: "italic" }],
      colors: { "editor.background": "#0b0d10", "editorLineNumber.foreground": "#3d4655" },
    });
    monaco.editor.setTheme("superagent-graphite");

    const editor = monaco.editor.create(hostRef.current, {
      value,
      language,
      automaticLayout: false,
      minimap: { enabled: false },
      fontSize: 12.5,
      lineHeight: 20,
      fontFamily: "JetBrains Mono, ui-monospace, monospace",
      scrollBeyondLastLine: false,
      renderLineHighlight: "line",
      padding: { top: 12 },
      readOnly,
    });
    editor.onDidChangeModelContent(() => {
      const model = editor.getModel();
      if (model) onChangeRef.current((model as unknown as { getValue: () => string }).getValue());
    });
    editorRef.current = {
      dispose: () => editor.dispose(),
      setModel: () => undefined,
      updateOptions: (o) => editor.updateOptions(o),
      layout: () => editor.layout(),
    };

    const observer = new ResizeObserver(() => editorRef.current?.layout());
    observer.observe(hostRef.current);

    return () => {
      observer.disconnect();
      editorRef.current?.dispose();
      editorRef.current = null;
    };
    // `value` is intentionally excluded: the model owns the text after mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monaco]);

  useEffect(() => {
    editorRef.current?.updateOptions({ readOnly });
  }, [readOnly]);

  if (failed || !monaco) {
    return (
      <div className="flex h-full flex-col">
        {failed ? (
          <p className="border-b border-subtle bg-overlay px-3 py-1.5 text-[11.5px] text-warn">
            Monaco is not installed. Run <code className="font-mono">npm i monaco-editor</code> for
            full editing; the plain editor below still works.
          </p>
        ) : null}
        <textarea
          aria-label={`Editing ${path}`}
          className="h-full w-full resize-none bg-base p-3 font-mono text-[12.5px] leading-5 text-primary outline-none"
          value={value}
          readOnly={readOnly}
          spellCheck={false}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
    );
  }

  return <div ref={hostRef} className="h-full w-full" data-testid="monaco-host" />;
}
